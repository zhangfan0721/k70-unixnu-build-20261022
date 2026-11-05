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
        self.assertFalse(result['controller_takeover'])
        self.assertIn('K70SctlrQualification.h',result['compiled_files'])

    def test_takeover_and_unprobed_reads_are_rejected(self):
        for operation in ('hostStopQueue(why);','hostStartQueue(why);',
                          'write32(gHost.smmu,0xc5000,0);',
                          'read32(gHost.smmu,0xc5000);'):
            with self.subTest(operation=operation),self.assertRaises(ValueError):
                self.check_copy(lambda s:s.replace('  static K70SmmuPlan p;p=k70PlanUfsSmmu(0,4,smmuRead,trace,true);',
                    '  '+operation+'\n  static K70SmmuPlan p;p=k70PlanUfsSmmu(0,4,smmuRead,trace,true);'))

    def test_extra_store_and_missing_write_probe_are_rejected(self):
        with self.assertRaises(ValueError):
            self.check_copy(lambda s:s.replace('smmu+o)=v;', 'smmu+o)=v; *reinterpret_cast<volatile uint32_t *>(smmu+o)=v;'))
        with self.assertRaises(ValueError):
            self.check_copy(lambda s:s.replace('k70ReadWriteTranslation(smmu+0xc5000)', 'k70ReadTranslation(smmu+0xc5000)'))

if __name__=='__main__':unittest.main()
