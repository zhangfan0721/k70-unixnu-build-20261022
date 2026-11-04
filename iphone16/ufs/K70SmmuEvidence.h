// SPDX-License-Identifier: MIT
#pragma once
#include <stdint.h>

// Read-only evidence for the existing mapPhys mapping, never a bank selector
// or configuration gate. All storage is fixed; no logging occurs while reading.
enum class K70MapFailure : uint32_t { None, Bounds, Translation, PhysicalAddress };
enum class K70EvidenceStatus : uint32_t { NotCollected, IdProbeFailed, UnknownIds, Collected };
struct K70MapWord {
    uint64_t va=0, expectedPa=0, actualPa=0, par=0;
    uint32_t offset=0;
    // Preserve even invalid-route raw words that normal formatting omits.
    volatile uint32_t value=0;
    K70MapFailure failure=K70MapFailure::Bounds;
    uint8_t attr=0, shareability=0, nonSecure=0, faultStatus=0;
};
struct K70SmmuEvidence {
    static constexpr unsigned kCriticalCount=13, kRouteCount=105, kRepeatCount=3;
    K70MapWord critical[kCriticalCount], smr[kRouteCount], s2cr[kRouteCount];
    K70MapWord sctlrRepeat[kRepeatCount];
    uint32_t failures=0, validRoutes=0, sid60Matches=0, bank69References=0;
    K70EvidenceStatus status=K70EvidenceStatus::NotCollected;
};

// The same DAIF/PAR preservation as the prepared BootProgressMin observer.
// Newlines are deliberate: Darwin's assembler treats ';' as a comment marker.
static inline uint64_t k70ReadTranslation(uint64_t va) {
#if defined(__aarch64__)
    uint64_t par, mask, saved;
    __asm__ volatile (
        "mrs %0, daif\n\t"
        "msr daifset, #15\n\t"
        "mrs %1, par_el1\n\t"
        "at s1e1r, %3\n\t"
        "isb\n\t"
        "mrs %2, par_el1\n\t"
        "msr par_el1, %1\n\t"
        "msr daif, %0"
        : "=&r"(mask), "=&r"(saved), "=&r"(par) : "r"(va) : "memory");
    return par;
#else
    (void)va;
    return 1; // A host cannot attest the kernel's ARM translation regime.
#endif
}

template<class Translate, class Read>
static K70MapWord k70ReadMappedWord(uint64_t va, uint64_t pa, uint64_t bytes,
                                  unsigned offset, Translate translate, Read read) {
    K70MapWord w;w.offset=offset;
    const uint64_t max=~uint64_t(0);
    // Include all four bytes, forbid wrap and a read crossing a 4KiB page.
    if(!va || (va&3) || (pa&3) || (offset&3) || bytes<4 || offset>bytes-4 ||
       va>max-offset || pa>max-offset || va+offset>max-3 || pa+offset>max-3)
        return w;
    w.va=va+offset;w.expectedPa=pa+offset;
    w.par=translate(w.va);
    if(w.par&1) {
        w.faultStatus=uint8_t((w.par>>1)&63);
        w.failure=K70MapFailure::Translation;return w;
    }
    w.actualPa=(w.par&0x000ffffffffff000ULL)|(w.va&4095);
    w.attr=uint8_t(w.par>>56);
    w.shareability=uint8_t((w.par>>7)&3);
    w.nonSecure=uint8_t((w.par>>9)&1);
    if(w.actualPa!=w.expectedPa) {
        w.failure=K70MapFailure::PhysicalAddress;return w;
    }
    w.failure=K70MapFailure::None;
    // This is the ONLY MMIO callback. Failed probes never reach it.
    w.value=read(offset);
    return w;
}

