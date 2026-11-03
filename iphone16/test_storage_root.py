"""Exercise the real root-loader helper's API order and failure boundaries."""
from pathlib import Path
import argparse, subprocess, json

HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    header=HERE/'K70StorageRoot.h'
    assert header.exists(), 'RAM root still lacks the grouped normal OSKext loader'
    a.out.mkdir()
    source=a.out/'storage-contract.cpp'
    source.write_text(r'''
#include <cassert>
#include <cstdint>
#include <vector>
#include <string>
using OSReturn=int;constexpr int kOSReturnSuccess=0,kOSKextExcludeNone=0;
static std::vector<std::string> loads,classes;static std::vector<uint64_t> results;
static unsigned fail_load;static bool symbol_ok=true;static bool class_ok=true;
struct Halt{};
[[noreturn]] void panic(const char*,...){throw Halt{};}
extern "C" void boot_progress_stage(const char*){}
extern "C" void k70_formal_cpu_trace(const char*,uint64_t v){results.push_back(v);}
static unsigned symbol_creates,symbol_releases;
constexpr int OSNoRetain=1;
struct OSSymbol {const char*name;static const OSSymbol*withCStringNoCopy(const char*n){static OSSymbol s;s.name=n;if(!symbol_ok)return nullptr;symbol_creates++;return &s;}};
template<class T>struct OSSharedPtr{T*p;OSSharedPtr(T*v,int ownership):p(v){assert(ownership==OSNoRetain);}~OSSharedPtr(){if(p)symbol_releases++;}T*get()const{return p;}explicit operator bool()const{return p!=nullptr;}};
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
}
''')
    exe=a.out/'storage-contract'
    subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
    report={'actual_helper_exercised':True,'non_ram_root_unchanged':True,
            'normal_api_order_and_options_checked':True,'both_load_failure_boundaries_checked':True,
            'missing_classes_reported_without_fabrication':True,'raw_factory_ownership_balanced':True,
            'real_component_runtime_tested':False}
    (a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
