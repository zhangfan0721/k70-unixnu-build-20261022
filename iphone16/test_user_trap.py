"""Check real PID1 trap observer bounds and compile its actual iOS16 object."""
from pathlib import Path
import argparse,subprocess,json,struct
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir()
    source=(HERE/'UserBootstrap.c').read_text()
    prefix='#include <stdint.h>\nvoid boot_progress_stage(const char*);void k70_formal_cpu_trace(const char*,uint64_t);\n'
    fixture=a.out/'observer-host.c'
    fixture.write_text(prefix+'#include <assert.h>\nstatic unsigned lines,values;static uint64_t last;\n'
        'void boot_progress_stage(const char*s){assert(s);++lines;}\n'
        'void k70_formal_cpu_trace(const char*s,uint64_t v){assert(s);++values;last=v;}\n'+source+
        '\nint main(void){k70_user_trap(0,2,123,0,5);k70_user_trap(99,1,123,0,5);'
        'k70_user_trap(0,1,123,5,5);assert(!lines&&!values);'
        'k70_user_trap(0,1,123,0,5);assert(lines==1&&values==2&&last==5);'
        'k70_user_trap(0,1,456,0,8);assert(lines==1&&values==2);'
        'k70_user_trap(1,1,789,0,10);assert(lines==2&&values==4&&last==10);'
        'for(unsigned i=0;i<1000;i++)k70_user_trap(i&1,1,i,0,i);assert(lines==2&&values==4);}\n')
    binary=a.out/'observer-host';subprocess.run(['clang','-std=c11','-O1','-Wall','-Wextra','-Werror',str(fixture),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    target=a.out/'observer-ios16.c';target.write_text(prefix+source);obj=target.with_suffix('.o')
    subprocess.run(['clang','--target=arm64-apple-ios16.0','-std=c11','-O2','-ffreestanding','-mgeneral-regs-only','-Wall','-Wextra','-Werror','-c',str(target),'-o',str(obj)],check=True)
    data=obj.read_bytes();assert struct.unpack_from('<4I',data)==(0xfeedfacf,0x100000c,0,1)
    imports=subprocess.check_output(['llvm-nm','--undefined-only',str(obj)],text=True)
    assert set(line.split()[-1] for line in imports.splitlines())=={'_boot_progress_stage','_k70_formal_cpu_trace'}
    (a.out/'undefined.txt').write_text(imports)
    result={'actual_observer_checked':True,'non_pid1_and_non_el0_rejected':True,'only_first_two_trap_kinds_reported':True,
        'arm64_ios16_object_compiled':True,'only_existing_display_imports':True,'actual_userspace_executed':False}
    (a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
