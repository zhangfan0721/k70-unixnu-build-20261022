import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('macho_asm',HERE/'macho_asm.py')
module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(module)


class MachoAssemblyTests(unittest.TestCase):
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
