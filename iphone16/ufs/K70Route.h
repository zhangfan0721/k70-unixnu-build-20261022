// SPDX-License-Identifier: MIT
#pragma once
// Reuse nuwa's inspect-before-takeover contract, without assuming its slot/CB.
// Never configure a stream or enable/disable a context. Unknown state is fatal
// to this qualification, before any request-list/controller write.
template<class Read, class Trace>
static bool k70CheckUfsRoute(Read read, Trace trace, unsigned *bank) {
    unsigned cr0=read(0);
    unsigned id0=read(0x20), id1=read(0x24), id2=read(0x28);
    trace("UFS SMMU CR0",cr0);
    trace("UFS SMMU ID0",id0);trace("UFS SMMU ID1",id1);trace("UFS SMMU ID2",id2);
    auto reject=[&](unsigned code){trace("UFS route reject",code);return false;};
    if (id0!=0x4c017e69 || id1!=0x60000046 || id2!=0x5111) return reject(1);
    // One bounded, read-only snapshot, including when the CR0 guard will fail.
    // This distinguishes a global guard from a missing stream without changing
    // any acceptance condition. Pairs are SMR in high32 / S2CR in low32.
    unsigned smrs[105],s2crs[105],valid=0,matches=0;
    for(unsigned i=0;i<105;++i) {
        unsigned smr=smrs[i]=read(0x800+4*i),s2cr=s2crs[i]=read(0xc00+4*i);
        if(!(smr&0x80000000U)) continue;
        ++valid;
        unsigned mask=(smr>>16)&0x7fff;
        if(!((((smr^0x60U)&0x7fff)&~mask)))++matches;
        trace("UFS valid slot",i);
        trace("UFS SMR/S2CR",(static_cast<unsigned long long>(smr)<<32)|s2cr);
    }
    trace("UFS valid slots",valid);trace("UFS SID60 matches",matches);
    if(read(0)!=cr0)return reject(7);
    if(cr0&9)return reject(2);
    unsigned selected=~0U, cb=~0U;
    for(unsigned i=0;i<105;++i) {
        unsigned smr=smrs[i], s2cr=s2crs[i];
        if (!(smr&0x80000000U)) continue;
        unsigned mask=(smr>>16)&0x7fff;
        if ((((smr^0x60U)&0x7fff)&~mask)!=0) continue;
        trace("UFS SMR",smr);trace("UFS S2CR",s2cr);
        if(selected!=~0U || smr!=0x80000060U || (s2cr&0xffff0000U)) return reject(3);
        selected=i;cb=s2cr&255;
    }
    if(selected==~0U || cb>=16) return reject(4);
    for(unsigned i=0;i<105;++i) {
        unsigned smr=smrs[i], s2cr=s2crs[i];
        if(i!=selected && (smr&0x80000000U) && !(s2cr&0x30000U) && (s2cr&255)==cb) return reject(5);
    }
    // ID1 identifies the same 4KiB SM8550 geometry; global space is 0x80000.
    unsigned base=0x80000+cb*4096;
    unsigned sctlr=read(base), cbar=read(0x1000+4*cb), cba2r=read(0x1800+4*cb);
    trace("UFS context bank",cb);trace("UFS SCTLR",sctlr);
    trace("UFS CBAR",cbar);trace("UFS CBA2R",cba2r);
    if(sctlr || cbar!=0x1f000 || cba2r!=1) return reject(6);
    for(unsigned i=0;i<105;++i)
        if(read(0x800+4*i)!=smrs[i]||read(0xc00+4*i)!=s2crs[i])return reject(7);
    if(read(0)!=cr0||read(base)!=sctlr||read(0x1000+4*cb)!=cbar||read(0x1800+4*cb)!=cba2r)return reject(7);
    *bank=cb;return true;
}
