import os
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx

from test_persistence import document, operation
from test_telemetry import setup_session, event, batch
from test_execution import submission


def test_acknowledged_workspace_survives_backend_process_restart(api):
    # The fixture migrates a dedicated PostgreSQL schema. Both real API processes use it.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]

    def start():
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=0.2).status_code == 200:
                    return process
            except httpx.TransportError:
                pass
            time.sleep(0.05)
        process.terminate()
        process.wait(timeout=5)
        raise AssertionError("Backend process failed to become ready")

    process = start()
    wid = str(uuid4())
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            assert client.post("/api/v1/session").status_code == 200
            assert client.post("/api/v1/sync/batches", json={"operations": [operation(wid, document())]}).status_code == 200
            sid, telemetry_wid, fid, _, _ = setup_session(client)
            telemetry_batch = batch(sid, [event(sid, telemetry_wid, fid)])
            acknowledgement = client.post('/api/v1/telemetry/batches', json=telemetry_batch)
            assert acknowledgement.status_code == 200, acknowledgement.text
            execution = submission(client)
            submitted = client.post('/api/v1/executions', json=execution)
            assert submitted.status_code == 201, submitted.text
            process.terminate()
            process.wait(timeout=5)
            process = start()
            response = client.get(f"/api/v1/workspaces/{wid}")
            assert response.status_code == 200
            assert response.json()["revision"] == 1
            assert len(response.json()["document"]["nodes"]) == 2
            assert client.post('/api/v1/telemetry/batches', json=telemetry_batch).json() == acknowledgement.json()
            assert client.get(f'/api/v1/telemetry/sessions/{sid}/status').json()['lastSequence'] == 1
            assert len(client.get(f'/api/v1/telemetry/sessions/{sid}/events').json()['events']) == 1
            assert client.post('/api/v1/executions', json=execution).json() == submitted.json()
            assert client.get(f"/api/v1/executions/{execution['id']}").json()['status'] == 'QUEUED'
    finally:
        process.terminate()
        process.wait(timeout=5)
