"""Exercise the production recorder/renderer and actual patched controller body."""
from pathlib import Path
import argparse,json,subprocess,re

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser()
    for name in ('patched','font-dir','out'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();args.out.mkdir()
    includes=['-I'+str(HERE),'-I'+str(HERE.parent/'formal-xnu'),'-I'+str(args.font_dir)]
    binary=args.out/'recorder-host'
    subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-g','-fsanitize=address,undefined',
                    *includes,str(HERE/'test_flight.c'),'-o',str(binary)],check=True)
    host=subprocess.check_output([str(binary)],cwd=args.out,text=True)
    fixture=args.out/'headers';(fixture/'kern').mkdir(parents=True);(fixture/'machine').mkdir()
    (fixture/'kern/thread.h').write_text('''#include <stdint.h>
typedef struct thread *thread_t;
extern uintptr_t kernel_stack_size;
extern thread_t current_thread(void);
extern uintptr_t thread_get_kernel_stack(thread_t);
''')
    (fixture/'machine/machine_routines.h').write_text('extern int ml_get_max_cpu_number(void);\n')
    # The target object validates instructions and undefined dependencies;
    # only the cloud integration uses the real exported/private XNU ABI.
    (fixture/'kern/K70Flight.h').write_bytes((HERE/'K70Flight.h').read_bytes())
    obj=args.out/'flight-ios16.o'
    subprocess.run(['clang','--target=arm64-apple-ios16.0','-mkernel','-std=c11','-O2','-ffreestanding',
                    '-fno-builtin','-Wall','-Wextra','-Werror',
                    '-I'+str(fixture),*includes,'-c',str(HERE/'K70FlightKernel.c'),'-o',str(obj)],check=True)
    undefined=subprocess.check_output(['llvm-nm','-u',str(obj)],text=True)
    allowed={'_current_thread','_kernel_stack_size','_thread_get_kernel_stack','_ml_get_max_cpu_number','_bzero','_memcpy','_memset',
             '___stack_chk_guard','___stack_chk_fail'}
    actual={line.split()[-1] for line in undefined.splitlines() if line.split()}
    if actual-allowed:raise ValueError('Unexpected recorder dependency: '+str(actual-allowed))
    asm=subprocess.check_output(['llvm-objdump','-d',str(obj)],text=True).lower()
    for pattern in (r'at\s+s1e1w',r'at\s+s1e1r',r'msr\s+par_el1',r'msr\s+daif',r'msr\s+daifset'):
        if not re.search(pattern,asm):raise ValueError('Lost architecture guard: '+pattern)
    instructions='\n'.join(line.split('\t',1)[-1] for line in asm.splitlines() if '\t' in line)
    if re.search(r'\b[qvds][0-9]+\b',instructions):
        raise ValueError('Unexpected FP/SIMD register in emergency recorder')
    (args.out/'flight-ios16-disassembly.txt').write_text(asm)
    text=(args.patched/'iokit/Kernel/IOCPU.cpp').read_text()
    start=text.index('IOCPUInterruptController::initCPUInterruptController(int sources, int cpus)')
    start=text.index('{',start);end=text.index('\nvoid\nIOCPUInterruptController::registerCPUInterruptController',start)
    body=text[start:end]
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <vector>
static std::vector<unsigned> ops;
static bool parent_ok;static bool lock_ok;
static unsigned enters[5],leaves[5];static uint64_t results[5];
void k70_flight_enter(unsigned id,uint64_t){enters[id]++;}
void k70_flight_leave(unsigned id,uint64_t v){leaves[id]++;results[id]=v;}
struct IOInterruptVector {void*interruptLock;};
#define ZALIGN(x) 7
void *zalloc_permanent(unsigned n,unsigned){ops.push_back(2);return calloc(1,n);}
void *IOLockAlloc(){ops.push_back(3);return lock_ok?reinterpret_cast<void*>(0x1234):nullptr;}
void IOLockFree(void*){}
void ml_set_max_cpus(unsigned n){assert(n==1);ops.push_back(4);}
constexpr int kIOReturnInvalid=10,kIOReturnNoResources=20,kIOReturnSuccess=0;
struct Parent {bool init(){ops.push_back(1);return parent_ok;}};
struct IOCPUInterruptController:Parent {
 using super=Parent;int numSources,numCPUs;IOInterruptVector*vectors=nullptr;
 ~IOCPUInterruptController(){free(vectors);}
 int init(int sources,int cpus)
'''
    suffix=r'''
};
int main(){
 for(unsigned mode=0;mode<3;mode++){
  ops.clear();for(unsigned i=0;i<5;i++){enters[i]=0;leaves[i]=0;results[i]=0;}
  parent_ok=mode!=0;lock_ok=mode==2;IOCPUInterruptController c;int r=c.init(1,1);
  assert(r==(mode==0?10:mode==1?20:0));
  assert(enters[1]==1 && leaves[1]==1 && results[1]==parent_ok);
  if(mode==0)assert(ops==std::vector<unsigned>{1});
  if(mode==1){assert((ops==std::vector<unsigned>{1,2,3}));assert(results[3]==0 && leaves[4]==0);}
  if(mode==2){assert((ops==std::vector<unsigned>{1,2,3,4}));assert(results[3]==0x1234 && leaves[4]==1);}
 }
}
'''
    source=args.out/'actual-controller-contract.cpp';source.write_text(prefix+body+suffix)
    executable=args.out/'actual-controller-contract'
    subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',str(source),'-o',str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
    panic=(args.patched/'osfmk/kern/debug.c').read_text()
    begin=panic.index('\npanic_trap_to_debugger(')
    assert panic.index('k70_flight_panic(',begin)<panic.index('iotrace_disable();',begin)
    scheduler=(args.patched/'osfmk/kern/sched_prim.c').read_text()
    begin=scheduler.index('\nthread_block_reason(\n')
    assert scheduler.index('k70_flight_wait(',begin)<scheduler.index('s = splsched();',begin)
    report={'host_sanitizers_and_renderer':host.strip(),'actual_patched_controller_success_and_fail_returns_preserved':True,
            'panic_capture_before_machine_panic_backend':True,'wait_capture_before_scheduling':True,
            'arm64_ios16_object_checked':True,'undefined_dependencies':sorted(actual),
            'real_kernel_header_and_link_validation_requires_cloud':True,'hardware_tested':False}
    (args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
