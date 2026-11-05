// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "K70Smmu.h"

// One invocation consumes the opportunity, including a precondition refusal.
// The upstream disable-only seam returns before CBA2R/CBAR/S2CR/SMR access.
template<class Read,class Write,class Idle,class Trace>
static const char *k70QualifySctlr(const K70SmmuPlan &p,bool &consumed,
                                Read read,Write write,Idle idle,Trace trace) {
    if(consumed)return "SCTLR qualification already consumed";
    consumed=true;
    if(p.error)return p.error;
    if(!p.sctlrQualification)return "SCTLR qualification plan required";
    if(!idle() || !k70SmmuSnapshotSame(p,read) || !idle())
        return "SCTLR qualification precondition changed";
    bool wrote=false,rejected=false;
    trace("SCTLR qualification original",p.context[0]);
    const char *result=configureUfsSmmu(p.upstream,0x60,[&](unsigned offset) {
        uint32_t value=read(offset);
        if(wrote && offset==0xc5000)trace("SCTLR upstream readback",value);
        return value;
    },
        [&](unsigned offset,uint32_t value) {
            if(wrote || rejected || offset!=0xc5000 || value!=0 ||
               !k70SmmuSnapshotSame(p,read) || !idle()) {
                rejected=true;return;
            }
            wrote=true; // Consume before the MMIO callback; never retry.
            write(offset,value);
        },true);
    trace("SCTLR qualification attempted",wrote);
    if(rejected || !wrote)return "SCTLR qualification write refused";
    if(result)return result; // Upstream requires the complete read value == 0.
    if(!idle())return "SCTLR qualification queue/mapping changed";
    for(unsigned i=0;i<105;++i)
        if(read(0x800+4*i)!=p.smr[i] || read(0xc00+4*i)!=p.s2cr[i])
            return "SCTLR qualification route changed";
    for(unsigned i=0;i<9;++i)
        if(read(k70ContextOffset(69,i))!=(i?p.context[i]:0))
            return "SCTLR qualification context readback changed";
    if(!idle() || read(0)!=p.cr0)return "SCTLR qualification final state changed";
    trace("SCTLR qualification passed",1);
    return nullptr;
}
