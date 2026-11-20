from pathlib import Path
import hashlib,importlib.util,json,re,tempfile,types,unittest

HERE=Path(__file__).resolve().parent
COMMIT='1'*40

class MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=None
        if not (HERE/'ci_matrix.py').exists():return
        s=importlib.util.spec_from_file_location('irq_ci',HERE/'ci_matrix.py');cls.m=importlib.util.module_from_spec(s);s.loader.exec_module(cls.m)
    def setUp(self):
        self.assertIsNotNone(self.m,'parallel CI runner missing')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def fake(self,fail=None,skip=None):
        def execute(cmd,*,cwd,env,stdout,stderr):
            suite=Path(cmd[-2]).name if cmd[-1]=='-v' else None
            self.assertEqual(cmd[1:4],['-m','unittest','discover']);self.assertEqual(cmd[-3],'-s')
            count=self.m.BASELINE_COUNTS.get(suite,8)
            stdout.write(f'Ran {count} tests in 0.100s\n\n'+('FAILED (failures=1)' if suite==fail else 'OK (skipped=1)' if suite==skip else 'OK')+'\n');stdout.flush()
            return types.SimpleNamespace(returncode=1 if suite==fail else 0)
        return execute
    def fixtures(self):
        for group in self.m.GROUPS:self.m.run_group(group,self.root,self.root/group,COMMIT,executor=self.fake())
    def report(self,group):return self.root/group/'group-report.json'
    def write(self,path,data):path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    def test_partition_preserves_all_prior_suites_once(self):
        all_suites=[s for a in self.m.GROUPS.values() for s in a]
        self.assertEqual(len(self.m.GROUPS),5);self.assertEqual(len(all_suites),13);self.assertEqual(len(set(all_suites)),13)
        self.assertEqual(set(all_suites),set(self.m.BASELINE_COUNTS)|{'xnu-timer-irq-checkpoint'})
        self.assertEqual(sum(self.m.BASELINE_COUNTS.values()),238)
    def test_successful_group_executes_suite_commands_and_binds_logs(self):
        r=self.m.run_group('lightweight',self.root,self.root/'lightweight',COMMIT,executor=self.fake())
        self.assertTrue(r['passed']);self.assertEqual(len(r['suites']),6)
        for item in r['suites']:
            data=(self.root/'lightweight'/item['log']).read_bytes();self.assertEqual(item['log_sha256'],hashlib.sha256(data).hexdigest());self.assertEqual(item['tests'],self.m.BASELINE_COUNTS[item['suite']])
    def test_failed_or_skipped_suite_is_not_hidden_and_remaining_suites_run(self):
        for kw in [dict(fail='uefi-probe'),dict(skip='uefi-probe')]:
            with self.subTest(kw=kw):
                out=self.root/str(len(list(self.root.iterdir())))
                r=self.m.run_group('lightweight',self.root,out,COMMIT,executor=self.fake(**kw));self.assertFalse(r['passed']);self.assertEqual(len(r['suites']),6)
    def test_all_five_groups_verify_exact_coverage_commit_and_counts(self):
        self.fixtures();r=self.m.verify_groups(self.root,COMMIT)
        self.assertEqual(r['prior_tests'],238);self.assertEqual(r['new_tests'],8);self.assertEqual(r['groups'],5)
    def test_missing_duplicate_wrong_commit_and_tampered_log_reject(self):
        self.fixtures()
        p=self.report('counter');raw=p.read_bytes();p.unlink()
        with self.assertRaises(ValueError):self.m.verify_groups(self.root,COMMIT)
        p.write_bytes(raw)
        extra=self.root/'duplicate';extra.mkdir();(extra/'group-report.json').write_bytes(raw)
        with self.assertRaises(ValueError):self.m.verify_groups(self.root,COMMIT)
        (extra/'group-report.json').unlink();extra.rmdir()
        d=json.loads(raw);d['integration_commit']='2'*40;self.write(p,d)
        with self.assertRaises(ValueError):self.m.verify_groups(self.root,COMMIT)
        p.write_bytes(raw);log=self.root/'counter'/d['suites'][0]['log'];log.write_text(log.read_text()+'tamper\n')
        with self.assertRaises(ValueError):self.m.verify_groups(self.root,COMMIT)
    def test_consistent_but_wrong_count_or_unsafe_path_reject(self):
        self.fixtures();p=self.report('counter');raw=p.read_bytes();d=json.loads(raw);item=d['suites'][0]
        log=self.root/'counter'/item['log'];data=b'Ran 19 tests in 0.100s\n\nOK\n';log.write_bytes(data);item['tests']=19;item['log_sha256']=hashlib.sha256(data).hexdigest();self.write(p,d)
        with self.assertRaises(ValueError):self.m.verify_groups(self.root,COMMIT)
        item['log']='../escape.log';self.write(p,d)
        with self.assertRaises(ValueError):self.m.verify_groups(self.root,COMMIT)

if __name__=='__main__':unittest.main()
