"""Package.json is authoritative; sync/check every derived version location."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def derived(root=ROOT):
    package = json.loads((root/'package.json').read_text(encoding='utf-8'))
    version = package['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+',version):
        raise ValueError('version must be stable X.Y.Z')
    init=(root/'creo_cli/__init__.py').read_text(encoding='utf-8')
    init,count=re.subn(r'__version__\s*=\s*"[^"]+"','__version__ = "'+version+'"',init)
    if count != 1:raise ValueError('missing unique __version__')
    skillpath=root/'skills/creo-cli/SKILL.md'
    skill=skillpath.read_text(encoding='utf-8')
    skill,n=re.subn(r'(?m)^version: "[^"]+"$', 'version: "'+version+'"',skill)
    skill,m=re.subn(r'"min_version":\s*"[^"]+"','"min_version": "'+version+'"',skill)
    if (n,m)!=(1,1):raise ValueError('missing unique Skill version fields')
    lock={'name':package['name'],'version':version,'lockfileVersion':3,'requires':True,
          'packages':{'':{'name':package['name'],'version':version,'license':package['license'],'bin':package['bin'],'engines':package['engines']}}}
    changelog=(root/'CHANGELOG.md').read_text(encoding='utf-8')
    if f'## [{version}]' not in changelog:raise ValueError('add the release changelog before syncing a version')
    return {'creo_cli/__init__.py':init,'skills/creo-cli/SKILL.md':skill,
            'package-lock.json':json.dumps(lock,indent=2)+'\n','creo_cli/CHANGELOG.md':changelog}

def main():
    p=argparse.ArgumentParser();p.add_argument('--sync',action='store_true');p.add_argument('--check',action='store_true');a=p.parse_args()
    try:
        items=derived();drift=[]
        for rel,text in items.items():
            path=ROOT/rel
            if a.sync:path.write_text(text,encoding='utf-8',newline='\n')
            elif not path.exists() or path.read_text(encoding='utf-8')!=text:drift.append(rel)
        print(json.dumps({'ok':not drift,'mode':'sync' if a.sync else 'check','drift':drift}))
        return int(bool(drift))
    except (OSError,ValueError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)}));return 1
if __name__=='__main__':raise SystemExit(main())
