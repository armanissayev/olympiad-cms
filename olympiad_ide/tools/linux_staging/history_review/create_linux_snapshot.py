import hashlib,json,os,shutil,sys,tarfile
from pathlib import Path,PurePosixPath
assert os.geteuid()==0
stage=Path('/opt/cms-ide-stage');live=stage/'source'
assert (stage/'AUTHORIZED_DISPOSABLE').is_file()
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
 members=iter(archive)
 first=next(members)
 assert first.name=='HISTORY_DELTA.json' and first.isfile() and first.size<100000
 manifest=json.loads(archive.extractfile(first).read())
 commit=manifest['commit'];assert len(commit)==40 and all(c in '0123456789abcdef' for c in commit)
 assert (stage/'SOURCE_COMMIT').read_text().strip()==manifest['previousApplicationCommit']
 records={item['path']:item for item in manifest['files']};assert len(records)==13
 for name,item in records.items():
  path=PurePosixPath(name);assert not path.is_absolute() and '..' not in path.parts
  assert name.startswith(('cms/server/admin/','cmstestsuite/unit_tests/server/olympiadide/','olympiad_ide/backend/app/','olympiad_ide/backend/tests/','olympiad_ide/frontend/tools/','docs/olympiad-ide/'))
  target=live/name;assert not target.is_symlink()
  if item['previousSha256'] is None:assert not target.exists(),name
  else:assert hashlib.sha256(target.read_bytes()).hexdigest()==item['previousSha256'],name
 location=stage/'verification'/('file-history-'+commit[:12]);location.mkdir(parents=True,exist_ok=False)
 source=location/'source'
 shutil.copytree(live,source,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','node_modules','.git'))
 written=set()
 for member in members:
  assert member.isfile() and member.name in records and member.name not in written
  data=archive.extractfile(member).read();assert hashlib.sha256(data).hexdigest()==records[member.name]['sha256']
  target=source/member.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(0o644);written.add(member.name)
 assert written==set(records)
 (location/'delta-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'status':'verification-copy-ready','source':str(source),'commit':commit,'liveSourceChanged':False}))
