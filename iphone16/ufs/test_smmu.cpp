// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <cstdint>
#include <cassert>
#include <cstdio>
#include <array>
#include <vector>
#include <utility>
#include "K70Smmu.h"
#include "K70SctlrQualification.h"
#include "RootTransportLayout.h"
#include "K70Dma.h"
static std::array<uint32_t,0xd0000/4> regs;
static std::vector<std::pair<unsigned,uint32_t>> writes;
static auto rd=[](unsigned o){assert(o<0xd0000 && !(o&3));return regs.at(o/4);};
static auto trace=[](const char *,uint64_t){};
static void reset() {
    regs.fill(0);writes.clear();regs[0]=0x2d406;
    regs[0x20/4]=0x4c017e69;regs[0x24/4]=0x60000046;regs[0x28/4]=0x5111;
    regs[(0x800+12)/4]=0x80021c00;regs[(0xc00+12)/4]=3;
}
static K70SmmuPlan plan(){return k70PlanUfsSmmu(0x8cb5e9000ULL,kDmaBytes,rd,trace);}
int main() {
    reset();auto p=plan();assert(!p.error && p.upstream.bank==69 && p.upstream.slot==104);
    auto wr=[](unsigned o,uint32_t v){writes.emplace_back(o,v);regs.at(o/4)=v;};
    assert(!k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace));
    assert(writes.size()==5 && regs[(0x800+12)/4]==0x80021c00 && regs[(0xc00+12)/4]==3);
    assert(writes[0].first==0xc5000 && writes[1].first==0x1914 && writes[2].first==0x1114);
    assert(writes[3].first==0xda0 && writes[4].first==0x9a0);
    assert(regs[0]==0x2d406);
    for(unsigned n=0;n<9;++n) {
        reset();regs[k70ContextOffset(69,n)/4]=n==7?0x10000:n==8?2:1;
        assert(plan().error && writes.empty());
    }
    reset();regs[(0x1000+4*69)/4]=0x100ff;assert(!plan().error);
    // Unreferenced SMR slots do not prove context ownership: tables/TCR,
    // activity, unknown CBAR, shared references and retained faults all refuse.
    for(auto pair: {std::make_pair(0x800U,0x80000060U),
                    std::make_pair(0x800U,0x80010060U),
                    std::make_pair(0x800U,0x80000061U)}) {
        reset();regs[pair.first/4]=pair.second;regs[0xc00/4]=69;
        assert(plan().error && writes.empty());
    }
    reset();regs[0x800/4]=regs[0x804/4]=0x80000060;assert(plan().error);
    reset();regs[0]|=1;assert(plan().error);
    reset();regs[0x24/4]^=1;assert(plan().error);
    reset();assert(k70PlanUfsSmmu(~0ULL,16,rd,trace).error);
    // Queue must already be stopped; any snapshot drift aborts before writes.
    reset();p=plan();assert(k70ConfigureUfsSmmu(p,rd,wr,[](){return false;},trace));assert(writes.empty());
    reset();p=plan();regs[0x804/4]=1;
    assert(k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace));assert(writes.empty());
    // Write/readback failure: no later register writes, never expose the SMR.
    for(unsigned fail=0;fail<5;++fail) {
        reset();p=plan();unsigned count=0;
        auto bad=[&](unsigned o,uint32_t v){writes.emplace_back(o,v);if(count++!=fail)regs.at(o/4)=v;else regs.at(o/4)=v^1;};
        assert(k70ConfigureUfsSmmu(p,rd,bad,[](){return true;},trace));assert(writes.size()==fail+1);
    }
    reset();p=plan();unsigned idleCalls=0;
    assert(k70ConfigureUfsSmmu(p,rd,wr,[&](){return ++idleCalls<3;},trace));assert(writes.size()==1);
    for(unsigned n=0;n<9;++n) {
        reset();p=plan();
        auto late=[&](unsigned o,uint32_t v){wr(o,v);if(o==0x9a0)regs[k70ContextOffset(69,n)/4]^=1;};
        assert(k70ConfigureUfsSmmu(p,rd,late,[](){return true;},trace));
    }
    // All pointers, descriptor subranges and actual serialized lengths checked.
    uint64_t base=0x8cb5e9000ULL,limit=1ULL<<36;uint32_t u[8]={},prd[4]={};
    u[0]=0x14000000;u[2]=15;u[4]=uint32_t(base+4096);u[5]=uint32_t((base+4096)>>32);
    u[6]=(512>>2)|((kRspOffset>>2)<<16);u[7]=1|((kPrdtOffset>>2)<<16);
    prd[0]=uint32_t(base+kDataOffset);prd[1]=uint32_t((base+kDataOffset)>>32);prd[3]=16384-1;
    assert(k70DmaDescriptors(base,limit,2,16384,u,prd));
    assert(!k70DmaAllocation(base,kDmaBytes-1,limit));
    assert(!k70DmaAllocation(limit-4096,kDmaBytes,limit));
    assert(!k70DmaAllocation(base+1,kDmaBytes,limit));
    for(unsigned n=0;n<8;++n){u[n]^=1;assert(!k70DmaDescriptors(base,limit,2,16384,u,prd));u[n]^=1;}
    for(unsigned n=0;n<4;++n){prd[n]^=1;assert(!k70DmaDescriptors(base,limit,2,16384,u,prd));prd[n]^=1;}
    assert(!k70DmaDescriptors(base,limit,1,16384,u,prd));
    assert(!k70DmaDescriptors(base,1ULL<<32,2,16384,u,prd));
    assert(!k70DmaDescriptors(base,limit,2,kDataMax+4,u,prd));
    puts("K70 SMMU ownership/write/readback and DMA descriptor checks passed");
    auto qualifyPlan=[](){return k70PlanUfsSmmu(0,4,rd,trace,true);};
    auto qualifyReset=[](){reset();regs[0]=0x250406;regs[0xc5000/4]=0x3fd9a71e;};
    qualifyReset();p=qualifyPlan();bool consumed=false;
    assert(!p.error && p.sctlrQualification);
    assert(k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace) && writes.empty());
    assert(!k70QualifySctlr(p,consumed,rd,wr,[](){return true;},trace));
    assert(consumed && writes.size()==1 && writes[0]==std::make_pair(0xc5000U,0U));
    assert(k70QualifySctlr(p,consumed,rd,wr,[](){return true;},trace) && writes.size()==1);
    // Full-width readback fails on ANY bit, without later writes or restoration.
    for(unsigned bit=0;bit<32;++bit) {
        qualifyReset();p=qualifyPlan();consumed=false;
        auto bad=[&](unsigned o,uint32_t v){writes.emplace_back(o,v);regs[o/4]=1U<<bit;};
        assert(k70QualifySctlr(p,consumed,rd,bad,[](){return true;},trace));
        assert(consumed && writes.size()==1);
    }
    qualifyReset();p=qualifyPlan();consumed=false;
    assert(k70QualifySctlr(p,consumed,rd,wr,[](){return false;},trace) && writes.empty());
    qualifyReset();p=qualifyPlan();consumed=false;regs[0xc5020/4]=4;
    assert(k70QualifySctlr(p,consumed,rd,wr,[](){return true;},trace) && writes.empty());
    for(unsigned n=0;n<9;++n) {
        qualifyReset();regs[k70ContextOffset(69,n)/4]^=1;
        assert(qualifyPlan().error && writes.empty());
    }
    qualifyReset();p=qualifyPlan();consumed=false;
    auto drift=[&](unsigned o,uint32_t v){wr(o,v);regs[0x80c/4]^=1;};
    assert(k70QualifySctlr(p,consumed,rd,drift,[](){return true;},trace) && writes.size()==1);
    puts("SCTLR-only qualification: single store, strict readback, pre/post drift and retry refusal passed");
}
