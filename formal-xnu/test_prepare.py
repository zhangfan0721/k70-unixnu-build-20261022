import importlib.util
import os
from pathlib import Path
import tempfile
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('formal_prepare', HERE/'prepare.py')


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepare = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(cls.prepare)

    def test_backend_reuses_upstream_renderer_with_write_translation_guard(self):
        text = self.prepare.observer_source()
        self.assertIn('k70_framebuffer_valid', text)
        self.assertIn('at s1e1w', text)
        self.assertNotIn('aperture + framebuffer', text)
        self.assertIn('K70 FORMAL XNU', text)
        self.assertNotIn('scheduler running', text)

    def test_late_patch_uses_existing_hooks_and_separate_backend(self):
        patch = self.prepare.kernel_patch('#define GLYPH_FONT {0}\n')
        self.assertIn('+++ b/pexpert/arm/k70_formal_diag.c', patch)
        self.assertIn('+#include "k70_formal_diag.c"', patch)
        self.assertIn('-#if defined(XNU_BOOT_PROGRESS) && XNU_BOOT_PROGRESS', patch)
        self.assertIn('--- a/osfmk/arm64/start.s', patch)

    def test_actual_observer_compiles_for_arm64_and_retains_prebind_history(self):
        uefi=Path(os.environ['K70_UEFI_SOURCE'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'kern').mkdir()
            (root/'kern/boot_progress.h').write_text('')
            (root/'FramebufferGuard.h').write_bytes((HERE/'FramebufferGuard.h').read_bytes())
            (root/'Font.h').write_bytes((uefi/'Silicon/Silicium/SiliciumPkg/Library/FrameBufferSerialPortLib/Font.h').read_bytes())
            source=self.prepare.observer_source()
            (root/'observer.c').write_text(source)
            subprocess.run(['clang','--target=aarch64-none-elf','-std=c11','-ffreestanding',
                '-fno-builtin','-Wall','-Wextra','-Werror','-I',str(root),'-c',str(root/'observer.c'),
                '-o',str(root/'observer.o')],check=True)
            (root/'host.c').write_text(source+'''
#include <assert.h>
int main(void) {
    boot_progress_init();
    boot_progress_stage("before VM");
    boot_progress_stage("after VM");
    boot_progress_irq(0,0,0);
    assert(g_state.stages == 2 && g_state.irqs == 1);
    assert(g_state.log_count == 2);
    assert(!boot_progress_active());
    boot_progress_bind(0,1440,3200,5760,32);
    assert(!boot_progress_active());
    assert(g_state.log_count == 2);
    k70_observer_busy=1;
    boot_progress_stage("reentrant update");
    assert(g_state.stages == 2);
    return 0;
}
''')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(root),
                str(root/'host.c'),'-o',str(root/'host')],check=True)
            subprocess.run([str(root/'host')],check=True)

    def test_firmware_contains_formal_modules_without_probe_application(self):
        uefi = Path(os.environ['K70_UEFI_SOURCE'])
        dtb = Path(os.environ['K70_DTB'])
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            root = Path(tmp)
            for item in ['Platforms/Xiaomi/vermeerPkg','Resources/Configs/vermeer.toml']:
                src,dst=uefi/item,root/item
                dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copytree(src,dst) if src.is_dir() else shutil.copy2(src,dst)
            self.prepare.firmware(root,dtb)
            package=root/'Platforms/Xiaomi/vermeerFormalPkg'
            dsc=(package/'vermeerFormal.dsc').read_text()
            fv='\n'.join(p.read_text() for p in package.rglob('*.inc'))
            fv+=(package/'vermeerFormal.fdf').read_text()
            for module in self.prepare.FORMAL_MODULES:
                self.assertIn(module,dsc)
                self.assertIn(module,fv)
            self.assertNotIn('VermeerProbe.inf',dsc+fv)
            self.assertNotIn('VermeerBootMemoryDxe.inf',dsc+fv)


if __name__ == '__main__':
    unittest.main()
