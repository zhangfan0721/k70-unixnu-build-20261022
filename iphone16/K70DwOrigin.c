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
static uintptr_t k70_ubc_caller;
static struct k70_kabort_rec k70_kabort_state;
/* v13: where ml_set_max_cpus is stuck, printed by the diagnostics thread. */
volatile uint32_t k70_max_cpus_phase;

/* v18: copied stage text, last blocking thread, and the live user-fault count. */
static char k70_stage_buf[48];
static struct k70_wait_rec k70_wait_state;
static volatile uint64_t k70_user_faults;

/* v20: only boot text is interesting here. The diagnostic lines all carry an
 * '=' or a known prefix, and recording them made LAST echo the heartbeat. */
static int
k70_stage_is_real(const char *s)
{
	unsigned i;
	if (s[0] == 'L' && s[1] == 'A' && s[2] == 'S' && s[3] == 'T') {
		return 0;
	}
	if (s[0] == 'F' && s[1] == '=') {
		return 0;
	}
	if (s[0] == 'M' && s[1] == 'C' && s[2] == 'P') {
		return 0;
	}
	if (s[0] == 'K' && s[1] == 'A') {
		return 0;
	}
	if (s[0] == 'S' && s[1] >= '0' && s[1] <= '9') {
		return 0;
	}
	if (s[0] == 'C' && s[1] == 'O' && s[2] == 'P' && s[3] == 'Y') {
		return 0;
	}
	if (s[0] == 'W' && (s[1] == 'E' || s[1] == 'L')) {
		return 0;
	}
	if (s[0] == 'F' && s[1] == 'A') {
		return 0;
	}
	for (i = 0; s[i] != 0; i++) {
		if (s[i] == '=') {
			return 0;
		}
	}
	return 1;
}

void
k70_stage_text_note(const char *s)
{
	unsigned i = 0;
	if (s == 0 || !k70_stage_is_real(s)) {
		return;
	}
	while (i + 1u < sizeof(k70_stage_buf) && s[i] != 0) {
		k70_stage_buf[i] = s[i];
		i++;
	}
	k70_stage_buf[i] = 0;
}

const char *
k70_stage_text_get(void)
{
	return k70_stage_buf;
}

static uintptr_t k70_worker_thread;
static struct k70_role_rec k70_role_state[4];
static volatile uint32_t k70_stage_bits;

void
k70_stage_set(uint32_t bit)
{
	if (bit < 32u) {
		k70_stage_bits = k70_stage_bits | (1u << bit);
	}
}

uint32_t
k70_stage_mask(void)
{
	return k70_stage_bits;
}

void
k70_role_note(uint32_t role, uintptr_t thread)
{
	volatile struct k70_role_rec *r;
	if (role == 0u || role > 3u || thread == 0) {
		return;
	}
	r = &k70_role_state[role];
	r->thread = thread;
	r->hit = r->hit + 1u;
}

const struct k70_role_rec *
k70_role_get(uint32_t role)
{
	if (role > 3u) {
		return 0;
	}
	return &k70_role_state[role];
}

void
k70_worker_note(uintptr_t thread)
{
	k70_worker_thread = thread;
}

void
k70_wait_note(uintptr_t thread, uintptr_t event, uintptr_t lr)
{
	volatile struct k70_wait_rec *w = &k70_wait_state;
	/* v21: the diagnostics worker itself blocks constantly in the console path;
	 * ignoring it leaves the site that actually matters. */
	for (uint32_t i = 1; i <= 3u; i++) {
		volatile struct k70_role_rec *r = &k70_role_state[i];
		if (r->thread != 0 && r->thread == thread) {
			r->lr = lr;
			r->event = event;
			r->blocks = r->blocks + 1u;
			return;
		}
	}
	{
		extern uintptr_t k70_flight_target_thread(void);
		uintptr_t want = k70_flight_target_thread();
		/* v22: only the boot thread's own blocking site is interesting. */
		if (want != 0 && thread != want) {
			return;
		}
		if (thread != 0 && thread == k70_worker_thread) {
			return;
		}
	}
	w->thread = thread;
	w->event = event;
	w->lr = lr;
	w->count = w->count + 1u;
}

const struct k70_wait_rec *
k70_wait_get(void)
{
	return &k70_wait_state;
}

uint64_t
k70_user_fault_count(void)
{
	return k70_user_faults;
}

void
k70_kabort_note(uint64_t esr, uint64_t far, uint64_t pc, uint64_t cpsr)
{
	volatile struct k70_kabort_rec *k = &k70_kabort_state;
	k->count = k->count + 1u;
	/* Keep the very first abort, and the first abort that targets a user
	 * address. Later samples are counted but never overwrite these. */
	if (k->count == 1u) {
		k->esr = esr;
		k->far = far;
		k->pc = pc;
		k->cpsr = cpsr;
	}
	if (far < 0x1000000000ull) {
		k70_user_faults = k70_user_faults + 1ull;
	}
	if (k->have2 == 0u && far < 0x1000000000ull) {
		k->esr2 = esr;
		k->far2 = far;
		k->pc2 = pc;
		k->cpsr2 = cpsr;
		k->have2 = 1u;
	}
}

const struct k70_kabort_rec *
k70_kabort_get(void)
{
	return &k70_kabort_state;
}

void
k70_abort_ubc_note(uintptr_t caller)
{
	k70_ubc_caller = caller;
}

uintptr_t
k70_abort_ubc_get(void)
{
	return k70_ubc_caller;
}

void
k70_abort_page_note(uint32_t ppn, uint32_t error, uint32_t flags, uint32_t dw_mask, uintptr_t caller)
{
	const uint32_t next = k70_abort_next + 1u;
	volatile struct k70_abort_rec *r = &k70_abort_ring[next & (K70_ABORT_SLOTS - 1u)];
	k70_abort_next = next;
	/* Invalidate, fill the payload, then publish the key last. A reader that
	 * interrupts this sequence sees caller == 0 and keeps scanning. */
	r->caller = 0;
	r->seq = 0;
	r->error = error;
	r->flags = flags;
	r->dw_mask = dw_mask;
	r->ppn = ppn;
	r->ubc_caller = k70_ubc_caller;
	r->caller = caller;
	r->seq = next;
}

int
k70_abort_page_get(uint32_t ppn, struct k70_abort_rec *out)
{
	int found = 0;
	uint32_t best = 0;
	/* Newest wins by 32-bit sequence distance, so wrap-around keeps ordering
	 * as long as the two records are less than 2^31 apart. */
	for (uint32_t i = 0; i < K70_ABORT_SLOTS; i++) {
		volatile struct k70_abort_rec *r = &k70_abort_ring[i];
		if (r->ppn != ppn || r->caller == 0) {
			continue;
		}
		/* Newest wins: the slot order says nothing about age after wrap. */
		if (!found || (int32_t)(r->seq - best) > 0) {
			best = r->seq;
			out->caller = r->caller;
			out->error = r->error;
			out->flags = r->flags;
			out->dw_mask = r->dw_mask;
			out->ppn = r->ppn;
			out->seq = r->seq;
			out->ubc_caller = r->ubc_caller;
			found = 1;
		}
	}
	return found;
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
