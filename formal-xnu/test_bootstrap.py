"""Exercise the actual early-map routine; no device operations."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class BootstrapTests(unittest.TestCase):
    def test_entry_patch_uses_interior_anchor_independent_of_eof_newlines(self):
        diff=(HERE/'EntryDiagnostics.patch').read_text()
        tail=diff[diff.rfind('@@ '):]
        snippet='\t/* Return to arm_init() */\n\tret\n\n//#include\t"globals_asm.h"\n\n/* vim: set ts=4: */'
        for suffix in ('\n','\n\n','\n\n\n'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); target=root/'osfmk/arm64/start.s'
                target.parent.mkdir(parents=True);target.write_text(snippet+suffix)
                patch='--- a/osfmk/arm64/start.s\n+++ b/osfmk/arm64/start.s\n'+tail
                subprocess.run(['git','apply','--unsafe-paths','-'],input=patch,text=True,cwd=root,check=True)
                self.assertLess(target.read_text().index('K70_ENTRY_HELPERS'),target.read_text().index('//#include'))

    def test_real_entry_macros_assemble_as_apple_arm64(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'entry.S'
            source.write_text('''
#define EXT(x) _##x
#define LEXT(x) _##x:
#include "EntryDiagnostics.s"
.text
.globl _entry_test
_entry_test:
    K70_PREPARE_DISPLAY
    K70_MARK x20, 0x00ff00ff, 0
    K70_MARK x20, 0x00ffffff, 1
    K70_MARK x20, 0x00ffff00, 2
    ret
K70_ENTRY_HELPERS
''')
            subprocess.run(['clang','--target=arm64-apple-darwin','-x','assembler-with-cpp',
                '-I',str(HERE),'-c',str(source),'-o',str(Path(tmp)/'entry.o')],check=True)

    def test_maps_only_reserved_display_without_overwriting_existing_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'map.c'
            source.write_text(r'''
#include <assert.h>
#include <string.h>
#include "BootstrapMap.h"
static uint64_t pages[3][512] __attribute__((aligned(4096)));
int main(void) {
    uint64_t lo=(uintptr_t)pages, hi=lo+sizeof(pages);
    assert(k70_bootstrap_fb_map(pages[0], pages[1],lo,hi));
    assert(pages[0][2] == ((uintptr_t)pages[1] | 3));
    for (unsigned i=0;i<512;i++) {
        uint64_t expected=(i>=448 && i<457) ?
            (UINT64_C(0xb8000000)+(i-448)*0x200000)|K70_FB_BLOCK_FLAGS : 0;
        assert(pages[1][i]==expected);
    }
    /* A repeat preserves already-identical descriptors and unrelated entries. */
    pages[1][3]=0x123;
    assert(k70_bootstrap_fb_map(pages[0], pages[2],lo,hi));
    assert(pages[1][3]==0x123 && pages[2][0]==0);
    /* Conflict detected before any entry is changed. */
    memset(pages,0,sizeof(pages));
    pages[0][2]=(uintptr_t)pages[1]|3;
    pages[1][456]=0xdead0001;
    assert(!k70_bootstrap_fb_map(pages[0],pages[2],lo,hi));
    assert(pages[1][448]==0 && pages[1][456]==0xdead0001);
    /* Invalid/block roots, foreign table pointers and out-of-window spare fail. */
    pages[0][2]=1;
    assert(!k70_bootstrap_fb_map(pages[0],pages[2],lo,hi));
    pages[0][2]=0x12345003;
    assert(!k70_bootstrap_fb_map(pages[0],pages[2],lo,hi));
    pages[0][2]=0;
    assert(!k70_bootstrap_fb_map(pages[0],pages[2],lo,hi-1));
    assert(pages[0][2]==0);
    /* The owned kernel window must never overlap the framebuffer carveout. */
    assert(!k70_bootstrap_fb_map(pages[0],pages[2],0xb8000000,0xd8000000));
    return 0;
}
''')
            binary=Path(tmp)/'map'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HERE),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)


if __name__ == '__main__':
    unittest.main()
