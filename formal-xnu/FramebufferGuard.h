/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef K70_FRAMEBUFFER_GUARD_H
#define K70_FRAMEBUFFER_GUARD_H
#include <stdint.h>
typedef int (*k70_probe)(uint64_t va, uint64_t *pa, void *context);
static inline int
k70_framebuffer_valid(uint64_t va, uint64_t pa, unsigned width, unsigned height,
    unsigned stride, unsigned depth, k70_probe probe, void *context)
{
    uint64_t bytes, end, at, translated;
    if (!probe || !va || (va & 3) || depth != 32 ||
        width < 320 || width > 8192 || height < 240 || height > 8192 ||
        (stride & 3) || stride < (uint64_t)width * 4 ||
        stride > (uint64_t)width * 4 + 16384) {
        return 0;
    }
    bytes = (uint64_t)stride * height;
    /* Restrict stores to this K70's known display carveout, never general RAM. */
    if (pa < UINT64_C(0xb8000000) || pa >= UINT64_C(0xbab00000) ||
        bytes > UINT64_C(0xbab00000) - pa || bytes - 1 > UINT64_MAX - va) {
        return 0;
    }
    end = va + bytes - 1;
    at = va;
    for (;;) {
        /* The architecture adapter must use a privileged WRITE translation. */
        if (!probe(at, &translated, context) || translated != pa + (at - va)) {
            return 0;
        }
        if (at == end) {
            return 1;
        }
        if (end - at < 4096 - (at & 4095)) {
            at = end;
        } else {
            at += 4096 - (at & 4095);
        }
    }
}
#endif
