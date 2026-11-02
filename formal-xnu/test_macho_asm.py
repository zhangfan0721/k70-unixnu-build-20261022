import importlib.util
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('macho_asm',HERE/'macho_asm.py')
module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(module)


class MachoAssemblyTests(unittest.TestCase):
    def test_cpu_traces_preserve_all_original_tokens_and_short_circuit_refusals(self):
        original=(Path(os.environ['K70_CORE_SOURCE'])/'drivers/ArmCpu/ArmCpu.cpp').read_text()
        fixed=module.instrument_armcpu(original)
        restored=fixed.replace('extern "C" void k70_formal_cpu_trace(const char *, uint64_t);','')
        restored=restored.replace('extern "C" void k70_formal_cpu_online(void);','').replace('k70_formal_cpu_online();','')
        restored=re.sub(r'k70_formal_cpu_trace\("[^"\n]+", [^;\n]+\);','',restored)
        self.assertEqual(re.sub(r'\s+','',restored),re.sub(r'\s+','',original))
        self.assertEqual(fixed.count('k70_formal_cpu_online();'),1)
        self.assertIn('k70_formal_cpu_trace("start passed", 1); k70_formal_cpu_online(); return true;',fixed)
        begin=fixed.index('bool ArmCpu::prepareGic (void)')
        end=fixed.index('\nvoid ArmCpu::enableGic',begin)
        body=fixed[begin:end]
        stub='''typedef unsigned long long uint64_t;
extern "C" void k70_formal_cpu_trace(const char *, uint64_t) {}
static unsigned mask, calls, gGicShared;
class ArmCpu { public:
 bool mapGic() {calls|=1;return mask&1;}
 bool initDistributor() {calls|=2;return mask&2;}
 bool wakeRedistributor(bool) {calls|=4;return mask&4;}
 bool prepareGic();
};
'''+body+'''
int main() {
 ArmCpu cpu;
 for(mask=0;mask<8;mask++) {
  calls=gGicShared=0;
  if(cpu.prepareGic() != (mask==7)) return 1;
  unsigned expected=1|((mask&1)?2:0)|(((mask&3)==3)?4:0);
  if(calls!=expected || gGicShared!=(mask==7)) return 2;
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'cpu.cpp';source.write_text(stub)
            subprocess.run(['clang++','-Wall','-Wextra','-Werror',str(source),'-o',str(root/'host')],check=True)
            subprocess.run([str(root/'host')],check=True)
            subprocess.run(['clang++','--target=arm64-apple-darwin','-ffreestanding',
                '-Wall','-Wextra','-Werror','-c',str(source),'-o',str(root/'cpu.o')],check=True)

    def test_counter_and_barriers_survive_darwin_assembly(self):
        text='''#include <stdint.h>
uint64_t counter(void) {
 uint64_t value;
 __asm__ volatile ("isb; mrs %0, cntvct_el0" : "=r" (value));
 return value;
}
void barrier(uint64_t value) {
 __asm__ volatile ("msr icc_sre_el1, %0; isb" :: "r" (value) : "memory");
}
'''
        fixed=module.normalize_inline_asm(text)
        self.assertIn('return value;',fixed)
        self.assertIn(': "=r" (value)',fixed)
        self.assertEqual(module.normalize_inline_asm(fixed),fixed)
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'counter.c';source.write_text(fixed)
            subprocess.run(['clang','--target=arm64-apple-darwin','-ffreestanding','-O2',
                '-Wall','-Wextra','-Werror','-c',str(source),'-o',str(tmp/'counter.o')],check=True)
            machine=subprocess.check_output(['llvm-objdump','-d',str(tmp/'counter.o')],text=True).lower()
            self.assertRegex(machine,r'mrs\s+x\d+, cntvct_el0')
            self.assertRegex(machine,r'msr\s+icc_sre_el1, x\d+')
            self.assertGreaterEqual(machine.count('isb'),2)


if __name__=='__main__':unittest.main()
