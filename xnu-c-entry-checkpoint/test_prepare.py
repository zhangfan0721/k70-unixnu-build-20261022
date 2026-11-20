import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('stage08_c_entry_fixture',HERE.parent/'xnu-bootstrap-checkpoint/test_prepare.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)


class CEntryPackageTests(old.BootstrapPackageTests):
    def setUp(self):
        self.assertTrue((HERE/'prepare.py').exists(),'virtual C-entry package generator missing')
        super().setUp()

    def run_prepare(self):
        return subprocess.run([sys.executable,str(HERE/'prepare.py'),'--uefi',str(self.root),'--dtb',str(old.DTB),
            '--kernel',str(self.kernel),'--payload',str(self.root/'payload.bin'),'--blobs',str(self.root/'blobs')],capture_output=True,text=True)

    # Replace the stage08-specific contract; inherit its wrong-input/font tests.
    def test_package_preserves_stage07_and_binds_four_page_runtime(self):
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE.parent/'xnu-mmu-checkpoint').iterdir() if p.is_file()}
        r=self.run_prepare();self.assertEqual(r.returncode,0,r.stderr)
        report=json.loads(r.stdout);self.assertEqual(report['mode'],'original-c-entry-checkpoint')
        self.assertTrue(report['entry']['bootstrap_map_contained']);self.assertFalse(report['hardware_tested'])
        app=self.root/'Platforms/Xiaomi/vermeerProbePkg/Probe'
        entry=(app/'Entry.c').read_text();pre=(app/'Preflight.c').read_text()
        self.assertIn('Before[7]',entry);self.assertEqual(entry.count('I < 7;'),4)
        self.assertIn('K70CpuSupportsXnu(Mmfr0)',entry)
        self.assertIn('K70DataRange(Map, MapBytes, DescriptorBytes, Guard, Capacity + 16384)',entry)
        self.assertIn('K70GuardReady(&Regs, Guard)',entry)
        self.assertLess(entry.index('ZeroMem((VOID *)(UINTN)0x881608000'),entry.index('mEntryOriginalPatch'))
        self.assertIn('mOriginalHelperHash',entry);self.assertIn('mMmuCodeOriginals',entry)
        self.assertLess(entry.index('mOriginalArmInitHash'),entry.index('mMmuCodeOriginals + 4 * I'))
        self.assertIn('CompareMem(Digest, mEntryStubHash, 32)',entry)
        self.assertIn('K70EntryCheckpoint(ImageHandle, Destination, EFI_PAGES_TO_SIZE(Pages), Plan.Span, Prefix)',pre)
        self.assertLess(pre.index('gBS->AllocatePages(AllocateAddress, EfiLoaderData, 4, &Prefix)'),pre.index('gBS->AllocatePages(AllocateAddress, EfiLoaderData, Pages, &Destination)'))
        self.assertLess(pre.index('gBS->FreePages(Destination, Pages)'),pre.index('gBS->FreePages(Prefix, 4)'))
        self.assertIn('if (PrefixAllocated) gBS->FreePages(Prefix, 4)',pre)
        self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE.parent/'xnu-mmu-checkpoint').iterdir() if p.is_file()})
        libfile=self.root/'policy.so'
        subprocess.run(['cc','-DK70_HOST','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(app),
            str(app/'EntryCore.c'),str(app/'GuardCore.c'),'-o',str(libfile)],check=True,capture_output=True)
        lib=C.CDLL(str(libfile));f=lib.K70EntryScopes;f.argtypes=[C.c_uint64]*5+[C.POINTER(C.c_uint64)]
        pages=(C.c_uint64*7)()
        self.assertEqual(f(0x880004000,0x10000000,0x1544000,4096,600,pages),1)
        self.assertEqual(list(pages),report['entry']['code_pages'])
        self.assertEqual(f(0x880004000,0x10000000,0x1544000,4097,600,pages),0)
        self.assertEqual(report['display']['record_last_row'],1334)
        self.assertEqual(report['display']['record_words'],32)
        self.assertEqual(report['display']['context_start_row'],1440)


if __name__=='__main__':unittest.main()
