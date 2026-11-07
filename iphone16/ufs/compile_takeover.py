"""Compile the actual integrated body for iOS16, without executing hardware.

Only external SDK declarations are supplied here. Production code and local
headers are compiled verbatim; full real IOKit compilation remains the CI gate.
"""
from pathlib import Path
import argparse,json,re,subprocess
HERE=Path(__file__).resolve().parent
DECLARATIONS=r'''
#include <stdint.h>
#include <stddef.h>
extern "C" {
void *memcpy(void *,const void *,size_t); int memcmp(const void *,const void *,size_t);
void bzero(void *,size_t); int snprintf(char *,size_t,const char *,...);
void boot_progress_stage(const char *); void k70_formal_cpu_trace(const char *,uint64_t);
void IODelay(uint32_t); uint64_t mach_absolute_time();
void clock_interval_to_deadline(uint32_t,unsigned,uint64_t *);
int PE_parse_boot_argn(const char *,void *,int);
char *PE_boot_args(void);
int PE_parse_boot_arg_str(const char *,char *,int);
}
constexpr int EIO=5,EINVAL=22;
using IOReturn=uint32_t;using IOByteCount=uint64_t;using IOOptionBits=uint64_t;using dev_t=int32_t;
constexpr IOReturn kIOReturnSuccess=0,kIOReturnError=1,kIOReturnBadArgument=2,
 kIOReturnIOError=3,kIOReturnBusy=4,kIOReturnTimeout=5,kIOReturnNotReady=6,kIOReturnNotPermitted=7;
constexpr unsigned kIOMapAnywhere=1,kIOMapInhibitCache=2,OSNoRetain=0,
 kIODirectionIn=1,kIODirectionInOut=3,kIOMemoryPhysicallyContiguous=4,kIOMemoryMapperNone=8,
 kMicrosecondScale=1,kMillisecondScale=1000;
extern void *kernel_task;
struct IOMemoryMap {uintptr_t getVirtualAddress();};
template<class T> struct OSSharedPtr {
 T *p=nullptr;OSSharedPtr()=default;OSSharedPtr(T *v,int):p(v){}
 operator bool()const{return p!=nullptr;} T *operator->()const{return p;}
};
struct IODeviceMemory {
 static IODeviceMemory *withRange(uint64_t,uint64_t);
 IOMemoryMap *map(unsigned);void release();
};
struct IOBufferMemoryDescriptor {
 static IOBufferMemoryDescriptor *inTaskWithOptions(void *,IOOptionBits,size_t,size_t);
 static IOBufferMemoryDescriptor *withCapacity(size_t,IOOptionBits);
 void *getBytesNoCopy();uint64_t getPhysicalSegment(uint64_t,IOByteCount *,unsigned);
};
struct IOLock {}; IOLock *IOLockAlloc();void IOLockLock(IOLock *);void IOLockUnlock(IOLock *);
struct SHA256_CTX {uint64_t opaque[32];};
void SHA256_Init(SHA256_CTX *);void SHA256_Update(SHA256_CTX *,const void *,size_t);
void SHA256_Final(uint8_t *,SHA256_CTX *);
'''
def compile_body(cxx,out):
    out.mkdir(parents=True,exist_ok=True)
    runtime=(HERE/'K70UfsTransport.inc').read_text()
    # Remove only SDK include directives; all actual functions remain intact.
    runtime=re.sub(r'^#include <[^>]+>\n','',runtime,flags=re.M)
    fixture=out/'actual-takeover-ios16.cpp';fixture.write_text(DECLARATIONS+runtime)
    command=[cxx,'--target=arm64-apple-ios16.0','-std=c++17','-ffreestanding',
      '-fno-exceptions','-fno-rtti','-O2','-Wall','-Wextra','-Wunused-template','-Werror',
      '-I',str(HERE),'-MJ',str(out/'takeover.compile.json'),'-c',str(fixture),
      '-o',str(out/'actual-takeover-ios16.o')]
    subprocess.run(command,check=True)
    return command
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cxx',required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    print(json.dumps(compile_body(a.cxx,a.out)))
