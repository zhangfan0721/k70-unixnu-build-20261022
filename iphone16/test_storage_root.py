"""Exercise the real root-loader helper's API order and failure boundaries."""
from pathlib import Path
import argparse, subprocess, json, shutil, hashlib, struct

HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    a=p.parse_args()
    header=HERE/'K70StorageRoot.h'
    assert header.exists(), 'RAM root still lacks the grouped normal OSKext loader'
    a.out.mkdir()
    headers=a.out/'headers/libkern/c++';headers.mkdir(parents=True)
    real_headers={}
    for name in ('OSPtr.h','OSSharedPtr.h','intrusive_shared_ptr.h'):
        original=a.source/'libkern/libkern/c++'/name
        shutil.copy2(original,headers/name)
        real_headers[name]=hashlib.sha256(original.read_bytes()).hexdigest()
    # Only the object runtime is substituted. Ownership aliases, complete
    # shared-pointer definition and its implementation are the real XNU files.
    (headers/'OSMetaClass.h').write_text('''#pragma once
struct OSMetaClassBase {void retain()const;void release()const;void taggedRetain(const void*)const;void taggedRelease(const void*)const;};
#define OSTypeID(T) ((const void*)0)
#define OSTypeAlloc(T) ((T*)nullptr)
#define OSDynamicCast(T,p) static_cast<T*>(p)
''')
    source=a.out/'storage-contract.cpp'
    source.write_text(r'''
#include <cassert>
#include <cstdint>
#include <vector>
#include <string>
#include <libkern/c++/OSPtr.h>
#include <libkern/c++/OSMetaClass.h>
using OSReturn=int;constexpr int kOSReturnSuccess=0,kOSKextExcludeNone=0;
static std::vector<std::string> loads,classes;static std::vector<uint64_t> results;
static unsigned fail_load;static bool symbol_ok=true;static bool class_ok=true;
struct Halt{};
[[noreturn]] void panic(const char*,...){throw Halt{};}
extern "C" void boot_progress_stage(const char*){}
extern "C" void k70_formal_cpu_trace(const char*,uint64_t v){results.push_back(v);}
static unsigned symbol_creates,symbol_releases,symbol_retains;
void OSMetaClassBase::retain()const{symbol_retains++;}
void OSMetaClassBase::release()const{symbol_releases++;}
struct OSSymbol:OSMetaClassBase {const char*name;static OSPtr<const OSSymbol>withCStringNoCopy(const char*n){static OSSymbol s;s.name=n;if(!symbol_ok)return nullptr;symbol_creates++;return &s;}};
struct OSMetaClass {static const OSMetaClass*getMetaClassWithName(const OSSymbol*s){classes.push_back(s->name);static OSMetaClass real;return class_ok?&real:nullptr;}};
struct OSKext {static OSReturn loadKextWithIdentifier(const char*n,bool defer,bool delay,int start,int match){
 assert(!defer && !delay && start==0 && match==0);loads.push_back(n);return loads.size()==fail_load?123:0;}};
'''+f'#include "{header}"\n'+r'''
int main(){
 k70_ramdisk_storage_prepare(false);assert(loads.empty() && classes.empty());
 k70_ramdisk_storage_prepare(true);
 assert((loads==std::vector<std::string>{"com.apple.iokit.IOStorageFamily","com.apple.filesystems.hfs.kext"}));
 assert((classes==std::vector<std::string>{"IOStorage","IOBlockStorageDevice","IOBlockStorageDriver","IOMedia","com_apple_filesystems_hfs"}));
 for(unsigned fail=1;fail<=2;fail++){
  loads.clear();classes.clear();fail_load=fail;bool halted=false;
  try{k70_ramdisk_storage_prepare(true);}catch(Halt&){halted=true;}
  assert(halted && loads.size()==fail);
 }
 loads.clear();classes.clear();results.clear();fail_load=0;class_ok=false;
 k70_ramdisk_storage_prepare(true);assert(classes.size()==5);
 assert(results.back()==0); /* Record failed class lookup; original root assertions remain. */
 loads.clear();classes.clear();results.clear();symbol_ok=false;
 k70_ramdisk_storage_prepare(true);assert(classes.empty() && results.back()==0);
 assert(symbol_creates==symbol_releases);
 assert(symbol_retains==0);
}
''')
    exe=a.out/'storage-contract'
    includes=['-I'+str(a.out/'headers')]
    subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',*includes,str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
    target=a.out/'actual-owner-ios16.cpp'
    target.write_text('''#include <stdint.h>
#include <libkern/c++/OSPtr.h>
#include <libkern/c++/OSMetaClass.h>
using OSReturn=int;constexpr int kOSReturnSuccess=0,kOSKextExcludeNone=0;
extern "C" void boot_progress_stage(const char*);
[[noreturn]] void panic(const char*,...);
struct OSSymbol:OSMetaClassBase{static OSPtr<const OSSymbol>withCStringNoCopy(const char*);};
struct OSMetaClass{static const OSMetaClass*getMetaClassWithName(const OSSymbol*);};
struct OSKext{static OSReturn loadKextWithIdentifier(const char*,bool,bool,int,int);};
'''+f'#include "{header}"\n'+'''void exercise_storage_owner(bool root){k70_ramdisk_storage_prepare(root);}
''')
    obj=a.out/'actual-owner-ios16.o'
    subprocess.run(['clang++','--target=arm64-apple-ios16.0','-mkernel','-std=c++17','-ffreestanding',
                    '-fno-builtin','-ftrivial-auto-var-init=zero','-Wall','-Wextra','-Werror',*includes,
                    '-c',str(target),'-o',str(obj)],check=True)
    assert struct.unpack_from('<4I',obj.read_bytes())==(0xfeedfacf,0x100000c,0,1)
    report={'actual_helper_exercised':True,'non_ram_root_unchanged':True,
            'normal_api_order_and_options_checked':True,'both_load_failure_boundaries_checked':True,
            'missing_classes_reported_without_fabrication':True,'raw_factory_ownership_balanced':True,
            'real_xnu_owner_headers':real_headers,'arm64_ios16_owner_object_compiled':True,
            'object_runtime_substituted_full_kernel_headers_still_require_cloud':True,
            'real_component_runtime_tested':False}
    (a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
