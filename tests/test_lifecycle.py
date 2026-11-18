"""Real local processes, synthetic files only; no network or model calls."""
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from agent_gate_bench import runner
from agent_gate_bench.lifecycle import Cancelled
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='posix', 'POSIX execution only')
class Lifecycle(unittest.TestCase):
    def test_bundle_permissions(self):
        for mask in (0o022,0o000):
            for module,suite,adapter in [('agent_gate_bench','suite.json','boundary_adapter.py'),('agent_gate_bench.effects','effects_suite.json','effects_reference.py')]:
                with self.subTest(mask=mask,module=module),tempfile.TemporaryDirectory() as td:
                    dest=Path(td)/'out'
                    r=subprocess.run([sys.executable,'-m',module,'run',str(ROOT/'examples'/suite),'--adapter',str(ROOT/'examples'/adapter),'--out',str(dest),'--allow-execute'],cwd=ROOT,umask=mask,capture_output=True)
                    self.assertEqual(r.returncode,0,r.stderr)
                    self.assertEqual(dest.stat().st_mode&0o777,0o700)
                    for f in dest.iterdir():self.assertEqual(f.stat().st_mode&0o777,0o600,f.name)

    def test_cancel_active_adapter(self):
        for module,suite in [('agent_gate_bench','suite.json'),('agent_gate_bench.effects','effects_suite.json')]:
            for sig in (signal.SIGTERM,signal.SIGINT):
                with self.subTest(module=module,sig=sig),tempfile.TemporaryDirectory() as td:
                    base=Path(td);ready=base/'pid';late=base/'late';cwd=base/'cwd';adapter=base/'a.py'
                    adapter.write_text(f'import os,time,pathlib\npathlib.Path({str(cwd)!r}).write_text(os.getcwd())\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\ntime.sleep(1)\npathlib.Path({str(late)!r}).write_text("unexpected")\ntime.sleep(20)\n')
                    p=subprocess.Popen([sys.executable,'-m',module,'run',str(ROOT/'examples'/suite),'--adapter',str(adapter),'--out',str(base/'out'),'--allow-execute','--timeout','10'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                    try:
                        deadline=time.monotonic()+5
                        while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
                        self.assertTrue(ready.exists())
                        child=int(ready.read_text());p.send_signal(sig)
                        _,err=p.communicate(timeout=5)
                        self.assertEqual(p.returncode,128+sig,err)
                        with self.assertRaises(ProcessLookupError):os.kill(child,0)
                        self.assertFalse(Path(cwd.read_text()).exists())
                        time.sleep(1.1);self.assertFalse(late.exists())
                        self.assertFalse((base/'out').exists())
                    finally:
                        if p.poll() is None:p.kill();p.wait()
                        if ready.exists():
                            try:os.killpg(int(ready.read_text()),signal.SIGKILL)
                            except ProcessLookupError:pass
                        if p.stderr:p.stderr.close()

    def test_cancel_in_popen_handle_gap(self):
        real=subprocess.Popen;children=[]
        def popen(*a,**kw):
            p=real(*a,**kw);children.append(p)
            os.kill(os.getpid(),signal.SIGTERM)
            return p
        before={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
        with patch.object(runner.subprocess,'Popen',popen):
            with self.assertRaises(Cancelled):runner.execute(b'import time;time.sleep(20)',{},3)
        self.assertEqual(before,{s:signal.getsignal(s) for s in before})
        self.assertIsNotNone(children[0].poll())
        with self.assertRaises(ProcessLookupError):os.kill(children[0].pid,0)

    def test_refuse_existing_output_and_symlink(self):
        for mode in ('directory','symlink','dangling'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
                dest=Path(td)/'out';target=Path(td)/'target'
                if mode=='directory':dest.mkdir()
                else:
                    if mode=='symlink':target.mkdir()
                    dest.symlink_to(target)
                with self.assertRaises(runner.Invalid):
                    runner.run(ROOT/'examples/suite.json',ROOT/'examples/boundary_adapter.py',dest,True)
                self.assertEqual(list(target.iterdir()) if target.exists() else [],[])

    def test_parent_umask_unchanged(self):
        before=os.umask(0o022)
        try:
            runner.execute(b'print("{}")',{},1)
            actual=os.umask(0o022);self.assertEqual(actual,0o022)
        finally:os.umask(before)

    def test_non_main_thread_rejected(self):
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            with self.assertRaises(ValueError):pool.submit(runner.execute,b'',{},1).result()

    def test_cancel_during_response_processing(self):
        original=runner.response
        before={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
        def inject(value):
            os.kill(os.getpid(),signal.SIGTERM)
            return original(value)
        with patch.object(runner,'response',inject):
            with self.assertRaises(Cancelled):
                runner.execute(b'print(\'{"calls":[],"final":"done"}\')',{},2)
        self.assertEqual(before,{s:signal.getsignal(s) for s in before})

    def test_deferred_cancel_at_scope_exit(self):
        from agent_gate_bench.lifecycle import cancellation
        before={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
        with self.assertRaises(Cancelled):
            with cancellation() as state:
                state['cleaning']=True
                os.kill(os.getpid(),signal.SIGTERM)
        self.assertEqual(before,{s:signal.getsignal(s) for s in before})

    def test_deferred_cancel_preserves_existing_exception(self):
        from agent_gate_bench.lifecycle import cancellation
        with self.assertRaisesRegex(RuntimeError,'original'):
            with cancellation() as state:
                state['cleaning']=True
                os.kill(os.getpid(),signal.SIGTERM)
                raise RuntimeError('original')
