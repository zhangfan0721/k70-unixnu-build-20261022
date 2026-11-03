"""Exercise the actual fixed OSKextVLog body, including its original formatter."""
from pathlib import Path
import argparse,subprocess,json,re,shutil,hashlib,struct

HERE=Path(__file__).resolve().parent

def function(text,name):
    start=text.index('\n'+name+'(\n')+1
    brace=text.index('{',start);depth=1;end=brace+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True);p.add_argument('--patched',type=Path)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir()
    source=a.patched or a.source
    text=(source/'libkern/c++/OSKext.cpp').read_text()
    body=function(text,'OSKextVLog')
    # Preserve the source predicate rather than restating its filtering logic.
    start=text.index('inline bool\nlogSpecMatch(');end=text.index('\nextern "C" {',start)
    predicate=text[start:end]
    private=(a.source/'libkern/libkern/OSKextLibPrivate.h').read_text()
    constants=[]
    for name,value in re.findall(r'^#define\s+(kOSKextLog\w+)\s+\(\(OSKextLogSpec\)\s*(0x[0-9a-fA-F]+)\)',private,re.M):
        constants.append('[[maybe_unused]] constexpr OSKextLogSpec '+name+'='+value+';')
    headers=a.out/'headers/libkern/c++';headers.mkdir(parents=True)
    hashes={}
    for name in ('OSSharedPtr.h','intrusive_shared_ptr.h'):
        src=a.source/'libkern/libkern/c++'/name;shutil.copy2(src,headers/name)
        hashes[name]=hashlib.sha256(src.read_bytes()).hexdigest()
    (headers/'OSMetaClass.h').write_text('''#pragma once
struct OSMetaClassBase {void retain()const{} void release()const{} void taggedRetain(const void*)const{} void taggedRelease(const void*)const{} };
#define OSTypeID(T) ((const void*)0)
#define OSTypeAlloc(T) ((T*)nullptr)
#define OSDynamicCast(T,p) static_cast<T*>(p)
''')
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <libkern/c++/OSSharedPtr.h>
using OSKextLogSpec=uint32_t;using OSReturn=int;
'''+ '\n'.join(constants)+r'''
struct OSKext {struct {bool loggingEnabled=false;}flags;const char*id;const char*getIdentifierCString(){return id;}};
static std::vector<std::string> visible,console;static std::vector<uint64_t> raw_values;
static bool active=true,allocation_fails=false;static unsigned allocs,frees,lock_depth;
extern "C" int boot_progress_active(){return active;}
extern "C" void boot_progress_stage(const char*s){visible.emplace_back(s);}
extern "C" void k70_formal_cpu_trace(const char*,uint64_t v){raw_values.push_back(v);}
void IOLockLock(void*){assert(lock_depth==0);lock_depth++;}
void IOLockUnlock(void*){assert(lock_depth==1);lock_depth--;}
constexpr int Z_WAITOK=1,VM_KERN_MEMORY_OSKEXT=0;
void*kalloc_data_tag(unsigned n,int,int){allocs++;return allocation_fails?nullptr:malloc(n);}
void kfree_data(void*p,unsigned){if(p)frees++;free(p);}
struct OSNumber:OSMetaClassBase{static OSSharedPtr<OSNumber>withNumber(uint64_t,unsigned){static OSNumber n;return OSSharedPtr<OSNumber>(&n,OSNoRetain);}};
struct OSString:OSMetaClassBase{static OSSharedPtr<OSString>withCString(const char*){static OSString s;return OSSharedPtr<OSString>(&s,OSNoRetain);}};
struct Array{void setObject(const OSMetaClassBase*){}};
static Array*sUserSpaceLogSpecArray=nullptr,*sUserSpaceLogMessageArray=nullptr;
static void*sKextLoggingLock=nullptr;
static OSKextLogSpec sKernelLogFilter=kOSKextLogDetailLevel|kOSKextLogKextOrGlobalMask|kOSKextLogGeneralFlag|kOSKextLogLoadFlag|kOSKextLogValidationFlag|kOSKextLogDependenciesFlag|kOSKextLogLinkFlag;
static OSKextLogSpec sUserSpaceKextLogFilter=0;
static bool sBootArgLogFilterFound=false;int disableConsoleOutput=1;
const char*colorForFlags(OSKextLogSpec){return "";}
#define VTRESET ""
int test_printf(const char*fmt,...){char text[4096];va_list args;va_start(args,fmt);int n=vsnprintf(text,sizeof(text),fmt,args);va_end(args);console.emplace_back(text);return n;}
'''
    helper=HERE/'K70KextLog.h'
    include=f'#include "{helper}"\n' if helper.exists() else ''
    suffix=r'''
