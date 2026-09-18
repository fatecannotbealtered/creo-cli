"""Informational source-process timings, NOT a Creo/native performance claim."""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output');p.add_argument('--runs',type=int,default=5);a=p.parse_args()
if not 1<=a.runs<=50:p.error('runs must be 1..50')
rows=[]
with tempfile.TemporaryDirectory() as tmp:
    env=dict(os.environ,CREO_CLI_CONFIG_DIR=tmp)
    for args in (['context','--compact'],['reference','--compact'],['reference','--command','model dimensions','--compact'],['snapshot','validate','--input','examples/bracket.creo.json','--compact']):
        times=[];sizes=[]
        for _ in range(a.runs):
            t=time.perf_counter();r=subprocess.run([sys.executable,'-m','creo_cli',*args],cwd=ROOT,env=env,capture_output=True,timeout=10,check=True)
            assert json.loads(r.stdout)['ok']
            times.append((time.perf_counter()-t)*1000);sizes.append(len(r.stdout))
        rows.append({'command':' '.join(args),'runs':a.runs,'median_ms':round(statistics.median(times),3),'max_ms':round(max(times),3),'stdout_bytes':max(sizes)})
doc={'python':platform.python_version(),'platform':platform.platform(),'native_measured':False,'measurements':rows,'note':'Repeated fresh Python processes, warm filesystem caches; not a cold-machine or native CAD benchmark.'}
text=json.dumps(doc,indent=2)+'\n'
if a.output:Path(a.output).write_text(text,encoding='utf-8')
print(text,end='')
