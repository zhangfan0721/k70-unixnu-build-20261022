import re
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class LoaderTests(unittest.TestCase):
    def test_actual_coff_cleans_handoff_code_before_mmu_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inc = Path(os.environ['K70_UEFI_SOURCE'])/'Mu_Basecore/MdePkg/Include'
            obj = root/'entry.obj'
            subprocess.run(['clang','--target=aarch64-pc-windows-msvc',
                '-D__ASSEMBLER__','-imacros',str(inc/'Base.h'),
                '-x','assembler-with-cpp','-I',str(inc/'AArch64'),'-I',str(inc),'-c',
                str(HERE/'LoaderEntry.S'),'-o',str(obj)],check=True)
            code = subprocess.check_output(['llvm-objdump','-d',str(obj)],text=True).lower()
            self.assertEqual(len(re.findall(r'dc\s+civac',code)),2)
            own = code.index('dc\tcivac, x12')
            off = code.index('msr\tsctlr_el1')
            self.assertLess(own,off)
            self.assertRegex(code,r'adr\s+x12,')
            self.assertRegex(code,r'adr\s+x13,')
            self.assertIn('br\tx1',code)
            # The actual ADR endpoints must cover every instruction through BR.
            start = int(re.search(r'([0-9a-f]+) <darwinenter>:',code)[1],16)
            end = int(re.search(r'^\s*([0-9a-f]+):.*\bbr\s+x1',code,re.M)[1],16)+4
            self.assertEqual(int(re.search(r'adr\s+x12, 0x([0-9a-f]+)',code)[1],16),start)
            self.assertEqual(int(re.search(r'adr\s+x13, 0x([0-9a-f]+)',code)[1],16),end)
            # Neither handoff argument may be overwritten by maintenance/markers.
            enter = code[code.index('<darwinenter>'):]
            self.assertNotRegex(enter,r'\t(?:mov|add|sub|ldr|mrs|bic|lsr)\s+[wx][01],')


if __name__ == '__main__':
    unittest.main()
