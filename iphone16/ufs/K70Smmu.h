// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "SmmuTakeover.h"
// K70 UFS02 IDs + Xiaomi bsp-vermeer-t-oss kalama/apps-SMMU geometry.
// One new route only. No reuse/fallback, global mode changes or other streams.
struct K70SmmuPlan {
    UfsSmmuPlan upstream;
    uint32_t cr0=0,smr[105]={},s2cr[105]={},context[9]={};
    const char *error="not planned";
};
static unsigned k70ContextOffset(unsigned bank,unsigned index) {
    const unsigned cbOffsets[]={0,0x20,0x24,0x28,0x2c,0x30,0x58};
    return index<7?0x80000+bank*4096+cbOffsets[index]:
           (index==7?0x1000:0x1800)+bank*4;
}
template<class Read,class Trace>
static K70SmmuPlan k70PlanUfsSmmu(uint64_t dma,uint64_t bytes,Read read,Trace trace) {
    K70SmmuPlan p;p.cr0=read(0);
    trace("UFS SMMU CR0",p.cr0);
    uint32_t id0=read(0x20),id1=read(0x24),id2=read(0x28);
    trace("UFS SMMU ID0",id0);trace("UFS SMMU ID1",id1);trace("UFS SMMU ID2",id2);
    if(id0!=0x4c017e69 || id1!=0x60000046 || id2!=0x5111 || (p.cr0&9)) {
        p.error="K70 SMMU IDs/global mode";return p;
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
    if(matches){p.error="existing/duplicate/masked UFS route; no overwrite";return p;}
    // The existing K70 display handoff is mandatory, never reprogrammed.
    if(valid!=1 || p.smr[3]!=0x80021c00 || p.s2cr[3]!=3) {
        p.error="K70 route ownership changed";return p;
    }
    p.upstream=planUfsSmmuBank(0x60,dma,bytes,read,0);
    if(p.upstream.error){p.error=p.upstream.error;return p;}
    if(p.upstream.reuse || p.upstream.bank!=69 || p.upstream.slot>=105 ||
       (p.smr[p.upstream.slot]&0x80000000U)) {
        p.error="K70 new-route geometry";return p;
    }
    // An empty SMR is insufficient: prohibit ANY valid reference to bank69,
    // active translation, retained tables/TCR/faults or an unknown CBAR state.
    for(unsigned i=0;i<105;++i)
        if((p.smr[i]&0x80000000U) && (p.s2cr[i]&255)==p.upstream.bank) {
            p.error="K70 context referenced";return p;
        }
    trace("UFS selected slot",p.upstream.slot);trace("UFS selected bank",p.upstream.bank);
    for(unsigned i=0;i<9;++i) {
        unsigned offset=k70ContextOffset(p.upstream.bank,i);
        p.context[i]=read(offset);
        trace("UFS context offset/value",(uint64_t(offset)<<32)|p.context[i]);
    }
    for(unsigned i=0;i<7;++i)if(p.context[i]) {
        p.error="K70 context not cleared/inactive";return p;
    }
    // 0: unused reset state. 0x100ff: exact ArmSmmuFreeContextBank cleanup
    // signature (S1_TRANS_S2_BYPASS, VMID255); never accept a live profile.
    if((p.context[7]!=0 && p.context[7]!=0x100ff) || p.context[8]>1) {
        p.error="K70 context ownership profile unknown";return p;
    }
    p.error=nullptr;return p;
}
template<class Read>
static bool k70SmmuSnapshotSame(const K70SmmuPlan &p,Read read) {
    if(p.error || read(0)!=p.cr0 || read(0x20)!=0x4c017e69 ||
       read(0x24)!=0x60000046 || read(0x28)!=0x5111)return false;
    for(unsigned i=0;i<105;++i)
        if(read(0x800+4*i)!=p.smr[i] || read(0xc00+4*i)!=p.s2cr[i])return false;
    for(unsigned i=0;i<9;++i)
        if(read(k70ContextOffset(p.upstream.bank,i))!=p.context[i])return false;
    return true;
}
template<class Read,class Write,class Idle,class Trace>
static const char *k70ConfigureUfsSmmu(const K70SmmuPlan &p,Read read,Write write,Idle idle,Trace trace) {
    if(p.error)return p.error;
    if(!idle() || !k70SmmuSnapshotSame(p,read))return "K70 ownership/queue changed before SMMU";
    unsigned cb=0x80000+4096*p.upstream.bank;
    unsigned allowed[]={cb,0x1800+4*p.upstream.bank,0x1000+4*p.upstream.bank,
                        0xc00+4*p.upstream.slot,0x800+4*p.upstream.slot};
    uint32_t expected[]={0,1,0x10000,p.upstream.bank,0x80000060};
    unsigned seen=0;bool failed=false;
    const char *result=configureUfsSmmu(p.upstream,0x60,read,[&](unsigned offset,uint32_t value) {
        if(failed)return;
        unsigned i=0;while(i<5 && offset!=allowed[i])++i;
        if(i==5 || value!=expected[i] || (seen&(1U<<i)) || !idle() || read(0)!=p.cr0) {failed=true;return;}
        if(read(0x800+4*p.upstream.slot)!=((seen&16)?0x80000060U:p.smr[p.upstream.slot]) ||
           read(0xc00+4*p.upstream.slot)!=((seen&8)?p.upstream.bank:p.s2cr[p.upstream.slot])) {
            failed=true;return;
        }
        for(unsigned j=0;j<9;++j) {
            uint32_t want=p.context[j];
            if(j==7 && (seen&4))want=0x10000;
            if(j==8 && (seen&2))want=1;
            if(read(k70ContextOffset(p.upstream.bank,j))!=want){failed=true;return;}
        }
        // Detect concurrent ownership changes to ALL other stream groups.
        for(unsigned j=0;j<105;++j)if(j!=p.upstream.slot &&
            (read(0x800+4*j)!=p.smr[j] || read(0xc00+4*j)!=p.s2cr[j])) {failed=true;return;}
        trace("UFS SMMU write offset/value",(uint64_t(offset)<<32)|value);
        seen|=1U<<i;write(offset,value);
        if(read(offset)!=value)failed=true;
    });
    if(failed)return "K70 SMMU bounded write/readback/ownership";
    if(result)return result;
    if(!idle() || read(0)!=p.cr0)return "K70 queue/global state changed after SMMU";
    for(unsigned i=0;i<105;++i)if(i!=p.upstream.slot &&
        (read(0x800+4*i)!=p.smr[i] || read(0xc00+4*i)!=p.s2cr[i]))
        return "K70 other route changed after SMMU";
    if(read(0x800+4*p.upstream.slot)!=0x80000060U ||
       read(0xc00+4*p.upstream.slot)!=p.upstream.bank)
        return "K70 selected route changed after SMMU";
    for(unsigned i=0;i<9;++i) {
        uint32_t want=i==7?0x10000U:i==8?1U:0U;
        if(read(k70ContextOffset(p.upstream.bank,i))!=want)
            return "K70 selected context changed after SMMU";
    }
    trace("UFS SMMU route configured",1);return nullptr;
}
