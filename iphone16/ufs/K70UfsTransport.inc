// SPDX-License-Identifier: BSD-2-Clause-Patent
// Derived from UniXNU/ShengUfs af785c1777161a62931425c2faaa536ce0bebd5b.
// Integrated one-shot UFS takeover and bounded read qualification.
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <libkern/crypto/sha2.h>
extern "C" {
#include <kern/clock.h>
#include <vm/vm_kern.h>
#include <sys/errno.h>
#include <sys/types.h>
#include <pexpert/pexpert.h>
}
#include "ReadOnlyPolicy.h"
#include "GccUfs.h"
#include "K70SmmuEvidence.h"
#include "K70Smmu.h"
#include "WindowPlan.h"
// Declared at global scope: an extern "C" declaration inside the unnamed
// namespace below would take internal linkage and stop matching memdev's
// definition.
extern "C" dev_t mdevadd_fetch (int devid, unsigned int size,
    int (*fetch) (int, uint64_t, void *, size_t));
namespace {
#include "RootDiagnostics.h"
#include "TransferPoll.h"
static UfsRootDiagnostics gRootDiagnostic;
static bool gRootDiagnosticEnabled=true;
static uint32_t read32(uintptr_t,unsigned);
static void write32(uintptr_t,unsigned,uint32_t);
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

}
namespace {
#include "RootTransportLayout.h"
#include "K70Dma.h"

struct UfsHost {
  OSSharedPtr<IOMemoryMap> hcMap, smmuMap;
  uintptr_t hc;
  IOBufferMemoryDescriptor *dma;
  uint8_t *virt;
  uint64_t phys;
  IOLock *lock;
  bool ready;
  bool poisoned = false;
  uintptr_t smmu = 0, cb = 0;
};
UfsHost gHost = { OSSharedPtr<IOMemoryMap> (), OSSharedPtr<IOMemoryMap> (), 0, nullptr, nullptr, 0, nullptr, false };

#include "K70HostIO.h"

static IOReturn recordTransport (IOReturn result, uint32_t ocs)
{
  gRootDiagnostic.result = static_cast<uint32_t> (result);
  gRootDiagnostic.ocs = ocs;
  if (result != kIOReturnSuccess && gRootDiagnosticEnabled) {
    // Read only the already mapped HC's status/registers used by this driver.
    gRootDiagnostic.hcs = read32 (gHost.hc, 0x30);
    gRootDiagnostic.hce = read32 (gHost.hc, 0x34);
    gRootDiagnostic.doorbell = read32 (gHost.hc, 0x58);
    gRootDiagnostic.interrupt = read32 (gHost.hc, 0x20);
    gRootDiagnostic.list = uint64_t (read32 (gHost.hc, 0x50)) |
                          (uint64_t (read32 (gHost.hc, 0x54)) << 32);
    gRootDiagnostic.runStop = read32 (gHost.hc, 0x60);
    gRootDiagnostic.ahit = read32 (gHost.hc, 0x18);
    for (unsigned i = 0; i < 5; ++i) gRootDiagnostic.uic[i] = read32 (gHost.hc, 0x38 + 4 * i);
    if (gHost.smmu && gHost.cb) {
      gRootDiagnostic.gfsr = read32 (gHost.smmu, 0x48);
      gRootDiagnostic.gsyn = read32 (gHost.smmu, 0x54);
      gRootDiagnostic.fsr = read32 (gHost.cb, 0x58);
      gRootDiagnostic.fsyn = read32 (gHost.cb, 0x68);
      gRootDiagnostic.far = uint64_t (read32 (gHost.cb, 0x60)) |
                            (uint64_t (read32 (gHost.cb, 0x64)) << 32);
    }
  }
  return result;
}

static void cacheCivac (const void *start, size_t length)
{
  uintptr_t address = reinterpret_cast<uintptr_t> (start) & ~uintptr_t (63);
  uintptr_t end = reinterpret_cast<uintptr_t> (start) + length;
  for (; address < end; address += 64) {
    __asm__ volatile ("dc civac, %0" :: "r" (address) : "memory");
  }
  __asm__ volatile ("dsb sy" ::: "memory");
}

// Device-owned cache lines must not be written back over DMA results. All
// callers use complete 64-byte lines from the dedicated page-aligned buffer.
static void cacheInvalidate (const void *start, size_t length)
{
  __asm__ volatile ("dsb sy" ::: "memory");
  uintptr_t address = reinterpret_cast<uintptr_t> (start);
  for (uintptr_t end = address + length; address < end; address += 64) {
    __asm__ volatile ("dc ivac, %0" :: "r" (address) : "memory");
  }
  __asm__ volatile ("dsb sy" ::: "memory");
}

static void hostWrite (unsigned offset, uint32_t value)
{
  __asm__ volatile ("dsb sy" ::: "memory");
  write32 (gHost.hc, offset, value);
  __asm__ volatile ("dsb sy" ::: "memory");
}

#include "RootQueue.h"

#include "ReadOnlyCommands.inc"


#include "K70Takeover.inc"
#include "Qualification.inc"
#include "K70UfsWindow.inc"
}
extern "C" void k70_ufs_readonly_qualify(void) {
  static bool entered=false;if(entered)return;entered=true;
  static UfsRootDiagnostics first;
  const char *why="capacity/GPT qualification failed";
  boot_progress_stage("K70 UFS-TAKEOVER05");
  bool pass=hostBringUp(&why) && k70qualify();
  if(!hostControlHealthy()){pass=false;why=gAccessFailure?gAccessFailure:"MMIO access failure";}
  const char *firstReason=pass?nullptr:why;
  if(!pass) {
    if(gHost.hc && hostControlHealthy())
      recordTransport(gRootDiagnostic.result?gRootDiagnostic.result:kIOReturnError,gRootDiagnostic.ocs);
    first=gRootDiagnostic;
  }
  K70StateFailure firstState=gStateFailure;
  K70WaitRecord firstWait=gK70Wait;
  gHost.ready=false;gHost.poisoned=true;
  gRootDiagnostic.stage="final own list stop";
  boot_progress_stage("UFS final stop enter");
  const char *endReason="own list stop failed";
  bool stopped=hostEnd(&endReason);
  if(pass && (!stopped || !hostControlHealthy() || !configuredIdentity() ||
      (read32(gHost.hc,0x20)&kUfsFatalStatus))) {
    pass=false;firstReason=endReason;first=gRootDiagnostic;firstState=gStateFailure;firstWait=gK70Wait;
  }
  k70_formal_cpu_trace("UFS final list stopped",stopped);
  k70_formal_cpu_trace("UFS takeover qualified",pass);
  k70_formal_cpu_trace("UFS terminal FSR raw",gRootDiagnostic.fsr);
  if(firstReason) {
    boot_progress_stage("UFS FIRST FAILURE");
    boot_progress_stage(firstReason);boot_progress_stage(first.stage);
    hostWaitTrace("UFS first wait",firstWait);
    k70ReportStateFailure(firstState,[](const char *s,uint64_t v){k70_formal_cpu_trace(s,v);});
    k70_formal_cpu_trace("UFS first result",first.result);
    k70_formal_cpu_trace("UFS first command/opcode",(uint64_t(first.command)<<32)|first.opcode);
    k70_formal_cpu_trace("UFS first type/LUN",(uint64_t(first.type)<<32)|first.lun);
    k70_formal_cpu_trace("UFS first OCS/response",(uint64_t(first.ocs)<<32)|first.response);
    k70_formal_cpu_trace("UFS first SCSI/sense",(uint64_t(first.scsi)<<32)|first.sense);
    k70_formal_cpu_trace("UFS first protocol/residual",(uint64_t(first.protocol)<<32)|first.residual);
    k70_formal_cpu_trace("UFS first IS/HCS",(uint64_t(first.interrupt)<<32)|first.hcs);
    k70_formal_cpu_trace("UFS first DB/RSR",(uint64_t(first.doorbell)<<32)|first.runStop);
    k70_formal_cpu_trace("UFS first DMA",first.dma);
    k70_formal_cpu_trace("UFS first list",first.list);
    k70_formal_cpu_trace("UFS first global/CB fault",(uint64_t(first.gfsr)<<32)|first.fsr);
    k70_formal_cpu_trace("UFS first fault address",first.far);
    for(unsigned i=0;i<5;++i)
      k70_formal_cpu_trace("UFS first UIC index/value",(uint64_t(i)<<32)|first.uic[i]);
  }
  if(!stopped){boot_progress_stage(endReason);hostWaitTrace("UFS stop wait");}
  k70_formal_cpu_trace("UFS map/write fault",(uint64_t(gMapFault)<<32)|gWriteFault);
  boot_progress_stage(pass?"UFS READ QUALIFIED; STOP":"UFS TAKEOVER STOP; no retry");
  // DMA/list/route remain retained until reboot. No rollback or publication.
}

