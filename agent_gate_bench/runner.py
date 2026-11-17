"""Execute explicitly trusted standalone adapters, with bounded pipes; not a sandbox."""
import os, selectors, signal, subprocess, sys, tempfile, time
from pathlib import Path
from .core import *
CAP=256*1024

def execute(script,request,timeout):
    if os.name!='posix':raise Invalid('Execution currently supports POSIX only; verification is portable.')
    integer(timeout,1,10)
    with tempfile.TemporaryDirectory(prefix='agent-gate-') as td:
        path=Path(td)/'adapter.py';path.write_bytes(script)
        with tempfile.TemporaryFile() as source:
            source.write(canonical(request));source.seek(0)
            env={'PATH':os.defpath,'LANG':'C.UTF-8'}
            p=subprocess.Popen([sys.executable,'-I',str(path)],stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=td,env=env,start_new_session=True)
            stdout=bytearray();stderr=bytearray();status=None;deadline=time.monotonic()+timeout
            def stop():
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            try:
                with selectors.DefaultSelector() as sel:
                    for f,buffer in ((p.stdout,stdout),(p.stderr,stderr)):
                        os.set_blocking(f.fileno(),False);sel.register(f,selectors.EVENT_READ,buffer)
                    while sel.get_map() or p.poll() is None:
                        if time.monotonic()>=deadline:status='timeout';break
                        if p.poll() is not None:stop() # close inherited pipes from same-group children
                        for key,_ in sel.select(min(.05,max(0,deadline-time.monotonic()))):
                            chunk=os.read(key.fileobj.fileno(),8192)
                            if not chunk:sel.unregister(key.fileobj);continue
                            available=CAP-len(stdout)-len(stderr)
                            key.data.extend(chunk[:available])
                            if len(chunk)>available:status='output_limit';break
                        if status:break
            finally:
                stop();p.wait(timeout=2);p.stdout.close();p.stderr.close()
            code=p.returncode;res=None
            if status is None:
                if code!=0:status='nonzero_exit'
                else:
                    try:res=response(parse(bytes(stdout)));status='complete'
                    except Invalid:status='invalid_response'
            return {'execution_status':status,'returncode':code,'stdout_sha256':digest(stdout),'stderr_sha256':digest(stderr),'stdout_bytes':len(stdout),'stderr_bytes':len(stderr),'stdout_text':bytes(stdout).decode('utf8') if status=='complete' else None,'response':res}

def run(suite_path,adapter_path,out,allow_execute=False,timeout=3):
    if not allow_execute:raise Invalid('Explicit --allow-execute is required for trusted adapter code.')
    if os.name!='posix':raise Invalid('Execution currently supports POSIX only.')
    if Path(out).exists() or Path(out).is_symlink():raise Invalid('Output path already exists.')
    raw=read(suite_path);suite=load(raw);script=read(adapter_path);integer(timeout,1,10)
    receipt={'schema':1,'suite_sha256':digest(raw),'adapter_sha256':digest(script),'timeout_seconds':timeout,'records':[]}
    for case in suite['cases']:
        result=execute(script,case['request'],timeout);result['case_id']=case['id'];receipt['records'].append(result)
    r=report(suite,receipt,raw)
    data={'suite.json':raw,'receipt.json':canonical(receipt),'report.json':canonical(r),'review.md':review(r)}
    if any(len(v)>OUTPUT_LIMIT for v in data.values()):raise Invalid('Generated bundle file too large.')
    Path(out).mkdir(exist_ok=False)
    for name,v in data.items():(Path(out)/name).write_bytes(v)
    return r
