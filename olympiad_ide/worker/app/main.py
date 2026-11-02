"""Trusted worker control process. Run with PYTHONPATH=backend:. python -m worker.app.main"""
import json
import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from app.database import make_engine, session_factory
from app.execution_models import ExecutionJob, ExecutionSnapshot, ExecutionWorker
from app.execution_schema import JobResult
from app.execution_service import claim, emit, fenced_job, finish, limits_for, transition
from app.models import utcnow
from .executor import execute
from .sandbox import Sandbox, SandboxUnavailable

log = logging.getLogger('olympiad.worker')


def run_job(factory, job_id, token, box_id):
    stop = threading.Event()
    done = threading.Event()
    def heartbeat():
        while not done.wait(2):
            try:
                with factory() as db:
                    job = fenced_job(db, job_id, token)
                    job.lease_expiration = utcnow() + timedelta(seconds=15)
                    if job.cancel_requested: stop.set()
                    db.commit()
            except Exception:
                stop.set(); return  # Fail closed on DB outage or a fenced/expired lease.
    thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
    def stage(status):
        with factory() as db:
            job = fenced_job(db, job_id, token); transition(db, job, status); db.commit()
    def output(stream, text):
        with factory() as db:
            job = fenced_job(db, job_id, token)
            encoded = text.encode()
            # Total job stream is bounded even across all 50 test cases.
            remaining = job.limits['outputBytes'] - job.output_bytes
            if remaining < len(encoded): stop.set(); raise RuntimeError('Aggregate job output budget exceeded')
            job.output_bytes += len(encoded); emit(db, job, 'OUTPUT', stream=stream, text=text); db.commit()
    def case_finished(case):
        with factory() as db:
            job = fenced_job(db, job_id, token); emit(db, job, 'CASE_RESULT', case=case); db.commit()
    try:
        with factory() as db:
            job = fenced_job(db, job_id, token)
            snapshot = db.get(ExecutionSnapshot, job.snapshot_id)
            tests, limits = job.tests, job.limits
        result = execute(snapshot, tests, limits, box_id, stop.is_set, stage, output, case_finished)
    except Exception as error:
        log.error(json.dumps({'jobId': job_id, 'event': 'infrastructure_error', 'errorType': type(error).__name__}))
        result = JobResult(status='INFRASTRUCTURE_ERROR', compilationOutput='', toolchainVersion='unavailable', cases=[], error=str(error)[:2000])
    finally:
        done.set(); thread.join(timeout=3)
    try:
        with factory() as db:
            job = fenced_job(db, job_id, token); finish(db, job, result.model_dump(mode='json')); db.commit()
    except Exception:
        log.error(json.dumps({'jobId': job_id, 'event': 'result_uncommitted_lease_recovery_required'}))


def main():
    logging.basicConfig(level=logging.INFO)
    capacity = min(16, max(1, int(os.getenv('WORKER_CONCURRENCY', '1'))))
    base_box = int(os.getenv('WORKER_BOX_ID_BASE', '100'))
    # Startup never advertises a healthy worker unless sandbox prerequisites AND deployment approval exist.
    Sandbox(base_box)
    if os.getenv('WORKER_SANDBOX_APPROVED') != '1': raise SandboxUnavailable('Run the real Linux language/security suite and approve this dedicated deployment before claiming jobs')
    with Sandbox(base_box).opened() as probe:
        result = probe.run(['/usr/bin/true'], '', limits_for('cpp20'), lambda: False, lambda *_: None)
        if result['status'] != 'FINISHED': raise SandboxUnavailable('isolate/cgroup/quota/seccomp self-test failed')
    worker_id = os.getenv('WORKER_ID', socket.gethostname()) + '-' + str(uuid4())[:8]
    factory = session_factory(make_engine())
    with ThreadPoolExecutor(max_workers=capacity) as executor:
        running = {}
        while True:
            running = {slot: future for slot, future in running.items() if not future.done()}
            with factory() as db:
                worker = db.get(ExecutionWorker, worker_id)
                if not worker: worker = ExecutionWorker(id=worker_id, capacity=capacity, sandbox='isolate/cgroup-v2'); db.add(worker)
                worker.last_seen = utcnow(); db.commit()
            for slot in range(capacity):
                if slot in running: continue
                with factory() as db:
                    job = claim(db, worker_id, capacity); db.commit()
                    if job: running[slot] = executor.submit(run_job, factory, job.id, job.lease_token, base_box + slot)
            time.sleep(0.5)


if __name__ == '__main__': main()
