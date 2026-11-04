// SPDX-License-Identifier: MIT
#include <cassert>
#include <cstdio>
#include <cstring>
#include "K70SmmuEvidence.h"

static constexpr uint64_t va=0xfffffff010000000ULL,pa=0x15000000ULL;
static uint64_t goodPar(uint64_t address) {
    return ((pa+address-va)&0x000ffffffffff000ULL)|(0x04ULL<<56)|(2U<<7)|(1U<<9);
}
int main() {
    assert(k70ReadTranslation(va)==1); // No host translation attestation.
    unsigned probes=0,reads=0;uint64_t lastProbe=0;
    auto translate=[&](uint64_t address) {++probes;lastProbe=address;return goodPar(address);};
    auto read=[&](unsigned offset) {assert(lastProbe==va+offset);++reads;return offset^0x55aaU;};
    auto word=k70ReadMappedWord(va,pa,0xd0000,0xc5024,translate,read);
    assert(word.failure==K70MapFailure::None && word.value==(0xc5024^0x55aaU));
    assert(word.va==va+0xc5024 && word.expectedPa==pa+0xc5024 && word.actualPa==word.expectedPa);
    assert(word.par==goodPar(word.va) && word.attr==4 && word.shareability==2 && word.nonSecure==1);
    word=k70ReadMappedWord(va,pa,0xd0000,0xcfffc,translate,read);
    assert(word.failure==K70MapFailure::None); // Last complete word in map.
    unsigned beforeProbes=probes,beforeReads=reads;
    const unsigned badOffsets[]={0xd0000U,0xcfffdU,1U,0xfffffffcU};
    for(unsigned offset:badOffsets) {
        word=k70ReadMappedWord(va,pa,0xd0000,offset,translate,read);
        assert(word.failure==K70MapFailure::Bounds);
    }
    const uint64_t badBases[]={0,~uint64_t(0)-3,va+1};
    for(uint64_t base:badBases) {
        word=k70ReadMappedWord(base,pa,0xd0000,4,translate,read);
        assert(word.failure==K70MapFailure::Bounds);
    }
    word=k70ReadMappedWord(va,pa,3,0,translate,read);assert(word.failure==K70MapFailure::Bounds);
    word=k70ReadMappedWord(va,~0ULL-3,16,4,translate,read);assert(word.failure==K70MapFailure::Bounds);
    assert(probes==beforeProbes && reads==beforeReads);
    word=k70ReadMappedWord(va,pa,0xd0000,0x20,[](uint64_t){return 1ULL|(0x15ULL<<1);},read);
    assert(word.failure==K70MapFailure::Translation && word.faultStatus==0x15 && word.par==0x2b);
    word=k70ReadMappedWord(va,pa,0xd0000,0x20,[](uint64_t){return 0x25000000ULL;},read);
    assert(word.failure==K70MapFailure::PhysicalAddress && word.actualPa==0x25000020);
    assert(reads==beforeReads); // Neither fault nor wrong PA reaches MMIO.

    static K70SmmuEvidence e;unsigned contextReads=0,routeReads=0,sctlrReads=0;
    auto fixture=[&](unsigned offset) {
        assert(lastProbe==va+offset);++reads;
        if(offset==0x20)return 0x4c017e69U;
        if(offset==0x24)return 0x60000046U;
        if(offset==0x28)return 0x5111U;
        if(offset==0xc5000){++sctlrReads;return 0x3fd9a71eU;}
        if((offset>=0xc5020 && offset<=0xc5058) || offset==0x1114 || offset==0x1914)++contextReads;
        if((offset>=0x800 && offset<0x9a4) || (offset>=0xc00 && offset<0xda4))++routeReads;
        if(offset==0x80c)return 0x80021c00U;
        if(offset==0xc0c)return 3U;
        return 0U;
    };
    assert(k70CollectSmmuEvidence(e,va,translate,fixture)==K70EvidenceStatus::Collected);
    assert(!e.failures && e.validRoutes==1 && !e.sid60Matches && !e.bank69References);
    assert(contextReads==8 && sctlrReads==4 && routeReads==210);
    assert(e.critical[4].value==0x3fd9a71e && e.critical[12].offset==0x1914);
    assert(e.smr[3].value==0x80021c00 && e.s2cr[3].value==3);
    for(const auto &w:e.sctlrRepeat)assert(w.value==0x3fd9a71e && w.failure==K70MapFailure::None);
    unsigned traces=0;beforeReads=reads;
    k70TraceSmmuEvidence(e,[&](const char *,uint64_t){++traces;});
    assert(traces && reads==beforeReads); // Formatting never rereads MMIO.

    // A failed SCTLR translation cannot skip the remaining eight context
    // words/routes or turn a fault into an apparent zero register.
    contextReads=routeReads=sctlrReads=0;
    auto badSctlr=[&](uint64_t address) {
        lastProbe=address;return address==va+0xc5000?1ULL:goodPar(address);
    };
    k70CollectSmmuEvidence(e,va,badSctlr,fixture);
    assert(e.failures==4 && contextReads==8 && routeReads==210 && !sctlrReads);
    assert(e.critical[4].failure==K70MapFailure::Translation);
    // Count every bank reference, without accepting masked/duplicate SID60.
    k70CollectSmmuEvidence(e,va,translate,[&](unsigned offset) {
        if(offset==0x20)return 0x4c017e69U;
        if(offset==0x24)return 0x60000046U;
        if(offset==0x28)return 0x5111U;
        if(offset==0x800)return 0x80000060U;
        if(offset==0x804)return 0x80010060U;
        if(offset==0xc00)return 69U;
        if(offset==0xc04)return 0x10000U|69;
        return 0U;
    });
    assert(e.validRoutes==2 && e.sid60Matches==2 && e.bank69References==2);
    // Reuse a populated snapshot: an ID refusal must never print old layout
    // words as fresh reads. The only MMIO addresses permitted are ID0..ID2.
    const uint32_t knownIds[]={0x4c017e69,0x60000046,0x5111};
    for(unsigned bad=0;bad<3;++bad) {
        for(unsigned mode=0;mode<3;++mode) {
            unsigned idProbes=0,idReads=0;
            auto idTranslate=[&](uint64_t address) -> uint64_t {
                assert(address>=va+0x20 && address<=va+0x28 && !(address&3));
                ++idProbes;
                if(address==va+0x20+4*bad && mode<2)
                    return mode==0?uint64_t(1):goodPar(address)^0x1000ULL;
                return goodPar(address);
            };
            auto idRead=[&](unsigned offset) {
                assert(offset>=0x20 && offset<=0x28 && !(offset&3));
                ++idReads;unsigned index=(offset-0x20)/4;
                return knownIds[index]^uint32_t(mode==2 && index==bad);
            };
            auto status=k70CollectSmmuEvidence(e,va,idTranslate,idRead);
            assert(status==(mode==2?K70EvidenceStatus::UnknownIds:K70EvidenceStatus::IdProbeFailed));
            assert(e.status==status && idProbes==3 && idReads==(mode==2?3U:2U));
            assert(e.failures==(mode==2?0U:1U) && !e.validRoutes && !e.bank69References);
            unsigned loggedReads=0;
            k70TraceSmmuEvidence(e,[&](const char *label,uint64_t value) {
                assert(std::strcmp(label,"UFS SCTLR repeat") && std::strcmp(label,"UFS evidence slot"));
                if(!std::strcmp(label,"UFS map offset/value")) {
                    ++loggedReads;unsigned offset=unsigned(value>>32);
                    assert(offset>=0x20 && offset<=0x28);
                }
            });
            assert(loggedReads==idReads);
        }
    }
    puts("K70 mapping PAR/bounds/read gating and complete context/route evidence passed");
}
