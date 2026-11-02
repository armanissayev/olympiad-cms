import os
import platform
from types import SimpleNamespace
from uuid import uuid4
import pytest
from worker.app.languages import commands
from worker.app.sandbox import Sandbox, SandboxUnavailable, safe_read
from worker.app.executor import execute
from app.execution_service import limits_for


def test_native_execution_has_no_unrestricted_fallback():
    if platform.system() == 'Linux': pytest.skip('Native-denial assertion is for non-Linux hosts')
    with pytest.raises(SandboxUnavailable, match='Linux'):
        Sandbox(100)


def test_allowlisted_commands_treat_dash_prefixed_paths_as_files_not_flags():
    file_id = str(uuid4())
    config = {'language': 'cpp20', 'entryPoint': file_id}
    compile_command, _ = commands(config, [{'id': file_id, 'path': '-fplugin=evil.cpp'}, {'id': str(uuid4()), 'path': 'helper.h'}])
    assert '/box/-fplugin=evil.cpp' in compile_command
    assert 'helper.h' not in compile_command
    assert '-std=c++20' in compile_command


def test_artifact_reads_reject_symlinks_and_oversized_files(tmp_path):
    target = tmp_path / 'target'; target.write_bytes(b'abc')
    link = tmp_path / 'link'; link.symlink_to(target)
    with pytest.raises(OSError): safe_read(link, 100)
    with pytest.raises(SandboxUnavailable): safe_read(target, 2)
    assert safe_read(target, 3) == b'abc'


def test_artifact_root_cannot_be_a_symlink_to_controller_files(tmp_path):
    secret = tmp_path / 'controller'; secret.mkdir(); (secret / 'secret').write_bytes(b'not-an-artifact')
    box_path = tmp_path / 'box'; box_path.mkdir(); (box_path / '__ide_build').symlink_to(secret, target_is_directory=True)
    # Test only the file-extraction policy, not an executed participant program.
    sandbox = object.__new__(Sandbox); sandbox.box = box_path
    with pytest.raises(SandboxUnavailable, match='root'): sandbox.artifacts()


@pytest.mark.parametrize('prints_child', [False, True])
def test_isolate_init_output_resolves_participant_directory(tmp_path, monkeypatch, prints_child):
    root = tmp_path / '100'
    box = root / 'box'; box.mkdir(parents=True)
    calls = []
    def control(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=str(box if prints_child else root) + '\n')
    monkeypatch.setattr('worker.app.sandbox.subprocess.run', control)
    sandbox = object.__new__(Sandbox); sandbox.prefix = ['isolate', '--cg', '--box-id=100']
    with sandbox.opened() as opened:
        assert opened.box == box
        opened.write('main.py', b'print(5)')
        assert (box / 'main.py').read_bytes() == b'print(5)'
    assert calls[-1][-1] == '--cleanup'
    assert sandbox.box is None


def test_invalid_isolate_init_path_still_cleans_up(monkeypatch):
    calls = []
    def control(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='relative/path\n')
    monkeypatch.setattr('worker.app.sandbox.subprocess.run', control)
    sandbox = object.__new__(Sandbox); sandbox.prefix = ['isolate', '--cg', '--box-id=100']
    with pytest.raises(SandboxUnavailable, match='path'):
        with sandbox.opened(): pytest.fail('Invalid path must not be used')
    assert calls[-1][-1] == '--cleanup'


@pytest.fixture
def real_linux():
    if platform.system() != 'Linux' or os.getenv('RUN_LINUX_SANDBOX_TESTS') != '1':
        pytest.skip('Requires explicit RUN_LINUX_SANDBOX_TESTS=1 on a dedicated Linux isolate/cgroup-v2/quota host; not certified by mock tests')
    # Missing facilities are FAILURES, not skips, when the operator requests real verification.
    Sandbox(int(os.getenv('WORKER_BOX_ID_BASE', '100')))


def real_run(language, source_files, entry, stdin='', expected=None):
    files = [{'id': str(uuid4()), 'path': path, 'content': content} for path, content in source_files.items()]
    config = {'language': language, 'entryPoint': next(f['id'] for f in files if f['path'] == entry), 'includedFiles': [f['id'] for f in files], 'mainClass': 'demo.Main'}
    snapshot = SimpleNamespace(configuration=config, files=files)
    tests = [{'id': str(uuid4()), 'name': 'Real Linux program', 'stdin': stdin, 'expectedStdout': expected}]
    return execute(snapshot, tests, limits_for(language), int(os.getenv('WORKER_BOX_ID_BASE', '100')), lambda: False, lambda _: None, lambda *_: None, lambda _: None)


