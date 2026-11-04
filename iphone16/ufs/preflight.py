"""Run the same strict preflight locally and with actual CI compilers."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cxx',required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    version=subprocess.check_output([a.cxx,'--version'],text=True)
    (a.out/'compiler.txt').write_text(version)
    subprocess.run([sys.executable,'-B',str(HERE/'generate.py'),str(a.upstream)],check=True)
    subprocess.run(['git','-C',str(HERE.parent.parent),'diff','--exit-code'],check=True)
    records=[]
    for name in ('policy','commands','smmu'):
        exe=(a.out/('ufs-'+name+'-test')).resolve()
        record=(a.out/(name+'.compile.json')).resolve()
        command=[a.cxx,'-std=c++17','-Wall','-Wextra','-Wunused-template','-Werror']
        if name=='policy':command+=['-DHOST_TEST']
        command += ['-MJ',str(record),str(HERE/('test_'+name+'.cpp')),'-o',str(exe)]
        subprocess.run(command,check=True);subprocess.run([str(exe)],check=True)
        records.append({'name':name,'command':command,'passed':True})
    subprocess.run([sys.executable,'-B',str(HERE/'check_inputs.py')],check=True)
    (a.out/'result.json').write_text(json.dumps({'compiler':version,'records':records,
        'SmmuTakeover_sha256':hashlib.sha256((HERE/'SmmuTakeover.h').read_bytes()).hexdigest(),
        'global_warning_suppression':False,'hardware_operations':False},indent=2)+'\n')
if __name__=='__main__':main()
