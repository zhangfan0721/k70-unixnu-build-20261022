"""Run the same strict preflight locally and with actual CI compilers."""
from pathlib import Path
import argparse,hashlib,json,struct,subprocess,sys
HERE=Path(__file__).resolve().parent

def verify_mapping_object(path):
    data=path.read_bytes()
    if struct.unpack_from('<III',data)!=(0xfeedfacf,0x100000c,0):
        raise ValueError('Mapping proof is not an ARM64 Mach-O object')
    if struct.unpack_from('<I',data,12)[0]!=1:
        raise ValueError('Mapping proof is not a relocatable object')
    words=struct.unpack('<'+'I'*(len(data)//4),data[:len(data)//4*4])
    for i in range(len(words)-7):
        a=words[i:i+8]
        if ((a[0]&~31)==0xd53b4220 and a[1]==0xd5034fdf and
            (a[2]&~31)==0xd5387400 and (a[3]&~31)==0xd5087800 and
            a[4]==0xd5033fdf and (a[5]&~31)==0xd5387400 and
            a[6]==(0xd5187400|(a[2]&31)) and a[7]==(0xd51b4220|(a[0]&31))):
            return
    raise ValueError('ARM64 object lost the saved/restored DAIF/PAR AT S1E1R sequence')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cxx',required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    version=subprocess.check_output([a.cxx,'--version'],text=True)
    (a.out/'compiler.txt').write_text(version)
    sdk=[]
    if sys.platform=='darwin':
        sdk=['-isysroot',subprocess.check_output(
            ['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()]
    subprocess.run([sys.executable,'-B',str(HERE/'generate.py'),str(a.upstream)],check=True)
    subprocess.run(['git','-C',str(HERE.parent.parent),'diff','--exit-code'],check=True)
    records=[]
    for name in ('policy','commands','smmu','mapping'):
        exe=(a.out/('ufs-'+name+'-test')).resolve()
        record=(a.out/(name+'.compile.json')).resolve()
        command=[a.cxx,*sdk,'-std=c++17','-Wall','-Wextra','-Wunused-template','-Werror']
        if name=='policy':command+=['-DHOST_TEST']
        command += ['-MJ',str(record),str(HERE/('test_'+name+'.cpp')),'-o',str(exe)]
        subprocess.run(command,check=True);subprocess.run([str(exe)],check=True)
        records.append({'name':name,'command':command,'passed':True})
    obj=(a.out/'mapping-ios16.o').resolve()
    command=[a.cxx,'--target=arm64-apple-ios16.0','-std=c++17','-ffreestanding',
             '-fno-exceptions','-fno-rtti','-O2','-Wall','-Wextra','-Wunused-template','-Werror',
             '-MJ',str((a.out/'mapping-ios16.compile.json').resolve()),
             '-c',str(HERE/'test_mapping_arm64.cpp'),'-o',str(obj)]
    subprocess.run(command,check=True);verify_mapping_object(obj)
    records.append({'name':'mapping-ios16-object','command':command,'passed':True,
                    'DAIF_PAR_AT_instructions_verified':True,
                    'sha256':hashlib.sha256(obj.read_bytes()).hexdigest()})
    subprocess.run([sys.executable,'-B',str(HERE/'test_mapping_scope.py')],check=True)
    subprocess.run([sys.executable,'-B',str(HERE/'check_inputs.py')],check=True)
    (a.out/'result.json').write_text(json.dumps({'compiler':version,'records':records,
        'SmmuTakeover_sha256':hashlib.sha256((HERE/'SmmuTakeover.h').read_bytes()).hexdigest(),
        'global_warning_suppression':False,'hardware_operations':False},indent=2)+'\n')
if __name__=='__main__':main()
