"""Derive the shared read-only transport from the immutable nuwa UFS input.

Only queue/transport/DMA handling is retained. No block publication, persistent
store, log, cache export, root authentication, legacy probe or SMMU setter.
"""
from pathlib import Path
import hashlib
import json
import re
import sys
HERE=Path(__file__).resolve().parent
def generate(source):
    def read(name,blob):
        data=(source/name).read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual!=blob:raise ValueError('Fixed upstream blob differs: '+name)
        return data.decode()
    main=read('NativeUfs.cpp','bdf3df5c457acd2c46de29e8bac3380366bf466e')
    commands=read('RootCommands.h','996304d7d22b74c0f2fcaad2d14676f480bc19c1')
    for name,blob in {'RootQueue.h':'989b956715100291de60c711d45d866904656a22','TransferPoll.h':'2f56e30a824eac1961076faee0907de54b8bac44','RootDiagnostics.h':'f8188dc225812b2a0c5a5e2f306344ab91b93144','RootTransportLayout.h':'a6245c6825ec3405e84afe2743d8b852d75fec82','GccUfs.h':'5d11663a81c7caca9cd27173805eadecde74fc1d','SmmuTakeover.h':'c30f5a91666369ea78e33d0dfa0959e72bc2d98d','LICENSE':'52a23a0ee6084ff047e0cef045efb8eb19518192'}.items():
        value=read(name,blob)
        if name=='SmmuTakeover.h':
            # Preserve the fixed input; mark only its optional fallback entry.
            # K70 deliberately calls the single-bank planner and rejects fallback.
            anchor='static UfsSmmuPlan planUfsSmmu('
            assert value.count(anchor)==1
            value=value.replace(anchor,'[[maybe_unused]] '+anchor,1)
            # Qualification reuses the upstream disable/write/readback step,
            # returning before any other context or route configuration.
            value=value.replace('Read read, Write write)\n{',
                'Read read, Write write, bool disableOnly=false)\n{',1)
            value=value.replace('  // Set VA64 before',
                '  if (disableOnly) return nullptr;\n  // Set VA64 before',1)
        (HERE/name).write_text(value)
    queue=(HERE/'RootQueue.h').read_text()
    queue=queue.replace('static bool hostStopQueue', '''static bool hostQueueIdleStopped(void) {
  return (read32(gHost.hc,0x34)&1) && (read32(gHost.hc,0x30)&15)==15 &&
         !read32(gHost.hc,0x58) && !read32(gHost.hc,0x78) &&
         !(read32(gHost.hc,0x60)&1) && !(read32(gHost.hc,0x80)&1) &&
         !(read32(gHost.hc,0x20)&kUfsFatalStatus);
}
static bool hostStopQueue''',1)
    queue=queue.replace('  hostWrite (0x24, 0);','''  if(read32(gHost.hc,0x80)&1) {
    *why="firmware task list still enabled";return false;
  }
  hostWrite (0x24, 0);''',1)
    queue=queue.replace('  hostWrite (0x50,', '''  uint64_t limit=(read32(gHost.hc,0)&0x01000000U)?(1ULL<<36):(1ULL<<32);
  if(!hostQueueIdleStopped() || !k70DmaAllocation(gHost.phys,kDmaBytes,limit)) {
    *why="queue/DMA changed before start";return false;
  }
  hostWrite (0x50,''',1)
    queue=queue.replace('    *why = "request list address";', '    gHost.poisoned=true;\n    *why = "request list address";')
    queue=queue.replace('    *why = "request list ready";', '    gHost.poisoned=true;\n    *why = "request list ready";')
    (HERE/'RootQueue.h').write_text(queue)
    commands=commands[:commands.index('// ---- Persistent store and log windows')]
    anchor='(dataBytes & 3) || (dataBytes ? !direction : direction)) return kIOReturnBadArgument;'
    assert commands.count(anchor)==1
    commands=commands.replace(anchor,anchor+'\n  if (!K70UfsPolicy::command(lun,cdb,cdbLength,direction,dataBytes)) return kIOReturnNotPermitted;')
    commands=commands.replace('  *ocs = 15;','  *ocs = 15;\n  if (direction == 1) return kIOReturnNotPermitted;',1)
    commands=commands.replace('  cacheCivac (gHost.virt, kDataOffset + dataBytes);','''  uint64_t limit=(read32(gHost.hc,0)&0x01000000U)?(1ULL<<36):(1ULL<<32);
  if(!k70DmaDescriptors(gHost.phys,limit,direction,dataBytes,words,
      reinterpret_cast<const uint32_t *>(gHost.virt+kUcdOffset+kPrdtOffset))) {
    gHost.poisoned=true;gHost.ready=false;return kIOReturnBadArgument;
  }
  cacheCivac (gHost.virt, kDataOffset + dataBytes);''',1)
    commands=commands.replace('Callers other than hostWrite4k never pass direction 1.',
        'Direction 1 is forbidden by the candidate policy and submit gate.')
    (HERE/'ReadOnlyCommands.inc').write_text(commands.rstrip()+'\n')
    mapping=main[main.index('static uintptr_t mapPhys'):main.index('void NativeUfs::inspect')]
    body=main[main.index('namespace {\n#include "RootTransportLayout.h"'):main.index('namespace {\nstatic uint32_t be32w')]
    body=body.replace('#include "RootCommands.h"','#include "ReadOnlyCommands.inc"')
    body=body.replace('#include "RootTransportLayout.h"','#include "RootTransportLayout.h"\n#include "K70Dma.h"',1)
    a=body.index('// Bring the live controller up')
    # Keep the reusable command/queue implementation, but this diagnostic
    # candidate only observes the existing SMMU map. No HC/GCC access, DMA
    # allocation, queue takeover, planning or configuration is executed.
    body=body[:a]+'''// Fixed, retained raw snapshot; formatting starts after all MMIO reads.
static K70SmmuEvidence gSmmuEvidence;
static bool hostBringUp (const char **why)
{
  gRootDiagnostic.stage = "K70 SMMU mapped read-only evidence";
  gHost.smmu=mapPhys(0x15000000ULL,0xd0000,gHost.smmuMap);
  if(!gHost.smmu){*why="K70 SMMU map";return false;}
  k70CollectSmmuEvidence(gSmmuEvidence,gHost.smmu,k70ReadTranslation,
      [](unsigned o){return read32(gHost.smmu,o);});
  auto trace=[](const char *s,uint64_t v){k70_formal_cpu_trace(s,v);};
  k70TraceSmmuEvidence(gSmmuEvidence,trace);
  // Unconditional stop: never derive a permissive ownership decision from
  // these words, and never enter hostStopQueue/configure/hostStartQueue.
  gRootDiagnostic.stage = "K70 SMMU evidence diagnostic stop";
  *why="K70 SMMU evidence diagnostic stop";
  return false;
}
}

'''
    body=body.replace('#include "RootQueue.h"','''[[maybe_unused]] static bool hostStopQueue(const char **);
[[maybe_unused]] static bool hostStartQueue(const char **);
#include "RootQueue.h"''',1)
    body=body.replace('#include "ReadOnlyCommands.inc"','''[[maybe_unused]] static IOReturn hostNop(void);
[[maybe_unused]] static IOReturn hostQueryRead(uint8_t,uint8_t,uint32_t *);
#include "ReadOnlyCommands.inc"''',1)
    prefix='''// SPDX-License-Identifier: BSD-2-Clause-Patent
// Derived from UniXNU/ShengUfs af785c1777161a62931425c2faaa536ce0bebd5b.
// Generated by generate.py; diagnostic entry stops after mapped SMMU evidence.
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <libkern/crypto/sha2.h>
extern "C" {
#include <kern/clock.h>
#include <vm/vm_kern.h>
}
#include "ReadOnlyPolicy.h"
#include "K70SmmuEvidence.h"
namespace {
#include "RootDiagnostics.h"
#include "TransferPoll.h"
static UfsRootDiagnostics gRootDiagnostic;
static bool gRootDiagnosticEnabled=true;
static uint32_t read32(uintptr_t b,unsigned o) {return *reinterpret_cast<volatile uint32_t *>(b+o);}
static void write32(uintptr_t b,unsigned o,uint32_t v) {*reinterpret_cast<volatile uint32_t *>(b+o)=v;}
'''+mapping+'}\n'
    tail='''namespace {
#include "Qualification.inc"
}
extern "C" void k70_ufs_readonly_qualify(void) {
 static bool entered=false;if(entered)return;entered=true;
 const char *why="capacity/GPT verification failed";
 boot_progress_stage("K70 formal UFS read-only transport enter");
 bool pass=hostBringUp(&why) && k70qualify();
 k70_formal_cpu_trace("UFS transport qualification",pass);
 if(pass)boot_progress_stage("UFS GPT passed; compare recorded SHA with local contract");
 else {
  boot_progress_stage(why);boot_progress_stage(gRootDiagnostic.stage);
  k70_formal_cpu_trace("UFS native result",gRootDiagnostic.result);
  k70_formal_cpu_trace("UFS command opcode",gRootDiagnostic.opcode);
  k70_formal_cpu_trace("UFS protocol reject",gRootDiagnostic.protocol);
  k70_formal_cpu_trace("UFS SCSI status",gRootDiagnostic.scsi);
  k70_formal_cpu_trace("UFS OCS",gRootDiagnostic.ocs);
  k70_formal_cpu_trace("UFS fault address",gRootDiagnostic.far);
 }
}
'''
    # This candidate compiles no UFS queue, command, DMA or route publisher.
    runtime='''// SPDX-License-Identifier: BSD-2-Clause-Patent
// Generated: one SCTLR disable qualification, never a UFS transport.
#include <IOKit/IODeviceMemory.h>
#include "K70SmmuEvidence.h"
#include "K70SctlrQualification.h"
namespace {
'''+mapping+'''
static OSSharedPtr<IOMemoryMap> smmuMap,hcMap;
static uintptr_t smmu,hc;
static bool mapFault=false,consumed=false;
static uint32_t checkedRead(uintptr_t base,uint64_t pa,uint64_t bytes,unsigned offset) {
  auto word=k70ReadMappedWord(base,pa,bytes,offset,k70ReadTranslation,
      [&](unsigned o){return *reinterpret_cast<volatile uint32_t *>(base+o);});
  if(word.failure!=K70MapFailure::None || word.attr!=0 ||
     word.shareability!=2 || word.nonSecure!=1)mapFault=true;
  return word.value;
}
static uint32_t smmuRead(unsigned o){return checkedRead(smmu,0x15000000,0xd0000,o);}
static bool queueIdle() {
  const unsigned offsets[]={0x34,0x30,0x58,0x78,0x60,0x80,0x20};
  uint32_t r[7];
  for(unsigned i=0;i<7;++i) {
    r[i]=checkedRead(hc,0x1d84000,0x3000,offsets[i]);
    k70_formal_cpu_trace("SCTLR HC offset/value",(uint64_t(offsets[i])<<32)|r[i]);
  }
  return !mapFault && (r[0]&1) && (r[1]&15)==15 && !r[2] && !r[3] &&
      !(r[4]&1) && !(r[5]&1) && !(r[6]&0x71880U);
}
static bool writePermission() {
  uint64_t par=k70ReadWriteTranslation(smmu+0xc5000);
  k70_formal_cpu_trace("SCTLR write PAR",par);
  return !(par&1) && (par&0x000ffffffffff000ULL)==0x150c5000 &&
      uint8_t(par>>56)==0 && ((par>>7)&3)==2 && ((par>>9)&1)==1;
}
}
extern "C" void k70_ufs_readonly_qualify(void) {
  static bool entered=false;if(entered)return;entered=true;
  boot_progress_stage("K70 SCTLR01 qualification only");
  smmu=mapPhys(0x15000000,0xd0000,smmuMap);
  hc=mapPhys(0x1d84000,0x3000,hcMap);
  if(!smmu || !hc){boot_progress_stage("SCTLR map refused");return;}
  auto trace=[](const char *s,uint64_t v){k70_formal_cpu_trace(s,v);};
  static K70SmmuPlan p;p=k70PlanUfsSmmu(0,4,smmuRead,trace,true);
  if(mapFault || p.error){boot_progress_stage(mapFault?"SCTLR read mapping refused":p.error);return;}
  const char *error=k70QualifySctlr(p,consumed,smmuRead,
      [&](unsigned o,uint32_t v) {
        // Only this store is compiled; barriers complete before upstream readback.
        *reinterpret_cast<volatile uint32_t *>(smmu+o)=v;
        __asm__ volatile("dsb sy" ::: "memory");
      },[](){return queueIdle() && writePermission();},trace);
  trace("SCTLR readback",smmuRead(0xc5000));
  trace("SCTLR map fault",mapFault);
  boot_progress_stage(error?error:mapFault?"SCTLR post-read mapping refused":"SCTLR qualification passed; STOP");
  // Always terminal for this diagnostic entry: no route, HC writes or DMA.
}
'''
    (HERE/'K70UfsTransport.inc').write_text(runtime)
    forbidden=('hostWrite4k','hostSyncCache','smmuBypassStream','native_ufs_store_',
               'native_ufs_log_','native_ufs_export_','verified_root','hostStoreOpen','hostLogOpen')
    compiled=runtime
    code=re.sub(r'/\*.*?\*/|//[^\n]*','',compiled,flags=re.S)
    if any(x in code for x in forbidden):raise ValueError('Forbidden implementation survived')
    return {'upstream':'af785c1777161a62931425c2faaa536ce0bebd5b','writes_compiled':True,
            'root_publication':False,'root_authentication_changed':False}
if __name__=='__main__':print(json.dumps(generate(Path(sys.argv[1])),indent=2))
