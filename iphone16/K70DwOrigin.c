/* SPDX-License-Identifier: MIT
 * K70 delayed-work page origin recorder (v2.1a implementation).
 * Single-CPU premise. No locks, no allocation, no object dereference.
 * Only the owning call chain reads a slot; BSS total for the pool is 4*1600 bytes. */
#include "K70DwOrigin.h"

/* The panic path has no FP/SIMD context. Forbid the compiler from using vector
 * registers in this recorder (clang aarch64 only; other compilers ignore it).
 * This is a restriction, not an enablement, and it changes no build flags. */
#if defined(__clang__) && defined(__aarch64__)
/* This recorder runs before any FP/SIMD state is guaranteed. Disable clang
 * optimisation for the translation unit so no vector registers are used for
 * copies/compares; the functions are tiny and only run on the diagnostic path. */
#pragma clang optimize off
#endif

static struct k70_dw_ctx k70_dw_pool[K70_DW_SLOTS];

/* v4: per-page UPL abort ring. Written field-wise through volatile so the
 * recorder still contains no FP/SIMD register use. */
static struct k70_abort_rec k70_abort_ring[K70_ABORT_SLOTS];
static uint32_t k70_abort_next;

void
k70_abort_page_note(uint32_t ppn, uint32_t error, uint32_t flags, uint32_t dw_mask, uintptr_t caller)
{
	const uint32_t slot = k70_abort_next & (K70_ABORT_SLOTS - 1u);
	volatile struct k70_abort_rec *r = &k70_abort_ring[slot];
	k70_abort_next = k70_abort_next + 1u;
	r->caller = caller;
	r->error = error;
	r->flags = flags;
	r->dw_mask = dw_mask;
	r->ppn = ppn;
}

int
k70_abort_page_get(uint32_t ppn, struct k70_abort_rec *out)
{
	for (uint32_t i = 0; i < K70_ABORT_SLOTS; i++) {
		volatile struct k70_abort_rec *r = &k70_abort_ring[i];
		if (r->ppn != ppn || r->caller == 0) {
			continue;
		}
		out->caller = r->caller;
		out->error = r->error;
		out->flags = r->flags;
		out->dw_mask = r->dw_mask;
		out->ppn = r->ppn;
		return 1;
	}
	return 0;
}

/* Volatile word helpers keep the recorder free of FP/SIMD register usage:
 * clang must not merge adjacent 32-bit stores into 8/16-byte vector stores. */
static void
k70_dw_zero_bytes(void *dst, size_t bytes)
{
	volatile uint32_t *d = (volatile uint32_t *)dst;
	for (size_t i = 0; i < bytes / sizeof(uint32_t); i++) {
		d[i] = 0;
	}
}

static void
k70_dw_copy_bytes(void *dst, const void *src, size_t bytes)
{
	volatile uint32_t *d = (volatile uint32_t *)dst;
	const volatile uint32_t *s = (const volatile uint32_t *)src;
	for (size_t i = 0; i < bytes / sizeof(uint32_t); i++) {
		d[i] = s[i];
	}
}

static void
k70_dw_zero_snapshot(struct k70_dw_snapshot *snap)
{
	k70_dw_zero_bytes(snap, sizeof(*snap));
}

/* Byte-wise volatile stores: the only guaranteed way to keep clang from using
 * FP/SIMD registers for scalar copies without changing build flags. */
static void
k70_dw_store_u64(void *dst, uint64_t v)
{
	volatile uint8_t *d = (volatile uint8_t *)dst;
	for (unsigned i = 0; i < 8; i++) {
		d[i] = (uint8_t)(v >> (8 * i));
	}
}

