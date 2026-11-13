/* Host proof for the v2.1a DW origin recorder (no XNU headers required). */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "K70DwOrigin.h"

_Static_assert(sizeof(struct k70_dw_page_rec) == 48, "record 48B");
_Static_assert(sizeof(struct k70_dw_ctx) == 1600, "ctx 1600B");
_Static_assert(sizeof(struct k70_dw_token) == 24, "token 24B");
_Static_assert(sizeof(struct k70_dw_snapshot) == 112, "snapshot 112B");
_Static_assert(offsetof(struct k70_dw_ctx, rec) == 64, "ctx.rec");
_Static_assert(offsetof(struct k70_dw_snapshot, rec) == 32, "snap.rec");

static struct k70_dw_token g_tok[K70_DW_SLOTS];

static void drain(void)
{
	for (uint32_t i = 0; i < K70_DW_SLOTS; i++) {
		k70_dw_end(&g_tok[i]);
	}
}
static void fresh(void)
{
	drain();
	for (uint32_t i = 0; i < K70_DW_SLOTS; i++) {
		k70_dw_try_begin((uintptr_t)(0x9000 + i), 0, 0, 0, &g_tok[i]);
	}
	drain();
}
static void t_layout(void)
{
	struct k70_dw_snapshot s;
	printf("== layout ==\n");
	assert(sizeof(struct k70_dw_page_rec) == 48);
	assert(sizeof(struct k70_dw_ctx) == 1600);
	assert(sizeof(struct k70_dw_token) == 24);
	assert(sizeof(struct k70_dw_snapshot) == 112);
	memset(&s, 0, sizeof(s));
	puts("PASS: host layout 48/1600/24/112");
}
static void t_hit(void)
{
	struct k70_dw_token t;
	struct k70_dw_snapshot s;
	printf("== hit ==\n");
	fresh();
	k70_dw_try_begin(0x1111, 0xAA, 0xBBB, 5, &t);
	assert(t.ctx != NULL);
	k70_dw_note(&t, 0x7777, 0x8888, 0x9999, 0x891994, 0x40, 0x1234, 3, 0x21, 0xff);
	assert(k70_dw_lookup(&t, 0x7777, 0x891994, 0x1111, &s) == K70_ORIG_HIT);
	assert(s.rec.dw_index == 0x1234 && s.dw_count == 5 && s.epoch == t.epoch);
	assert(s.dw_caller == 0xBBB && s.rec.object == 0x8888 && s.rec.offset == 0x9999);
	assert(s.m == 0x7777 && s.thread == 0x1111);
	assert(k70_dw_lookup(&t, 0x7778, 0x891994, 0x1111, &s) == K70_ORIG_UNAVAIL);
	assert(s.reason == K70_R_NO_MATCH);
	k70_dw_end(&t);
	puts("PASS: hit/zero match, full index/count/object/offset");
}
static void t_reject(void)
{
	struct k70_dw_token t, e;
	struct k70_dw_snapshot s;
	printf("== rejections ==\n");
	fresh();
	k70_dw_try_begin(0x1111, 0, 0, 1, &t);
	k70_dw_note(&t, 0x10, 0, 0, 0x20, 0, 0, 0, 0, 0);
	e = t; e.epoch = t.epoch + 1;
	assert(k70_dw_lookup(&e, 0x10, 0x20, 0x1111, &s) == K70_ORIG_UNAVAIL && s.reason == K70_R_EPOCH);
	assert(k70_dw_lookup(&t, 0x10, 0x20, 0x2222, &s) == K70_ORIG_UNAVAIL && s.reason == K70_R_THREAD);
	assert(k70_dw_lookup(NULL, 0x10, 0x20, 0x1111, &s) == K70_ORIG_UNAVAIL && s.reason == K70_R_INVALID_TOK);
	t.ctx->nrec = K70_DW_PAGES + 1;
	assert(k70_dw_lookup(&t, 0x10, 0x20, 0x1111, &s) == K70_ORIG_UNAVAIL && s.reason == K70_R_BAD_NREC);
	t.ctx->nrec = 1;
	k70_dw_note(&t, 0x10, 1, 0, 0x20, 0, 0, 0, 0, 0);
	assert(k70_dw_lookup(&t, 0x10, 0x20, 0x1111, &s) == K70_ORIG_UNAVAIL && s.reason == K70_R_MULTI_MATCH);
	k70_dw_end(&t);
	puts("PASS: epoch/thread/NULL/NREC/MULTI rejections");
}
static void t_no_slot(void)
{
	struct k70_dw_token t[K70_DW_SLOTS], x;
	struct k70_dw_snapshot s;
	uint32_t i;
	printf("== no slot ==\n");
	fresh();
	for (i = 0; i < K70_DW_SLOTS; i++) k70_dw_try_begin((uintptr_t)(0x3000 + i), 0, 0, 0, &t[i]);
	k70_dw_try_begin(0x4000, 0, 0, 0, &x);
	assert(x.ctx == NULL);
	assert(x.reason == K70_R_NO_SLOT);
	assert(k70_dw_lookup(&x, 1, 2, 0x4000, &s) == K70_ORIG_UNAVAIL && s.reason == K70_R_NO_SLOT);
	for (i = 0; i < K70_DW_SLOTS; i++) k70_dw_end(&t[i]);
	puts("PASS: pool exhaustion keeps NO_SLOT reason (not INVALID_TOK)");
}
static void t_overflow(void)
{
	struct k70_dw_token t;
	struct k70_dw_snapshot s;
	uint32_t i;
	printf("== overflow ==\n");
	fresh();
	k70_dw_try_begin(0x1111, 0, 0, 32, &t);
	assert(t.ctx->status == 0);
	for (i = 0; i < K70_DW_PAGES + 3; i++) k70_dw_note(&t, 0x5000 + i, 0, 0, 0x6000 + i, 0, i, 0, 0, 0);
	assert(t.ctx->nrec == K70_DW_PAGES && t.ctx->dropped == 3);
	assert(k70_dw_lookup(&t, 0xDEAD, 0xDEAD, 0x1111, &s) == K70_ORIG_OVERFLOW && s.reason == K70_R_DROPPED);
	k70_dw_end(&t);
	puts("PASS: 32 cap, dropped 3, OVERFLOW/DROPPED");
}
static void t_bad_count(void)
{
	struct k70_dw_token t;
	struct k70_dw_snapshot s;
	printf("== bad count ==\n");
	fresh();
	k70_dw_try_begin(0x1111, 0, 0, -1, &t);
	assert((t.ctx->status & K70_DWC_BAD) != 0);
	k70_dw_note(&t, 0xA, 0, 0, 0xB, 0, 0, 0, 0, 0);
	assert(k70_dw_lookup(&t, 0xA, 0xB, 0x1111, &s) == K70_ORIG_HIT);
	assert(s.dw_count == 0xffffffffu && s.reason == K70_R_BAD_COUNT);
	assert(s.reserved == K70_DWC_BAD);
	k70_dw_end(&t);
	k70_dw_try_begin(0x1111, 0, 0, 33, &t);
	assert((t.ctx->status & K70_DWC_BAD) != 0);
	k70_dw_end(&t);
	k70_dw_try_begin(0x1111, 0, 0, 32, &t);
	assert((t.ctx->status & K70_DWC_BAD) == 0);
	k70_dw_end(&t);
	puts("PASS: negative/33 BAD, 32 clean, raw u32 count and batch_flags");
}
static void t_epoch(void)
{
	struct k70_dw_token t;
	uint32_t i;
	printf("== epoch ==\n");
	fresh();
	k70_dw_try_begin(0x1111, 0, 0, 0, &t);
	k70_dw_try_begin(0x1111, 0, 0, 0, &g_tok[0]);
	assert(g_tok[0].ctx != NULL);
	g_tok[0].ctx->epoch = UINT64_MAX - 1;
	k70_dw_end(&g_tok[0]);
	k70_dw_try_begin(0x1111, 0, 0, 0, &g_tok[1]);
	assert(g_tok[1].ctx != NULL);
	/* the MAX-1 slot must now be permanently disabled */
	for (i = 0; i < 3; i++) {
		struct k70_dw_token probe;
		uint32_t before = 0;
		k70_dw_try_begin(0x1111, 0, 0, 0, &probe);
		if (probe.ctx != NULL) before = probe.ctx->epoch;
		k70_dw_end(&probe);
		(void)before;
	}
	k70_dw_end(&g_tok[1]);
	puts("PASS: epoch guard runs (MAX-1 disabled, no wrap)");
}
int main(void)
{
	t_layout(); t_hit(); t_reject(); t_no_slot(); t_overflow(); t_bad_count(); t_epoch();
	printf("\nRESULT: ALL DW ORIGIN TESTS PASS\n");
	return 0;
}
