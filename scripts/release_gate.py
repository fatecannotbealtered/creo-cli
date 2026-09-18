"""Fail closed. Dispatch coverage or a flipped readiness constant cannot publish."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from bootstrap_spec import check
from creo_cli.service import RELEASE
from test import fingerprint
from version import derived

issues=[]
try:
    for rel,text in derived().items():
        if not (ROOT/rel).exists() or (ROOT/rel).read_text(encoding='utf-8')!=text:issues.append('version drift: '+rel)
    issues+=check()
    if json.loads((ROOT/'package.json').read_bytes())['private']:issues.append('package is intentionally private/development-only')
    if RELEASE['level']=='unpublishable':issues.append(RELEASE['reason'])
    for name in ('full-conformance.json','live-creo.json'):
        p=ROOT/'docs/evidence'/name
        if not p.is_file():issues.append('missing reviewed evidence: '+name);continue
        data=json.loads(p.read_bytes())
        if data.get('source_fingerprint_sha256')!=fingerprint() or data.get('status')!='verified':issues.append('stale or unverified evidence: '+name)
    if not (ROOT/'creo_cli/contract_gen.py').is_file():issues.append('upstream-generated runtime contract is not integrated')
except Exception as exc:issues.append(type(exc).__name__+': '+str(exc))
print(json.dumps({'ok':not issues,'blocked_by':issues,'note':'Evidence review remains a human responsibility; this guard does not attest arbitrary JSON claims.'},indent=2))
raise SystemExit(int(bool(issues)))
