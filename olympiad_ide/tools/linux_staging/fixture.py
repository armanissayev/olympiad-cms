"""Create only the dedicated empty Linux staging contest; never use on a live DB."""
import argparse,json,os,secrets
from datetime import timedelta
from pathlib import Path
from cms import config,FEEDBACK_LEVEL_RESTRICTED,TOKEN_MODE_FINITE
from cms.db import Admin,Attachment,Contest,Dataset,Participation,SessionGen,Statement,Task,Testcase,User,engine,init_db
from cms.db.filecacher import FileCacher
from cmscommon.crypto import hash_password
from cmscommon.datetime import make_datetime


def pdf(text):
    stream=('BT /F1 14 Tf 40 760 Td ('+text.replace('(','\\(').replace(')','\\)')+') Tj ET').encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=b'%PDF-1.4\n';offsets=[0]
    for index,item in enumerate(objects,1):
        offsets.append(len(data));data+=str(index).encode()+b' 0 obj\n'+item+b'\nendobj\n'
    xref=len(data);data+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets[1:])
    return data+b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF\n'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--add-load-participants',type=int,default=0);args=parser.parse_args()
    assert str(engine.url.database)=='cmside_linux_fortesting'
    assert engine.url.query.get('host')=='/run/cms-ide-stage-pg'
    assert engine.url.query.get('port')=='15432'
    out=Path('/var/lib/cms-ide-stage/fixture')
    if args.add_load_participants:
        assert 1<=args.add_load_participants<=350
        with SessionGen() as db:
            contest=db.query(Contest).filter_by(name='ide-load-linux-staging').one()
            assert db.query(User).filter(User.username.like('stage-load-%')).count()==0
            creds=[]
            for index in range(args.add_load_participants):
                username=f'stage-load-{index+1:03d}';password=secrets.token_urlsafe(24)
                user=User(username=username,password=hash_password(password),first_name='Load',last_name=str(index+1))
                db.add(Participation(contest=contest,user=user));creds.append({'username':username,'password':password,'taskId':contest.tasks[0].id})
            db.commit()
        path=out/'load-credentials.json';path.write_text(json.dumps(creds));path.chmod(0o600)
        print(json.dumps({'loadParticipantsCreated':len(creds)}));return
    assert not engine.table_names(), 'New empty dedicated DB required'
    init_db();files=FileCacher();now=make_datetime();password=secrets.token_urlsafe(24);admin_password=secrets.token_urlsafe(24)
    with SessionGen() as db:
        contest=Contest(name='ide-load-linux-staging',description='Disposable native CMS Linux acceptance',start=now-timedelta(minutes=10),stop=now+timedelta(days=2),languages=['C++17 / g++','C++20 / g++','Python 3 / CPython'],token_mode=TOKEN_MODE_FINITE,token_gen_initial=2,token_gen_number=0,token_gen_max=2)
        user=User(username='staging-participant',password=hash_password(password),first_name='Linux',last_name='Participant')
        db.add_all([contest,Participation(contest=contest,user=user),Admin(username='staging-admin',name='Staging administrator',authentication=hash_password(admin_password),permission_all=True)])
        for index,name in enumerate(['cppsum','pysum']):
            task=Task(contest=contest,num=index,name=name,title='Integer sum — '+('C++' if index==0 else 'Python'),submission_format=['main.%l'],primary_statements=['en'],feedback_level=FEEDBACK_LEVEL_RESTRICTED,token_mode=TOKEN_MODE_FINITE,token_gen_initial=2,token_gen_number=0,token_gen_max=2)
            data=Dataset(task=task,description='original',task_type='Batch',task_type_parameters=['alone',['',''],'diff'],score_type='Sum',score_type_parameters=25,time_limit=2.0,memory_limit=256*1024*1024)
            task.active_dataset=data
            cases=[('sample','2 3\n','5\n',True),('hidden-a','1234567 7654321\n','8888888\n',False),('hidden-b','-4000000 17\n','-3999983\n',False),('hidden-c','9999999999 1\n','10000000000\n',False)]
            for code,stdin,stdout,public in cases:
                Testcase(dataset=data,codename=code,public=public,input=files.put_file_content(stdin.encode(),'staging judge input'),output=files.put_file_content(stdout.encode(),'staging judge output'))
            Statement(task=task,language='en',digest=files.put_file_content(pdf('Read two signed integers and print their sum. Sample: 2 3 -> 5.'),'staging public statement'))
            Attachment(task=task,filename='sample.txt',digest=files.put_file_content(b'Input: 2 3\nOutput: 5\n','staging public sample'))
            db.add(task)
        db.commit()
        metadata={'kind':'disposable-linux-staging','baseUrl':'https://localhost:28443','adminUrl':'https://localhost:28444','rankingUrl':'https://localhost:28445','certificate':'/etc/cms-ide-stage/localhost.crt','username':user.username,'password':password,'adminUsername':'staging-admin','adminPassword':admin_password,'contestId':contest.id,'contestName':contest.name,'installationId':config.olympiad_ide_installation_id,'tasks':[{'id':t.id,'name':t.name,'datasetId':t.active_dataset_id} for t in contest.tasks]}
        p=out/'browser.json';p.write_text(json.dumps(metadata,indent=2)+'\n');p.chmod(0o600)
        print(json.dumps({'createdContest':contest.id,'tasks':len(contest.tasks),'publicCases':2,'hiddenCases':6,'user':user.username,'secrets':'protected fixture file only'}))

if __name__=='__main__':main()
