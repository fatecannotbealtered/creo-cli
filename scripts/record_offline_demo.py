"""Record a real subprocess mock loop, excluding tokens and temporary paths."""
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
records=[]
with tempfile.TemporaryDirectory() as tmp:
    work=Path(tmp);model=work/'bracket.creo.json';change=work/'change.json'
    model.write_bytes((ROOT/'examples/bracket.creo.json').read_bytes());change.write_bytes((ROOT/'examples/change.json').read_bytes())
    env=dict(os.environ,CREO_CLI_CONFIG_DIR=str(work/'state'),CREO_CLI_PERMISSION='write')
    def sanitize(value):
        if isinstance(value,dict):return {k:'[one-time token omitted]' if k=='confirm_token' else sanitize(v) for k,v in value.items()}
        if isinstance(value,list):return [sanitize(v) for v in value]
        if isinstance(value,str):return value.replace(str(work),'$WORK')
        return value
    def call(args,expected=0):
        p=subprocess.run([sys.executable,'-m','creo_cli',*map(str,args),'--compact'],cwd=ROOT,env=env,capture_output=True,timeout=15)
        body=json.loads(p.stdout)
        if p.returncode!=expected or len(p.stdout.splitlines())!=1:raise RuntimeError((p.returncode,body))
        safe=list(map(str,args))
        if '--confirm' in safe:safe[safe.index('--confirm')+1]='[one-time token omitted]'
        records.append({'command':['python','-m','creo_cli',*sanitize(safe),'--compact'],'exit_code':p.returncode,'stdout':sanitize(body)})
        return body
    before=call(['model','snapshot','--backend','mock','--model',model])
    call(['change','validate','--changeset',change])
    call(['change','preview','--backend','mock','--model',model,'--changeset',change])
    args=['change','apply','--backend','mock','--model',model,'--changeset',change]
    token=call([*args,'--dry-run'])['data']['confirm_token']
    result=call([*args,'--confirm',token])
    after=call(['model','snapshot','--backend','mock','--model',model])
    call(['change','history'])
    call([*args,'--confirm',token],6)
    assert before['data']['dimensions'][1]['value']==40
    assert after['data']['dimensions'][1]['value']==45
    assert Path(result['data']['backup']).is_file()
    doc={'ok':True,'backend':'mock','simulation':True,'native_live_verified':False,'before_hole_pitch':40,'after_hole_pitch':45,
         'subprocess_calls':len(records),'note':'Actual source CLI processes against JSON fixtures, not CAD geometry. Replay also encounters a changed expected value; atomic-ledger replay is independently tested in the suite.','records':records}
text=json.dumps(doc,ensure_ascii=False,indent=2)+'\n'
(ROOT/'docs/evidence/offline-demo.json').write_text(text,encoding='utf-8')
print(json.dumps({k:v for k,v in doc.items() if k!='records'},indent=2))
