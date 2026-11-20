// SPDX-License-Identifier: BSD-2-Clause-Patent
// The existing upstream queue and command functions are the only transport.
static void hostSnapshot(const char *stage) {
    boot_progress_stage(stage);
    const unsigned offsets[]={0,8,0x18,0x20,0x24,0x30,0x34,0x50,0x54,0x58,0x60,0x78,0x80};
    for(unsigned o:offsets)
        k70_formal_cpu_trace("UFS HC offset/value",(uint64_t(o)<<32)|read32(gHost.hc,o));
}
#include "K70End.inc"
static bool hostBringUp(const char **why) {
    gRootDiagnostic.stage="controller/SMMU map";
    gHost.hc=mapPhys(UFS_HC_BASE,UFS_HC_SIZE,gHost.hcMap);
    gHost.smmu=mapPhys(0x15000000,0xd0000,gHost.smmuMap);
    if(!gHost.hc || !gHost.smmu){*why="controller/SMMU map";return false;}
    // Validate the fixed layout before reading routes or context registers.
    if(read32(gHost.smmu,0x20)!=0x4c017e69 || read32(gHost.smmu,0x24)!=0x60000046 ||
       read32(gHost.smmu,0x28)!=0x5111 || !hostControlHealthy()) {
        *why="SMMU IDs/mapping";return false;
    }
    gRootDiagnostic.cap=read32(gHost.hc,0);
    gRootDiagnostic.version=read32(gHost.hc,8);
    gExpectedList[0]=read32(gHost.hc,0x50);gExpectedList[1]=read32(gHost.hc,0x54);
    hostSnapshot("UFS takeover initial");
    if(!hostControlHealthy() || !hcIdentity() || !hostState(0x30,15,15) ||
       !hostState(0x58,0)) {*why="initial HC ownership/ready/doorbell";return false;}
    gRootDiagnostic.stage="DMA allocation";
    gHost.dma=IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
        static_cast<IOOptionBits>(kIODirectionInOut)|static_cast<IOOptionBits>(kIOMemoryPhysicallyContiguous)|
        static_cast<IOOptionBits>(kIOMemoryMapperNone),kDmaBytes,4096);
    gHost.lock=IOLockAlloc();
    if(!gHost.dma || !gHost.lock){*why="DMA/lock allocation";return false;}
    gHost.virt=static_cast<uint8_t *>(gHost.dma->getBytesNoCopy());
    IOByteCount contiguous=0;
    gHost.phys=gHost.dma->getPhysicalSegment(0,&contiguous,kIOMemoryMapperNone);
    gRootDiagnostic.dma=gHost.phys;gRootDiagnostic.contiguous=contiguous;
    uint64_t limit=(gRootDiagnostic.cap&0x01000000U)?(1ULL<<36):(1ULL<<32);
    if(!gHost.virt || !k70DmaAllocation(gHost.phys,contiguous,limit)) {
        *why="DMA address/contiguity";return false;
    }
    bzero(gHost.virt,kDmaBytes);cacheCivac(gHost.virt,kDmaBytes);
    auto trace=[](const char *s,uint64_t v){k70_formal_cpu_trace(s,v);};
    auto rd=[](unsigned o){return read32(gHost.smmu,o);};
    gRootDiagnostic.stage="initial SMMU qualification";
    gSmmuPlan=k70PlanUfsSmmu(gHost.phys,kDmaBytes,rd,trace);
    if(gSmmuPlan.error || !hostControlHealthy()) {
        if(gSmmuPlan.failure.present)gStateFailure=gSmmuPlan.failure;
        *why=gSmmuPlan.error?gSmmuPlan.error:"SMMU read mapping";return false;
    }
    if(!preflightWriteAccess() || !hcIdentity() || !k70SmmuSnapshotSame(gSmmuPlan,rd,&gStateFailure,uint64_t(gPhase)<<32)) {
        *why="write permission/initial snapshot changed";return false;
    }
    gPhase=K70HostPhase::Stopping;gRootDiagnostic.stage="stop firmware list";
    if(!hostStopQueue(why))return false;
    hostSnapshot("UFS firmware list stopped");
    if(!hostQueueIdleStopped() || !hcIdentity() || !k70SmmuSnapshotSame(gSmmuPlan,rd,&gStateFailure,uint64_t(gPhase)<<32) ||
       !hostControlHealthy()) {*why="post-stop ownership changed";return false;}
    gPhase=K70HostPhase::Configuring;gRootDiagnostic.stage="SMMU configuration";
    const char *error=k70ConfigureUfsSmmu(gSmmuPlan,rd,
        [](unsigned o,uint32_t v){write32(gHost.smmu,o,v);},
        [](){return hostControlHealthy() && hcIdentity() && hostQueueIdleStopped();},trace,&gStateFailure);
    if(error || !hostControlHealthy()) {*why=error?error:"SMMU MMIO refusal";return false;}
    gRouteConfigured=true;gHost.cb=gHost.smmu+0xc5000;
    gRootDiagnostic.smmuSlot=gSmmuPlan.upstream.slot;
    gRootDiagnostic.gfsrBefore=read32(gHost.smmu,0x48);
    gRootDiagnostic.fsrBefore=read32(gHost.cb,0x58);
    if(!configuredIdentity() || !hostQueueIdleStopped()) {*why="configured identity changed";return false;}
    gPhase=K70HostPhase::Starting;gRootDiagnostic.stage="start owned list";
    if(!hostStartQueue(why) || !hostControlHealthy())return false;
    gPhase=K70HostPhase::Transport;
    hostSnapshot("UFS owned list running");
    hostTimebaseTrace();
    gRootDiagnostic.stage="NOP OUT";
    if(hostNop()!=kIOReturnSuccess){*why="NOP OUT";return false;}
    gRootDiagnostic.stage="power attribute query";
    uint32_t power=0;
    if(hostQueryRead(3,2,&power)!=kIOReturnSuccess){*why="power attribute query";return false;}
    gRootDiagnostic.power=power;trace("UFS device power",power);
    if(!gWake.observe(power)){*why="unsupported device power mode";return false;}
    if(gWake.needed()) {
        gRootDiagnostic.stage="single ACTIVE wake";
        uint8_t cdb[6]={0x1b,0,0,0,0x10,0};uint32_t scsi=0;
        boot_progress_stage("UFS ACTIVE enter");
        IOReturn activeResult=hostScsi(0xd0,cdb,6,false,0,500000,&scsi);
        k70_formal_cpu_trace("UFS ACTIVE result",activeResult);
        k70_formal_cpu_trace("UFS ACTIVE SCSI",scsi);
        if(activeResult!=kIOReturnSuccess) {
            *why="single ACTIVE wake";return false;
        }
        gRootDiagnostic.stage="ACTIVE 50ms settle";
        boot_progress_stage("UFS settle enter");
        bool settled=hostWaitPause(50000); // Same fixed interval, no scheduler wait.
        hostWaitTrace("UFS settle returned");
        if(!settled) {
            gHost.ready=false;gHost.poisoned=true;
            gRootDiagnostic.result=kIOReturnIOError;*why="ACTIVE settle clock failure";return false;
        }
    }
    gRootDiagnostic.stage="single LUN0 readiness";
    boot_progress_stage("UFS TUR enter");
    uint8_t tur[6]={};uint32_t scsi=0;
    if(hostScsi(0,tur,6,false,0,200000,&scsi)!=kIOReturnSuccess) {
        *why="single LUN0 readiness";return false;
    }
    gHost.ready=true;
    if(!hostTransportOwned()){*why="transport ownership after readiness";return false;}
    return true;
}
