"""Synthetic local process tests; no LLM, live agent, credential or network request."""
import copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from agent_gate_bench.core import *
from agent_gate_bench.runner import execute,run,CAP
ROOT=Path(__file__).resolve().parents[1]
def suite():return load(read(ROOT/'examples/suite.json'))
def good():return {'calls':[{'tool':'read_record','arguments':{'id':'invoice-42'}}],'final':'Invoice total is 42.'}
def script(x):return ('import json\nprint('+repr(json.dumps(x))+')\n').encode()
class Scoring(unittest.TestCase):
    def test_good(self):self.assertEqual(grade(suite()['cases'][0],good())['status'],'pass')
    def test_unauthorized(self):
        x=good();x['calls'].append({'tool':'delete_record','arguments':{'id':'invoice-42'}});self.assertEqual(grade(suite()['cases'][0],x)['findings'],[{'rule':'unauthorized_call','index':1}])
    def test_argument_change(self):
        x=good();x['calls'][0]['arguments']['id']='other';self.assertEqual(len(grade(suite()['cases'][0],x)['findings']),2)
    def test_empty_actions(self):
        x=good();x['calls']=[];self.assertEqual(grade(suite()['cases'][0],x)['findings'][0]['rule'],'missing_required_call')
    def test_refusal_utility(self):self.assertEqual(len(grade(suite()['cases'][0],{'calls':[],'final':'Cannot help.'})['findings']),2)
    def test_literal_in_final_and_argument(self):
        for where in ('final','argument','key'):
            x=good()
            if where=='final':x['final']+=' PUBLIC_FAKE_CANARY_42'
            elif where=='argument':x['calls'][0]['arguments']['id']='PUBLIC_FAKE_CANARY_42'
            else:x['calls'][0]['arguments']['PUBLIC_FAKE_CANARY_42']='test'
            self.assertIn('forbidden_literal',[a['rule'] for a in grade(suite()['cases'][0],x)['findings']])
    def test_encoding_not_detected(self):
        x=good();x['final']+=' UFVCTElDX0ZBS0VfQ0FOQVJZXzQy';self.assertEqual(grade(suite()['cases'][0],x)['status'],'pass')
    def test_no_checks_rejected(self):
        x=suite();x['cases'][0]['required_calls']=[];x['cases'][0]['required_final']=[]
        with self.assertRaises(Invalid):load(canonical(x))
    def test_duplicate_case_rejected(self):
        x=suite();x['cases'].append(x['cases'][0])
        with self.assertRaises(Invalid):load(canonical(x))
    def test_conflicting_checks(self):
        x=suite();x['cases'][0]['forbidden_literals']=['Invoice']
        with self.assertRaises(Invalid):load(canonical(x))
    def test_required_allowed(self):
        x=suite();x['cases'][0]['allowed_calls']=[]
        with self.assertRaises(Invalid):load(canonical(x))
    def test_schema_validation(self):
        for raw in [b'{"schema":1,"schema":1}',b'{"x":1e999}',b'{"x":NaN}',b'{"x":"\\ud800"}',b'['*20000+b']'*20000]:
            with self.assertRaises(Invalid):load(raw)
        x=suite();x['schema']=True
        with self.assertRaises(Invalid):load(canonical(x))
    def test_bad_response(self):
        for x in [{}, {'calls':[],'final':True},{'calls':[{'tool':'x','arguments':{'id':1}}],'final':'test'}, {'calls':[],'final':'test','extra':'x'}]:
            with self.assertRaises(Invalid):response(x)
    def test_limits(self):
        x=suite();x['cases']=x['cases']*4
        with self.assertRaises(Invalid):load(canonical(x))
        x=good();x['calls']=x['calls']*33
        with self.assertRaises(Invalid):response(x)

@unittest.skipUnless(os.name=='posix','Runner supports POSIX only.')
class Process(unittest.TestCase):
    def test_actual_process(self):
        r=execute(script(good()),{'hello':'world'},2);self.assertEqual(r['execution_status'],'complete');self.assertEqual(r['response'],good());self.assertEqual(digest(r['stdout_text'].encode()),r['stdout_sha256'])
    def test_input_stdin(self):
        s=b'import json,sys\nx=json.load(sys.stdin)\nprint(json.dumps({"calls":[],"final":x["value"]}))\n';self.assertEqual(execute(s,{'value':'read stdin'},2)['response']['final'],'read stdin')
    def test_no_inherited_secret(self):
        old=os.environ.get('SYNTHETIC_ENV_SENTINEL');os.environ['SYNTHETIC_ENV_SENTINEL']='PUBLIC_FAKE_ENV'
        try:
            r=execute(b'import os,json\nprint(json.dumps({"calls":[],"final":os.environ.get("SYNTHETIC_ENV_SENTINEL","absent")}))',{},2);self.assertEqual(r['response']['final'],'absent')
        finally:
            if old is None:os.environ.pop('SYNTHETIC_ENV_SENTINEL',None)
            else:os.environ['SYNTHETIC_ENV_SENTINEL']=old
    def test_timeout(self):self.assertEqual(execute(b'import time\ntime.sleep(20)',{},1)['execution_status'],'timeout')
    def test_nonzero(self):self.assertEqual(execute(b'raise RuntimeError("SECRET_SENTINEL")',{},2)['execution_status'],'nonzero_exit')
    def test_invalid_json(self):
        for s in [b'print("not json")',b'print("{}")',b'import os\nos.write(1,b"\\xff")',b'print("{\\\"calls\\\":[],\\\"calls\\\":[],\\\"final\\\":\\\"x\\\"}")']:
            self.assertEqual(execute(s,{},2)['execution_status'],'invalid_response')
    def test_output_limit(self):
        r=execute(b'import os\nwhile True:os.write(1,b"x"*8192)',{},2);self.assertEqual(r['execution_status'],'output_limit');self.assertLessEqual(r['stdout_bytes']+r['stderr_bytes'],CAP);self.assertIsNone(r['stdout_text'])
    def test_stderr_limit(self):self.assertEqual(execute(b'import os\nwhile True:os.write(2,b"x"*8192)',{},2)['execution_status'],'output_limit')
    def test_child_pipe_cleanup(self):
        r=execute(b'import subprocess,sys,json\nsubprocess.Popen([sys.executable,"-c","import time;time.sleep(20)"])\nprint(json.dumps({"calls":[],"final":"done"}))',{},2);self.assertEqual(r['execution_status'],'complete')

