/* SPDX-License-Identifier: MIT
 * K70 delayed-work page origin recorder (v2.1a implementation).
 * Fixed BSS pool, explicit per-batch token, no allocation, no locks, no object walk. */
#ifndef K70_DW_ORIGIN_H
#define K70_DW_ORIGIN_H

#include <stdint.h>
#include <stddef.h>

/* C/C++ compatible compile-time assertion (this header is included from both
 * C sources and C++ IOCPU.cpp through K70Flight.h). */
#ifndef K70_STATIC_ASSERT
#if defined(__cplusplus)
#define K70_STATIC_ASSERT(c, m) static_assert(c, m)
#elif defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
#define K70_STATIC_ASSERT(c, m) _Static_assert(c, m)
#else
#define K70_STATIC_ASSERT(c, m) typedef char k70_sa_t_##__COUNTER__[(c) ? 1 : -1]
#endif
#endif

#define K70_DW_SLOTS 4u
#define K70_DW_PAGES 32u

#define K70_DW_SLOT_FREE     0u
#define K70_DW_SLOT_OWNED    1u
#define K70_DW_SLOT_DISABLED 2u

#define K70_ORIG_HIT      0u
#define K70_ORIG_UNAVAIL  1u
#define K70_ORIG_OVERFLOW 2u

#define K70_R_NONE        0u
#define K70_R_INVALID_TOK 1u
#define K70_R_NO_SLOT     2u
#define K70_R_EPOCH       3u
#define K70_R_OWNER       4u
#define K70_R_NO_MATCH    5u
#define K70_R_MULTI_MATCH 6u
#define K70_R_DROPPED     7u
#define K70_R_THREAD      8u
#define K70_R_BAD_NREC    9u
#define K70_R_BAD_COUNT   10u

#define K70_DWC_BAD (1u << 0)

/* page flag bits; flags_known bit i == 1 means flags bit i is meaningful */
/* Flag semantics: pmapped/wpmapped are historical "was ever entered" markers,
 * not proof that a live PTE exists now; wire_count is a raw field snapshot and
 * may be reused as a local id depending on q_state. The record is evidence of
 * what the kernel held at capture time, not a synchronisation guarantee. */
#define K70_DW_PF_BUSY        (1u << 0)
#define K70_DW_PF_FICTITIOUS  (1u << 1)
#define K70_DW_PF_DIRTY       (1u << 2)
#define K70_DW_PF_PMAPPED     (1u << 3)
#define K70_DW_PF_WPMAPPED    (1u << 4)
#define K70_DW_PF_WIRED       (1u << 5)
#define K70_DW_PF_LOPAGE      (1u << 6)
#define K70_DW_PF_PRIVATE     (1u << 7)
#define K70_DW_PF_KNOWN       (0x000000ffu)

struct k70_dw_page_rec {
	uint64_t m;
	uint64_t object;
	uint64_t offset;
	uint32_t ppn;
	uint32_t dw_mask;
	uint32_t dw_index;
	uint32_t wire_count;
	uint32_t flags;
	uint32_t reserved;      /* flags_known */
};

struct k70_dw_ctx {
	uint32_t owner;
	uint32_t status;
	uint64_t epoch;
	uint64_t thread;
	uint64_t dw_caller;
	uint64_t input_object;
	uint32_t dw_count;
	uint32_t nrec;
	uint32_t dropped;
	uint32_t reserved;
	uint64_t reserved64;
	struct k70_dw_page_rec rec[K70_DW_PAGES];
};

struct k70_dw_token {
	struct k70_dw_ctx *ctx;
	uint64_t epoch;
	uint32_t status;
	uint32_t reason;
};

struct k70_dw_snapshot {
	uint32_t status;
	uint32_t reason;
	uint64_t epoch;
	uint32_t index;
	uint32_t dw_count;
	uint32_t reserved;      /* batch_flags = ctx->status */
	struct k70_dw_page_rec rec;
	uint64_t m;
	uint64_t thread;
	uint64_t input_object;
	uint64_t dw_caller;
};

