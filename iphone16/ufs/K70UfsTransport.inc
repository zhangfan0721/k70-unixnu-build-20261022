// SPDX-License-Identifier: BSD-2-Clause-Patent
// Generated: one SCTLR disable qualification, never a UFS transport.
#include <IOKit/IODeviceMemory.h>
#include "K70SmmuEvidence.h"
#include "K70SctlrQualification.h"
namespace {
static uintptr_t mapPhys (uint64_t phys, uint64_t length, OSSharedPtr<IOMemoryMap> &keep)
{
  IODeviceMemory *memory = IODeviceMemory::withRange (phys, length);
  if (!memory) {
    return 0;
  }
  keep = OSSharedPtr<IOMemoryMap> (memory->map (kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
  memory->release ();
  return keep ? static_cast<uintptr_t> (keep->getVirtualAddress ()) : 0;
}


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
