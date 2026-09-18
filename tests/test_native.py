"""COM interface-shaped substitutes, explicitly not real PTC SDK/live tests."""
from __future__ import annotations
import copy
import json
import os
import subprocess
import sys
from types import SimpleNamespace as N
from unittest.mock import patch
from tests.test_contract import Base, ROOT
from creo_cli import models, native, safety
from creo_cli.core import Error, CODES, canonical

class Seq:
    def __init__(self, values): self.values=values
    @property
    def Count(self):return len(self.values)
    def Item(self,n):return self.values[n]

NAMES=('EpfcMDL_PART','EpfcMDL_ASSEMBLY','EpfcMDL_DRAWING','EpfcPARAM_STRING','EpfcPARAM_DOUBLE','EpfcPARAM_INTEGER','EpfcPARAM_BOOLEAN','EpfcPARAM_NOTE','EpfcITEM_DIMENSION','EpfcDIM_LINEAR','EpfcDIM_RADIAL','EpfcDIM_DIAMETER','EpfcDIM_ANGULAR')
C=N(**{name:n for n,name in enumerate(NAMES)})

class Model:
    def __init__(self):
        self.FileName='bracket.prt';self.FullName='bracket';self.Origin='disposable-test'
        self.Type=C.EpfcMDL_PART;self.IsModified=False;self.Relations=Seq([])
        self.params=[N(Name='DESCRIPTION',Value=N(discr=C.EpfcPARAM_STRING,StringValue='test'),IsRelationDriven=False)]
        self.dims=[N(Id=1,Symbol='width',DimValue=80.,DimType=C.EpfcDIM_LINEAR,IsRelationDriven=False,ExtendsInNegativeDirection=False),
                   N(Id=2,Symbol='hole_pitch',DimValue=40.,DimType=C.EpfcDIM_LINEAR,IsRelationDriven=False,ExtendsInNegativeDirection=False)]
        self.failed=[];self.regenerations=0;self.fail_regenerate=False;self.modifiable=True
    def ListParams(self):return Seq(self.params)
    def GetParam(self,name):return next((p for p in self.params if p.Name==name),None)
    def ListItems(self,kind):return Seq(self.dims)
    def GetPrincipalUnits(self):return N(Name='mm')
    def ListFeaturesByType(self,*args):return Seq([N(Id=1,Name='BASE',FeatTypeName='extrude',Status='active')])
    def ListFailedFeatures(self):return Seq(self.failed)
    def CheckIsModifiable(self,ask):
        assert ask is False
        return self.modifiable
    def Regenerate(self,flags):
        assert flags is None
        self.regenerations+=1;self.IsModified=True
        if self.fail_regenerate:raise RuntimeError('fake failure')

