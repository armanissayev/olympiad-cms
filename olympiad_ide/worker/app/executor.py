from app.execution_schema import JobResult, CaseResult
from app.execution_service import compare
from .languages import commands, version_command
from .sandbox import Sandbox


def execute(snapshot, tests, limits, box_id, cancelled, stage, output, case_finished):
    configuration, files = snapshot.configuration, snapshot.files
    compile_command, run_command = commands(configuration, files)
    diagnostics, compile_seconds, artifacts = '', None, {}
    remaining = limits['outputBytes']
    output_exceeded = False
    def bounded_output(stream, text):
        nonlocal remaining, output_exceeded
        encoded = text.encode()
        if len(encoded) > remaining:
            output_exceeded = True
            text = encoded[:remaining].decode('utf-8', errors='ignore')
        remaining -= len(text.encode())
        if text: output(stream, text)
    # Toolchain version is measured inside the same sandbox, never fabricated.
    with Sandbox(box_id).opened() as box:
        measured = box.run(version_command(configuration['language']), '', limits, cancelled, lambda *_: None, compilation=True)
        if measured['status'] != 'FINISHED': raise RuntimeError('Toolchain version probe failed')
        version = (measured['stdout'] + measured['stderr']).strip()[:500]
        if configuration['language'] == 'java17' and 'version "17' not in version:
            raise RuntimeError('Configured Java runtime is not Java 17')
    if compile_command:
        stage('COMPILING')
        with Sandbox(box_id).opened() as box:
            for file in files: box.write(file['path'], file['content'].encode())
            (box.box / '__ide_build').mkdir(); (box.box / '__ide_build').chmod(0o777)
            result = box.run(compile_command, '', {**limits, 'outputBytes': remaining}, cancelled, bounded_output, compilation=True)
            if output_exceeded: result['status'] = 'OUTPUT_LIMIT_EXCEEDED'
            diagnostics = result['stdout'] + result['stderr']; compile_seconds = result['wallTime']
            if result['status'] != 'FINISHED':
                status = result['status'] if result['status'] in ('CANCELLED', 'INFRASTRUCTURE_ERROR', 'OUTPUT_LIMIT_EXCEEDED') else 'COMPILATION_ERROR'
                return JobResult(status=status, compilationOutput=diagnostics, compilationSeconds=compile_seconds, toolchainVersion=version, cases=[])
            artifacts = box.artifacts()
    stage('RUNNING')
    results = []
    for test in tests:
        if cancelled(): break
        with Sandbox(box_id).opened() as box:
            for file in files: box.write(file['path'], file['content'].encode())
            if artifacts:
                root = box.box / '__ide_build'; root.mkdir(mode=0o777)
                for path, data in artifacts.items():
                    # Validated regular-file output from a completed, no-longer-running build sandbox.
                    target = root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data); target.chmod(0o755)
            result = box.run(run_command, test['stdin'], {**limits, 'outputBytes': remaining}, cancelled, bounded_output)
            if output_exceeded: result['status'] = 'OUTPUT_LIMIT_EXCEEDED'
            case = CaseResult(testId=test['id'], name=test['name'], **result, expectedStdout=test['expectedStdout'], verdict=compare(result['status'], result['stdout'], test['expectedStdout']))
            results.append(case); case_finished(case)
        if result['status'] in ('CANCELLED', 'INFRASTRUCTURE_ERROR'): break
    status = 'CANCELLED' if cancelled() else next((c.status for c in results if c.status != 'FINISHED'), 'FINISHED')
    return JobResult(status=status, compilationOutput=diagnostics, compilationSeconds=compile_seconds, toolchainVersion=version, cases=results)
