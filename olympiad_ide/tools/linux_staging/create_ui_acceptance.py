from pathlib import Path
import json,os,secrets
from datetime import datetime,timezone
from cms import config
from cms.db import SessionGen,Contest,Participation,User,engine
from cmscommon.crypto import hash_password
os.umask(0o077)
assert str(engine.url.database)=='cms_restore_21c7bd2d5bfortesting'
assert engine.url.query.get('host')=='/run/cms-ide-stage-pg' and str(engine.url.query.get('port'))=='15432'
path=Path('/var/lib/cms-ide-stage/fixture/ui-acceptance.json')
assert not path.exists(),'Refuses to replace existing fixture'
original=json.loads(Path('/var/lib/cms-ide-stage/fixture/browser.json').read_text())
assert original['kind']=='disposable-linux-staging' and config.olympiad_ide_installation_id==original['installationId']
username='ui-acceptance-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
password=secrets.token_urlsafe(24)
with SessionGen() as db:
 contest=db.query(Contest).filter(Contest.id==original['contestId'],Contest.name=='ide-load-linux-staging').one()
 assert {t.name for t in contest.tasks}=={'cppsum','pysum'}
 assert db.query(User).filter(User.username==username).first() is None
 user=User(username=username,password=hash_password(password),first_name='Interface',last_name='Acceptance')
 db.add(Participation(contest=contest,user=user));db.commit()
 original.update(username=username,password=password,baseUrl='https://54.206.171.67',certificate='/private/tmp/cms-linux-staging/localhost.crt',acceptanceUserId=user.id)
 path.write_text(json.dumps(original,indent=2)+'\n');path.chmod(0o600)
print(json.dumps({'createdDisposableActor':username,'existingAccountsChanged':False,'fixture':'protected ui-acceptance.json'}))
