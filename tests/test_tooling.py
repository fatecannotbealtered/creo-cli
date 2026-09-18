import concurrent.futures
import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from unittest.mock import patch
from tests.test_contract import Base, ROOT, read_model
from creo_cli import __version__, models, registry, safety
from creo_cli.core import CORE, Error, canonical, redact
from scripts.bootstrap_spec import check, PIN
from scripts.version import derived

class ToolingAndRegression(Base):
    def test_dispatch_namespace_is_separate_from_public_command_filter(self):
        from creo_cli.cli import parser
        from creo_cli.registry import COMMANDS
        opts = vars(parser().parse_args(['reference', '--command', 'model dimensions']))
        self.assertEqual(opts['command'], 'model dimensions')
        self.assertEqual(opts['_dispatch_command'].path, 'reference')
        for command in COMMANDS:
            self.assertNotIn('_dispatch_command', {p.name for p in command.params})

    def test_version_consistency(self):
        for rel,text in derived().items():self.assertEqual((ROOT/rel).read_text(encoding='utf-8'),text)
    def test_version_drift_is_detectable(self):
        output=derived();self.assertNotEqual(output['creo_cli/__init__.py'],output['creo_cli/__init__.py'].replace(__version__,'999.0.0'))
        p=subprocess.run([sys.executable,'scripts/version.py','--check'],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout)
    def test_release_gate_blocks_development(self):
        p=subprocess.run([sys.executable,'scripts/release_gate.py'],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,1);self.assertFalse(json.loads(p.stdout)['ok'])
    def test_missing_spec_lock_fails(self):
        self.assertTrue(check(self.dir))
    def test_bootstrap_mapping_is_explicitly_noncanonical(self):
        c=read_model(ROOT/'contract/bootstrap.json')
        self.assertFalse(c['canonical'])
        self.assertEqual(c['error_codes'],{k:{'exit':v[0],'retryable':v[1]} for k,v in CORE.items()})
    def test_pin_is_immutable(self):
        self.assertEqual(len(PIN),40)
        self.assertEqual((ROOT/'.agent/SPEC_VERSION').read_text().strip(),'v1.6.2')
    def test_default_policy_is_read(self):
        env=dict(self.env);env.pop('CREO_CLI_PERMISSION',None)
        self.assertEqual(self.cli('context',env=env)['data']['config']['permission'],'read')
    def test_parser_does_not_echo_unknown_secret_argv(self):
        r=self.cli('context','--password','do-not-print-me',status=2)
        self.assertNotIn('do-not-print-me',json.dumps(r))
    def test_concurrent_first_secret_creation(self):
        with patch.dict(os.environ,self.env,clear=True),concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            values=list(pool.map(lambda _:safety.secret(),range(16)))
        self.assertEqual(len(set(values)),1);self.assertEqual(len(values[0]),32)
    def test_confirmation_payload_not_credential_redacted(self):
        r=redact({'confirm_token':'ct_required','parameters':[{'name':'API_KEY','kind':'string','value':'private'}]})
        self.assertEqual(r['confirm_token'],'ct_required');self.assertEqual(r['parameters'][0]['value'],'[REDACTED]')
    def test_native_read_cannot_accept_write_fields(self):
        req={'protocol_version':'1.0','action':'model.list','confirm_token':'ct_fake'}
        p=subprocess.run([sys.executable,'-m','creo_cli.native'],input=canonical(req),cwd=ROOT,env=self.env,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,1);self.assertEqual(json.loads(p.stdout)['error']['code'],'E_PROTOCOL')
    def test_native_invalid_output_gets_terminal_error(self):
        code='from creo_cli import native; native.run_native=lambda req: {"number":float("nan")}; raise SystemExit(native.worker())'
        p=subprocess.run([sys.executable,'-c',code],input=canonical({'protocol_version':'1.0','action':'model.list'}),cwd=ROOT,env=self.env,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,1);self.assertEqual(json.loads(p.stdout)['error']['code'],'E_PROTOCOL')
    def test_initialized_schema_is_distinct(self):
        c=next(c for c in registry.COMMANDS if c.path=='model init')
        self.assertEqual(c.schema,'initialized');self.assertIn('audit_status',registry.SCHEMAS[c.schema]['fields'])
    def test_changelog_past_version_delta(self):
        r=self.cli('changelog','--since','0.0.0')['data'];self.assertEqual(r['entries'][0]['version'],__version__)
    def test_secret_preview_is_redacted(self):
        s=models.sample();s['parameters'][0].update(name='PASSWORD',value='old-secret');self.path.write_bytes(canonical(s))
        c={'schema_version':'1.0','model':'bracket.prt','operations':[{'op':'parameter.set','name':'PASSWORD','value':'new-secret'}]}
        self.change.write_bytes(canonical(c));r=self.cli(*self.apply_args(),'--dry-run')['data']
        self.assertNotIn('old-secret',json.dumps(r));self.assertNotIn('new-secret',json.dumps(r));self.assertIn('confirm_token',r)
    def test_mock_revision_size_bound(self):
        s=models.sample();s['model']['revision']='9'*10000;self.path.write_bytes(canonical(s))
        self.cli('model','snapshot','--backend','mock','--model',self.path,status=2)
    def test_reference_exposes_pagination_semantics(self):
        r=self.cli('reference')['data']
        for c in r['commands']:
            if any(p['name']=='limit' for p in c['params']):
                self.assertTrue(c['pagination']['default_sort']);self.assertFalse(c['pagination']['snapshot_consistent_across_calls'])
    def test_real_process_utf8_envelope(self):
        s=models.sample();s['parameters'][0]['value']='中文与 Unicode 🚀';self.path.write_bytes(canonical(s))
        p=subprocess.run([sys.executable,'-m','creo_cli','model','snapshot','--backend','mock','--model',str(self.path),'--compact'],cwd=ROOT,env=self.env,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['data']['parameters'][0]['value'],s['parameters'][0]['value'])
        self.assertNotIn(b'\xef\xbb\xbf',p.stdout);self.assertEqual(len(p.stdout.splitlines()),1)


