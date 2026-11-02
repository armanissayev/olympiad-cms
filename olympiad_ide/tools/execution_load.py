"""Real HTTP queue workload; no simulated execution results. Run only on a dedicated test deployment."""
import argparse
import asyncio
import json
import statistics
import time
from uuid import uuid4
import httpx


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--participants', type=int, default=10)
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.participants <= 300: parser.error('participants must be 1..300; benchmark progressively')
    # Import shared canonical hashing without creating the API app or executing code locally.
    from app.telemetry import digest
    async def participant():
        async with httpx.AsyncClient(base_url=args.url, timeout=10) as client:
            await client.post('/api/v1/session')
            workspace_id, file_id, config_id = (str(uuid4()) for _ in range(3))
            timestamp = '2026-10-20T00:00:00Z'
            source = 'print(sum(map(int,input().split())))\n'
            document = {'name': 'Execution load test', 'nodes': {file_id: {'id': file_id, 'parentId': None, 'type': 'file', 'name': 'main.py', 'language': 'python', 'documentRevision': 1, 'content': source, 'createdAt': timestamp, 'updatedAt': timestamp}}, 'settings': {}, 'editorState': {}}
            response = await client.post('/api/v1/workspaces', json={'id': workspace_id, 'document': document}); response.raise_for_status()
            configuration = {'kind': 'configuration', 'id': config_id, 'name': 'Load Python', 'language': 'python3', 'entryPoint': file_id, 'includedFiles': [file_id], 'compilerProfile': 'release', 'mainClass': None, 'defaultTestId': None}
            files = [{'id': file_id, 'path': 'main.py', 'content': source}]
            body = {'id': str(uuid4()), 'workspaceId': workspace_id, 'files': files, 'configuration': configuration, 'sourceHash': digest({'files': files, 'configuration': configuration}), 'tests': [{'kind': 'test', 'id': str(uuid4()), 'name': 'sum', 'stdin': '2 3\n', 'expectedStdout': '5\n'}]}
            started = time.monotonic()
            response = await client.post('/api/v1/executions', json=body)
            admitted = time.monotonic() - started
            if response.status_code != 201: return {'admitted': False, 'httpStatus': response.status_code, 'apiSeconds': admitted}
            deadline = time.monotonic() + args.timeout
            job = response.json()
            while job['status'] in ('QUEUED', 'PREPARING', 'COMPILING', 'RUNNING') and time.monotonic() < deadline:
                await asyncio.sleep(1)
                response = await client.get('/api/v1/executions/' + body['id']); response.raise_for_status(); job = response.json()
            from datetime import datetime
            wait = (datetime.fromisoformat(job['startedAt']) - datetime.fromisoformat(job['createdAt'])).total_seconds() if job['startedAt'] else None
            return {'admitted': True, 'apiSeconds': admitted, 'status': job['status'], 'queueWaitSeconds': wait, 'compilationSeconds': job['result']['compilationSeconds'] if job['result'] else None, 'caseMetrics': job['result']['cases'] if job['result'] else None}
    results = await asyncio.gather(*(participant() for _ in range(args.participants)))
    durations = sorted(r['apiSeconds'] for r in results)
    print(json.dumps({'participants': args.participants, 'apiMedianSeconds': statistics.median(durations), 'apiP95Seconds': durations[int(.95 * (len(durations) - 1))], 'results': results}, indent=2))


if __name__ == '__main__': asyncio.run(main())
