import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
SOURCE=Path(os.environ.get('K70_UEFI_SOURCE',HERE.parents[1]/'k70-uefi-source'))
DTB=Path(os.environ.get('K70_DTB',HERE.parents[1]/'k70-device-source/scripts/data/vermeer.dtb'))
KERNEL=Path(os.environ.get('K70_KERNEL',HERE.parents[1]/'k70-xnu-kernel/kernel.development.vermeer-build.macho'))


class BootstrapPackageTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE/'prepare.py').exists(),'bootstrap package generator missing')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ['Platforms/Xiaomi/vermeerPkg','Resources/Configs/vermeer.toml']:
            source,dest=SOURCE/name,self.root/name;dest.parent.mkdir(parents=True,exist_ok=True)
            if source.is_dir():shutil.copytree(source,dest)
            else:shutil.copy2(source,dest)
        for name in ['Font.h','FrameBuffer.h','FrameBufferSerialPortLib.c']:
            path='Silicon/Silicium/SiliciumPkg/Library/FrameBufferSerialPortLib/'+name
            target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True)
            source=SOURCE/path
            content=source.read_bytes() if source.exists() else subprocess.check_output(['git','-C',str(SOURCE),'show','HEAD:'+path])
            target.write_bytes(content)
        self.kernel=self.root/'kernel';self.kernel.write_bytes(KERNEL.read_bytes())

    def run_prepare(self):
        return subprocess.run([sys.executable,str(HERE/'prepare.py'),'--uefi',str(self.root),
            '--dtb',str(DTB),'--kernel',str(self.kernel),'--payload',str(self.root/'payload.bin'),
            '--blobs',str(self.root/'blobs')],capture_output=True,text=True)

    def test_package_preserves_stage07_and_binds_four_page_runtime(self):
        old=HERE.parent/'xnu-entry-checkpoint'
        snapshot=lambda:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in old.iterdir() if p.is_file()}
        before=snapshot();result=self.run_prepare();self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report['mode'],'original-prefix-bootstrap-checkpoint')
        self.assertFalse(report['entry']['bootstrap_map_will_be_enabled'])
        self.assertTrue(report['entry']['original_first_cpu_prefix_preserved'])
        self.assertFalse(report['hardware_tested']);self.assertFalse(report['original_cpu_init_completed'])
        app=self.root/'Platforms/Xiaomi/vermeerProbePkg/Probe'
        source=(app/'Entry.c').read_text()
        self.assertIn('Before[4]',source);self.assertIn('K70_U64 Pages[4]',source)
        self.assertEqual(source.count('I < 4;'),4)
        self.assertIn('I < 40;',source)
        self.assertIn('DEBUG((DEBUG_ERROR, "\\f"))',source)
        self.assertEqual(report['display']['console_row_pixels'],36)
        self.assertEqual(report['display']['context_start_row'],1440)
        self.assertGreater(report['display']['context_start_row'],1322)
        self.assertIn('Base + 0x3f7290',source)
        self.assertIn('mEntryVectorPatch',source);self.assertIn('0x881606000',source)
        self.assertIn('mOriginalPrefixHash',source)
        self.assertIn('STAGE08 ORIGINAL BOOTSTRAP',source)
        self.assertEqual((app/'EntryBlobs.h').read_bytes(),(self.root/'blobs/EntryBlobs.h').read_bytes())
        self.assertEqual(snapshot(),before)
        # Exercise the generated portable policy, not just its textual anchors.
        libfile=self.root/'policy.so'
        subprocess.run(['cc','-DK70_HOST','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',
                        '-I',str(app),str(app/'EntryCore.c'),'-o',str(libfile)],check=True,capture_output=True)
        lib=C.CDLL(str(libfile));f=lib.K70EntryScopes
        f.argtypes=[C.c_uint64]*5+[C.POINTER(C.c_uint64)]
        pages=(C.c_uint64*4)()
        self.assertEqual(f(0x880004000,0x10000000,0x1544000,3440,528,pages),1)
        self.assertEqual(list(pages),[0x8803f9000,0x8803fb000,0x881604000,0x8803fa000])
        self.assertEqual(f(0x880004000,0x10000000,0x1544000,3441,528,pages),0)

    def test_wrong_kernel_creates_no_package_payload_or_blobs(self):
        self.kernel.write_bytes(b'wrong');r=self.run_prepare();self.assertNotEqual(r.returncode,0)
        for p in ['Platforms/Xiaomi/vermeerProbePkg','payload.bin','blobs']:
            self.assertFalse((self.root/p).exists())

    def test_changed_console_font_profile_is_rejected_before_output(self):
        font=self.root/'Silicon/Silicium/SiliciumPkg/Library/FrameBufferSerialPortLib/Font.h'
        original=font.read_bytes();font.write_bytes(original+b'\nchanged\n')
        r=self.run_prepare();self.assertNotEqual(r.returncode,0)
        self.assertIn('Pinned framebuffer console changed',r.stderr)
        self.assertFalse((self.root/'blobs').exists())
        font.write_bytes(original)
        dsc=self.root/'Platforms/Xiaomi/vermeerPkg/vermeer.dsc'
        dsc.write_text(dsc.read_text().replace('PcdFrameBufferFontScale|3','PcdFrameBufferFontScale|2'))
        r=self.run_prepare();self.assertNotEqual(r.returncode,0)
        self.assertIn('36-pixel console',r.stderr)
        self.assertFalse((self.root/'blobs').exists())


if __name__=='__main__':unittest.main()