/* Kernel-side ABI gate: these are the layouts the implementation and the
 * host tests both rely on; a mismatch must fail the kernel build, not a script. */
K70_STATIC_ASSERT(sizeof(struct k70_dw_page_rec) == 48, "dw page record size");
K70_STATIC_ASSERT(sizeof(struct k70_dw_ctx) == 1600, "dw ctx size");
K70_STATIC_ASSERT(sizeof(struct k70_dw_token) == 24, "dw token size");
K70_STATIC_ASSERT(sizeof(struct k70_dw_snapshot) == 112, "dw snapshot size");
K70_STATIC_ASSERT(K70_DW_SLOTS * sizeof(struct k70_dw_ctx) == 6400, "dw pool size");
K70_STATIC_ASSERT(offsetof(struct k70_dw_ctx, rec) == 64, "dw ctx rec offset");
K70_STATIC_ASSERT(offsetof(struct k70_dw_snapshot, rec) == 32, "dw snapshot rec offset");

/* v4: per-page UPL abort context. The record is keyed by the physical page the
 * abort is about to hand to delayed work, so a lookup at assertion time returns
 * the abort that concerned this page, not the most recent abort on the CPU. */
#define K70_ABORT_SLOTS 16u
#define K70_ABORT_F_ABSENT    (1u << 0)
#define K70_ABORT_F_CLUSTERED (1u << 1)
#define K70_ABORT_F_BUSY      (1u << 2)
#define K70_ABORT_F_WIRED     (1u << 3)
struct k70_abort_rec {
 uintptr_t caller;
 uintptr_t ubc_caller;
 uint32_t ppn, error, flags, dw_mask, seq;
};
void k70_abort_page_note(uint32_t ppn, uint32_t error, uint32_t flags, uint32_t dw_mask,
    uintptr_t caller);
/* Set by ubc_upl_abort_range before it enters upl_abort_range, so the per-page
 * record can name the UBC caller that asked for the abort. */
void k70_abort_ubc_note(uintptr_t caller);
uintptr_t k70_abort_ubc_get(void);

/* v8: the kernel-mode abort itself, kept in memory so the panel can show it
 * without printing from the exception handler. */
struct k70_kabort_rec {
 uint64_t esr, far, pc, cpsr;
 uint64_t esr2, far2, pc2, cpsr2;
 uint32_t count, have2;
};
void k70_kabort_note(uint64_t esr, uint64_t far, uint64_t pc, uint64_t cpsr);
const struct k70_kabort_rec *k70_kabort_get(void);

/* v18: safe snapshots. The stage text is copied, the wait slot is written by the
 * blocking entry, and the user-fault counter grows on every user-target abort. */
void k70_stage_text_note(const char *s);
const char *k70_stage_text_get(void);
struct k70_wait_rec {
 uintptr_t thread, event, lr;
 uint64_t count;
};
void k70_wait_note(uintptr_t thread, uintptr_t event, uintptr_t lr);
const struct k70_wait_rec *k70_wait_get(void);
uint64_t k70_user_fault_count(void);
int k70_abort_page_get(uint32_t ppn, struct k70_abort_rec *out);

void k70_dw_try_begin(uintptr_t thread, uintptr_t input_object, uintptr_t dw_caller,
    int dw_count, struct k70_dw_token *tok);
void k70_dw_note(struct k70_dw_token *tok, uintptr_t m, uintptr_t object,
    uint64_t offset, uint32_t ppn, uint32_t dw_mask, uint32_t dw_index,
    uint32_t wire_count, uint32_t flags, uint32_t flags_known);
void k70_dw_end(struct k70_dw_token *tok);
uint32_t k70_dw_lookup(const struct k70_dw_token *tok, uintptr_t mem, uint32_t ppn,
    uintptr_t thread, struct k70_dw_snapshot *snap);

#endif /* K70_DW_ORIGIN_H */
