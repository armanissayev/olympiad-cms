import hashlib,json,os,sys,tarfile
from pathlib import Path
assert os.geteuid()==0
stage=Path('/opt/cms-ide-stage');source=stage/'source'
assert (stage/'SOURCE_COMMIT').read_text().strip()=='84f42f02aa872b01a77c6280695f077437fa2a07'
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
 members=iter(archive);first=next(members);assert first.name=='NOTES_DELTA.json' and first.isfile()
 meta=json.loads(archive.extractfile(first).read());assert meta['commit']=='505c1a4b401da9662775efa3020621dfca344349'
 expected={row['path']:row for row in meta['files']}
 assert set(expected)=={'cms/server/admin/static/ide_history.js','cms/server/admin/templates/ide_history.html','olympiad_ide/frontend/tools/verify-file-history-ui.cjs'}
 location=stage/'verification/file-history-notes-505c1a4b401d';location.mkdir(exist_ok=False)
 saved=location/'source-before';saved.mkdir()
 for name,row in expected.items():
  target=source/name;assert not target.is_symlink() and hashlib.sha256(target.read_bytes()).hexdigest()==row['previousSha256']
  backup=saved/name;backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(target.read_bytes())
 seen=set()
 for member in members:
  assert member.isfile() and member.name in expected and member.name not in seen
  data=archive.extractfile(member).read();assert hashlib.sha256(data).hexdigest()==expected[member.name]['sha256']
  target=source/member.name;target.write_bytes(data);target.chmod(0o644);seen.add(member.name)
 assert seen==set(expected)
 (location/'notes-manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
print('COMPACT_NOTES_SOURCE_READY; INSTALLED_NATIVE_PACKAGE_UNCHANGED')
