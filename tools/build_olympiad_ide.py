#!/usr/bin/env python3
"""Opt-in frontend build and asset staging before building the CMS wheel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true", help="Reuse dependencies from a prior successful npm ci")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    frontend = root / "olympiad_ide/frontend"
    version = subprocess.check_output(["node", "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) not in (22, 24):
        parser.error("Use Node 22 or 24 on PATH; observed " + version)
    if not args.skip_install:
        subprocess.run(["npm", "ci"], cwd=frontend, check=True)
    env = dict(os.environ, VITE_CMS_MODE="true", VITE_IDE_BASE="/ide/")
    subprocess.run(["npm", "run", "build"], cwd=frontend, env=env, check=True)
    source, target = frontend / "dist", root / "cms/server/olympiadide/static"
    manifest_path = target / ".build-manifest.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, digest in previous.items():
        file = target / name
        if not file.is_relative_to(target) or ".." in Path(name).parts:
            raise ValueError("Unsafe asset manifest")
        if file.exists() and hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError("Refusing to overwrite modified generated asset: " + name)
    for name in previous:
        (target / name).unlink(missing_ok=True)
    manifest = {}
    for file in sorted(source.rglob("*")):
        if not file.is_file():
            continue
        if file.is_symlink():
            raise ValueError("Symlink in frontend build")
        relative = file.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError("Refusing to overwrite untracked asset: " + str(relative))
        shutil.copyfile(file, destination)
        manifest[relative.as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("Staged %d public frontend assets for CMS packaging; no Node requirement added to ordinary CMS installation." % len(manifest))


if __name__ == "__main__":
    main()
