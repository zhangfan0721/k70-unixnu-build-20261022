"""Install the bounded, shared production UFS transport in normal BSD startup."""
from pathlib import Path
import shutil
HERE=Path(__file__).resolve().parent
def install(root):
    for path in HERE.iterdir():
        if path.suffix in ('.inc','.h') and not path.name.startswith('test_'):
            shutil.copy2(path,root/'iokit/bsddev'/path.name)
    p=root/'iokit/bsddev/IOKitBSDInit.cpp';s=p.read_text()
    anchor='#include <libkern/c++/OSAllocation.h>'
    assert s.count(anchor)==1
    s=s.replace(anchor,anchor+'\n#include "K70UfsTransport.inc"')
    anchor='\tk70_ramdisk_storage_prepare(IORamDiskBSDRoot());'
    assert s.count(anchor)==1
    # A declared window, when the boot arguments ask for one, keeps the request
    # list running and backs md0 on demand. Otherwise the one-shot qualification
    # runs exactly as before.
    s=s.replace(anchor,anchor+'\n\tk70_ufs_window_bootargs();\n\tif(!k70_ufs_window_prepare())k70_ufs_readonly_qualify();')
    p.write_text(s)
