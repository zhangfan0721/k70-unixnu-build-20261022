// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <cstdint>
#include <cassert>
#include <cstdio>
#include <array>
#include <vector>
#include <utility>
#include <cstring>
#include "K70Smmu.h"
#include "K70SctlrQualification.h"
#include "RootTransportLayout.h"
#include "K70Dma.h"
static std::array<uint32_t,0xd0000/4> regs;
static std::vector<std::pair<unsigned,uint32_t>> writes;
static auto rd=[](unsigned o){assert(o<0xd0000 && !(o&3));return regs.at(o/4);};
static std::vector<std::pair<const char *,uint64_t>> traces;
static auto trace=[](const char *s,uint64_t v){traces.emplace_back(s,v);};
static uint64_t traced(const char *name) {
    for(auto entry:traces)if(!std::strcmp(entry.first,name))return entry.second;
    return ~uint64_t(0);
}
static void reset() {
    regs.fill(0);writes.clear();traces.clear();regs[0]=0x2d406;
    regs[0x20/4]=0x4c017e69;regs[0x24/4]=0x60000046;regs[0x28/4]=0x5111;
    regs[(0x800+12)/4]=0x80021c00;regs[(0xc00+12)/4]=3;
}
static K70SmmuPlan plan(){return k70PlanUfsSmmu(0x8cb5e9000ULL,kDmaBytes,rd,trace);}
int main() {
    // Different boots may leave different inactive attributes. Qualification
    // must not bind them to the MAP01 CR0/SCTLR/route snapshot.
    for(uint32_t cr0: {0x250406U,0x24d406U,0x2d406U,0x25fc06U}) {
        reset();regs[0]=cr0;regs[0xc5000/4]=0x3fd9a71e;
        auto initial=plan();
        assert(!initial.error && initial.cr0==cr0);
    }
    reset();auto p=plan();assert(!p.error && p.upstream.bank==69 && p.upstream.slot==104);
    auto wr=[](unsigned o,uint32_t v){writes.emplace_back(o,v);regs.at(o/4)=v;};
    assert(!k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace));
    assert(writes.size()==5 && regs[(0x800+12)/4]==0x80021c00 && regs[(0xc00+12)/4]==3);
    assert(writes[0].first==0xc5000 && writes[1].first==0x1914 && writes[2].first==0x1114);
    assert(writes[3].first==0xda0 && writes[4].first==0x9a0);
    assert(regs[0]==0x2d406);
    // FSR Format[10:9] is not a fault, including the measured VA64 change.
    for(uint32_t format: {0U,0x200U,0x400U,0x600U}) {
        reset();regs[0xc5058/4]=format;p=plan();
        assert(!p.error && p.context[6]==format);
        regs[0xc5058/4]=format^0x600U;
        assert(k70SmmuSnapshotSame(p,rd));
        assert(!k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace));
        assert(writes.size()==5 && regs[0xc5058/4]==(format^0x600U));
    }
    // Format changes at every write boundary remain allowed; every other bit
    // rejects before initialization or before the next write/route publication.
    for(unsigned step=0;step<5;++step) {
        reset();p=plan();unsigned count=0;
        auto mode=[&](unsigned o,uint32_t v){wr(o,v);if(count++==step)regs[0xc5058/4]=0x400;};
        assert(!k70ConfigureUfsSmmu(p,rd,mode,[](){return true;},trace));
        assert(writes.size()==5);
        for(unsigned bit=0;bit<32;++bit)if(bit!=9 && bit!=10) {
            reset();regs[0xc5058/4]=0x400U|(1U<<bit);assert(plan().error);
            reset();p=plan();count=0;
            auto fault=[&](unsigned o,uint32_t v){wr(o,v);if(count++==step)regs[0xc5058/4]=0x400U|(1U<<bit);};
            K70StateFailure failure;
            assert(k70ConfigureUfsSmmu(p,rd,fault,[](){return true;},trace,&failure));
            assert(writes.size()==step+1 && failure.present);
            assert(failure.offset==0xc5058 && failure.actual==(0x400U|(1U<<bit)));
            assert(failure.expected==0 && failure.mask==0xfffff9ffU);
        }
    }
    // A mode-change mismatch must retain the first exact register/value pair,
    // stop before CBAR and never publish a route. Do not assume a VA64 write
    // makes arbitrary changes acceptable.
    for(unsigned n=0;n<9;++n) {
        reset();p=plan();
        auto changedView=[&](unsigned o,uint32_t v){
            wr(o,v);
            if(o==0x1914)regs[k70ContextOffset(69,n)/4]^=0x20;
        };
        assert(k70ConfigureUfsSmmu(p,rd,changedView,[](){return true;},trace));
        assert(writes.size()==2 && regs[0x9a0/4]==0);
        assert(traced("UFS state offset")==k70ContextOffset(69,n));
        uint32_t expected=n==8?1:0;
        assert(traced("UFS state expected")==expected);
        assert(traced("UFS state actual")==uint32_t(expected^0x20));
        assert(traced("UFS state mask")==(n==6?0xfffff9ffU:0xffffffffU));
        assert(traced("UFS state space")==2);
        assert(traced("UFS state phase")==((uint64_t(2)<<32)|(n==8?0x101U:0x302U)));
    }
    K70StateFailure first;
    assert(!first.check(1,7,0x58,0,0x100));
    assert(!first.check(2,9,0xc5000,0,1));
    assert(first.space==1 && first.phase==7 && first.offset==0x58 && first.actual==0x100);
    assert(first.check(1,10,0x30,3,0x10f,3));
    assert(first.offset==0x58); // Later matching reads and cleanup cannot replace it.
    // The real K70 residual must progress through ALL five writes, and the
    // callback must compare SCTLR against zero after the first write.
    reset();regs[0]=0x250406;regs[0xc5000/4]=0x3fd9a71e;p=plan();
    assert(!p.error && !k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace));
    assert(writes.size()==5 && regs[0xc5000/4]==0 && regs[0x9a0/4]==0x80000060);
    for(unsigned bit=0;bit<32;++bit) {
        reset();regs[0]=0x250406;regs[0xc5000/4]=0x3fd9a71e;
        p=plan();auto bad=[&](unsigned o,uint32_t v){writes.emplace_back(o,v);regs[o/4]=v|(1U<<bit);};
        assert(k70ConfigureUfsSmmu(p,rd,bad,[](){return true;},trace));
        assert(writes.size()==1 && !(regs[0x9a0/4]&0x80000000));
    }
    for(unsigned n=0;n<9;++n) {
        reset();regs[k70ContextOffset(69,n)/4]=n==7?0x10000:n==8?4:1;
        assert(plan().error && writes.empty());
    }
    reset();regs[(0x1000+4*69)/4]=0x100ff;assert(!plan().error);
    // Firmware reclaim predicates permit inactive attributes, not an exact
    // reset/cleanup word. All are replaced and fully checked before routing.
    for(uint32_t sctlr: {0U,2U,0x3fd9a71eU,0x40000000U})
    for(uint32_t cbar: {0U,0x05000023U,0x01020000U,0x0121f7ffU})
    for(uint32_t cba2r: {0U,1U,2U,3U}) {
        reset();regs[0]=0x24d406;regs[0xc5000/4]=sctlr;
        regs[0x1114/4]=cbar;regs[0x1914/4]=cba2r;p=plan();
        assert(!p.error && p.context[0]==sctlr && p.context[7]==cbar);
        assert(!k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace));
        assert(regs[0xc5000/4]==0 && regs[0x1114/4]==0x10000 && regs[0x1914/4]==1);
    }
    // A retained MDP route can occupy another slot and have other attributes;
    // preserve every raw word. Only the already qualified bank3 is supported.
    reset();regs[0x800/4]=0x80001c01;regs[0xc00/4]=0x00008303;
    regs[0x80c/4]=0;regs[0xc0c/4]=0x12345678;p=plan();
    assert(!p.error && p.smr[0]==0x80001c01);
    assert(!k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace));
    assert(regs[0xc00/4]==0x00008303 && regs[0xc0c/4]==0x12345678);
    // Fixed UEFI records CBNDX even for a bypass/fault retained route: bank69
    // must still refuse, despite the architectural field being ignored there.
    reset();regs[0xc0c/4]=0x20003;assert(!plan().error);
    reset();regs[0xc0c/4]=0x20045;assert(plan().error);
    // Named qualification failures retain the true register/mask/raw value.
    for(auto bad: {std::make_pair(0U,1U),std::make_pair(0U,8U),
                   std::make_pair(0U,0x80000000U),std::make_pair(0U,0x40000000U),
                   std::make_pair(0xc5000U,1U),std::make_pair(0x1114U,0x10001U),
                   std::make_pair(0x1114U,0x30000U),std::make_pair(0x1914U,4U),
                   std::make_pair(0x1914U,0x10000U)}) {
        reset();regs[bad.first/4]|=bad.second;p=plan();
        assert(p.error && p.failure.present && p.failure.offset==bad.first);
        assert(p.failure.actual==regs[bad.first/4] && writes.empty());
    }
    reset();regs[0xc0c/4]=4;p=plan();
    assert(p.error && p.failure.offset==0xc0c && p.failure.mask==255);
    // A legal initial variation must never mask drift during the same takeover.
    const unsigned changed[]={0,0xc5000,0x1114,0x1914,0x80c,0xc0c,0x804,0xc04};
    for(unsigned offset:changed) {
        reset();regs[0]=0x24d406;regs[0xc5000/4]=0x3fd9a71e;p=plan();
        assert(!p.error);regs[offset/4]^=0x1000;K70StateFailure f;
        assert(!k70SmmuSnapshotSame(p,rd,&f));
        assert(f.present && f.offset==offset && f.mask==0xffffffffU);
        assert(k70ConfigureUfsSmmu(p,rd,wr,[](){return true;},trace,&f));
        assert(writes.empty());
    }
    for(unsigned offset:changed)for(unsigned step=0;step<5;++step) {
        reset();regs[0]=0x24d406;regs[0xc5000/4]=0x3fd9a71e;p=plan();
        unsigned count=0;
        auto drift=[&](unsigned o,uint32_t v){wr(o,v);if(count++==step)regs[offset/4]^=0x1000;};
        K70StateFailure f;
        assert(k70ConfigureUfsSmmu(p,rd,drift,[](){return true;},trace,&f));
        if(!f.present || f.offset!=offset || f.mask!=0xffffffffU)
            std::fprintf(stderr,"drift offset=%x step=%u first=%x mask=%x present=%u\n",offset,step,f.offset,f.mask,unsigned(f.present));
        assert(f.present && f.offset==offset && f.mask==0xffffffffU);
        assert(writes.size()==step+1);
    }
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
        qualifyReset();regs[k70ContextOffset(69,n)/4]^=n==7?0x10000:n==8?4:1;
        assert(qualifyPlan().error && writes.empty());
    }
    qualifyReset();p=qualifyPlan();consumed=false;
    auto drift=[&](unsigned o,uint32_t v){wr(o,v);regs[0x80c/4]^=1;};
    assert(k70QualifySctlr(p,consumed,rd,drift,[](){return true;},trace) && writes.size()==1);
    puts("SCTLR-only qualification: single store, strict readback, pre/post drift and retry refusal passed");
}
