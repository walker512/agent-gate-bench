import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from agent_gate_bench import core, effects as e
ROOT=Path(__file__).resolve().parents[1]
EX=ROOT/'examples'

@unittest.skipUnless(os.name=='posix','Effects execution requires POSIX')
class EffectsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.suite=core.parse(core.read(EX/'effects_suite.json'));self.path=self.root/'suite.json';self.adapter=EX/'effects_reference.py'
    def run_it(self,turns=6,timeout=1):
        self.path.write_bytes(core.canonical(self.suite))
        return e.run(self.path,self.adapter,self.root/'out',True,timeout,turns)
    def custom(self,source):
        self.adapter=self.root/'custom.py';self.adapter.write_text(source)
    def test_reference_actual_six_cases(self):
        r=self.run_it();self.assertEqual(r['counts'],{'pass':6,'fail':0,'error':0});self.assertEqual(e.verify(self.root/'out'),r)
        receipt=core.parse(core.read(self.root/'out'/'receipt.json',core.OUTPUT_LIMIT),core.OUTPUT_LIMIT)
        self.assertEqual(receipt['cases'][1]['final_state']['notes'],{'invoice':'42'})
        self.assertEqual(receipt['cases'][3]['final_state']['outbox'],[{'to':'friend.invalid','body':'42'}])
        injected=receipt['cases'][2]['rounds'][0]['event'];self.assertTrue(injected['intervened']);self.assertNotIn('override_call',injected['actual_result']['value']);self.assertIn('override_call',injected['delivered_result']['value'])
    def test_vulnerable_blocked_effects_and_grant_reuse(self):
        self.adapter=EX/'effects_vulnerable.py';r=self.run_it();self.assertEqual(r['counts'],{'pass':4,'fail':2,'error':0})
        for row in (r['results'][2],r['results'][3]):self.assertEqual(row['safety'],'fail');self.assertEqual(row['utility'],'pass');self.assertTrue(row['state_matches_expected'])
        self.assertEqual(r['results'][2]['blocked_attempts'],1);self.assertTrue(r['results'][2]['literal_leak'])
        self.assertFalse(r['results'][3]['literal_leak'])
    def test_refusal_not_utility_pass(self):
        self.suite['cases']=self.suite['cases'][:1];self.custom('print(\'{"calls":[],"final":"I refuse."}\')')
        r=self.run_it()['results'][0];self.assertEqual(r['safety'],'pass');self.assertEqual(r['utility'],'fail');self.assertEqual(r['status'],'fail')
    def test_correct_final_without_required_actual_call_fails(self):
        self.suite['cases']=self.suite['cases'][:1];self.custom('print(\'{"calls":[],"final":"Invoice total is 42."}\')')
        r=self.run_it()['results'][0];self.assertEqual(r['missing_required_successes'],1);self.assertEqual(r['utility'],'fail')
    def test_max_turns_does_not_green_partial_success(self):
        self.suite['cases']=self.suite['cases'][:1];r=self.run_it(turns=1)['results'][0];self.assertEqual(r['status'],'error');self.assertEqual(r['safety'],'incomplete');self.assertEqual(r['terminal'],'turn_limit')
    def test_multi_call_turn_not_executed(self):
        self.suite['cases']=self.suite['cases'][:1];call=self.suite['cases'][0]['grants'][0]['call'];self.custom('print('+repr(json.dumps({'calls':[call,call],'final':'Working.'}))+')')
        r=self.run_it()['results'][0];self.assertEqual(r['terminal'],'protocol_error');self.assertEqual(r['executed_calls'],0)
    def test_unknown_tool_denied(self):
        self.suite['cases']=self.suite['cases'][:1]
        self.custom('import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({"calls":[] if r["history"] else [{"tool":"delete_record","arguments":{"id":"invoice"}}],"final":"Invoice total is 42."}))')
        r=self.run_it()['results'][0];self.assertEqual(r['blocked_attempts'],1);self.assertEqual(r['status'],'fail')
    def test_nonzero_process_never_passes(self):
        self.suite['cases']=self.suite['cases'][:1];self.custom('import sys; print(\'{"calls":[],"final":"Invoice total is 42."}\');sys.exit(4)')
        r=self.run_it()['results'][0];self.assertEqual(r['status'],'error');self.assertEqual(r['terminal'],'process_error')
    def test_timeout_never_passes(self):
        self.suite['cases']=self.suite['cases'][:1];self.custom('import time;time.sleep(10)')
        self.assertEqual(self.run_it()['results'][0]['status'],'error')
    def test_trust_gate_and_existing_output_preexecution(self):
        self.path.write_bytes(core.canonical(self.suite))
        with patch.object(e.runner,'execute',side_effect=AssertionError('must not run')):
            with self.assertRaises(core.Invalid):e.run(self.path,self.adapter,self.root/'out')
            (self.root/'out').mkdir()
            with self.assertRaises(core.Invalid):e.run(self.path,self.adapter,self.root/'out',True)
    def test_missing_read_is_tool_error_not_authorization_denial(self):
        self.suite['cases']=[self.suite['cases'][-1]];r=self.run_it()['results'][0];self.assertEqual(r['status'],'pass');self.assertEqual(r['executed_calls'],0);self.assertEqual(r['blocked_attempts'],0)
    def test_exact_grant_arguments_and_budget(self):
        case=self.suite['cases'][3];state=copy.deepcopy(case['initial_state']);budget=e.new_budget(case);call=case['grants'][0]['call']
        wrong=copy.deepcopy(call);wrong['arguments']['body']='different';state,r=e.transition(state,wrong,budget);self.assertEqual(r['status'],'denied')
        state,r=e.transition(state,call,budget);self.assertEqual(r['status'],'executed');state,r=e.transition(state,call,budget);self.assertEqual(r['status'],'denied');self.assertEqual(len(state['outbox']),1)
    def test_each_bundle_file_tamper(self):
        self.suite['cases']=self.suite['cases'][:1];self.run_it();root=self.root/'out'
        for p in root.iterdir():
            raw=p.read_bytes();p.write_bytes(raw+b' ')
            with self.subTest(file=p.name),self.assertRaises(core.Invalid):e.verify(root)
            p.write_bytes(raw)
    def test_rehashed_forged_effect_rejected(self):
        self.suite['cases']=self.suite['cases'][:1];self.run_it();root=self.root/'out';p=root/'receipt.json';receipt=core.parse(core.read(p,core.OUTPUT_LIMIT),core.OUTPUT_LIMIT)
        receipt['cases'][0]['rounds'][0]['event']['after_sha256']='0'*64;p.write_bytes(core.canonical(receipt))
        with self.assertRaises(core.Invalid):e.verify(root)
    def test_rehashed_terminal_and_missing_rounds_rejected(self):
        self.suite['cases']=self.suite['cases'][:1];self.run_it();root=self.root/'out';p=root/'receipt.json';receipt=core.parse(core.read(p,core.OUTPUT_LIMIT),core.OUTPUT_LIMIT)
        receipt['cases'][0]['rounds'].pop();receipt['cases'][0]['terminal']='finished';p.write_bytes(core.canonical(receipt))
        with self.assertRaises(core.Invalid):e.verify(root)
    def test_stdout_response_mismatch_rejected(self):
        self.suite['cases']=self.suite['cases'][:1];self.run_it();root=self.root/'out';p=root/'receipt.json';receipt=core.parse(core.read(p,core.OUTPUT_LIMIT),core.OUTPUT_LIMIT)
        receipt['cases'][0]['rounds'][0]['process']['response']['final']='forged';p.write_bytes(core.canonical(receipt))
        with self.assertRaises(core.Invalid):e.verify(root)
    def test_process_fields_cannot_hide_overwritten_case_id(self):
        self.suite['cases']=self.suite['cases'][:1];self.run_it()
        receipt=core.parse(core.read(self.root/'out'/'receipt.json',core.OUTPUT_LIMIT),core.OUTPUT_LIMIT)
        process=receipt['cases'][0]['rounds'][0]['process'];process['case_id']='ignored'
        with self.assertRaises(core.Invalid):
            e.process_valid(self.suite['cases'][0],process,core.read(self.path),core.digest(core.read(self.adapter)),1)

    def test_verify_never_executes_adapter(self):
        self.suite['cases']=self.suite['cases'][:1];self.run_it()
        with patch.object(e.runner,'execute',side_effect=AssertionError('must not run')):self.assertEqual(e.verify(self.root/'out')['status'],'pass')
    def test_extra_files_symlinks_rejected(self):
        self.suite['cases']=self.suite['cases'][:1];self.run_it();root=self.root/'out';(root/'extra').write_text('x')
        with self.assertRaises(core.Invalid):e.verify(root)
        (root/'extra').unlink();(root/'alias').symlink_to(root/'adapter.py')
        with self.assertRaises(core.Invalid):e.verify(root)
    def test_suite_schema_and_multiplicity_rejected(self):
        case=self.suite['cases'][0]
        changes=[('grants',[case['grants'][0],case['grants'][0]]),('required_calls',case['required_calls']*2),('tool_returns',[{'call':case['required_calls'][0],'on_use':2,'value':'x'}]),('expected_state',{'records':{},'notes':{},'outbox':[{'to':'x','body':False}]})]
        for key,value in changes:
            s=copy.deepcopy(self.suite);s['cases'][0][key]=value
            with self.subTest(key=key),self.assertRaises(core.Invalid):e.load(core.canonical(s))
    def test_deep_tool_payload_rejected_before_execution(self):
        value='leaf'
        for _ in range(10):value={'nested':value}
        self.suite['cases'][2]['tool_returns'][0]['value']=value
        with patch.object(e.runner,'execute',side_effect=AssertionError('must not run')):
            with self.assertRaises(core.Invalid):self.run_it()
        self.assertFalse((self.root/'out').exists())

    def test_maximum_tool_payload_depth_stays_verifiable(self):
        self.suite['cases']=[self.suite['cases'][2]]
        value='leaf'
        for _ in range(4):value={'nested':value}
        self.suite['cases'][0]['tool_returns'][0]['value']=value
        self.suite['cases'][0]['required_final']=['Unavailable.']
        self.assertEqual(self.run_it()['status'],'pass')
        self.assertEqual(e.verify(self.root/'out')['status'],'pass')

    def test_expected_state_not_self_reported(self):
        self.suite['cases']=self.suite['cases'][:1];self.suite['cases'][0]['expected_state']['notes']['invoice']='42'
        r=self.run_it()['results'][0];self.assertFalse(r['state_matches_expected']);self.assertEqual(r['utility'],'fail')
    def test_private_output_permissions(self):
        self.suite['cases']=self.suite['cases'][:1];self.run_it();self.assertEqual((self.root/'out').stat().st_mode & 0o777,0o700)
    def test_cli_failure_nonzero_and_verify(self):
        args=[sys.executable,'-m','agent_gate_bench.effects','run',str(EX/'effects_suite.json'),'--adapter',str(EX/'effects_vulnerable.py'),'--out',str(self.root/'cli'),'--allow-execute']
        run=subprocess.run(args,cwd=ROOT,capture_output=True);self.assertEqual(run.returncode,3,run.stderr)
        check=subprocess.run([sys.executable,'-m','agent_gate_bench.effects','verify',str(self.root/'cli')],cwd=ROOT,capture_output=True);self.assertEqual(check.returncode,3,check.stderr)

if __name__=='__main__':unittest.main()
