"""Linux isolate adapter. No unrestricted/native subprocess fallback exists."""
import os
import codecs
import platform
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager


class SandboxUnavailable(RuntimeError): pass


def safe_read(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise SandboxUnavailable('Unsafe/oversized sandbox artifact')
        with os.fdopen(fd, 'rb', closefd=False) as file: return file.read(limit + 1)
    finally: os.close(fd)


class Sandbox:
    def __init__(self, box_id):
        if platform.system() != 'Linux': raise SandboxUnavailable('Execution requires a verified Linux isolate worker; native execution is forbidden')
        self.binary = shutil.which('isolate')
        if not self.binary: raise SandboxUnavailable('isolate is not installed')
        info = Path(self.binary).stat()
        if info.st_uid != 0 or not info.st_mode & stat.S_ISUID or info.st_mode & 0o022: raise SandboxUnavailable('isolate must be a non-writable root-owned setuid helper; worker itself must be non-root')
        if os.getuid() == 0: raise SandboxUnavailable('Worker control process must not run as root')
        if not Path('/sys/fs/cgroup/cgroup.controllers').exists(): raise SandboxUnavailable('cgroup v2 is required')
        if len(Path('/proc/swaps').read_text().splitlines()) > 1: raise SandboxUnavailable('Disable swap before enabling worker memory enforcement')
        self.box_id = box_id
        self.prefix = [self.binary, '--cg', f'--box-id={box_id}']
        self.control = None
        self.box = None

    @contextmanager
    def opened(self):
        # Only isolate --init chooses the sandbox directory. No source path can select host paths.
        with tempfile.TemporaryDirectory(prefix='olympiad-control-') as control:
            self.control = Path(control)
            initialized = subprocess.run([*self.prefix, '--quota=65536,1024', '--init'], capture_output=True, text=True, timeout=10, check=True)
            try:
                # isolate 2.7 prints the box's root; participant files live in its
                # box/ child. Older releases printed that child directly.
                root = Path(initialized.stdout.strip())
                if not root.is_absolute() or root.is_symlink(): raise SandboxUnavailable('Unexpected isolate box path')
                self.box = root if root.name == 'box' else root / 'box'
                if not self.box.is_absolute() or self.box.name != 'box' or self.box.is_symlink(): raise SandboxUnavailable('Unexpected isolate box path')
                if not self.box.is_dir(): raise SandboxUnavailable('Missing isolate box directory')
                yield self
            finally:
                subprocess.run([*self.prefix, '--cleanup'], capture_output=True, timeout=10, check=True)
                self.box = None

    def write(self, path, data):
        from app.execution_schema import safe_path
        safe_path(path)
        target = self.box / path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Only called before participant code runs in this NEW box.
        with target.open('xb') as file: file.write(data)
        target.chmod(0o644)

    def run(self, command, stdin, limits, cancelled, output, compilation=False):
        if not self.box: raise SandboxUnavailable('Sandbox is not initialized')
        # This name is reserved by the API and cannot collide with a participant file.
        input_path = self.box / '__ide_input'
        input_path.write_bytes(stdin.encode())
        meta = self.control / 'metadata'
        wall = limits['compileWallSeconds'] if compilation else limits['wallSeconds']
        memory = limits['compileMemoryKiB'] if compilation else limits['memoryKiB']
        args = [*self.prefix, '--silent', '--syscalls=31', f'--meta={meta}', '--chdir=/box', '--stdin=/box/__ide_input',
            f'--time={wall if compilation else limits["cpuSeconds"]}', f'--wall-time={wall}', f'--cg-mem={memory}',
            f'--processes={64 if compilation else limits["maxProcesses"]}', '--open-files=64', '--core=0',
            f'--fsize={64 * 1024 if compilation else 1024}', '--env=PATH=/usr/bin:/bin', '--env=HOME=/box', '--env=LANG=C.UTF-8',
            '--env=PYTHONPATH=/box', '--env=TMPDIR=/box', '--run', '--', *command]
        if Path('/etc/java-17-openjdk').is_dir():
            args.insert(len(self.prefix), '--dir=etc/java-17-openjdk=/etc/java-17-openjdk')
        # stdout/stderr are inherited bounded pipes, never participant-created paths/symlinks.
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env={'PATH': '/usr/bin:/bin'})
        selector = selectors.DefaultSelector()
        streams = {'stdout': bytearray(), 'stderr': bytearray()}
        decoders = {name: codecs.getincrementaldecoder('utf-8')('replace') for name in streams}
        selector.register(process.stdout, selectors.EVENT_READ, 'stdout'); selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
        status = None
        deadline = time.monotonic() + wall + 3
        try:
            while selector.get_map():
                if cancelled(): status = 'CANCELLED'
                elif time.monotonic() > deadline: status = 'INFRASTRUCTURE_ERROR'
                if status:
                    process.terminate()
                    break
                for key, _ in selector.select(0.1):
                    data = os.read(key.fileobj.fileno(), 8192)
                    if not data: selector.unregister(key.fileobj); continue
                    remaining = limits['outputBytes'] - sum(len(v) for v in streams.values())
                    accepted = data[:max(0, remaining)]
                    streams[key.data].extend(accepted)
                    decoded = decoders[key.data].decode(accepted)
                    if decoded: output('compiler' if compilation else key.data, decoded)
                    if len(data) > remaining: status = 'OUTPUT_LIMIT_EXCEEDED'; process.terminate(); break
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
        finally:
            selector.close()
            if process.poll() is None: process.kill(); process.wait(timeout=2)
            process.stdout.close(); process.stderr.close()
        for name, decoder in decoders.items():
            tail = decoder.decode(b'', final=True)
            if tail: output('compiler' if compilation else name, tail)
        metadata = dict(line.split(':', 1) for line in meta.read_text().splitlines() if ':' in line) if meta.exists() else {}
        if not status:
            if process.returncode not in (0, 1) or metadata.get('status') == 'XX' or not metadata: status = 'INFRASTRUCTURE_ERROR'
            elif 'cg-oom-killed' in metadata: status = 'MEMORY_LIMIT_EXCEEDED'
            elif metadata.get('status') == 'TO': status = 'TIME_LIMIT_EXCEEDED'
            elif metadata.get('exitsig') == '25': status = 'OUTPUT_LIMIT_EXCEEDED'
            elif metadata.get('status') in ('RE', 'SG') or metadata.get('exitcode', '0') != '0': status = 'COMPILATION_ERROR' if compilation else 'RUNTIME_ERROR'
            else: status = 'FINISHED'
        number = lambda key, cast: cast(metadata[key]) if key in metadata else None
        return {'status': status, 'stdout': bytes(streams['stdout']).decode('utf-8', errors='replace'), 'stderr': bytes(streams['stderr']).decode('utf-8', errors='replace'),
            'exitCode': number('exitcode', int), 'cpuTime': number('time', float), 'wallTime': number('time-wall', float),
            'peakMemoryKiB': number('cg-mem', int)}

    def artifacts(self):
        root = self.box / '__ide_build'
        if root.is_symlink() or not root.is_dir(): raise SandboxUnavailable('Unsafe build artifact root')
        result = {}
        total = 0
        def visit(directory):
            nonlocal total
            for entry in os.scandir(directory):
                if entry.is_symlink(): raise SandboxUnavailable('Symlink artifact rejected')
                if entry.is_dir(follow_symlinks=False): visit(Path(entry.path))
                else:
                    data = safe_read(entry.path, 16_000_000)
                    total += len(data)
                    if total > 32_000_000 or len(result) >= 1000: raise SandboxUnavailable('Build artifact budget exceeded')
                    result[str(Path(entry.path).relative_to(root))] = data
        visit(root)
        return result
