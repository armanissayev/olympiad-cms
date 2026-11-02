"""Allowlisted argument vectors only; no shell or participant-supplied compiler switches."""
from pathlib import Path


def java_binary(name):
    # Debian alternatives point through /etc, which is deliberately not mounted into the sandbox.
    resolved = Path('/usr/bin/' + name).resolve()
    if not str(resolved).startswith('/usr/'): raise ValueError('Java toolchain must be installed under the read-only /usr tree')
    return str(resolved)


def commands(configuration, files):
    language = configuration['language']
    entry = next(f['path'] for f in files if f['id'] == configuration['entryPoint'])
    if language in ('cpp17', 'cpp20'):
        sources = ['/box/' + f['path'] for f in files if f['path'].endswith(('.cpp', '.cc', '.cxx'))]
        return ['/usr/bin/g++', '-std=c++' + language[3:], '-O2', '-pipe', '-I/box', *sources, '-o', '__ide_build/program'], ['/box/__ide_build/program']
    if language == 'python3': return None, ['/usr/bin/python3', '-B', '/box/' + entry]
    if language == 'java17':
        return [java_binary('javac'), '-J-Xmx512m', '-encoding', 'UTF-8', '-d', '__ide_build', *['/box/' + f['path'] for f in files if f['path'].endswith('.java')]], [
            java_binary('java'), '-Xmx256m', '-Xss256k', '-XX:MaxMetaspaceSize=96m', '-XX:ReservedCodeCacheSize=32m', '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC', '-cp', '/box/__ide_build', configuration['mainClass']]
    raise ValueError('Unsupported language')


def version_command(language):
    return ['/usr/bin/g++', '--version'] if language.startswith('cpp') else ['/usr/bin/python3', '--version'] if language == 'python3' else [java_binary('java'), '-version']
