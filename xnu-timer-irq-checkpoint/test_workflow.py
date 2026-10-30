import importlib.util
from pathlib import Path
import unittest
import yaml

HERE=Path(__file__).resolve().parent
PATH=HERE.parent/'.github/workflows/k70-timer-irq-checkpoint.yml'

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.exists(),'parallel workflow missing')
        self.text=PATH.read_text();self.w=yaml.load(self.text,Loader=yaml.BaseLoader)
        self.jobs=self.w['jobs']

    def test_five_groups_run_all_suites_only_in_checks(self):
        self.assertEqual(self.jobs['checks']['strategy']['matrix']['group'],['lightweight','memory','call','counter','irq'])
        self.assertEqual(self.jobs['checks']['strategy']['fail-fast'],'false')
        self.assertIn('ci_matrix.py run',str(self.jobs['checks']));self.assertNotIn('unittest discover',self.text)
        self.assertNotIn('ci_matrix.py run',str(self.jobs['firmware']))

    def test_firmware_requires_all_groups_and_verifies_before_prepare(self):
        f=self.jobs['firmware'];self.assertEqual(f['needs'],['checks'])
        script='\n'.join(s.get('run','') for s in f['steps'])
        self.assertLess(script.index('ci_matrix.py verify'),script.index('checkpoint/prepare.py'))
        self.assertIn('--commit "$GITHUB_SHA"',script)
        self.assertNotIn('continue-on-error',str(f))
        self.assertEqual(next(s for s in f['steps'] if s.get('uses')=='actions/download-artifact@v4')['with']['merge-multiple'],'true')

    def test_evidence_is_always_collected_after_checks_or_build_failure(self):
        e=self.jobs['evidence'];self.assertEqual(e['needs'],['checks','firmware'])
        self.assertEqual(e['if'],'always()')
        uploads=[s for s in e['steps'] if s.get('uses')=='actions/upload-artifact@v4']
        self.assertEqual(len(uploads),1);self.assertEqual(uploads[0]['if'],'always()')
        self.assertIn('k70-timer-irq-evidence-',uploads[0]['with']['name'])
        for name in ['checks','firmware']:
            step=next(s for s in self.jobs[name]['steps'] if s.get('name')=='Preserve job evidence')
            self.assertEqual(step['if'],'always()')
        self.assertIn('$'+'{{ github.run_attempt }}',self.text)

    def test_same_revision_and_pinned_external_inputs(self):
        for name in ['checks','firmware']:
            steps=self.jobs[name]['steps']
            own=next(s for s in steps if s.get('uses')=='actions/checkout@v4' and s['with'].get('path')=='integration')
            self.assertEqual(own['with']['ref'],'$'+'{{ github.sha }}')
            for repo,ref in [('yyx2025/uefi-vermeer','da38b23cc7b3b3716cf7c72c42866bd73c978dd3'),
                             ('yyx2025/UniXNU-vermeer','4d1572a93d15f5596309c0687fdc85d20ebf2e24')]:
                self.assertEqual(next(s for s in steps if s.get('with',{}).get('repository')==repo)['with']['ref'],ref)

    def test_public_artifact_requires_irq_profile_and_never_claims_hardware(self):
        f='\n'.join(s.get('run','') for s in self.jobs['firmware']['steps'])
        for text in ['virtual-timer-irq-v1','irq_intid','irq_eret','stable_gp_mask','0xd69f03e0',
                     'timer_irq_hardware_verified',"'hardware_tested': False",'private_seed_required']:
            self.assertIn(text,f)
        self.assertNotIn('fastboot',self.text)
        uploads=[s for s in self.jobs['firmware']['steps'] if s.get('uses')=='actions/upload-artifact@v4' and s.get('name')!='Preserve job evidence']
        self.assertEqual(len(uploads),1);self.assertNotIn('if',uploads[0])

if __name__=='__main__':unittest.main()
