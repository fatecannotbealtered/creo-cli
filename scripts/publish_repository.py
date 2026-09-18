"""Create/push the designated public GitHub repo via the user's authenticated gh.

Default is preflight only; --apply is explicit. Refuses existing remote repos,
foreign remotes, dirty worktrees and the wrong authenticated account. Never
force-pushes and never creates a release/tag or publishes an npm package.
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OWNER='fatecannotbealtered';SLUG=OWNER+'/creo-cli'
# The public description has one source; do not leave a stale copy in this helper.
DESCRIPTION=json.loads((ROOT/'package.json').read_text(encoding='utf-8'))['description']
def run(*args):
    return subprocess.run(list(args),cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
def fail(message):
    print(json.dumps({'ok':False,'repository':SLUG,'created':False,'error':message}));return 1

def main():
    p=argparse.ArgumentParser();mode=p.add_mutually_exclusive_group();mode.add_argument('--apply',action='store_true');mode.add_argument('--check',action='store_true');a=p.parse_args()
    if not shutil.which('gh'):return fail('GitHub CLI (gh) is not installed in this environment; no remote action was attempted')
    if not shutil.which('git'):return fail('git is not available')
    profile=run('gh','api','user','--jq','.login')
    if profile.returncode or profile.stdout.strip()!=OWNER:return fail('gh must authenticate as the exact repository owner; credentials are never requested by this script')
    top=run('git','rev-parse','--show-toplevel')
    if top.returncode or Path(top.stdout.strip()).resolve()!=ROOT.resolve():return fail('refusing to publish a parent or different Git repository')
    branch=run('git','symbolic-ref','--short','HEAD')
    if branch.returncode or branch.stdout.strip()!='main':return fail('source publication requires the checked-out main branch')
    head=run('git','rev-parse','HEAD')
    if head.returncode:return fail('local repository must have a commit')
    if run('git','status','--porcelain').stdout.strip():return fail('worktree must be clean')
    remotes=run('git','remote').stdout.split()
    bundle_origin=False
    if remotes:
        if remotes!=['origin']:return fail('unexpected remotes; inspect them before publishing')
        url=run('git','remote','get-url','origin').stdout.strip()
        bundle=Path(url).expanduser()
        if not bundle.is_absolute():bundle=ROOT/bundle
        if bundle.suffix!='.bundle' or not bundle.is_file():return fail('existing origin is not a local bundle; refuse to alter it')
        verified_bundle=run('git','bundle','verify',str(bundle))
        bundle_heads=run('git','bundle','list-heads',str(bundle),'refs/heads/main').stdout.split()
        if verified_bundle.returncode or not bundle_heads or bundle_heads[0]!=head.stdout.strip():return fail('bundle origin does not match this local main; inspect it manually')
        bundle_origin=True
    existing=run('gh','api','repos/'+SLUG)
    if existing.returncode==0:return fail('target repository already exists; this script refuses to overwrite or adopt it')
    # A network/auth error must not be confused with an absent repository.
    if 'HTTP 404' not in existing.stderr:return fail('could not verify that the repository is absent; no write attempted')
    if not a.apply:
        print(json.dumps({'ok':True,'repository':SLUG,'created':False,'visibility':'public','replace_verified_local_bundle_origin':bundle_origin,'next':'python scripts/publish_repository.py --apply'}));return 0
    if bundle_origin:
        removed=run('git','remote','remove','origin')
        if removed.returncode:return fail('could not remove the verified local bundle origin')
    result=run('gh','repo','create',SLUG,'--public','--description',DESCRIPTION,'--source',str(ROOT),'--remote','origin','--push')
    if result.returncode:
        check=run('gh','api','repos/'+SLUG)
        print(json.dumps({'ok':False,'repository':SLUG,'created':'unknown','remote_exists':check.returncode==0,'error':'create/push did not fully verify; inspect the remote and local origin before retrying'}));return 1
    remote=run('git','ls-remote','origin','refs/heads/main')
    verified=remote.returncode==0 and remote.stdout.split()[0]==head.stdout.strip() if remote.stdout.split() else False
    print(json.dumps({'ok':verified,'repository':SLUG,'created':True,'main_push_verified':verified,'commit':head.stdout.strip(),'release_published':False}));return int(not verified)
if __name__=='__main__':
    try:raise SystemExit(main())
    except subprocess.TimeoutExpired:raise SystemExit(fail('external command timed out; inspect remote state before another attempt'))
