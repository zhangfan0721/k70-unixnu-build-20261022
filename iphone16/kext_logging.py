"""Expose existing OSKext messages and pre-wrapper results; no loader policy edits."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent

def install(root):
    p = root / 'libkern/c++/OSKext.cpp'
    text = p.read_text()
    def edit(before, after):
        nonlocal text
        if text.count(before) != 1:
            raise ValueError('OSKext logging anchor changed: ' + before[:100])
        text = text.replace(before, after, 1)
    edit('#include <libkern/c++/OSLib.h>',
         '#include <libkern/c++/OSLib.h>\n#include "K70KextLog.h"')
    edit('\t\tif (!allocBuffer) {\n\t\t\tgoto finish;',
         '\t\tif (!allocBuffer) {\n\t\t\tif (logForKernel) k70_kext_visible(aKext, msgLogSpec, stackBuffer, true);\n\t\t\tgoto finish;')
    edit('\t/* If user space wants the log message, queue it up.',
         '\tif (logForKernel) k70_kext_visible(aKext, msgLogSpec, buffer, false);\n\n\t/* If user space wants the log message, queue it up.')
    edit('\tresult = validateKextMapping(/* start? */ true);',
         '\tresult = validateKextMapping(/* start? */ true);\n\tk70_kext_raw(this, "kext map raw", result);')
    edit('\tboot_progress_stage(result == KERN_SUCCESS ? "OSKext constructors OK" : "OSKext constructors FAILED");',
         '\tk70_kext_raw(this, "kext C++ raw", result);')
    edit('\t\tboot_progress_stage(result == KERN_SUCCESS ? "OSKext start OK" : "OSKext start FAILED");',
         '\t\tk70_kext_raw(this, "kext entry raw", result);')
    edit('\t\t\tresult = start();',
         '\t\t\tresult = start();\n\t\t\tk70_kext_raw(this, "kext start raw", result);')
    # Keep the original validation text and original VM query result together.
    before = '"Kext %s - bad %s pointer %p.",\n\t\t\t\t    getIdentifierCString(),\n\t\t\t\t    whichOp, (void *)ml_static_unslide(address));'
    edit(before, '"Kext %s - bad %s pointer %p (VM query 0x%x).",\n\t\t\t\t    getIdentifierCString(),\n\t\t\t\t    whichOp, (void *)ml_static_unslide(address), kern_result);')
    p.write_text(text)
    shutil.copy2(HERE / 'K70KextLog.h', p.parent / 'K70KextLog.h')
