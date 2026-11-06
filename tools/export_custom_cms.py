#!/usr/bin/env python3
"""Export committed CMS source plus freshly built IDE assets, without local state."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New output directory outside the checkout')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.is_relative_to(root) or output.exists():
        parser.error('Use a new output directory outside the checkout')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root):
        parser.error('Commit or preserve outstanding changes before exporting')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    subprocess.run([sys.executable, str(root/'tools/build_olympiad_ide.py')], cwd=root, check=True)
    assets = root/'cms/server/olympiadide/static'
    manifest = json.loads((assets/'.build-manifest.json').read_text())
    for name, sha in manifest.items():
        file = assets/name
        if '..' in Path(name).parts or Path(name).is_absolute() or file.is_symlink():
            raise ValueError('Unsafe asset path')
        if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
            raise ValueError('Asset integrity failure: '+name)
    output.mkdir(mode=0o700, parents=True)
    source = output/'cms-source.tar'
    subprocess.run(['git', 'archive', '--format=tar', '--output='+str(source), commit], cwd=root, check=True)
    bundle = output/'ide-assets.tar'
    with tarfile.open(bundle, 'w') as archive:
        for name in ['.build-manifest.json', *sorted(manifest)]:
            archive.add(assets/name, arcname='cms/server/olympiadide/static/'+name, recursive=False)
    (output/'source-commit.txt').write_text(commit+'\n')
    (output/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (source,bundle)))
    print('Exported '+commit+' to '+str(output))


if __name__ == '__main__':
    main()
