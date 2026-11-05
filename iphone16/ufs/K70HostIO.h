// SPDX-License-Identifier: BSD-2-Clause-Patent
// Board-local MMIO boundary for the single integrated takeover invocation.
enum class K70HostPhase { Inspect, Stopping, Configuring, Starting, Transport, Ending, Ended };
static K70HostPhase gPhase=K70HostPhase::Inspect;
static bool gMapFault=false,gWriteFault=false,gOwnStarted=false;
static bool gCleanupAttempted=false,gRouteConfigured=false;
static const char *gAccessFailure=nullptr;
static uint32_t gExpectedList[2]={};
static K70SmmuPlan gSmmuPlan;
static K70StateFailure gStateFailure;
static K70UfsPolicy::Wake gWake;

static void accessFailure(const char *reason,uint64_t address,uint64_t detail) {
    if(!gAccessFailure) {
        gAccessFailure=reason;
        k70_formal_cpu_trace(reason,address);
        k70_formal_cpu_trace("UFS access detail",detail);
    }
}
static bool mappedLocation(uintptr_t base,unsigned offset,uint64_t &pa) {
    if((offset&3) || base>~uintptr_t(0)-offset)return false;
    if(gHost.hc && base==gHost.hc && offset<=0x3000-4) {pa=0x1d84000+offset;return true;}
    if(gHost.smmu && base>=gHost.smmu && base-gHost.smmu<0xd0000 &&
       offset<=0xd0000-4-(base-gHost.smmu)) {
        pa=0x15000000+base-gHost.smmu+offset;return true;
    }
    return false;
}
static bool translationOK(uintptr_t va,uint64_t pa,bool write) {
    uint64_t par=write?k70ReadWriteTranslation(va):k70ReadTranslation(va);
    bool good=!(par&1) && ((par&0x000ffffffffff000ULL)|(va&4095))==pa &&
        uint8_t(par>>56)==0 && ((par>>7)&3)==2 && ((par>>9)&1)==1;
    if(!good) {gMapFault=true;accessFailure(write?"UFS write mapping refused":"UFS read mapping refused",pa,par);}
    return good;
}
static uint32_t read32(uintptr_t base,unsigned offset) {
    uint64_t pa=0;
    if(!mappedLocation(base,offset,pa)) {gMapFault=true;accessFailure("UFS read range refused",base,offset);return 0;}
    if(!translationOK(base+offset,pa,false))return 0;
    return *reinterpret_cast<volatile uint32_t *>(base+offset);
}
static bool hostControlHealthy() {return !gMapFault && !gWriteFault;}
static bool hostStateValue(unsigned o,uint32_t want,uint32_t actual,uint32_t mask=0xffffffffU) {
    return gStateFailure.check(1,uint64_t(gPhase)<<32,o,want,actual,mask);
}
static bool hostState(unsigned o,uint32_t want,uint32_t mask=0xffffffffU) {
    return hostStateValue(o,want,read32(gHost.hc,o),mask);
}
static bool smmuState(unsigned o,uint32_t want) {
    return gStateFailure.check(2,uint64_t(gPhase)<<32,o,want,read32(gHost.smmu,o));
}
static bool listIdentity() {
    return hostState(0x50,gExpectedList[0]) &&
        hostState(0x54,gExpectedList[1]) && hostControlHealthy();
}
static bool configuredIdentity() {
    if(!gStateFailure.check(3,uint64_t(gPhase)<<32,1,1,gRouteConfigured) ||
       !smmuState(0,gSmmuPlan.cr0) || !smmuState(0x20,0x4c017e69) ||
       !smmuState(0x24,0x60000046) || !smmuState(0x28,0x5111))return false;
    for(unsigned i=0;i<105;++i) {
        uint32_t smr=i==gSmmuPlan.upstream.slot?0x80000060:gSmmuPlan.smr[i];
        uint32_t s2cr=i==gSmmuPlan.upstream.slot?69:gSmmuPlan.s2cr[i];
        if(!smmuState(0x800+4*i,smr) || !smmuState(0xc00+4*i,s2cr))return false;
    }
    for(unsigned i=0;i<9;++i)
        if(!smmuState(k70ContextOffset(69,i),i==7?0x10000U:i==8?1U:0U))return false;
    return hostControlHealthy();
}
static bool hcIdentity(bool ignoreFatal=false) {
    return hostState(0,gRootDiagnostic.cap) &&
        hostState(8,gRootDiagnostic.version) && hostState(0x34,1,1) &&
        hostState(0x80,0,1) && hostState(0x78,0) && listIdentity() &&
        (ignoreFatal || hostState(0x20,0,kUfsFatalStatus)) && hostControlHealthy();
}
static bool hostTransportOwned() {
    return gStateFailure.check(3,uint64_t(gPhase)<<32,0,uint32_t(K70HostPhase::Transport),uint32_t(gPhase)) &&
        hcIdentity() && hostState(0x30,3,3) && hostState(0x60,1,1) &&
        hostState(0x24,0) && configuredIdentity() && hostControlHealthy();
}
static void write32(uintptr_t base,unsigned offset,uint32_t value) {
    uint64_t pa=0;
    if(!hostControlHealthy() || !mappedLocation(base,offset,pa) ||
       !translationOK(base+offset,pa,true)) {
        gWriteFault=true;accessFailure("UFS write access refused",pa,value);return;
    }
    bool allowed=false;
    if(base==gHost.smmu && gPhase==K70HostPhase::Configuring) {
        unsigned slot=gSmmuPlan.upstream.slot;
        allowed=(offset==0xc5000 && value==0) || (offset==0x1914 && value==1) ||
            (offset==0x1114 && value==0x10000) ||
            (offset==0xc00+4*slot && value==69) ||
            (offset==0x800+4*slot && value==0x80000060);
    } else if(base==gHost.hc && hcIdentity(gPhase==K70HostPhase::Ending)) {
        if(gPhase==K70HostPhase::Stopping)
            allowed=((offset==0x24 || offset==0x60) && !value && hostState(0x58,0));
        if(gPhase==K70HostPhase::Starting && hostState(0x58,0) && hostState(0x24,0)) {
            if(offset==0x50 || offset==0x54)
                allowed=hostState(0x60,0,1) &&
                    value==uint32_t(gHost.phys>>(offset==0x54?32:0));
            if(offset==0x20)allowed=value==1;
            if(offset==0x60 && value==1)
                allowed=gRouteConfigured && configuredIdentity() &&
                    gExpectedList[0]==uint32_t(gHost.phys) && gExpectedList[1]==uint32_t(gHost.phys>>32);
        }
        if(gPhase==K70HostPhase::Transport)
            allowed=(offset==0x20 || offset==0x58) && value==1 &&
                hostState(0x58,0) && hostTransportOwned();
        if(gPhase==K70HostPhase::Ending)
            allowed=offset==0x60 && value==0 && gOwnStarted && gCleanupAttempted;
    }
    if(!allowed || !hostControlHealthy()) {
        gWriteFault=true;accessFailure("UFS write phase refused",pa,value);return;
    }
    k70_formal_cpu_trace("UFS MMIO write PA/value",(uint64_t(uint32_t(pa))<<32)|value);
    if(base==gHost.hc && offset==0x60 && value==1)gOwnStarted=true;
    __asm__ volatile("dsb sy" ::: "memory");
    *reinterpret_cast<volatile uint32_t *>(base+offset)=value;
    __asm__ volatile("dsb sy" ::: "memory");
    // Run/stop and status have their own bounded completion checks.
    if(base==gHost.hc && (offset==0x24 || offset==0x50 || offset==0x54)) {
        uint32_t actual=read32(base,offset);
        if(!hostStateValue(offset,value,actual)) {gWriteFault=true;accessFailure("UFS HC write readback failed",pa,actual);return;}
        if(offset==0x50)gExpectedList[0]=value;
        if(offset==0x54)gExpectedList[1]=value;
    }
}
static bool preflightWriteAccess() {
    const unsigned hc[]={0x20,0x24,0x50,0x54,0x58,0x60};
    const unsigned smmu[]={0xc5000,0x1914,0x1114,
        0xc00+4*gSmmuPlan.upstream.slot,0x800+4*gSmmuPlan.upstream.slot};
    for(unsigned o:hc)if(!translationOK(gHost.hc+o,0x1d84000+o,true))return false;
    for(unsigned o:smmu)if(!translationOK(gHost.smmu+o,0x15000000+o,true))return false;
    return hostControlHealthy();
}
