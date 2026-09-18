"""Run actual tests and a dispatch-based command guard. Does not certify full FCC."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def fingerprint():
    """Hash source/config/public contract docs, excluding generated evidence/handoff."""
    h=hashlib.sha256();paths=[]
    ignored={'.git','__pycache__','.venv','venv','node_modules','build','dist','.pytest_cache','.ruff_cache'}
    extensions={'.py','.json','.md','.js','.toml','.yml','.yaml'}
    special={'LICENSE','.gitignore','.gitattributes','.npmrc','SPEC_VERSION'}
    for directory,dirs,names in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in ignored and not d.endswith('.egg-info')]
        for name in names:
            p=Path(directory)/name;rel=p.relative_to(ROOT).as_posix()
            if rel.startswith('docs/evidence/') or rel=='docs/HANDOFF_zh.md':continue
            if p.suffix in extensions or name in special:paths.append(p)
    for p in sorted(paths):
        h.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+p.read_bytes())
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence');a=p.parse_args();t=time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        trace=Path(tmp)/'dispatch.log'
        os.environ['CREO_CLI_TEST_TRACE']=str(trace)
        os.environ['CREO_CLI_CONFIG_DIR']=str(Path(tmp)/'isolated-state')
        from creo_cli.cli import main as cli
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT))
        result=unittest.TextTestRunner(verbosity=2,stream=sys.stderr).run(suite)
        os.environ.pop('CREO_CLI_TEST_TRACE',None) # guard must not manufacture its own evidence
        out=io.StringIO()
        with redirect_stdout(out):code=cli(['reference','--compact'])
        ref=json.loads(out.getvalue())
        reference_valid = code == 0 and ref.get('ok') is True and isinstance(ref.get('data'), dict)
        declared={c['path'] for c in ref['data'].get('commands', [])} if reference_valid else set()
        invoked=set(trace.read_text(encoding='utf-8').splitlines()) if trace.exists() else set()
        missing,stale=sorted(declared-invoked),sorted(invoked-declared)
        ok=result.wasSuccessful() and code==0 and bool(declared) and not missing and not stale
        doc={'ok':ok,'at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
             'python':platform.python_version(),'platform':platform.platform(),'tests_run':result.testsRun,
             'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
             'declared_commands':len(declared),'invoked_commands':len(invoked),'missing':missing,'stale':stale,
             'duration_seconds':round(time.monotonic()-t,3),'source_fingerprint_sha256':fingerprint(),
             'full_fcc_certified':False,'native_live_verified':False,
             'reference_ok':reference_valid,'reference_error':None if reference_valid else ref.get('error', {'message':'invalid reference output'}),
             'limitations':['Command dispatch coverage is not branch/flag/error-contract completeness.','Native tests use interface-shaped substitutes, not the installed PTC SDK.','GitHub CI has not run in this environment.','CREOSON tests use real loopback HTTP with a stateful substitute, not the actual CREOSON server or Creo.']}
        if a.evidence:
            dest=Path(a.evidence);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(doc,indent=2));return int(not ok)
if __name__=='__main__':raise SystemExit(main())