class APIFakes(Base):
    def setUp(self):
        super().setUp();self.env['CREO_CLI_EXPERIMENTAL_NATIVE_WRITES']='1'
        p=patch.dict(os.environ,self.env,clear=True);p.start();self.addCleanup(p.stop)
        self.m=Model();self.loaded=[self.m]
        self.s=N(ListModels=lambda:Seq(self.loaded),CurrentModel=self.m)
        self.api=native.Session(self.s,C,session_identity='disposable-session-1')
        self.change_data=json.loads(self.change.read_bytes())
    def confirmed(self):
        s=self.api.snapshot(self.m);rev=models.revision(s)
        t,_=safety.issue(safety.scope('change apply','native','bracket.prt',self.change_data,rev))
        return rev,t
    def test_native_reads_are_observations(self):
        for action in sorted(native.ACTIONS-{'change.apply'}):
            r=self.api.dispatch({'action':action,'model':'bracket.prt'})
            self.assertIsInstance(r,dict)
        self.assertEqual(self.m.regenerations,0)
        self.assertFalse(self.api.snapshot(self.m)['provenance']['simulation'])
        self.assertFalse(self.api.snapshot(self.m)['provenance']['adapter_live_verified'])
    def test_exact_loaded_model(self):
        with self.assertRaises(Error):self.api.model('other.prt')
        self.assertIs(self.api.model('BRACKET.PRT'),self.m)
    def test_duplicate_model_fails(self):
        self.loaded.append(self.m)
        with self.assertRaises(Error) as e:self.api.model('bracket.prt')
        self.assertEqual(e.exception.code,'E_CONFLICT')
    def test_param_union(self):
        for enum,field,value,kind in (('EpfcPARAM_DOUBLE','DoubleValue',1.25,'double'),('EpfcPARAM_INTEGER','IntValue',2,'integer'),('EpfcPARAM_BOOLEAN','BoolValue',True,'boolean'),('EpfcPARAM_NOTE','NoteId',3,'note')):
            p=N(Name='X',Value=N(discr=getattr(C,enum),**{field:value}),IsRelationDriven=False)
            self.m.params=[p]
            self.assertEqual(self.api.parameters(self.m)[0]['kind'],kind)
    def test_unknown_param_enum(self):
        self.m.params[0].Value.discr=-999
        with self.assertRaises(Error):self.api.parameters(self.m)
    def test_collection_ceiling(self):
        with self.assertRaises(Error):native.sequence(N(Count=50001))
    def test_native_success_remains_unsaved(self):
        rev,t=self.confirmed();r=self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(self.m.dims[1].DimValue,45.0)
        self.assertEqual(self.m.regenerations,1)
        self.assertFalse(r['persisted']);self.assertIsNone(r['backup'])
        self.assertFalse(r['verification']['geometry_verified'])
        self.assertTrue(r['verification']['requested_values'])
        self.assertEqual(r['audit_status'],'recorded')
        # Fake model deliberately has NO Save, Close, RetrieveModel or End methods.
    def test_two_write_gates(self):
        rev,t=self.confirmed()
        with patch.dict(os.environ,{'CREO_CLI_EXPERIMENTAL_NATIVE_WRITES':'0'}),self.assertRaises(Error):
            self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(self.m.dims[1].DimValue,40.)
    def test_read_permission(self):
        rev,t=self.confirmed()
        with patch.dict(os.environ,{'CREO_CLI_PERMISSION':'read'}),self.assertRaises(Error):
            self.api.apply('bracket.prt',self.change_data,rev,t)
    def test_worker_gate_no_outer_cli_required(self):
        rev,_=self.confirmed()
        with self.assertRaises(Error) as e:self.api.apply('bracket.prt',self.change_data,rev,'ct_forged')
        self.assertEqual(e.exception.code,'E_CONFLICT');self.assertEqual(self.m.dims[1].DimValue,40.)
    def test_native_state_drift(self):
        rev,t=self.confirmed();self.m.dims[0].DimValue=99
        with self.assertRaises(Error) as e:self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(e.exception.code,'E_CONFLICT')
    def test_session_change_invalidates(self):
        rev,t=self.confirmed();self.api.session_id='different-session'
        with self.assertRaises(Error):self.api.apply('bracket.prt',self.change_data,rev,t)
    def test_modifiability_check_no_ui(self):
        rev,t=self.confirmed();self.m.modifiable=False
        with self.assertRaises(Error) as e:self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(e.exception.code,'E_FORBIDDEN')
    def test_assembly_writes_unsupported(self):
        self.m.Type=C.EpfcMDL_ASSEMBLY;rev,t=self.confirmed()
        with self.assertRaises(Error) as e:self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(e.exception.code,'E_UNSUPPORTED')
    def test_angular_not_linear(self):
        self.m.dims[1].DimType=C.EpfcDIM_ANGULAR;rev,t=self.confirmed()
        with self.assertRaises(Error) as e:self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(e.exception.code,'E_UNSUPPORTED')
    def test_regenerate_failure_is_not_whole_model_rollback(self):
        rev,t=self.confirmed();self.m.fail_regenerate=True
        with self.assertRaises(Error) as e:self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(e.exception.code,'E_NATIVE_FAILURE')
        self.assertFalse(e.exception.details['whole_model_restored'])
        self.assertTrue(e.exception.details['state_unknown'])
        self.assertFalse(e.exception.details['persisted'])
    def test_setter_can_apply_then_throw(self):
        rev,t=self.confirmed();original=self.api.set_value
        count=[0]
        def fail_once(m,c,v):
            original(m,c,v);count[0]+=1
            if count[0]==1:raise RuntimeError('after setter')
        with patch.object(self.api,'set_value',side_effect=fail_once),self.assertRaises(Error) as e:
            self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(self.m.dims[1].DimValue,40.)
        self.assertTrue(e.exception.details['requested_values_restored'])
        self.assertFalse(e.exception.details['whole_model_restored'])
    def test_native_front_door_with_substitute(self):
        def call(backend,action,**kw):
            return self.api.dispatch({'action':action,'model':backend.model,**kw})
        with patch.object(native.Native,'request',new=call):
            for leaf in ('list','info','snapshot','parameters','dimensions','features','relations'):
                self.cli('model',leaf,'--model','bracket.prt')
            self.cli('session','status')
            args=['change','apply','--model','bracket.prt','--changeset',self.change]
            t=self.cli(*args,'--dry-run')['data']['confirm_token']
            r=self.cli(*args,'--confirm',t)['data']
            self.assertFalse(r['persisted']);self.assertFalse(r['provenance']['simulation'])
    def test_parameter_write(self):
        self.change_data['operations']=[{'op':'parameter.set','name':'DESCRIPTION','value':'modified','expected':'test'}]
        rev,t=self.confirmed();self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(self.m.params[0].Value.StringValue,'modified')
    def test_audit_terminal_failure_does_not_hide_commit(self):
        rev,t=self.confirmed();original=safety.event
        def fail_end(*args):
            if args[3]=='verified':raise Error('E_IO','full disk')
            return original(*args)
        with patch.object(safety,'event',side_effect=fail_end):r=self.api.apply('bracket.prt',self.change_data,rev,t)
        self.assertEqual(r['audit_status'],'started_only')
        self.assertEqual(self.m.dims[1].DimValue,45.)

