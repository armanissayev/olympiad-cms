"""Repair only freshly installed application code, never dependencies, config or keys."""
from pathlib import Path
import csv,os,stat,subprocess
root=Path('/opt/cms-ide-stage');site=root/'cms-venv/lib/python3.12/site-packages';source=root/'source'
packages=[(site/name,source/name) for name in ['cms','cmscommon','cmscontrib','cmsranking']]
packages.append((root/'runtime-venv/lib/python3.12/site-packages/app',source/'olympiad_ide/backend/app'))
for installed,src in packages:
 assert installed.is_dir() and src.is_dir()
 for file in installed.rglob('*.py'):
  assert not file.is_symlink()
  original=src/file.relative_to(installed)
  assert original.is_file() and file.read_bytes()==original.read_bytes(),str(file)
# CMS distribution metadata is public package metadata; no other distributions are touched.
paths=[p for p,_ in packages]+[site/'cms-1.5.1.dist-info']
for folder in paths:
 assert folder.is_dir() and not folder.is_symlink()
 for file in [folder,*folder.rglob('*')]:
  assert not file.is_symlink(),str(file)
  current=file.stat().st_mode
  file.chmod((current & 0o700) | (0o055 if file.is_dir() or current&0o111 else 0o044))
record=site/'cms-1.5.1.dist-info/RECORD'
for row in csv.reader(record.read_text().splitlines()):
 path=row[0]
 if path.startswith('../../../bin/cms'):
  file=(site/path).resolve();assert file.parent==root/'cms-venv/bin' and file.name.startswith('cms');file.chmod(0o755)
print('Only CMS/app package code, CMS metadata and CMS launchers repaired; source .py byte comparisons passed')