// Reports the command line the kernel actually received. Reading it back on the
// screen is what separated a parser problem from a handoff problem once.
extern "C" void k70_ufs_window_bootargs(void)
{
  const char *line = PE_boot_args();
  boot_progress_stage(line && *line ? line : "(no boot arguments)");
}

// Freezes the machine on request so a hardware run reports its own outcome on a
// screen that cannot scroll away. The reason becomes the last progress stage.
static bool k70WindowHaltReport(const char *why, bool ok)
{
  char halt[8];
  if (PE_parse_boot_arg_str("k70halt", halt, sizeof(halt)) && halt[0] == '1') {
    boot_progress_stage(why);
    for (;;) {
      __asm__ volatile ("wfi");
    }
  }
  return ok;
}

extern "C" bool k70_ufs_window_prepare(void)
{
  char argument[64];
  unsigned long long lba = 0;
  unsigned blocks = 0;
  if (!PE_parse_boot_arg_str("k70rd", argument, sizeof(argument))) {
    return k70WindowHaltReport("K70 UFS window: no k70rd argument", false);
  }
  if (!K70Window::parseArgument(argument, &lba, &blocks)) {
    return k70WindowHaltReport("K70 UFS window: argument refused", false);
  }
  const char *why = "window bring-up refused";
  boot_progress_stage("K70 UFS window bring-up");
  if (!hostBringUp(&why)) {
    return k70WindowHaltReport(why, false);
  }
  if (!k70WindowOpen(lba, blocks, 0)) {
    return k70WindowHaltReport(k70WindowRefusalReason(), false);
  }
  k70_formal_cpu_trace("UFS window base lba", lba);
  k70_formal_cpu_trace("UFS window blocks", blocks);
  boot_progress_stage("K70 UFS window open");
  return k70WindowHaltReport("K70 UFS window: open; halted", true);
}
