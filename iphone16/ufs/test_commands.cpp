// SPDX-License-Identifier: BSD-2-Clause-Patent
// Real production commands with a deterministic DMA/HC fault fixture.
#include "test_bridge.inc"
#include <array>
#include <algorithm>
#include <string>
enum class Fault { None, Empty, Type, Tag, Lun, Query, Residual, Underflow,
  Oversize, SenseLength, CheckCondition, Timeout, Fatal, Stop, Start, HighBase,
  Frozen, Regressed, BusyTimeout, Deferred, QueueRegressed };
static Fault fault;
static std::array<uint8_t,kDmaBytes> device;
static std::array<uint32_t,64> registers;
static uint64_t now;
static unsigned writes, releases, sleepingDelays;
static bool released;
static uint32_t completionFsr=0;
static unsigned clockReads;

static uint64_t io(unsigned op,uint64_t address,uint64_t value,void *bytes)
{
  if (op==0) {
    if(address==0x58 && fault==Fault::Deferred && now>=20) {
      registers[0x58/4]=0;*reinterpret_cast<uint32_t *>(device.data()+8)=0;
      auto cmd=device.data()+kUcdOffset;auto rsp=cmd+kRspOffset;
      memcpy(rsp,cmd,32);rsp[0]=cmd[0]+0x20;rsp[1]=0;
    }
    return registers.at(address/4);
  }
  if (op==1) {
    ++writes;
    if (address==0x20) registers[address/4]&=~uint32_t(value);
    else if (!(address==0x60 && (((fault==Fault::Stop || fault==Fault::QueueRegressed) && !value) || (fault==Fault::Start && value))) &&
             !(address==0x54 && fault==Fault::HighBase)) registers.at(address/4)=uint32_t(value);
    if (address==0x58) {
      gRootDiagnostic.fsr=completionFsr;
      assert(released); released=false;
      if (fault==Fault::Fatal) { registers[0x20/4]=0x20000; return 0; }
      if (fault==Fault::BusyTimeout || fault==Fault::Deferred) return 0;
      registers[0x58/4]=0;
      if (fault==Fault::Timeout || fault==Fault::Frozen || fault==Fault::Regressed) return 0;
      uint8_t *cmd=device.data()+kUcdOffset, *rsp=cmd+kRspOffset;
      std::fill(rsp,rsp+512,0);
      memset(device.data()+kDataOffset,0x7b,kDataMax);
      *reinterpret_cast<uint32_t *>(device.data()+8)=0;
      if (fault==Fault::Empty) return 0;
      memcpy(rsp,cmd,32); rsp[0]=cmd[0]+0x20; rsp[1]=0;
      if (cmd[0]==1) putBe32(rsp+12,0);
      if (cmd[0]==0x16) putBe32(rsp+20,0x11);
      if (fault==Fault::Type) rsp[0]=0x3f;
      if (fault==Fault::Tag) ++rsp[3];
      if (fault==Fault::Lun) ++rsp[2];
      if (fault==Fault::Query) ++rsp[13];
      if (fault==Fault::Residual) putBe32(rsp+12,4096);
      if (fault==Fault::Underflow) rsp[1]=0x20;
      if (fault==Fault::Oversize) rsp[10]=0xff;
      if (fault==Fault::SenseLength) { rsp[11]=2; rsp[33]=18; }
      if (fault==Fault::CheckCondition) {
        rsp[7]=2; rsp[11]=20; rsp[33]=18; rsp[34]=0x70;
        rsp[36]=6; rsp[46]=0x29; rsp[47]=0;
      }
    }
  }
  if (op==2 || op==3) {
    assert(address>=gHost.phys && address-gHost.phys+value<=device.size());
    auto at=device.data()+(address-gHost.phys);
    if (op==2) { ++releases; memcpy(at,bytes,value); released=true; }
    else memcpy(bytes,at,value);
  }
  if (op==4) {
    ++clockReads;
    if(fault==Fault::Frozen)return now;
    if(fault==Fault::Regressed && clockReads==8)now=0;
    if(fault==Fault::QueueRegressed && clockReads==14)now=0;
    return now++;
  }
  if (op==5) { ++sleepingDelays; now+=value; }
  return 0;
}
static void reset(Fault f=Fault::None)
{
  completionFsr=0;fault=f; device.fill(0); registers.fill(0); now=0; writes=releases=sleepingDelays=0; released=false;
  clockReads=0;
  registers[0x34/4]=1; registers[0x30/4]=15; registers[0x60/4]=1;
  registers[0]=0x01000000;
  ufs_test_reset(io,0x8cb5e9000);
}
static void assertQuarantined()
{
  assert(ufs_test_poisoned());
  std::array<uint8_t,kDmaBytes> old; memcpy(old.data(),memory,sizeof(memory));
  unsigned oldWrites=writes, oldReleases=releases;
  uint8_t cdb[6]={}; uint32_t scsi=0, value=0xabcdef;
  assert(ufs_test_nop()!=0);
  assert(ufs_test_query(3,2,&value)!=0 && value==0xabcdef);
  assert(ufs_test_scsi(0,cdb,6,false,0,&scsi)!=0);
  assert(writes==oldWrites && releases==oldReleases);
  assert(!memcmp(old.data(),memory,sizeof(memory)));
}
int main()
{
  // The real submit timeout must not rely on a scheduler-capable IODelay to
  // return before it can examine its deadline again.
  reset(Fault::Timeout);assert(ufs_test_nop()==kIOReturnTimeout);
  assert(sleepingDelays==0);
  reset(Fault::Deferred);assert(ufs_test_nop()==0 && now>=20 && sleepingDelays==0);
  for(Fault f:{Fault::Frozen,Fault::Regressed}) {
    reset(f);assert(ufs_test_nop()==kIOReturnIOError);
    assert(sleepingDelays==0 && clockReads<5000);assertQuarantined();
  }
  reset();assert(hostWaitPause(50000) && now>=50000 && sleepingDelays==0);
  reset(Fault::Frozen);assert(!hostWaitPause(50000));
  assert(gK70Wait.code==K70WaitCode::Frozen && clockReads<5000);
  reset(Fault::Regressed);assert(!hostWaitPause(50000));
  assert(gK70Wait.code==K70WaitCode::Regressed);
  reset();assert(ufs_test_stop_queue() && ufs_test_start_queue());
  gOwnStarted=true;fault=Fault::QueueRegressed;clockReads=0;now=0;
  assert(!ufs_test_end_queue());
  assert(gK70Wait.code==K70WaitCode::Regressed && clockReads<30);
  // The SAME terminal function as production: normal completion, timeout
  // with DB clear, timeout with DB still owned, bad clocks, failed list stop.
  for(Fault f:{Fault::None,Fault::Deferred,Fault::Timeout,Fault::BusyTimeout,Fault::Frozen,Fault::Stop}) {
    reset();assert(ufs_test_stop_queue() && ufs_test_start_queue());
    gOwnStarted=true;gPhase=K70HostPhase::Transport;
    uint8_t activeCmd[6]={0x1b,0,0,0,0x10,0};uint32_t scsi=0;
    assert(gWake.observe(0x33));fault=f;
    IOReturn result=hostScsi(0xd0,activeCmd,6,false,0,500000,&scsi);
    if(f==Fault::None || f==Fault::Deferred || f==Fault::Stop) {
      assert(result==0 && scsi==0);
      assert(!memcmp(device.data()+kUcdOffset+16,activeCmd,6));
      assert(device[kUcdOffset]==1 && device[kUcdOffset+2]==0xd0);
      assert(device[kUcdOffset+1]==0 && device[kUcdOffset+3]==0);
      assert((*reinterpret_cast<uint32_t *>(device.data())&0x06000000U)==0);
      assert((*reinterpret_cast<uint32_t *>(device.data()+28)&0xffff)==0);
      assert(hostWaitPause(50000));
      uint8_t tur[6]={};assert(hostScsi(0,tur,6,false,0,200000,&scsi)==0);
    } else assert(result!=0 && gHost.poisoned);
    if(f==Fault::Timeout || f==Fault::BusyTimeout)assert(now>=500000);
    uint8_t saved[kDmaBytes];memcpy(saved,memory,sizeof(saved));
    gHost.ready=false;gHost.poisoned=true;
    bool stopped=ufs_test_end_queue();
    assert(gCleanupAttempted && sleepingDelays==0);
    assert(stopped==(f!=Fault::Stop && f!=Fault::BusyTimeout));
    assert(!memcmp(saved,memory,sizeof(saved))); // Retained; no reuse/free/write.
    unsigned endWrites=writes;
    assert(!ufs_test_end_queue() && writes==endWrites); // No second stop attempt.
    assertQuarantined();
  }
  for(uint32_t format: {0U,0x200U,0x400U,0x600U}) {
    reset();completionFsr=format;assert(ufs_test_nop()==0);
    assert(gRootDiagnostic.fsr==format && !ufs_test_poisoned());
    for(unsigned bit=0;bit<32;++bit)if(bit!=9 && bit!=10) {
      reset();completionFsr=format|(1U<<bit);
      assert(ufs_test_nop()==kIOReturnIOError);
      assert(gRootDiagnostic.fsr==completionFsr);assertQuarantined();
    }
  }
  reset(); assert(ufs_test_nop()==0);
  reset();transportOwned=false;
  assert(ufs_test_nop()!=0 && writes==0 && releases==0);assertQuarantined();
  reset();uint8_t active[6]={0x1b,0,0,0,0x10,0};uint32_t wakeScsi=0;
  assert(ufs_test_scsi(0xd0,active,6,false,0,&wakeScsi)!=0 && writes==0);
  assert(gWake.observe(0x22));
  assert(ufs_test_scsi(0xd0,active,6,false,0,&wakeScsi)==0);
  auto wakeWrites=writes;
  assert(ufs_test_scsi(0xd0,active,6,false,0,&wakeScsi)!=0 && writes==wakeWrites);
  reset();assert(ufs_test_nop()==0);
  uint32_t value=0; assert(ufs_test_query(3,2,&value)==0 && value==0x11);
  std::array<uint8_t,16384> out;
  assert(ufs_test_read(0,2,4,out.data())==0);
  assert(std::all_of(out.begin(),out.end(),[](uint8_t x){return x==0x7b;}));
  assert(*reinterpret_cast<uint32_t *>(device.data()+20)==8);
  assert(*reinterpret_cast<uint32_t *>(device.data()+4096+1024+4)==8);
  assert(ufs_test_read(0,K70UfsPolicy::blocks-1,1,out.data())==0); // Last READ(10) LBA is valid.
  auto oldWrites=writes;
  assert(ufs_test_read(0,0xffffffffULL,2,out.data())==kIOReturnBadArgument && writes==oldWrites);
  for (Fault f: {Fault::Empty,Fault::Type,Fault::Tag,Fault::Lun,Fault::Residual,
                Fault::Underflow,Fault::Oversize,Fault::SenseLength,Fault::Timeout,Fault::Fatal}) {
    reset(f); out.fill(0xa5);
    assert(ufs_test_read(0,1,1,out.data())!=0);
    assert(std::all_of(out.begin(),out.end(),[](uint8_t x){return x==0xa5;}));
    assertQuarantined();
  }
  reset(Fault::Query); value=0xabcdef;
  assert(ufs_test_query(3,2,&value)!=0 && value==0xabcdef); assertQuarantined();
  reset(Fault::CheckCondition); out.fill(0xa5);
  assert(ufs_test_read(0,1,1,out.data())==kIOReturnNotReady);
  assert(!gHost.poisoned && gRootDiagnostic.sense==0x062900);
  assert(out[0]==0xa5);
  fault=Fault::None; assert(ufs_test_read(0,1,1,out.data())==0);
  reset(); uint8_t cdb[17]={}; uint32_t scsi;
  assert(ufs_test_scsi(0,cdb,17,false,0,&scsi)!=0);
  assert(ufs_test_scsi(0,cdb,6,true,kDataMax+4,&scsi)==kIOReturnBadArgument);
  assert(ufs_test_scsi(0,cdb,6,false,4096,&scsi)==kIOReturnBadArgument); // No writes to media.
  assert(writes==0 && releases==0);
  // Exercise the actual submit gate: forbidden commands do not touch MMIO/DMA.
  reset();
  for(unsigned opcode=0;opcode<256;++opcode) {
    uint8_t cmd[10]={};cmd[0]=opcode;cmd[5]=1;cmd[8]=1;
    uint32_t st=0;
    unsigned before=writes;
    assert(hostScsiDir(0,cmd,10,1,4096,200000,&st)!=0 && writes==before);
    if(opcode!=0x28)
      assert(hostScsiDir(0,cmd,10,2,4096,200000,&st)!=0 && writes==before);
  }
  assert(ufs_test_read(0,211008,1,out.data())!=0 && writes==0);
  assert(ufs_test_read(0,2570304,1,out.data())!=0 && writes==0);
  assert(ufs_test_read(0,5716032,1,out.data())!=0 && writes==0);
  for (unsigned offset: {0x58U,0x78U,0x80U}) {
    reset(); registers[offset/4]=1;
    assert(!ufs_test_stop_queue() && writes==0);
  }
  reset(); registers[0x34/4]=0; assert(!ufs_test_stop_queue() && writes==0);
  reset(); registers[0x20/4]=0x20000;
  assert(!ufs_test_stop_queue() && writes==0);
  assert(ufs_test_nop()!=0 && writes==0 && releases==0); assertQuarantined();
  reset(Fault::Stop); assert(!ufs_test_stop_queue() && now>=100000);
  reset(Fault::Start); assert(ufs_test_stop_queue()); assert(!ufs_test_start_queue());
  reset(Fault::HighBase); assert(ufs_test_stop_queue()); assert(!ufs_test_start_queue());
  reset(); assert(ufs_test_stop_queue() && ufs_test_start_queue());
  assert(registers[0x50/4]==0xcb5e9000 && registers[0x54/4]==8);
  puts("PASS: actual command/queue path; malformed DMA responses, bounds, short reads, sense, quarantine, queue refusal and full-width DMA");
}