class PublishingGuards(Base):
    def invoke(self, replies, argv=('--check',)):
        from scripts import publish_repository as pub
        from types import SimpleNamespace
        calls=[]
        def run(*args):
            calls.append(args)
            key=' '.join(args)
            response=replies.get(key, ('', '', 0))
            return SimpleNamespace(stdout=response[0],stderr=response[1],returncode=response[2])
        out=io.StringIO()
        with patch.object(sys,'argv',['publish_repository.py',*argv]), patch.object(pub.shutil,'which',return_value='/test/executable'), patch.object(pub,'run',side_effect=run), redirect_stdout(out):
            status=pub.main()
        return status,json.loads(out.getvalue()),calls

    def base_replies(self):
        return {
            'gh api user --jq .login':('fatecannotbealtered\n','',0),
            'git rev-parse --show-toplevel':(str(ROOT)+'\n','',0),
            'git symbolic-ref --short HEAD':('main\n','',0),
            'git rev-parse HEAD':('a'*40+'\n','',0),
            'gh api repos/fatecannotbealtered/creo-cli':('','gh: Not Found (HTTP 404)',1),
        }

    def test_check_does_not_create_remote(self):
        status,doc,calls=self.invoke(self.base_replies())
        self.assertEqual(status,0);self.assertTrue(doc['ok']);self.assertFalse(doc['created'])
        self.assertFalse(any(c[:3]==('gh','repo','create') for c in calls))

    def test_wrong_owner_is_refused_before_git_actions(self):
        replies=self.base_replies();replies['gh api user --jq .login']=('someone-else','',0)
        status,doc,calls=self.invoke(replies)
        self.assertEqual(status,1);self.assertEqual(len(calls),1);self.assertFalse(doc['created'])

    def test_parent_repository_is_not_published(self):
        replies=self.base_replies();replies['git rev-parse --show-toplevel']=(str(ROOT.parent),'',0)
        status,_,calls=self.invoke(replies)
        self.assertEqual(status,1);self.assertFalse(any(c[:3]==('gh','repo','create') for c in calls))

    def test_non_main_branch_is_refused(self):
        replies=self.base_replies();replies['git symbolic-ref --short HEAD']=('other','',0)
        self.assertEqual(self.invoke(replies)[0],1)

    def test_network_failure_is_not_repository_absence(self):
        replies=self.base_replies();replies['gh api repos/fatecannotbealtered/creo-cli']=('','connection failed',1)
        status,_,calls=self.invoke(replies,('--apply',))
        self.assertEqual(status,1);self.assertFalse(any(c[:3]==('gh','repo','create') for c in calls))

    def test_check_and_apply_are_mutually_exclusive(self):
        from scripts import publish_repository as pub
        from contextlib import redirect_stderr
        with patch.object(sys,'argv',['publish_repository.py','--apply','--check']), patch.object(pub,'run') as runner, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            pub.main()
        self.assertEqual(failure.exception.code,2);runner.assert_not_called()