template<class Translate, class Read>
static K70EvidenceStatus k70CollectSmmuEvidence(K70SmmuEvidence &e, uint64_t mapped,
                                  Translate translate, Read read) {
    const unsigned offsets[]={0,0x20,0x24,0x28,0xc5000,0xc5020,0xc5024,
                              0xc5028,0xc502c,0xc5030,0xc5058,0x1114,0x1914};
    auto capture=[&](unsigned offset) {
        K70MapWord w=k70ReadMappedWord(mapped,0x15000000ULL,0xd0000,offset,translate,read);
        if(w.failure!=K70MapFailure::None)++e.failures;
        return w;
    };
    e.failures=e.validRoutes=e.sid60Matches=e.bank69References=0;
    e.status=K70EvidenceStatus::IdProbeFailed;
    // Establish the fixed register layout before any CR0, route or context
    // access. Retain all three ID probes even if one translation fails.
    for(unsigned i=1;i<=3;++i)e.critical[i]=capture(offsets[i]);
    for(unsigned i=1;i<=3;++i)
        if(e.critical[i].failure!=K70MapFailure::None)return e.status;
    if(e.critical[1].value!=0x4c017e69 || e.critical[2].value!=0x60000046 ||
       e.critical[3].value!=0x5111) {
        e.status=K70EvidenceStatus::UnknownIds;return e.status;
    }
    // Always collect all nine bank69 words, even when a planner would refuse
    // its first SCTLR word; this evidence never makes the context acceptable.
    e.critical[0]=capture(offsets[0]);
    for(unsigned i=4;i<e.kCriticalCount;++i)e.critical[i]=capture(offsets[i]);
    for(unsigned i=0;i<e.kRouteCount;++i) {
        e.smr[i]=capture(0x800+4*i);e.s2cr[i]=capture(0xc00+4*i);
        if(e.smr[i].failure!=K70MapFailure::None || e.s2cr[i].failure!=K70MapFailure::None)
            continue;
        uint32_t smr=e.smr[i].value,s2cr=e.s2cr[i].value;
        if(!(smr&0x80000000U))continue;
        ++e.validRoutes;
        unsigned mask=(smr>>16)&0x7fff;
        if(!(((smr^0x60U)&0x7fff)&~mask))++e.sid60Matches;
        // Count all valid references, including bypass/fault profiles.
        if((s2cr&255)==69)++e.bank69References;
    }
    for(unsigned i=0;i<e.kRepeatCount;++i)e.sctlrRepeat[i]=capture(0xc5000);
    e.status=K70EvidenceStatus::Collected;return e.status;
}

template<class Trace>
static void k70TraceMapWord(const K70MapWord &w, Trace trace) {
    trace("UFS map offset",w.offset);trace("UFS map VA",w.va);
    trace("UFS map expected PA",w.expectedPa);trace("UFS map actual PA",w.actualPa);
    trace("UFS map PAR",w.par);
    trace("UFS map ATTR/SH/NS",(uint64_t(w.attr)<<16)|(uint64_t(w.shareability)<<8)|w.nonSecure);
    trace("UFS map failure/FST",(uint64_t(w.failure)<<32)|w.faultStatus);
    if(w.failure==K70MapFailure::None)
        trace("UFS map offset/value",(uint64_t(w.offset)<<32)|w.value);
}

template<class Trace>
static void k70TraceSmmuEvidence(const K70SmmuEvidence &e, Trace trace) {
    // Formatting uses retained raw values; it never rereads a device register.
    trace("UFS evidence status",uint64_t(e.status));
    if(e.status==K70EvidenceStatus::NotCollected)return;
    for(unsigned i=1;i<=3;++i)k70TraceMapWord(e.critical[i],trace);
    if(e.status!=K70EvidenceStatus::Collected) {
        trace("UFS map failures",e.failures);return;
    }
    k70TraceMapWord(e.critical[0],trace);
    for(unsigned i=4;i<e.kCriticalCount;++i)k70TraceMapWord(e.critical[i],trace);
    for(unsigned i=0;i<e.kRouteCount;++i) {
        // Retain every route, but bound normal output to valid/failing pairs.
        if(e.smr[i].failure!=K70MapFailure::None || e.s2cr[i].failure!=K70MapFailure::None ||
           (e.smr[i].value&0x80000000U)) {
            trace("UFS evidence slot",i);
            k70TraceMapWord(e.smr[i],trace);k70TraceMapWord(e.s2cr[i],trace);
        }
    }
    for(unsigned i=0;i<e.kRepeatCount;++i) {
        trace("UFS SCTLR repeat",i);k70TraceMapWord(e.sctlrRepeat[i],trace);
    }
    trace("UFS map failures",e.failures);trace("UFS valid slots",e.validRoutes);
    trace("UFS SID60 matches",e.sid60Matches);trace("UFS bank69 references",e.bank69References);
}