void
k70_dw_try_begin(uintptr_t thread, uintptr_t input_object, uintptr_t dw_caller,
    int dw_count, struct k70_dw_token *tok)
{
	{
		volatile struct k70_dw_token *vt = tok;
		vt->ctx = NULL;
		vt->epoch = 0;
		vt->status = K70_ORIG_UNAVAIL;
		vt->reason = K70_R_NO_SLOT;
	}
	for (uint32_t i = 0; i < K70_DW_SLOTS; i++) {
		struct k70_dw_ctx *c = &k70_dw_pool[i];
		uint32_t expected = K70_DW_SLOT_FREE;
		if (!__atomic_compare_exchange_n(&c->owner, &expected, K70_DW_SLOT_OWNED,
		    0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) {
			continue;
		}
		/* Guard before increment: MAX-1 is the last usable value, never wraps. */
		if (c->epoch >= UINT64_MAX - 1) {
			__atomic_store_n(&c->owner, K70_DW_SLOT_DISABLED, __ATOMIC_RELEASE);
			tok->reason = K70_R_EPOCH;
			continue;
		}
		c->epoch = c->epoch + 1;
		c->thread = (uint64_t)thread;
		c->input_object = (uint64_t)input_object;
		c->dw_caller = (uint64_t)dw_caller;
		c->dw_count = (uint32_t)dw_count;
		c->status = (dw_count < 0 || dw_count > (int)K70_DW_PAGES) ? K70_DWC_BAD : 0;
		c->nrec = 0;
		c->dropped = 0;
		{
			volatile struct k70_dw_token *vt = tok;
			vt->ctx = c;
			vt->epoch = c->epoch;
			vt->status = K70_ORIG_UNAVAIL;
			vt->reason = K70_R_NONE;
		}
		return;
	}
}

void
k70_dw_note(struct k70_dw_token *tok, uintptr_t m, uintptr_t object,
    uint64_t offset, uint32_t ppn, uint32_t dw_mask, uint32_t dw_index,
    uint32_t wire_count, uint32_t flags, uint32_t flags_known)
{
	struct k70_dw_ctx *c;
	struct k70_dw_page_rec *r;

	if (tok == NULL || tok->ctx == NULL) {
		return;
	}
	c = tok->ctx;
	if (c->nrec >= K70_DW_PAGES) {
		if (c->dropped != UINT32_MAX) {
			c->dropped++;
		}
		return;
	}
	r = &c->rec[c->nrec++];
	r->m = (uint64_t)m;
	r->object = (uint64_t)object;
	r->offset = offset;
	r->ppn = ppn;
	r->dw_mask = dw_mask;
	r->dw_index = dw_index;
	r->wire_count = wire_count;
	r->flags = flags;
	r->reserved = flags_known;
}

void
k70_dw_end(struct k70_dw_token *tok)
{
	if (tok == NULL || tok->ctx == NULL) {
		return;
	}
	if (tok->ctx->epoch == tok->epoch && tok->ctx->owner == K70_DW_SLOT_OWNED) {
		__atomic_store_n(&tok->ctx->owner, K70_DW_SLOT_FREE, __ATOMIC_RELEASE);
	}
	tok->ctx = NULL;
}

uint32_t
k70_dw_lookup(const struct k70_dw_token *tok, uintptr_t mem, uint32_t ppn,
    uintptr_t thread, struct k70_dw_snapshot *snap)
{
	uint32_t hits = 0;
	uint32_t idx = 0;
	uint32_t reason = K70_R_NONE;

	k70_dw_zero_snapshot(snap);
	if (tok == NULL) {
		volatile uint32_t *v = (volatile uint32_t *)snap;
		v[0] = K70_ORIG_UNAVAIL;   /* status */
		v[1] = K70_R_INVALID_TOK;  /* reason */
		return snap->status;
	}
	if (tok->ctx == NULL) {
		/* reason passthrough: a failed claim must stay visible */
		snap->status = K70_ORIG_UNAVAIL;
		snap->reason = tok->reason;
		return snap->status;
	}
	if (__atomic_load_n(&tok->ctx->owner, __ATOMIC_ACQUIRE) != K70_DW_SLOT_OWNED) {
		snap->status = K70_ORIG_UNAVAIL;
		snap->reason = K70_R_OWNER;
		return snap->status;
	}
	if (tok->ctx->epoch != tok->epoch) {
		snap->status = K70_ORIG_UNAVAIL;
		snap->reason = K70_R_EPOCH;
		return snap->status;
	}
	if (tok->ctx->thread != (uint64_t)thread) {
		snap->status = K70_ORIG_UNAVAIL;
		snap->reason = K70_R_THREAD;
		return snap->status;
	}
	if (tok->ctx->nrec > K70_DW_PAGES) {
		snap->status = K70_ORIG_UNAVAIL;
		snap->reason = K70_R_BAD_NREC;
		return snap->status;
	}
	snap->reserved = tok->ctx->status;   /* batch_flags: BAD survives HIT */
#if defined(__clang__)
#pragma clang loop vectorize(disable) unroll(disable)
#endif
	for (uint32_t i = 0; i < tok->ctx->nrec; i++) {
		if (tok->ctx->rec[i].m == (uint64_t)mem && tok->ctx->rec[i].ppn == ppn) {
			hits++;
			idx = i;
		}
	}
	if (hits == 1) {
		snap->status = K70_ORIG_HIT;
		snap->epoch = tok->ctx->epoch;
		snap->index = idx;
		snap->dw_count = tok->ctx->dw_count;
		k70_dw_copy_bytes(&snap->rec, &tok->ctx->rec[idx], sizeof(snap->rec));
		k70_dw_store_u64(&snap->m, tok->ctx->rec[idx].m);
		k70_dw_store_u64(&snap->thread, tok->ctx->thread);
		k70_dw_store_u64(&snap->input_object, tok->ctx->input_object);
		k70_dw_store_u64(&snap->dw_caller, tok->ctx->dw_caller);
		snap->reason = (tok->ctx->status & K70_DWC_BAD) ? K70_R_BAD_COUNT : K70_R_NONE;
		return snap->status;
	}
	if (hits > 1) {
		reason = K70_R_MULTI_MATCH;
	} else if (tok->ctx->dropped != 0) {
		reason = K70_R_DROPPED;
	} else {
		reason = K70_R_NO_MATCH;
	}
	snap->status = (reason == K70_R_DROPPED) ? K70_ORIG_OVERFLOW : K70_ORIG_UNAVAIL;
	snap->reason = reason;
	return snap->status;
}

#if defined(__clang__) && defined(__aarch64__)
#pragma clang optimize on
#endif
