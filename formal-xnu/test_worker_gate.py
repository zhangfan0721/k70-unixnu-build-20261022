import re
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent


class WorkerGateTests(unittest.TestCase):
    def test_early_not_ready_does_not_consume_late_once_gate(self):
        text=(HERE/'KernelAdapter.c').read_text()
        body=re.search(r'static int k70_formal_claim_worker\(void\)\n\{.*?\n\}',text,re.S)
        self.assertIsNotNone(body)
        source='''volatile unsigned armcpu_registered, armcpu_gic_ready;
static volatile unsigned k70_worker_started;
static volatile unsigned k70_cpu_online_ready;
'''+body[0]+'''
int main(void) {
 if(k70_formal_claim_worker() || k70_worker_started) return 1;
 armcpu_registered=1;
 if(k70_formal_claim_worker() || k70_worker_started) return 2;
 armcpu_gic_ready=1;
 if(k70_formal_claim_worker() || k70_worker_started) return 5;
 k70_cpu_online_ready=1;
 if(!k70_formal_claim_worker() || !k70_worker_started) return 3;
 if(k70_formal_claim_worker()) return 4;
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'gate.c';path.write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',str(path),'-o',str(root/'host')],check=True)
            subprocess.run([str(root/'host')],check=True)
            subprocess.run(['clang','--target=arm64-apple-darwin','-ffreestanding',
                '-std=c11','-Wall','-Wextra','-Werror','-c',str(path),'-o',str(root/'gate.o')],check=True)


if __name__=='__main__':unittest.main()
