"""Read-only snapshot proof; no firmware build or device access."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class EvidenceTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('uefi_smmu_evidence', HERE/'uefi_smmu_evidence.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def source(self):
        root = Path(os.environ.get('K70_UEFI_SOURCE', HERE.parents[2]/'deps/uefi'))
        if not root.is_dir():
            self.skipTest('Set K70_UEFI_SOURCE to the pinned UEFI source')
        return root

    def stage(self, root, module):
        source = self.source()
        for relative in module.INPUTS:
            target = root/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source/relative, target)
        package = root/module.FORMAL_DSC
        package.parent.mkdir(parents=True)
        package.write_text('[Defines]\n  PLATFORM_NAME = VermeerFormal\n')

    def test_build_copy_only_exact_sources_and_cleanup_unchanged(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.stage(root, module)
            before = {relative:(root/relative).read_text() for relative in module.INPUTS}
            report = module.install(root, 'test-b895104')
            patched = (root/module.LIBRARY).read_text()
            self.assertEqual(module.remove_library_instrumentation(patched), before[module.LIBRARY])
            self.assertEqual(report['cleanup_original_sha256'], report['cleanup_restored_sha256'])
            self.assertEqual(patched.count('ArmSmmuDetachAll (SkipStreams, SkipStreamCount);'), 1)
            self.assertLess(patched.index(module.BEFORE), patched.index('ArmSmmuDetachAll (SkipStreams'))
            self.assertGreater(patched.index(module.AFTER), patched.index('ArmSmmuDetachAll (SkipStreams'))
            sec = (root/module.SEC).read_text()
            call = sec.index('  ArmSmmuEvidencePrint ();')
            self.assertLess(sec.index('Status = SerialPortInitialize ();'), call)
            self.assertLess(sec.index('  PrintFirmwareVersion ();'), call)
            self.assertLess(call, sec.index('  InitializeDebugAgent ('))
            for relative in (module.PLATFORM, module.SMMU_IO):
                self.assertEqual((root/relative).read_text(), before[relative])
            with self.assertRaises(ValueError):
                module.install(root, 'second')

    def test_refusals_do_not_partially_modify_copy(self):
        module = self.module()
        for failure in ('no-build-copy', 'changed-source', 'bad-tag'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.stage(root, module)
                if failure == 'no-build-copy':
                    (root/module.FORMAL_DSC).unlink()
                if failure == 'changed-source':
                    (root/module.SEC).write_text((root/module.SEC).read_text()+'\nchanged\n')
                before = {p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with self.assertRaises(ValueError):
                    module.install(root, 'bad\nDEBUG' if failure == 'bad-tag' else 'test')
                self.assertEqual(before, {p:p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_installed_library_aarch64_syntax_with_real_uefi_headers(self):
        clang = shutil.which('clang')
        if not clang:
            self.skipTest('AArch64-capable clang is required')
        module = self.module()
        source = self.source()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.stage(root, module)
            module.install(root, 'syntax-test')
            include = [source/'Mu_Basecore/MdePkg/Include',
                       source/'Mu_Basecore/MdePkg/Include/AArch64',
                       source/'Mu_Basecore/ArmPkg/Include',
                       source/'Silicon/Qualcomm/QcomPkg/Include',
                       source/'Silicon/Silicium/SiliciumPkg/Include',
                       (source/module.LIBRARY).parent]
            subprocess.run([clang,'--target=aarch64-none-elf','-std=c11',
                            '-ffreestanding','-fshort-wchar','-Wall','-Wextra','-Werror',
                            '-include','Uefi.h',
                            *[flag for path in include for flag in ('-I',str(path))],
                            '-fsyntax-only',str(root/module.LIBRARY)],check=True)

    def test_raw_snapshot_bounded_and_unknown_layout_declined(self):
        cc = shutil.which('cc') or shutil.which('clang')
        if not cc:
            self.skipTest('A host C compiler is required')
        source = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef uint32_t UINT32;
typedef uint64_t UINT64;
typedef uintptr_t UINTN;
typedef int BOOLEAN;
typedef void VOID;
#define STATIC static
#define CONST const
#define TRUE 1
#define FALSE 0
#include "UefiSmmuEvidence.h"
static UINT32 words[0xd0000 / 4];
static unsigned reads, highest, id_reads;
static UINT32 read32(VOID *unused, UINTN address) {
  (void)unused;
  assert(address >= 0x15000000 && address <= 0x150cffff - 3);
  UINT32 offset=(UINT32)(address - 0x15000000);
  assert(!(offset & 3));
  reads++;
  if(offset > highest) highest=offset;
  if(offset==0x20 || offset==0x24 || offset==0x28) id_reads++;
  return words[offset / 4];
}
static void setup(void) {
  memset(words,0,sizeof(words));reads=highest=id_reads=0;
  words[0x20/4]=0x4c017e69;words[0x24/4]=0x60000046;words[0x28/4]=0x5111;
  words[0]=0xdeadbeef;
}
int main(void) {
  UEFI_SMMU_SNAPSHOT pre,post;
  setup();
  words[0xc5000/4]=0x3fd9a71e;words[0xc5020/4]=0x87654321;
  words[0xc5024/4]=0xfedcba98;words[0xc5028/4]=0xa5a5a5a5;
  words[0xc502c/4]=0x5a5a5a5a;words[0xc5030/4]=0x11223344;
  words[0xc5058/4]=0x80000001;words[0x1114/4]=0xffffffff;
  words[0x1914/4]=0xabcdef01;
  words[(0x800+3*4)/4]=0x80021c00;words[(0xc00+3*4)/4]=3;
  words[(0x800+104*4)/4]=0x80010060;words[(0xc00+104*4)/4]=0x20045;
  UefiSmmuCapture(&pre,0x15000000,0x200000,0xfedcba9876543210ULL,123,read32,0);
  assert(pre.Status==UefiSmmuCaptured && pre.RouteCount==2);
  assert(pre.Base==0x15000000 && pre.ResourceBytes==0x200000 && pre.WindowBytes==0xd0000);
  assert(pre.PairId==0xfedcba9876543210ULL && pre.Counter==123);
  assert(pre.Cr0==0xdeadbeef && pre.Bank69[0]==0x3fd9a71e);
  assert(pre.Bank69[1]==0x87654321 && pre.Bank69[2]==0xfedcba98);
  assert(pre.Bank69[3]==0xa5a5a5a5 && pre.Bank69[4]==0x5a5a5a5a);
  assert(pre.Bank69[5]==0x11223344 && pre.Bank69[6]==0x80000001);
  assert(pre.Bank69[7]==0xffffffff && pre.Bank69[8]==0xabcdef01);
  assert(pre.Routes[1].Slot==104 && pre.Routes[1].Smr==0x80010060);
  assert(pre.Sid60Matches==1 && pre.Bank69References==1);
  assert(reads==3+1+9+105+2 && highest==0xc5058);
  // Simulate the existing cleanup's table/TCR changes; SCTLR survives.
  words[0xc5020/4]=words[0xc5024/4]=words[0xc5028/4]=0;
  words[0xc502c/4]=words[0xc5030/4]=0;
  words[(0x800+104*4)/4]&=0x7fffffff;
  UefiSmmuCapture(&post,0x15000000,0x200000,pre.PairId,456,read32,0);
  assert(post.PairId==pre.PairId && post.Counter==456);
  assert(post.Bank69[0]==pre.Bank69[0] && post.Bank69[1]==0);
  assert(pre.Bank69[1]==0x87654321); // Saved pre-state is independent.
  assert(post.RouteCount==1 && post.Routes[0].Slot==3);
  assert(post.Sid60Matches==0 && post.Bank69References==0);
  setup();
  for(unsigned i=0;i<105;i++) {
    words[(0x800+4*i)/4]=0xffff0000; // All SIDs match, full mask.
    words[(0xc00+4*i)/4]=0x20045; // Count references even in FAULT mode.
  }
  UefiSmmuCapture(&pre,0x15000000,0xd0000,1,2,read32,0);
  assert(pre.RouteCount==105 && pre.Sid60Matches==105 && pre.Bank69References==105);
  for(unsigned i=0;i<3;i++) {
    setup();words[(0x20+4*i)/4]^=1;
    UefiSmmuCapture(&pre,0x15000000,0x200000,1,2,read32,0);
    assert(pre.Status==UefiSmmuUnknownIds && reads==3 && id_reads==3);
    assert(pre.RouteCount==0 && pre.Bank69[0]==0);
  }
  const UINT64 bases[]={0,0x15000004,UINT64_MAX-3,0x15000000,0x15000000};
  const UINT64 lengths[]={0xd0000,0xd0000,0xd0000,0xc505b,UINT64_MAX};
  for(unsigned i=0;i<5;i++) {
    setup();
    UefiSmmuCapture(&pre,bases[i],lengths[i],1,2,read32,0);
    assert(pre.Status==UefiSmmuInvalidResource && reads==0);
  }
  assert(!UefiSmmuWordFits(0xd0000,0xcffff));
  assert(!UefiSmmuWordFits(0xd0000,0xd0000));
  assert(!UefiSmmuWordFits(3,0));
  assert(UefiSmmuWordFits(0xd0000,0xcfffc));
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'test.c').write_text(source)
            subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-I',str(HERE),
                            str(root/'test.c'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True)


if __name__ == '__main__':
    unittest.main()
