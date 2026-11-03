"""Host exercise of real CPU-controller ordering with observation-only checkpoints."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'formal-xnu'))
from macho_asm import instrument_armcpu
from cpu_start_trace import instrument


class CPUStartTraceTests(unittest.TestCase):
    def test_real_controller_path_and_stopped_phase(self):
        upstream = (HERE.parents[1] / 'deps/core/drivers/ArmCpu/ArmCpu.cpp').read_text()
        original = instrument_armcpu(upstream)
        fixed = instrument(original)
        self.assertEqual(instrument(fixed), fixed)
        start = fixed.index('  unsigned cpuCount =')
        end = fixed.index('  __atomic_store_n (&gBootRegistered', start)
        body = fixed[start:end]
        prefix = r'''
#include <cassert>
#include <cstdint>
#include <vector>
volatile uint32_t k70_cpu_start_phase;
static std::vector<unsigned> calls;
static unsigned stop;
struct Stop {};
void call(unsigned phase) { assert(k70_cpu_start_phase == phase); calls.push_back(phase); if(stop==phase) throw Stop{}; }
void k70_cpu_phase(unsigned phase) { __atomic_store_n(&k70_cpu_start_phase, phase, __ATOMIC_RELEASE); }
void k70_flight_begin(){}
void k70_flight_allocation(uintptr_t){}
unsigned ml_get_max_cpu_number() {return 0;}
constexpr int kIOReturnSuccess=0;
void panic(const char*) {assert(false);}
struct IOCPUInterruptController {
 int initCPUInterruptController(unsigned sources,unsigned cpus) {assert(sources==1 && cpus==1);call(12);return 0;}
 void registerCPUInterruptController(){call(20);}
 void enableCPUInterrupt(void*){call(30);}
 int registerInterrupt(void*,unsigned,void*,void(*)(void*,void*,void*,int),void*){call(40);return 0;}
};
IOCPUInterruptController *gController;
struct ArmCpu {
 IOCPUInterruptController *controller=nullptr;
 unsigned logicalId=0;
 static void dispatch(void*,void*,void*,int){}
 void initCPU(bool boot){assert(boot);call(50);}
 void registerService(){call(60);}
 void run(void *provider) {
'''
        suffix = r'''
 }
 ~ArmCpu(){delete controller;}
};
int main() {
 const std::vector<unsigned> expected{12,20,30,40,50,60};
 for (unsigned failure: {0u,12u,20u,30u,40u,50u,60u}) {
  calls.clear();stop=failure;k70_cpu_start_phase=0;
  ArmCpu cpu;
  try {cpu.run(nullptr);assert(failure==0);assert(k70_cpu_start_phase==61);assert(calls==expected);}
  catch(Stop&) {assert(k70_cpu_start_phase==failure);assert(calls.back()==failure);}
 }
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'controller.cpp'
            source.write_text(prefix + body + suffix)
            binary = Path(tmp) / 'controller'
            subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
