// SPDX-License-Identifier: MIT
// Compile-only: instantiate the actual kernel helper, including the AT probe,
// for arm64-apple-ios16.0. Never execute this translation unit on a host/device.
#include "K70SmmuEvidence.h"
static K70SmmuEvidence retained;
extern "C" void k70_mapping_compile(uint64_t mapped,
                                    void (*trace)(const char *,uint64_t)) {
    k70CollectSmmuEvidence(retained,mapped,k70ReadTranslation,[&](unsigned offset) {
        return *reinterpret_cast<volatile uint32_t *>(mapped+offset);
    });
    k70TraceSmmuEvidence(retained,trace);
}
extern "C" uint64_t k70_write_mapping_compile(uint64_t mapped) {
    return k70ReadWriteTranslation(mapped);
}
