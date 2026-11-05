"""Regression proof that the generated diagnostic cannot reach takeover."""
from pathlib import Path
import shutil
import tempfile
import unittest
import check_inputs

HERE=Path(__file__).resolve().parent

class ScopeTests(unittest.TestCase):
    def check_copy(self, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for p in HERE.iterdir():
                if p.suffix in ('.h','.inc'):shutil.copy2(p,root/p.name)
            transport=root/'K70UfsTransport.inc'
            transport.write_text(mutate(transport.read_text()))
            original=check_inputs.HERE
            try:
                check_inputs.HERE=root
                return check_inputs.check()
            finally:check_inputs.HERE=original

    def test_actual_include_set_excludes_preserved_configuration(self):
        result=self.check_copy(lambda s:s)
        self.assertTrue(result['smmu_configuration_writes'])
        self.assertTrue(result['controller_takeover'])
        self.assertNotIn('K70SctlrQualification.h',result['compiled_files'])

    def test_raw_store_and_reentry_are_rejected(self):
        with self.assertRaises(ValueError):
            self.check_copy(lambda s:s.replace('  bool pass=hostBringUp',
                '  *reinterpret_cast<volatile uint32_t *>(0x150c5000)=0;\n  bool pass=hostBringUp'))
        with self.assertRaises(ValueError):
            self.check_copy(lambda s:s.replace('if(entered)return;entered=true;', 'entered=true;'))

    def test_extra_command_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self.check_copy(lambda s:s+'\nvoid bad(){hostWrite(0x34,0);}')

if __name__=='__main__':unittest.main()
