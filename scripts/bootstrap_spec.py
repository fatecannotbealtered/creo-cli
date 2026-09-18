"""Vendor the EXACT immutable spec files. No paraphrased normative substitutes.

All downloads validate Git blob identities before any target files are changed.
--from uses `git show` at the known commit, not an editable working tree.
The final lock is written last; --check refuses partial/inconsistent installs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPO='fatecannotbealtered/ai-native-cli-spec'
PIN='abbebfdf03dbfa28d1378b2fe3dd55ac34b22981'
TAG='v1.6.2'
PATHS=['.agent/'+x+suffix+'.md' for x in ('AGENT','CLI-SPEC','SEC-SPEC','SKILL-SPEC') for suffix in ('','_zh')]+['contract/contract.json']+['scripts/'+x+'.js' for x in ('spec-files','gen-contract','sync-spec','check-spec')]

def blob_hash(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'creo-cli-spec-bootstrap','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=20) as r:
        raw=r.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('upstream response exceeds size ceiling')
    return raw

def check(root=ROOT):
    lock=root/'.agent/SPEC_LOCK.json'
    if not lock.is_file():return ['.agent/SPEC_LOCK.json (exact upstream files are not vendored yet)']
    data=json.loads(lock.read_bytes())
    if data.get('commit')!=PIN or set(data.get('files',{}))!=set(PATHS):return ['invalid/incomplete spec lock']
    return [rel for rel in PATHS if not (root/rel).is_file() or blob_hash((root/rel).read_bytes())!=data['files'][rel]]

def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--from',dest='source');a=p.parse_args()
    try:
        if a.check:
            missing=check();print(json.dumps({'ok':not missing,'missing_or_drifted':missing}));return int(bool(missing))
        staged={};hashes={}
        if a.source:
            source=Path(a.source).resolve()
            def git(*args):return subprocess.run(['git','-C',str(source),*args],capture_output=True,check=True,timeout=20).stdout
            if git('rev-parse',PIN+'^{commit}').decode().strip()!=PIN:raise ValueError('wrong immutable source commit')
            for rel in PATHS:
                raw=git('show',PIN+':template/common/'+rel)
                expected=git('rev-parse',PIN+':template/common/'+rel).decode().strip()
                if blob_hash(raw)!=expected:raise ValueError('source blob identity mismatch: '+rel)
                staged[rel],hashes[rel]=raw,expected
        else:
            tree=json.loads(fetch('https://api.github.com/repos/'+REPO+'/git/trees/'+PIN+'?recursive=1'))
            if tree.get('truncated'):raise ValueError('refusing truncated upstream tree')
            entries={x['path']:x['sha'] for x in tree['tree'] if x['type']=='blob'}
            for rel in PATHS:
                raw=fetch('https://raw.githubusercontent.com/'+REPO+'/'+PIN+'/template/common/'+rel)
                expected=entries['template/common/'+rel]
                if blob_hash(raw)!=expected:raise ValueError('downloaded blob identity mismatch: '+rel)
                staged[rel],hashes[rel]=raw,expected
        for rel,raw in staged.items():
            dest=ROOT/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        (ROOT/'.agent/SPEC_LOCK.json').write_text(json.dumps({'repository':REPO,'tag':TAG,'commit':PIN,'files':hashes},indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'ok':True,'copied':len(staged),'commit':PIN,'next':'Integrate upstream gen-contract.js, run official check-spec.js and full conformance review; vendoring alone is not conformance.'}));return 0
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc),'note':'No successful vendoring claim is made. Run --check to inspect local state.'}));return 1
if __name__=='__main__':raise SystemExit(main())
