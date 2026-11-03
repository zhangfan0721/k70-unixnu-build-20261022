"""Initialize the matched RAM-root dependencies through the normal XNU loader."""
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent

def replace(text,before,after):
    if text.count(before)!=1:raise ValueError('Storage source anchor changed: '+before[:80])
    return text.replace(before,after,1)

def install(root):
    shutil.copy2(HERE/'K70StorageRoot.h',root/'iokit/bsddev/K70StorageRoot.h')
    p=root/'iokit/bsddev/IOKitBSDInit.cpp';text=p.read_text()
    text=replace(text,'#include <IOKit/IOBSD.h>',
        '#include <IOKit/IOBSD.h>\n#include <libkern/c++/OSKext.h>\n#include <libkern/c++/OSSymbol.h>\n#include "K70StorageRoot.h"')
    text=replace(text,'\tboot_progress_stage("IOFindBSDRoot enter; IOBSD wait next");',
        '\tk70_ramdisk_storage_prepare(IORamDiskBSDRoot());\n\tboot_progress_stage("IOFindBSDRoot enter; IOBSD wait next");')
    before='\t\t\t\t(void)mdevadd(-1, ml_static_ptovirt(ramdParms[0]) >> 12, (unsigned int) (ramdParms[1] >> 12), 0);'
    text=replace(text,before,
        '\t\t\t\tdev_t ram_device=mdevadd(-1, ml_static_ptovirt(ramdParms[0]) >> 12, (unsigned int) (ramdParms[1] >> 12), 0);\n'
        '\t\t\t\tk70_formal_cpu_trace("RAMDisk mdevadd returned device",(uint64_t)ram_device);')
    text=replace(text,'\tIOService::setRootMedia(service);',
        '\tif (IORamDiskBSDRoot()) k70_formal_cpu_trace("selected root device",(uint64_t)*root);\n\tIOService::setRootMedia(service);\n\tif (IORamDiskBSDRoot()) boot_progress_stage("root media configured");')
    p.write_text(text)
    p=root/'bsd/vfs/kpi_vfs.c';text=p.read_text()
    text='#include <kern/boot_progress.h>\n'+text
    text=replace(text,'\t\t(*newvfstbl->vfc_vfsops->vfs_init)(&vfsc);',
        '\t\tif (!strncmp(vfsc.vfc_name,"hfs",4)) boot_progress_stage("HFS vfs_init enter");\n'
        '\t\t(*newvfstbl->vfc_vfsops->vfs_init)(&vfsc);\n'
        '\t\tif (!strncmp(vfsc.vfc_name,"hfs",4)) boot_progress_stage("HFS vfs_init returned");')
    p.write_text(text)
    p=root/'bsd/vfs/vfs_subr.c';text=p.read_text()
    text='#include <kern/boot_progress.h>\nextern void k70_formal_cpu_trace(const char *, uint64_t);\n'+text
    text=replace(text,'\t\tmp->mnt_devvp = rootvp;\n\n\t\tif (vfsp->vfc_mountroot)',
        '\t\tmp->mnt_devvp = rootvp;\n\t\tboot_progress_stage("root filesystem mount attempt");\n\t\tboot_progress_stage(vfsp->vfc_name);\n\n\t\tif (vfsp->vfc_mountroot)')
    text=replace(text,'\t\t\terror = VFS_MOUNT(mp, rootvp, 0, ctx);\n\t\t}\n\n\t\tif (!error)',
        '\t\t\terror = VFS_MOUNT(mp, rootvp, 0, ctx);\n\t\t}\n\t\tk70_formal_cpu_trace("root filesystem mount result",(uint32_t)error);\n\n\t\tif (!error)')
    p.write_text(text)