class Transport(Base):
    def ok(self):return {'ok':True,'schema_version':'1.0','data':{'items':[]},'meta':{'duration_ms':0}}
    def use(self,payload,exit=0,action='model.list'):
        def run(cmd,**kw):
            self.assertFalse(kw['shell']);self.assertEqual(kw['timeout'],1)
            self.assertEqual(json.loads(kw['input'])['protocol_version'],'1.0')
            return N(stdout=payload,returncode=exit)
        return native.Native('bracket.prt',timeout=1,runner=run).request(action)
    def test_valid_transport(self):self.assertEqual(self.use(canonical(self.ok())),{'items':[]})
    def test_noise_and_trailing_json(self):
        for payload in (b'',b'noise\n'+canonical(self.ok()),canonical(self.ok())+b'\n{}',b'{}',b'[]',b'null'):
            with self.assertRaises(Error) as e:self.use(payload)
            self.assertEqual(e.exception.code,'E_PROTOCOL')
    def test_exit_status_is_not_ignored(self):
        with self.assertRaises(Error):self.use(canonical(self.ok()),exit=1)
    def test_wrong_version_and_meta(self):
        for doc in (self.ok()|{'schema_version':'2.0'},self.ok()|{'meta':{'duration_ms':-1}},self.ok()|{'meta':{'duration_ms':True}},self.ok()|{'meta':{'duration_ms':0,'debug':1}}):
            with self.assertRaises(Error):self.use(canonical(doc))
    def test_all_error_mappings(self):
        for code,(status,retryable) in CODES.items():
            doc={'ok':False,'schema_version':'1.0','error':Error(code,'test').payload(),'meta':{'duration_ms':0}}
            with self.assertRaises(Error) as e:self.use(canonical(doc),exit=status)
            self.assertEqual(e.exception.code,code)
    def test_bad_retryable_mapping(self):
        doc={'ok':False,'schema_version':'1.0','error':Error('E_CONFLICT','test').payload(),'meta':{'duration_ms':0}}
        doc['error']['retryable']=True
        with self.assertRaises(Error) as e:self.use(canonical(doc),exit=6)
        self.assertEqual(e.exception.code,'E_PROTOCOL')
    def test_timeout_has_state_uncertainty(self):
        def run(*a,**k):raise subprocess.TimeoutExpired('worker',1)
        b=native.Native(runner=run)
        for action in ('model.list','change.apply'):
            with self.assertRaises(Error) as e:b.request(action)
            self.assertEqual(e.exception.code,'E_TIMEOUT')
            self.assertEqual(e.exception.details['state_unknown'],action=='change.apply')
    def test_start_failure_has_no_write(self):
        def run(*a,**k):raise OSError('not found')
        with self.assertRaises(Error) as e:native.Native(runner=run).request('change.apply')
        self.assertFalse(e.exception.details['write_started'])
    def test_worker_rejects_invalid_request_before_connection(self):
        for req,expected in (({'protocol_version':'1.0','action':'script.execute'},1),({'protocol_version':'1.0','action':'change.apply','model':'bracket.prt','changeset':json.loads(self.change.read_bytes()),'expected_revision':'x'},5)):
            p=subprocess.run([sys.executable,'-m','creo_cli.native'],input=canonical(req),capture_output=True,cwd=ROOT,env=self.env,timeout=15)
            self.assertEqual(p.returncode,expected,json.loads(p.stdout))
            self.assertFalse(json.loads(p.stdout)['ok'])
