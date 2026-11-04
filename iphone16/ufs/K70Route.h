// SPDX-License-Identifier: MIT
#pragma once
// Reuse nuwa's inspect-before-takeover contract, without assuming its slot/CB.
// Never configure a stream or enable/disable a context. Unknown state is fatal
// to this qualification, before any request-list/controller write.
template<class Read, class Trace>
static bool k70CheckUfsRoute(Read read, Trace trace, unsigned *bank) {
    unsigned id0=read(0x20), id1=read(0x24), id2=read(0x28);
    trace("UFS SMMU ID0",id0);trace("UFS SMMU ID1",id1);trace("UFS SMMU ID2",id2);
    if ((read(0)&9) || id0!=0x4c017e69 || id1!=0x60000046 || id2!=0x5111) return false;
    unsigned selected=~0U, cb=~0U;
    for(unsigned i=0;i<105;++i) {
        unsigned smr=read(0x800+4*i), s2cr=read(0xc00+4*i);
        if (!(smr&0x80000000U)) continue;
        unsigned mask=(smr>>16)&0x7fff;
        if ((((smr^0x60U)&0x7fff)&~mask)!=0) continue;
        trace("UFS SMR",smr);trace("UFS S2CR",s2cr);
        if(selected!=~0U || smr!=0x80000060U || (s2cr&0xffff0000U)) return false;
        selected=i;cb=s2cr&255;
    }
    if(selected==~0U || cb>=16) return false;
    for(unsigned i=0;i<105;++i) {
        unsigned smr=read(0x800+4*i), s2cr=read(0xc00+4*i);
        if(i!=selected && (smr&0x80000000U) && !(s2cr&0x30000U) && (s2cr&255)==cb) return false;
    }
    // ID1 identifies the same 4KiB SM8550 geometry; global space is 0x80000.
    unsigned base=0x80000+cb*4096;
    unsigned sctlr=read(base), cbar=read(0x1000+4*cb), cba2r=read(0x1800+4*cb);
    trace("UFS context bank",cb);trace("UFS SCTLR",sctlr);
    trace("UFS CBAR",cbar);trace("UFS CBA2R",cba2r);
    if(sctlr || cbar!=0x1f000 || cba2r!=1) return false;
    *bank=cb;return true;
}
