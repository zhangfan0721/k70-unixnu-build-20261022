/* SPDX-License-Identifier: MIT
 * Normal BSD bootstrap context, never the emergency panic capture path.
 * The includer supplies the actual XNU OSKext/OSSymbol/OSMetaClass headers.
 */
#ifndef K70_STORAGE_ROOT_H
#define K70_STORAGE_ROOT_H
extern "C" bool IORamDiskBSDRoot(void);
extern "C" void k70_formal_cpu_trace(const char *,uint64_t);

static void k70_storage_load(const char *identifier)
{
 boot_progress_stage(identifier);
 OSReturn result=OSKext::loadKextWithIdentifier(identifier,false,false,
     kOSKextExcludeNone,kOSKextExcludeNone);
 k70_formal_cpu_trace("RAM root component load result",(uint32_t)result);
 if(result!=kOSReturnSuccess)panic("RAM root component %s failed: 0x%x",identifier,result);
}

static void k70_storage_probe_class(const char *name)
{
 auto key=OSSymbol::withCStringNoCopy(name);
 const OSMetaClass *registered=key?OSMetaClass::getMetaClassWithName(key.get()):nullptr;
 boot_progress_stage(name);
 k70_formal_cpu_trace("RAM root real class registered",registered!=nullptr);
}

static void k70_ramdisk_storage_prepare(bool ramdisk_root)
{
 if(!ramdisk_root)return;
 boot_progress_stage("RAM root normal storage initialization");
 k70_storage_load("com.apple.iokit.IOStorageFamily");
 k70_storage_probe_class("IOStorage");
 k70_storage_probe_class("IOBlockStorageDevice");
 k70_storage_probe_class("IOBlockStorageDriver");
 k70_storage_probe_class("IOMedia");
 k70_storage_load("com.apple.filesystems.hfs.kext");
 k70_storage_probe_class("com_apple_filesystems_hfs");
}
#endif