@unittest.skipUnless(os.name=='posix','Runner supports POSIX only.')
class Bundles(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.p=Path(self.t.name);self.out=self.p/'out'
    def tearDown(self):self.t.cleanup()
    def build(self,adapter='boundary_adapter.py'):return run(ROOT/'examples/suite.json',ROOT/'examples'/adapter,self.out,True,2)
    def test_real_reference_and_vulnerable(self):
        self.assertEqual(self.build()['counts'],{'pass':5,'fail':0,'error':0});self.assertEqual(verify(self.out)['status'],'pass')
        other=self.p/'other';r=run(ROOT/'examples/suite.json',ROOT/'examples/vulnerable_adapter.py',other,True,2);self.assertEqual(r['counts'],{'pass':1,'fail':4,'error':0});self.assertEqual(verify(other)['status'],'fail_or_error')
    def test_explicit_permission(self):
        with self.assertRaises(Invalid):run(ROOT/'examples/suite.json',ROOT/'examples/boundary_adapter.py',self.out)
        self.assertFalse(self.out.exists())
    def test_existing_no_execute(self):
        self.out.mkdir()
        with self.assertRaises(Invalid):self.build()
        self.assertEqual(list(self.out.iterdir()),[])
    def test_tamper(self):
        self.build()
        for name in ('report.json','review.md','suite.json','receipt.json'):
            p=self.out/name;raw=p.read_bytes()
            if name=='receipt.json':
                x=json.loads(raw);x['records'][0]['response']['final']+=' changed';p.write_bytes(canonical(x))
            else:p.write_bytes(raw+b' ')
            with self.assertRaises(Invalid):verify(self.out)
            p.write_bytes(raw)
    def test_record_order_and_complete(self):
        self.build();p=self.out/'receipt.json';raw=p.read_bytes()
        for change in ('order','missing','bool','status'):
            x=json.loads(raw)
            if change=='order':x['records'].reverse()
            elif change=='missing':x['records'].pop()
            elif change=='bool':x['records'][0]['returncode']=False
            else:x['records'][0]['execution_status']='timeout'
            p.write_bytes(canonical(x))
            with self.assertRaises(Invalid):verify(self.out)
    def test_error_not_pass(self):
        f=self.p/'bad.py';f.write_text('raise RuntimeError("SECRET_SENTINEL")');r=run(ROOT/'examples/suite.json',f,self.out,True,2);self.assertEqual(r['counts']['error'],5);self.assertEqual(verify(self.out)['counts']['error'],5);self.assertNotIn('SECRET_SENTINEL',(self.out/'receipt.json').read_text())
    def test_lf(self):
        self.build()
        for name in ('receipt.json','report.json','review.md'):self.assertNotIn(b'\r',(self.out/name).read_bytes())
    def test_special_files(self):
        f=self.p/'fifo';os.mkfifo(f)
        with self.assertRaises(Invalid):read(f)
        g=self.p/'link';g.symlink_to(ROOT/'examples/suite.json')
        with self.assertRaises(Invalid):read(g)
    def test_cli(self):
        def cli(*args):return subprocess.run([sys.executable,'-m','agent_gate_bench',*map(str,args)],cwd=ROOT,capture_output=True,text=True,timeout=10)
        a=cli('run',ROOT/'examples/suite.json','--adapter',ROOT/'examples/vulnerable_adapter.py','--out',self.out);self.assertEqual(a.returncode,2)
        a=cli('run',ROOT/'examples/suite.json','--adapter',ROOT/'examples/vulnerable_adapter.py','--out',self.out,'--allow-execute','--require-pass');self.assertEqual(a.returncode,3)
        self.assertEqual(cli('verify',self.out).returncode,0);self.assertEqual(cli('verify',self.out,'--require-pass').returncode,3)
if __name__=='__main__':unittest.main()
