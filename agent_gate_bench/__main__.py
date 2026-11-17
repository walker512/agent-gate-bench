import argparse,json,sys
from .core import Invalid,verify
from .runner import run

def main():
    p=argparse.ArgumentParser(description='Run trusted local adapter code; NOT a security sandbox.')
    sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');r.add_argument('suite');r.add_argument('--adapter',required=True);r.add_argument('--out',required=True);r.add_argument('--allow-execute',action='store_true');r.add_argument('--timeout',type=int,default=3);r.add_argument('--require-pass',action='store_true')
    v=sub.add_parser('verify');v.add_argument('bundle');v.add_argument('--require-pass',action='store_true')
    a=p.parse_args()
    try:
        result=run(a.suite,a.adapter,a.out,a.allow_execute,a.timeout) if a.command=='run' else verify(a.bundle)
        print(json.dumps({'consistent':True,'status':result['status'],'counts':result['counts']},sort_keys=True))
        return 3 if a.require_pass and result['status']!='pass' else 0
    except Invalid as e:print('Invalid: '+str(e),file=sys.stderr);return 2
    except (OSError,ValueError,OverflowError,subprocess.SubprocessError):print('Operational error; no input or paths are echoed.',file=sys.stderr);return 2
import subprocess
if __name__=='__main__':sys.exit(main())
