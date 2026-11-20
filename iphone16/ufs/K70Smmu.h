// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "SmmuTakeover.h"
#include "K70Fsr.h"
// One fixed first-mismatch record for the existing takeover diagnostics.
// Space: 1=HC, 2=SMMU, 3=software state. No allocation or hardware action.
struct K70StateFailure {
    bool present=false;
    uint32_t space=0,offset=0,expected=0,actual=0,mask=0;
    uint64_t phase=0;
    bool check(unsigned s,uint64_t p,unsigned o,uint32_t want,uint32_t got,
               uint32_t bits=0xffffffffU) {
        if((got&bits)==want)return true;
        if(!present) {
            present=true;space=s;phase=p;offset=o;expected=want;actual=got;mask=bits;
        }
        return false;
    }
};
template<class Trace>
static void k70ReportStateFailure(const K70StateFailure &f,Trace trace) {
    if(!f.present)return;
    trace("UFS state space",f.space);trace("UFS state phase",f.phase);
    trace("UFS state offset",f.offset);trace("UFS state expected",f.expected);
    trace("UFS state actual",f.actual);trace("UFS state mask",f.mask);
}
// K70 UFS02 IDs + Xiaomi bsp-vermeer-t-oss kalama/apps-SMMU geometry.
// One new route only. No reuse/fallback, global mode changes or other streams.
struct K70SmmuPlan {
    UfsSmmuPlan upstream;
    uint32_t cr0=0,smr[105]={},s2cr[105]={},context[9]={};
    K70StateFailure failure;
    const char *error="not planned";
    bool sctlrQualification=false;
};
static unsigned k70ContextOffset(unsigned bank,unsigned index) {
    const unsigned cbOffsets[]={0,0x20,0x24,0x28,0x2c,0x30,0x58};
    return index<7?0x80000+bank*4096+cbOffsets[index]:
           (index==7?0x1000:0x1800)+bank*4;
}
static uint32_t k70SmmuWordMask(unsigned bank,unsigned offset) {
    return offset==k70ContextOffset(bank,6)?k70FsrFaultMask:0xffffffffU;
}
template<class Read,class Trace>
static K70SmmuPlan k70PlanUfsSmmu(uint64_t dma,uint64_t bytes,Read read,Trace trace,
                                bool sctlrQualification=false) {
    K70SmmuPlan p;p.sctlrQualification=sctlrQualification;p.cr0=read(0);
    trace("UFS SMMU CR0",p.cr0);
    uint32_t id0=read(0x20),id1=read(0x24),id2=read(0x28);
    trace("UFS SMMU ID0",id0);trace("UFS SMMU ID1",id1);trace("UFS SMMU ID2",id2);
    auto reject=[&](const char *reason,unsigned offset,uint32_t want,uint32_t got,
                    uint32_t mask=0xffffffffU) {
        p.failure.check(2,0,offset,want,got,mask);p.error=reason;return p;
    };
    if(id0!=0x4c017e69)return reject("K70 IDR0 layout",0x20,0x4c017e69,id0);
    if(id1!=0x60000046)return reject("K70 IDR1 geometry",0x24,0x60000046,id1);
    if(id2!=0x5111)return reject("K70 IDR2 formats/address widths",0x28,0x5111,id2);
    // IHI0062D.c 9.6.3: routing must be enabled and use legacy 15-bit IDs.
    // IDR2=0x5111 has neither VMID16S nor E2HS; do not enter those modes.
    // All remaining CR0 attributes are observed, never rewritten. In particular
    // MemAttr/BSU affect stream-table bypass, and PTM affects TLB maintenance;
    // none requires a historical value for a matched, translation-disabled CB.
    const uint32_t cr0Fields[]={0x1U,0x8U,0x80000000U,0x40000000U,0x30000000U};
    for(uint32_t field:cr0Fields) {
        if(!(p.cr0&field))continue;
        const char *reason=field==1?"K70 CR0.CLIENTPD must be zero":
            field==8?"K70 CR0.EXIDENABLE unsupported":
            field==0x80000000U?"K70 CR0.VMID16EN unsupported":
            field==0x40000000U?"K70 CR0.HYPMODE unsupported":"K70 CR0 reserved bits";
        return reject(reason,0,0,p.cr0,field);
    }
    unsigned valid=0,matches=0;
    for(unsigned i=0;i<105;++i) {
        p.smr[i]=read(0x800+4*i);p.s2cr[i]=read(0xc00+4*i);
        if(!(p.smr[i]&0x80000000U))continue;
        ++valid;unsigned mask=(p.smr[i]>>16)&0x7fff;
        if(!(((p.smr[i]^0x60U)&0x7fff)&~mask))++matches;
        trace("UFS valid slot",i);
        trace("UFS SMR/S2CR",(uint64_t(p.smr[i])<<32)|p.s2cr[i]);
    }
    trace("UFS valid slots",valid);trace("UFS SID60 matches",matches);
    // Fixed PlatformSecLib passes these MDP SIDs to ArmSmmuDetachAll.
    // Its SkipStream predicate, not a slot/count/raw-word snapshot, identifies
    // the routes it is allowed to preserve. Never modify any preserved route.
    const unsigned mdp[]={0x1c00,0x1c01,0x1c03,0x1c04,0x2801,0x2c01};
    for(unsigned i=0;i<105;++i)if(p.smr[i]&0x80000000U) {
        unsigned mask=(p.smr[i]>>16)&0x7fff,id=p.smr[i]&0x7fff;
        if(!((id^0x60U)&~mask))
            return reject("K70 SID60 route already exists",0x800+4*i,0,p.smr[i],0x80000000U);
        unsigned type=(p.s2cr[i]>>16)&3,bank=p.s2cr[i]&255;
        // Even when TYPE makes CBNDX architecturally ignored, the fixed UEFI
        // detach code uses it unconditionally in its retained-bank list.
        if(bank==69)
            return reject("K70 firmware retained bank69",0xc00+4*i,3,p.s2cr[i],0xff);
        bool retained=false;
        for(unsigned sid:mdp)if((sid&~mask)==(id&~mask))retained=true;
        if(!retained)
            return reject("K70 non-MDP route survived cleanup",0x800+4*i,0,p.smr[i],0x80000000U);
        if(type==3)
            return reject("K70 retained S2CR.TYPE reserved",0xc00+4*i,0,p.s2cr[i],0x30000);
        // Only bank3 is established as the retained K70 display context by the
        // fixed-firmware evidence. Do not generalize to uninspected contexts
        // (in particular their possible nested stage-2 references).
        if(bank!=3)
            return reject("K70 retained MDP context unsupported",0xc00+4*i,3,p.s2cr[i],0xff);
    }
    // Check the selected context before the upstream planner can return a
    // generic error. Preserve the actual offending field for terminal logs.
    for(unsigned i=0;i<9;++i) {
        unsigned offset=k70ContextOffset(69,i);
        p.context[i]=read(offset);
        trace("UFS context offset/value",(uint64_t(offset)<<32)|p.context[i]);
    }
    // SCTLR reset fields are mostly UNKNOWN (16.5.18). The existing fixed
    // firmware reclaims non-display banks but deliberately leaves SCTLR.
    // M=0 alone is NOT ownership: also require the cleanup invariant below,
    // cleared tables/TCR, no faults and no live reference, then quiesce HC.
    if(p.context[0]&1)
        return reject("K70 SCTLR.M enabled",0xc5000,0,p.context[0],1);
    for(unsigned i=1;i<6;++i)if(p.context[i])
        return reject("K70 context table/TCR not reclaimed",k70ContextOffset(69,i),0,p.context[i]);
    if(k70FsrFaults(p.context[6]))
        return reject("K70 initial FSR fault",0xc5058,0,p.context[6],k70FsrFaultMask);
    // ArmSmmuFreeContextBank preserves TYPE=0/2, or TYPE=1 with VMID=255;
    // other TYPE/VMID combinations are rewritten to that TYPE=1 signature.
    // Attributes/IRPTNDX are not ownership tokens and are replaced before SID
    // publication. This is a firmware cleanup invariant, not an Arm guarantee.
    unsigned type=(p.context[7]>>16)&3;
    if(type==3)
        return reject("K70 CBAR.TYPE not reclaimed",0x1114,0x10000,p.context[7],0x30000);
    if(type==1 && (p.context[7]&255)!=255)
        return reject("K70 CBAR.VMID not reclaimed",0x1114,255,p.context[7],255);
    // 10.2.2: VA64 may initially be either width; MONC is ignored for this
    // Non-secure bank. VMID16 is RES0 on this IDR2, bits15:2 are reserved.
    if(p.context[8]&0xffff0000U)
        return reject("K70 CBA2R.VMID16 unsupported",0x1914,0,p.context[8],0xffff0000U);
    if(p.context[8]&0xfffcU)
        return reject("K70 CBA2R reserved bits",0x1914,0,p.context[8],0xfffcU);
    p.upstream=planUfsSmmuBank(0x60,dma,bytes,read,0);
    if(p.upstream.error){p.error=p.upstream.error;return p;}
    if(p.upstream.reuse || p.upstream.bank!=69 || p.upstream.slot>=105 ||
       (p.smr[p.upstream.slot]&0x80000000U)) {
        p.error="K70 new-route geometry";return p;
    }
    trace("UFS selected slot",p.upstream.slot);trace("UFS selected bank",p.upstream.bank);
    p.error=nullptr;return p;
}
template<class Read>
static bool k70SmmuSnapshotSame(const K70SmmuPlan &p,Read read,
                              K70StateFailure *detail=nullptr,uint64_t phase=0) {
    K70StateFailure local;auto &f=detail?*detail:local;
    auto same=[&](unsigned o,uint32_t want){
        uint32_t mask=k70SmmuWordMask(p.upstream.bank,o);
        return f.check(2,phase,o,want&mask,read(o),mask);
    };
    if(p.error || !same(0,p.cr0) || !same(0x20,0x4c017e69) ||
       !same(0x24,0x60000046) || !same(0x28,0x5111))return false;
    for(unsigned i=0;i<105;++i)
        if(!same(0x800+4*i,p.smr[i]) || !same(0xc00+4*i,p.s2cr[i]))return false;
    for(unsigned i=0;i<9;++i)
        if(!same(k70ContextOffset(p.upstream.bank,i),p.context[i]))return false;
    return true;
}
template<class Read,class Write,class Idle,class Trace>
[[maybe_unused]] static const char *k70ConfigureUfsSmmu(const K70SmmuPlan &p,Read read,Write write,Idle idle,Trace trace,
                                                     K70StateFailure *detail=nullptr) {
    K70StateFailure local;auto &f=detail?*detail:local;
    uint64_t phase=uint64_t(2)<<32; // HC Configuring, low word=seen mask/write index.
    auto same=[&](unsigned o,uint32_t want){
        uint32_t mask=k70SmmuWordMask(p.upstream.bank,o);
        bool ok=f.check(2,phase,o,want&mask,read(o),mask);
        if(!ok && !detail)k70ReportStateFailure(f,trace);
        return ok;
    };
    if(p.error)return p.error;
    if(p.sctlrQualification)return "K70 qualification cannot configure a route";
    if(!idle() || !k70SmmuSnapshotSame(p,read,&f,phase))return "K70 ownership/queue changed before SMMU";
    unsigned cb=0x80000+4096*p.upstream.bank;
    unsigned allowed[]={cb,0x1800+4*p.upstream.bank,0x1000+4*p.upstream.bank,
                        0xc00+4*p.upstream.slot,0x800+4*p.upstream.slot};
    uint32_t expected[]={0,1,0x10000,p.upstream.bank,0x80000060};
    unsigned seen=0;bool failed=false;
    const char *firstFailure=nullptr;
    auto reject=[&](const char *reason){failed=true;if(!firstFailure)firstFailure=reason;};
    // Upstream also performs reads between callbacks. Preserve the raw value
    // it sees, while retaining the exact first mismatch before its generic
    // readback error can return early (no extra MMIO operation).
    auto upstreamRead=[&](unsigned offset) {
        uint32_t actual=read(offset),want=0;bool known=true;
        if(offset==cb)want=(seen&1)?0:p.context[0];
        else if(offset==allowed[1])want=(seen&2)?1:p.context[8];
        else if(offset==allowed[2])want=(seen&4)?0x10000:p.context[7];
        else if(offset==allowed[3])want=(seen&8)?p.upstream.bank:p.s2cr[p.upstream.slot];
        else if(offset==allowed[4])want=(seen&16)?0x80000060U:p.smr[p.upstream.slot];
        else known=false;
        if(known && !f.check(2,phase,offset,want,actual))reject("K70 upstream readback/state changed");
        return actual;
    };
    const char *result=configureUfsSmmu(p.upstream,0x60,upstreamRead,[&](unsigned offset,uint32_t value) {
        if(failed)return;
        unsigned i=0;while(i<5 && offset!=allowed[i])++i;
        phase=(uint64_t(2)<<32)|(seen<<8)|i;
        if(i==5 || value!=expected[i] || (seen&(1U<<i))) {reject("K70 SMMU write outside plan");return;}
        if(!idle() || !same(0,p.cr0)) {reject("K70 queue/global state changed before write");return;}
        if(!same(0x800+4*p.upstream.slot,(seen&16)?0x80000060U:p.smr[p.upstream.slot]) ||
           !same(0xc00+4*p.upstream.slot,(seen&8)?p.upstream.bank:p.s2cr[p.upstream.slot])) {
            reject("K70 selected route changed before write");return;
        }
        for(unsigned j=0;j<9;++j) {
            uint32_t want=p.context[j];
            if(j==0 && (seen&1))want=0;
            if(j==7 && (seen&4))want=0x10000;
            if(j==8 && (seen&2))want=1;
            // Only FSR Format[10:9] is excluded from fault checks. Tables,
            // TCR, SCTLR, CBA2R and CBAR remain exact; never rebaseline them.
            if(!same(k70ContextOffset(p.upstream.bank,j),want)){reject("K70 context phase changed before write");return;}
        }
        // Detect concurrent ownership changes to ALL other stream groups.
        for(unsigned j=0;j<105;++j)if(j!=p.upstream.slot &&
            (!same(0x800+4*j,p.smr[j]) || !same(0xc00+4*j,p.s2cr[j]))) {reject("K70 other route changed before write");return;}
        trace("UFS SMMU write offset/value",(uint64_t(offset)<<32)|value);
        seen|=1U<<i;write(offset,value);
        uint32_t actual=read(offset);
        trace("UFS SMMU readback offset/value",(uint64_t(offset)<<32)|actual);
        if(!f.check(2,phase,offset,value,actual)) {
            if(!detail)k70ReportStateFailure(f,trace);
            reject("K70 SMMU full-value readback failed");
        }
    });
    if(result)trace(result,0); // Preserve the upstream error before wrapping.
    if(failed)return firstFailure;
    if(result)return result;
    phase=(uint64_t(2)<<32)|(seen<<8)|5;
    if(!idle() || !same(0,p.cr0))return "K70 queue/global state changed after SMMU";
    for(unsigned i=0;i<105;++i)if(i!=p.upstream.slot &&
        (!same(0x800+4*i,p.smr[i]) || !same(0xc00+4*i,p.s2cr[i])))
        return "K70 other route changed after SMMU";
    if(!same(0x800+4*p.upstream.slot,0x80000060U) ||
       !same(0xc00+4*p.upstream.slot,p.upstream.bank))
        return "K70 selected route changed after SMMU";
    for(unsigned i=0;i<9;++i) {
        uint32_t want=i==7?0x10000U:i==8?1U:0U;
        if(!same(k70ContextOffset(p.upstream.bank,i),want))
            return "K70 selected context changed after SMMU";
    }
    trace("UFS SMMU route configured",1);return nullptr;
}