@pytest.mark.parametrize('language,files,entry,stdin,output,status', [
    ('cpp17', {'main.cpp': '#include <iostream>\nint main(){std::cout<<"Hello\\n";}'}, 'main.cpp', '', 'Hello\n', 'FINISHED'),
    ('cpp20', {'main.cpp': '#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}'}, 'main.cpp', '2 3\n', '5\n', 'FINISHED'),
    ('cpp20', {'main.cpp': '#include<iostream>\nint sum();int main(){std::cout<<sum();}', 'helper.cpp': 'int sum(){return 5;}'}, 'main.cpp', '', '5', 'FINISHED'),
    ('cpp17', {'main.cpp': 'not valid C++'}, 'main.cpp', '', None, 'COMPILATION_ERROR'),
    ('cpp20', {'main.cpp': 'int main(){__builtin_trap();}'}, 'main.cpp', '', None, 'RUNTIME_ERROR'),
    ('cpp20', {'main.cpp': 'int main(){while(true){asm volatile("");}}'}, 'main.cpp', '', None, 'TIME_LIMIT_EXCEEDED'),
    ('python3', {'main.py': 'print("Hello")'}, 'main.py', '', 'Hello\n', 'FINISHED'),
    ('python3', {'main.py': 'a,b=map(int,input().split());print(a+b)'}, 'main.py', '2 3\n', '5\n', 'FINISHED'),
    ('python3', {'main.py': 'from helper import value\nprint(value)', 'helper.py': 'value=7'}, 'main.py', '', '7\n', 'FINISHED'),
    ('python3', {'main.py': 'raise RuntimeError("expected exception")'}, 'main.py', '', None, 'RUNTIME_ERROR'),
    ('python3', {'main.py': 'while True: pass'}, 'main.py', '', None, 'TIME_LIMIT_EXCEEDED'),
    ('java17', {'demo/Main.java': 'package demo; public class Main {public static void main(String[] a){System.out.println("Hello");}}'}, 'demo/Main.java', '', 'Hello\n', 'FINISHED'),
    ('java17', {'demo/Main.java': 'package demo; public class Main {public static void main(String[] a){System.out.println(Helper.x);}}', 'demo/Helper.java': 'package demo; class Helper {static int x=5;}'}, 'demo/Main.java', '', '5\n', 'FINISHED'),
    ('java17', {'demo/Main.java': 'not Java'}, 'demo/Main.java', '', None, 'COMPILATION_ERROR'),
    ('java17', {'demo/Main.java': 'package demo; public class Main {public static void main(String[] a){throw new RuntimeException("expected");}}'}, 'demo/Main.java', '', None, 'RUNTIME_ERROR'),
])
def test_real_language_programs(real_linux, language, files, entry, stdin, output, status):
    result = real_run(language, files, entry, stdin, output)
    assert result.status == status, result.model_dump()
    if output is not None: assert result.cases[0].stdout == output


@pytest.mark.parametrize('source,expected', [
    ('import os\nwhile True: os.fork()', 'RUNTIME_ERROR'),
    ('import sys\nwhile True: sys.stdout.write("x"*8192);sys.stdout.flush()', 'OUTPUT_LIMIT_EXCEEDED'),
    ('import socket\nsocket.create_connection(("1.1.1.1",53),timeout=1)', 'RUNTIME_ERROR'),
    ('open("/var/local/lib/isolate/101/box/secret").read()', 'RUNTIME_ERROR'),
    ('open("/etc/olympiad/worker.env").read()', 'RUNTIME_ERROR'),
    ('def f():f()\nf()', 'RUNTIME_ERROR'),
])
def test_real_pathological_programs_are_contained(real_linux, source, expected):
    result = real_run('python3', {'main.py': source}, 'main.py')
    assert result.status == expected, result.model_dump()


def test_real_credentials_are_not_inherited(real_linux, monkeypatch):
    monkeypatch.setenv('WORKER_CREDENTIAL_SENTINEL', 'must-not-enter-sandbox')
    result = real_run('python3', {'main.py': 'import os\nassert "WORKER_CREDENTIAL_SENTINEL" not in os.environ\nassert "DATABASE_URL" not in os.environ\nprint("isolated")'}, 'main.py')
    assert result.status == 'FINISHED'
    assert result.cases[0].stdout == 'isolated\n'


def test_real_neighbor_box_files_are_hidden(real_linux):
    # Use an existing, populated neighbour, rather than a nonexistent host path.
    neighbor_id = int(os.getenv('WORKER_BOX_ID_BASE', '100')) + 1
    with Sandbox(neighbor_id).opened() as neighbor:
        neighbor.write('secret', b'other participant data')
        source = f'open({str(neighbor.box / "secret")!r}).read()'
        result = real_run('python3', {'main.py': source}, 'main.py')
        assert result.status == 'RUNTIME_ERROR', result.model_dump()


def test_real_box_disk_quota_is_enforced(real_linux):
    # Write many sub-limit files so this exercises the aggregate quota rather
    # than the per-file limit. Keep the host workload bounded even on failure.
    source = '''import errno
try:
    for i in range(96):
        with open(f"data{i}", "wb") as f:
            f.write(b"x" * (1024 * 1024))
except OSError as e:
    assert e.errno == errno.EDQUOT, e
    print("quota enforced")
else:
    raise AssertionError("sandbox disk quota was not enforced")
'''
    result = real_run('python3', {'main.py': source}, 'main.py')
    assert result.status == 'FINISHED', result.model_dump()
    assert result.cases[0].stdout == 'quota enforced\n'


def test_real_memory_exhaustion_is_bounded(real_linux):
    result = real_run('python3', {'main.py': 'x=[]\nwhile True:x.append(bytearray(1024*1024))'}, 'main.py')
    assert result.status in ('MEMORY_LIMIT_EXCEEDED', 'RUNTIME_ERROR')
    assert result.cases[0].wallTime is not None


def test_real_java_memory_overhead_is_explicitly_bounded(real_linux):
    result = real_run('java17', {'demo/Main.java': 'package demo; import java.util.*; public class Main {public static void main(String[] a){List<byte[]> x=new ArrayList<>();while(true)x.add(new byte[1024*1024]);}}'}, 'demo/Main.java')
    assert result.status in ('MEMORY_LIMIT_EXCEEDED', 'RUNTIME_ERROR')
