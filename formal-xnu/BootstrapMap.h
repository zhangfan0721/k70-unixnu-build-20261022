/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef K70_BOOTSTRAP_MAP_H
#define K70_BOOTSTRAP_MAP_H
#include <stdint.h>
#include <stddef.h>

/* 4 KiB tables, 2 MiB blocks; EL1 RW, XN/PXN, outer-shareable Normal NC.
 * XNU's non-Apple MAIR index 1 is CACHE_ATTRINDX_WRITECOMB. */
#define K70_FB_BLOCK_FLAGS UINT64_C(0x0060000000000605)
static inline int k70_owned_page(uintptr_t page, uint64_t lo, uint64_t hi)
{
    return !(page & 4095) && hi >= lo && hi-lo >= 4096 &&
        page >= lo && page <= hi-4096;
}

/* Called with MMU off, only on the boot CPU. It can add missing mappings,
 * never replace a descriptor or dereference a table outside the owned window.
 * Nine blocks cover the 1440*3200*4 framebuffer, wholly inside its carveout. */
static inline int k70_bootstrap_fb_map(volatile uint64_t *root,
    volatile uint64_t *spare, uint64_t lo, uint64_t hi)
{
    if (hi < lo || (lo < UINT64_C(0xbab00000) && hi > UINT64_C(0xb8000000)) ||
        !k70_owned_page((uintptr_t)root,lo,hi)) { return 0; }
    uint64_t descriptor=root[2];
    volatile uint64_t *table;
    if (!descriptor) {
        if (!k70_owned_page((uintptr_t)spare,lo,hi) || spare==root) { return 0; }
        table=spare;
    } else {
        if ((descriptor & 3)!=3) { return 0; }
        uintptr_t address=descriptor & UINT64_C(0x0000fffffffff000);
        if (!k70_owned_page(address,lo,hi) || address==(uintptr_t)root) { return 0; }
        table=(volatile uint64_t *)address;
    }
    for (unsigned i=448; descriptor && i<457; i++) {
        uint64_t wanted=(UINT64_C(0xb8000000)+(i-448)*UINT64_C(0x200000))|K70_FB_BLOCK_FLAGS;
        if (table[i] && table[i]!=wanted) { return 0; }
    }
    if (!descriptor) {
        for (unsigned i=0;i<512;i++) { table[i]=0; }
    }
    for (unsigned i=448;i<457;i++) {
        table[i]=(UINT64_C(0xb8000000)+(i-448)*UINT64_C(0x200000))|K70_FB_BLOCK_FLAGS;
    }
    if (!descriptor) { root[2]=(uintptr_t)table|3; }
    return 1;
}
#endif
