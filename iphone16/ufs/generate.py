"""Derive the shared read-only transport from the immutable nuwa UFS input.

Only queue/transport/DMA handling is retained. No block publication, persistent
store, log, cache export, root authentication change or legacy probe.
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
        if name=='TransferPoll.h':
            value=value.replace('Completed, Fatal, Timeout','Completed, Fatal, Timeout, ClockFailure, Budget')
            value=value.replace('if (port.expired()) return UfsTransferEnd::Timeout;',
                'if (port.expired()) return port.clockFailed()?UfsTransferEnd::ClockFailure:UfsTransferEnd::Timeout;')
            value=value.replace('    port.delay();',
                '    if (!port.delay()) return UfsTransferEnd::ClockFailure;\n    if (state.polls>=0x1000000U) return UfsTransferEnd::Budget;')
        (HERE/name).write_text(value)
    queue=(HERE/'RootQueue.h').read_text()
    queue=queue.replace('static bool hostStopQueue', '''static bool hostQueueIdleStopped(void) {
  return (read32(gHost.hc,0x34)&1) && (read32(gHost.hc,0x30)&15)==15 &&
         !read32(gHost.hc,0x58) && !read32(gHost.hc,0x78) &&
         !(read32(gHost.hc,0x60)&1) && !(read32(gHost.hc,0x80)&1) &&
         !(read32(gHost.hc,0x20)&kUfsFatalStatus) && hostControlHealthy();
}
static bool hostStopQueue''',1)
    queue=queue.replace('  hostWrite (0x24, 0);','''  if(!hostControlHealthy() || (read32(gHost.hc,0x80)&1)) {
    *why="task list enabled or MMIO unhealthy";return false;
  }
  hostWrite (0x24, 0);
  if(!hostControlHealthy() || read32(gHost.hc,0x24)!=0) {
    *why="interrupt mask readback";return false;
  }''',1)
    queue=queue.replace('  if (!hostWaitRegister (0x60, 1, 0))',
        '  if (!hostControlHealthy() || !hostWaitRegister (0x60, 1, 0))',1)
    anchor='  return true;\n}\n\nstatic bool hostStartQueue'
    queue=queue.replace(anchor,'''  if(!hostQueueIdleStopped()){*why="post-stop queue changed";return false;}
  return true;
}

static bool hostStartQueue''',1)
    queue=queue.replace('  hostWrite (0x50,', '''  uint64_t limit=(read32(gHost.hc,0)&0x01000000U)?(1ULL<<36):(1ULL<<32);
  if(!hostQueueIdleStopped() || !k70DmaAllocation(gHost.phys,kDmaBytes,limit)) {
    *why="queue/DMA changed before start";return false;
  }
  hostWrite (0x50,''',1)
    queue=queue.replace('  hostWrite (0x54,', '''  if(!hostControlHealthy()){*why="UTRL low address write";return false;}
  hostWrite (0x54,''',1)
    queue=queue.replace('  if (read32 (gHost.hc, 0x50)', '  if (!hostControlHealthy() || read32 (gHost.hc, 0x50)',1)
    queue=queue.replace('hostWrite (0x20, gRootDiagnostic.isBefore);','hostWrite (0x20, 1);')
    queue=queue.replace('  hostWrite (0x60, 1);','''  if(!hostControlHealthy()){*why="status acknowledgement";return false;}
  hostWrite (0x60, 1);''',1)
    queue=queue.replace('  if (!hostWaitRegister (0x60, 1, 1)', '  if (!hostControlHealthy() || !hostWaitRegister (0x60, 1, 1)',1)
    queue=queue.replace('    *why = "request list address";', '    gHost.poisoned=true;\n    *why = "request list address";')
    queue=queue.replace('    *why = "request list ready";', '    gHost.poisoned=true;\n    *why = "request list ready";')
    # Retain original predicates/masks; only add first-mismatch evidence.
    queue=queue.replace('(read32(gHost.hc,0x34)&1)', 'hostState(0x34,1,1)')
    queue=queue.replace('(read32(gHost.hc,0x30)&15)==15', 'hostState(0x30,15,15)')
    queue=queue.replace('!read32(gHost.hc,0x58)', 'hostState(0x58,0)')
    queue=queue.replace('!read32(gHost.hc,0x78)', 'hostState(0x78,0)')
    queue=queue.replace('!(read32(gHost.hc,0x60)&1)', 'hostState(0x60,0,1)')
    queue=queue.replace('!(read32(gHost.hc,0x80)&1)', 'hostState(0x80,0,1)')
    queue=queue.replace('!(read32(gHost.hc,0x20)&kUfsFatalStatus)', 'hostState(0x20,0,kUfsFatalStatus)')
    queue=queue.replace('!(read32 (gHost.hc, 0x34) & 1)', '!hostState(0x34,1,1)')
    queue=queue.replace('(read32 (gHost.hc, 0x30) & 0x0f) != 0x0f', '!hostState(0x30,15,15)')
    queue=queue.replace('read32 (gHost.hc, 0x58) || read32 (gHost.hc, 0x78)', '!hostState(0x58,0) || !hostState(0x78,0)')
    queue=queue.replace('read32 (gHost.hc, 0x20) & kUfsFatalStatus', '!hostState(0x20,0,kUfsFatalStatus)')
    queue=queue.replace('(read32(gHost.hc,0x80)&1)', '!hostState(0x80,0,1)')
    queue=queue.replace('read32(gHost.hc,0x24)!=0', '!hostState(0x24,0)')
    queue=queue.replace('read32 (gHost.hc, 0x50) != uint32_t (gHost.phys)', '!hostState(0x50,uint32_t(gHost.phys))')
    queue=queue.replace('read32 (gHost.hc, 0x54) != uint32_t (gHost.phys >> 32)', '!hostState(0x54,uint32_t(gHost.phys>>32))')
    queue=queue.replace('  do {','  uint32_t actual=0;\n  do {',1)
    queue=queue.replace('if ((read32 (gHost.hc, offset) & mask) == value)','if (((actual=read32(gHost.hc,offset)) & mask) == value)',1)
    queue=queue.replace('  return false;\n}','  hostStateValue(offset,value,actual,mask);\n  return false;\n}',1)
    queue=queue.replace('    IODelay (10);','    if(!hostWaitPause(10))return false;')
    queue=queue.replace('  uint32_t actual=0;', '  uint64_t last=mach_absolute_time();\n  uint32_t actual=0,iterations=0;')
    queue=queue.replace('  } while (mach_absolute_time () < deadline);', '''    uint64_t current=mach_absolute_time();
    if(current<last) {gK70Wait={last,deadline,current,iterations,K70WaitCode::Regressed};return false;}
    last=current;
    if(++iterations==0x1000000U) {gK70Wait={last,deadline,current,iterations,K70WaitCode::Budget};return false;}
  } while (last < deadline);''')
    (HERE/'RootQueue.h').write_text(queue)
    commands=commands[:commands.index('// ---- Persistent store and log windows')]
    anchor='(dataBytes & 3) || (dataBytes ? !direction : direction)) return kIOReturnBadArgument;'
    assert commands.count(anchor)==1
    commands=commands.replace(anchor,anchor+'\n  if (!gWake.permit(lun,cdb,cdbLength,direction,dataBytes)) return kIOReturnNotPermitted;')
    commands=commands.replace('  *ocs = 15;','  *ocs = 15;\n  if (direction == 1) return kIOReturnNotPermitted;',1)
    commands=commands.replace('  cacheCivac (gHost.virt, kDataOffset + dataBytes);','''  uint64_t limit=(read32(gHost.hc,0)&0x01000000U)?(1ULL<<36):(1ULL<<32);
  if(!k70DmaDescriptors(gHost.phys,limit,direction,dataBytes,words,
      reinterpret_cast<const uint32_t *>(gHost.virt+kUcdOffset+kPrdtOffset))) {
    gHost.poisoned=true;gHost.ready=false;return kIOReturnBadArgument;
  }
  cacheCivac (gHost.virt, kDataOffset + dataBytes);''',1)
    commands=commands.replace('Callers other than hostWrite4k never pass direction 1.',
        'Direction 1 is forbidden by the candidate policy and submit gate.')
    commands=commands.replace('  if (gHost.poisoned) return kIOReturnNotReady;',
        '''  if (gHost.poisoned) return kIOReturnNotReady;
  if(!hostTransportOwned()){
    gHost.poisoned=true;gHost.ready=false;
    return recordTransport(kIOReturnNotReady,*ocs);
  }''',1)
    commands=commands.replace('  if (gHost.poisoned) return false;',
        '''  if (gHost.poisoned) return false;
  if(!hostTransportOwned()){
    gHost.poisoned=true;gHost.ready=false;
    recordTransport(kIOReturnNotReady,15);return false;
  }''',1)
    commands=commands.replace('  hostWrite (0x20, 1);','''  if(!hostTransportOwned()){
    gHost.poisoned=true;gHost.ready=false;return recordTransport(kIOReturnNotReady,*ocs);
  }
  hostWrite (0x20, 1);''',1)
    commands=commands.replace('  cacheInvalidate (gHost.virt, kDataOffset + dataBytes);', '  if(!hostContextHealthy()){\n    gHost.poisoned=true;gHost.ready=false;return recordTransport(kIOReturnIOError,*ocs);\n  }\n  cacheInvalidate (gHost.virt, kDataOffset + dataBytes);',1)
    commands=commands.replace('  UfsTransferPoll state;','''  if(!hostControlHealthy()){
    gHost.poisoned=true;gHost.ready=false;return recordTransport(kIOReturnNotReady,*ocs);
  }
  UfsTransferPoll state;''',1)
    commands=commands.replace('  if (!value || (opcode != 3 && opcode != 5)) return kIOReturnBadArgument;',
        '''  if (!value || (opcode != 3 && opcode != 5)) return kIOReturnBadArgument;
  if(opcode!=3 || idn!=2)return kIOReturnNotPermitted;''',1)
    commands=commands.replace('  uint64_t deadline;',
        '  uint64_t deadline,started=0,last=0;\n  bool regressed=false;',1)
    commands=commands.replace('  bool expired () { return mach_absolute_time () >= deadline; }',
        '  bool expired () { uint64_t current=mach_absolute_time();regressed=current<last;last=current;if(regressed)gK70Wait={started,deadline,current,0,K70WaitCode::Regressed};return regressed || last>=deadline; }\n  bool clockFailed () { return regressed; }')
    commands=commands.replace('  void delay () { IODelay (2); }',
        '  bool delay () { return hostWaitPause(2); }')
    commands=commands.replace('  HardwareTransferPort port;',
        '''  boot_progress_stage(gRootDiagnostic.stage);
  k70_formal_cpu_trace("UFS CMD/op",(uint64_t(gRootDiagnostic.command)<<32)|gRootDiagnostic.opcode);
  k70_formal_cpu_trace("UFS type/LUN",(uint64_t(gRootDiagnostic.type)<<32)|gRootDiagnostic.lun);
  if(gRootDiagnostic.type==1) {
    uint64_t cdb=0;for(unsigned n=0;n<6;++n)cdb=(cdb<<8)|gHost.virt[kUcdOffset+16+n];
    k70_formal_cpu_trace("UFS CDB first6",cdb);
  }
  k70_formal_cpu_trace("UFS timeout us",timeoutUs);
  HardwareTransferPort port;
  port.started=port.last=mach_absolute_time();''',1)
    commands=commands.replace('  *ocs = state.ocs;',
        '''  *ocs = state.ocs;
  k70_formal_cpu_trace("UFS xfer end/count",(uint64_t(end)<<32)|state.polls);
  k70_formal_cpu_trace("UFS xfer OCS/DB",(uint64_t(state.ocs)<<32)|state.doorbellSeen);
  k70_formal_cpu_trace("UFS CMD start",port.started);
  k70_formal_cpu_trace("UFS CMD deadline",port.deadline);
  k70_formal_cpu_trace("UFS CMD last",mach_absolute_time());
  if(end==UfsTransferEnd::ClockFailure)hostWaitTrace("UFS clock failure");''',1)
    (HERE/'ReadOnlyCommands.inc').write_text(commands.rstrip()+'\n')
    mapping=main[main.index('static uintptr_t mapPhys'):main.index('void NativeUfs::inspect')]
    body=main[main.index('namespace {\n#include "RootTransportLayout.h"'):main.index('// Bring the live controller up')]
    body=body.replace('#include "RootCommands.h"','#include "ReadOnlyCommands.inc"')
    body=body.replace('#include "RootTransportLayout.h"','#include "RootTransportLayout.h"\n#include "K70Dma.h"',1)
    anchor='static IOReturn recordTransport'
    body=body.replace(anchor,'#include "K70HostIO.h"\n\n'+anchor,1)
    body+='\n#include "K70Takeover.inc"\n#include "Qualification.inc"\n#include "K70UfsWindow.inc"\n}\n'
    prefix='''// SPDX-License-Identifier: BSD-2-Clause-Patent
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
'''+mapping+'}\n'
    tail='''extern "C" void k70_ufs_readonly_qualify(void) {
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
'''
    window='''
// Reports the command line the kernel actually received, then parks the CPU when
// it mentions k70halt. This deliberately avoids the boot-argument parser so a
// transport problem cannot masquerade as a missing argument.
extern "C" void k70_ufs_window_bootargs(void)
{
  const char *line = PE_boot_args();
  boot_progress_stage(line && *line ? line : "(no boot arguments)");
  static const char needle[] = "k70halt";
  bool halt = false;
  if (line) {
    for (const char *p = line; *p && !halt; ++p) {
      unsigned i = 0;
      while (needle[i] && p[i] == needle[i]) {
        ++i;
      }
      halt = needle[i] == 0;
    }
  }
  if (halt) {
    for (;;) {
      __asm__ volatile ("wfi");
    }
  }
}

// Freezes the machine on request so a hardware run reports its own outcome on a
// screen that cannot scroll away. The reason becomes the last progress stage.
static bool k70WindowHaltReport(const char *why, bool ok)
{
  char halt[8];
  if (PE_parse_boot_argn("k70halt", halt, sizeof(halt)) && halt[0] == '1') {
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
  if (!PE_parse_boot_argn("k70rd", argument, sizeof(argument))) {
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
    return k70WindowHaltReport("K70 UFS window: open refused", false);
  }
  k70_formal_cpu_trace("UFS window base lba", lba);
  k70_formal_cpu_trace("UFS window blocks", blocks);
  boot_progress_stage("K70 UFS window open");
  return k70WindowHaltReport("K70 UFS window: open; halted", true);
}
'''
    runtime=prefix+body+tail+window
    (HERE/'K70UfsTransport.inc').write_text(runtime)
    forbidden=('hostWrite4k','hostSyncCache','smmuBypassStream','native_ufs_store_',
               'native_ufs_log_','native_ufs_export_','verified_root','hostStoreOpen','hostLogOpen')
    compiled=runtime
    code=re.sub(r'/\*.*?\*/|//[^\n]*','',compiled,flags=re.S)
    if any(x in code for x in forbidden):raise ValueError('Forbidden implementation survived')
    return {'upstream':'af785c1777161a62931425c2faaa536ce0bebd5b','writes_compiled':True,
            'root_publication':False,'root_authentication_changed':False}
if __name__=='__main__':print(json.dumps(generate(Path(sys.argv[1])),indent=2))