void emit(OSKext*k,OSKextLogSpec s,const char*fmt,...){va_list a;va_start(a,fmt);OSKextVLog(k,s,fmt,a);va_end(a);}
std::string shown(){std::string s;for(const auto&l:visible)s+=l;return s;}
int main(){
 OSKext storage{{false},"com.apple.iokit.IOStorageFamily"};
 OSKext hfs{{false},"com.apple.filesystems.hfs.kext"},dep{{false},"com.apple.kpi.iokit"},other{{false},"com.example.unrelated"};
 emit(&storage,kOSKextLogErrorLevel|kOSKextLogLoadFlag,"start failed raw=0x%x",0xdc008007u);
 assert(shown().find("dc008007")!=std::string::npos && shown().find(storage.id)!=std::string::npos);
 visible.clear();console.clear();allocs=frees=0;
 std::string longline="mapping: "+std::string(220,'a')+" ORIGINAL_RAW_TAIL=0xdc008007";
 emit(&storage,kOSKextLogErrorLevel|kOSKextLogValidationFlag,"%s",longline.c_str());
 assert(shown().find("ORIGINAL_RAW_TAIL=0xdc008007")!=std::string::npos);
 assert(console.back()==longline+"\n" && allocs==1 && frees==1);
 for(const auto&l:visible)assert(l.size()<=48);
 visible.clear();emit(&dep,kOSKextLogDetailLevel|kOSKextLogDependenciesFlag,"dependency identity and return");assert(!visible.empty());
 visible.clear();emit(&hfs,kOSKextLogStepLevel|kOSKextLogLoadFlag,"original HFS loader text");assert(!visible.empty());
 visible.clear();emit(&other,kOSKextLogErrorLevel|kOSKextLogLoadFlag,"unrelated");assert(visible.empty());
 visible.clear();emit(nullptr,kOSKextLogErrorLevel|kOSKextLogGeneralFlag,"global C++ runtime failure");assert(!visible.empty());
 visible.clear();emit(nullptr,kOSKextLogDetailLevel|kOSKextLogGeneralFlag,"global detail noise");assert(visible.empty());
 visible.clear();active=false;emit(&storage,kOSKextLogErrorLevel|kOSKextLogLoadFlag,"inactive");assert(visible.empty());active=true;
 visible.clear();allocation_fails=true;emit(&storage,kOSKextLogErrorLevel|kOSKextLogLoadFlag,"%s",longline.c_str());allocation_fails=false;
 assert(shown().find("prefix")!=std::string::npos && shown().find("mapping:")!=std::string::npos);
 visible.clear();std::string huge(1000,'x');emit(&storage,kOSKextLogErrorLevel|kOSKextLogLoadFlag,"%s",huge.c_str());
 assert(visible.size()<=18 && shown().find("capped")!=std::string::npos && console.back()==huge+"\n");
 visible.clear();std::string multiline;for(unsigned i=0;i<100;i++)multiline+="x\n";
 emit(&storage,kOSKextLogErrorLevel|kOSKextLogLoadFlag,"%s",multiline.c_str());
 assert(visible.size()<=18 && shown().find("capped")!=std::string::npos && console.back()==multiline+"\n");
 visible.clear();k70_kext_raw(&storage,"kext map raw",(int)0xdc008007u);
 assert(raw_values.back()==0xdc008007u && shown().find(storage.id)!=std::string::npos);
 assert(lock_depth==0);
}
'''
    fixture=a.out/'actual-vlog.cpp'
    fixture.write_text(prefix+include+predicate+'\n#define printf test_printf\nvoid\n'+body+'\n#undef printf\n'+suffix)
    binary=a.out/'actual-vlog'
    subprocess.run(['clang++','-std=c++17','-O1','-Wall','-Wextra','-Werror','-I'+str(a.out/'headers'),str(fixture),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    # Compile the display adapter for the real deployment format too. Full
    # OSKext headers/runtime remain the responsibility of the native CI build.
    target=a.out/'display-ios16.cpp';obj=target.with_suffix('.o')
    target.write_text('#include <stdint.h>\nextern "C" int strcmp(const char*,const char*);\n'
        'extern "C" int strncmp(const char*,const char*,unsigned long);\n'
        'using OSKextLogSpec=uint32_t;using OSReturn=int;\n'+ '\n'.join(constants)+
        '\nstruct OSKext {const char*getIdentifierCString();};\n'+include+
        '\nextern "C" void display_adapter(OSKext*k,char*b,OSReturn r){'
        'k70_kext_visible(k,kOSKextLogErrorLevel,b,false);k70_kext_raw(k,"kext map raw",r);}\n')
    subprocess.run(['clang++','--target=arm64-apple-ios16.0','-std=c++17','-ffreestanding',
        '-fno-builtin','-fno-exceptions','-fno-rtti','-mgeneral-regs-only','-O1',
        '-Wall','-Wextra','-Werror','-c',str(target),'-o',str(obj)],check=True)
    data=obj.read_bytes();assert struct.unpack_from('<4I',data)==(0xfeedfacf,0x100000c,0,1)
    offset=32;deployment=False
    for _ in range(struct.unpack_from('<I',data,16)[0]):
        cmd,size=struct.unpack_from('<II',data,offset)
        if cmd==0x32:deployment=struct.unpack_from('<II',data,offset+8)==(2,0x100000)
        offset+=size
    assert deployment
    undefined=subprocess.check_output(['llvm-nm','--undefined-only',str(obj)],text=True)
    assert not re.search(r'alloc|free|Lock|printf|timer',undefined)
    (a.out/'display-ios16-undefined.txt').write_text(undefined)
    report={'actual_fixed_vlog_and_filter_exercised':True,'raw_code_and_component_visible':True,
            'long_message_tail_visible_with_48_column_wrapping':True,'original_printf_text_restored':True,
            'allocation_failure_prefix_retained':True,'bounded_output_and_identity_filter_checked':True,
            'arm64_ios16_adapter_object_checked':True,'adapter_no_allocator_lock_formatter_timer_imports':True,
            'real_owner_header_sha256':hashes,'kernel_object_runtime_substituted':True,'hardware_tested':False}
    (a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
