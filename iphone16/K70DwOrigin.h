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
/* v35: the kernel abort panic passes its reason and saved state here. */
extern char k70_pex_msg[41];
extern uint64_t k70_pex_pc, k70_pex_lr;
void k70_pex_note(const char *msg, uint64_t pc, uint64_t lr);
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
void k70_worker_note(uintptr_t thread);

/* v23: identify the boot threads by role instead of guessing from a block LR. */
#define K70_ROLE_KB        1u
#define K70_ROLE_BSD_INIT  2u
#define K70_ROLE_PID1      3u
struct k70_role_rec {
 uintptr_t thread, lr, event;
 uintptr_t outer;   /* v48: caller one frame above the block site */
 uint64_t hit, blocks;
};
void k70_role_note(uint32_t role, uintptr_t thread);
/* v24: one bit per reached stage, so the last completed span is visible. */
void k70_stage_set(uint32_t bit);
uint32_t k70_stage_mask(void);
/* v25: userland activity, so a launched PID1 can be told apart from a silent one. */
void k70_trap_note(uint32_t pid, uint64_t number);
void k70_trap_get(uint64_t *count, uint32_t *pid, uint64_t *number);
/* v29: exec progress bits and the first failing vn_rdwr of the loader. */
void k70_exec_mark(uint32_t bit);
uint32_t k70_exec_bits(void);
uint32_t k70_exec_last(void);
/* v39: the last ram-window fetch, so a hanging read is visible. */
void k70_win_note(uint64_t offset, uint64_t length, int rc);
/* v40: the condition wait behind an rw sleep. */
void k70_rws_note(uintptr_t lck, uintptr_t event, uint32_t action, uintptr_t caller);
void k70_rws_get(uintptr_t *lck, uintptr_t *event, uint32_t *action, uintptr_t *caller);
void k70_rws_wake(void);
uint32_t k70_rws_wakes(void);
void k70_rws_entry(uintptr_t thread, uintptr_t lck, uintptr_t event, uint32_t action, uintptr_t caller);
/* v51: the two counters an object paging wait actually watches. */
void k70_obj_note(uintptr_t object, int paging, int activity);
/* v53: the entry whose kernel wiring keeps a disappearing map alive. */
struct k70_wire_rec {
 uintptr_t map, entry, caller;
 uint64_t start, end;
 int wired, user_wired, in_transition, needs_wakeup, is_kernel_map, is_task_map;
};
void k70_wire_note(uintptr_t map, uintptr_t entry, uint64_t start, uint64_t end,
    int wired, int user_wired, int in_transition, int needs_wakeup,
    uintptr_t caller, int is_kernel_map, int is_task_map);
const struct k70_wire_rec *k70_wire_get(void);
void k70_obj_get(uintptr_t *object, int *paging, int *activity);
void k70_rws_read(uintptr_t *lck, uintptr_t *event, uint32_t *action, uintptr_t *caller, uint32_t *wakes);
/* v45: the caller one frame above a blocking site, taken from the frame pointer. */
void k70_outer_note(uintptr_t thread, uintptr_t lr);
uintptr_t k70_outer_get(void);
void k70_win_get(uint64_t *count, uint64_t *offset, uint64_t *length, int *rc);
void k70_vn_note(uint32_t site, int err, int64_t resid);
void k70_vn_get(uint32_t *site, int *err, int64_t *resid);
const struct k70_role_rec *k70_role_get(uint32_t role);
const struct k70_wait_rec *k70_wait_get(void);
uint64_t k70_user_fault_count(void);
int k70_abort_page_get(uint32_t ppn, struct k70_abort_rec *out);

/* v76: loader return read before and after the cleanup calls. */
void k70_rc_note(int stage, int rc);
void k70_rc_get(int *a, int *b);

/* v76: userland stderr text from the boot task. */
void k70_open_note(const char *path, int ret);
int k70_open_count(void);
const char *k70_open_path_at(int slot);
int k70_open_ret_at(int slot);

void k70_err_note(const char *buf, int len);
int k70_err_len(void);
char k70_err_at(int i);

/* v74: which check inside get_macho_vnode failed. */
void k70_gmv_note(int site, int err);
void k70_gmv_get(int *site, int *err);

/* v71: loader boundary returns. */
void k70_bd_note(int id, int ret, unsigned long long x, unsigned long long y);
void k70_bd_get(int id, int *ret, unsigned long long *x, unsigned long long *y);

/* v68: sizes behind the first bad-Mach-O check. */
void k70_lm_bad_note(unsigned long long macho_size, unsigned long long file_size);
void k70_lm_bad_get(unsigned long long *macho_size, unsigned long long *file_size);

/* v67: which bad-Mach-O site fired. */
void k70_lm_site(int site);
void k70_lm_site_get(int *site, int *count);

/* v64: raw load_machfile result. */
void k70_load_note(int lret, unsigned int subtype);
void k70_load_get(int *lret, unsigned int *subtype);

/* v61: raw activate_exec_state return. */
void k70_act_note(int kr);
int k70_act_get(void);

/* v60: latched exec failure that kills the boot process. */
void k70_exec_fail_note(int site, int ns, long long code, int err);
void k70_exec_fail_get(int *site, int *ns, long long *code, int *err);

/* v57: initproc signal and code-signing fault provenance. */
void k70_psignal_note(int pid, int signum, unsigned long long csflags, unsigned long long reason,
    unsigned long long raw0, unsigned long long raw1, unsigned long long caller);
void k70_cs_note(int pid, unsigned long long vaddr, unsigned long long csflags);
void k70_psignal_get(int *pid, int *signum, unsigned long long *csflags,
    unsigned long long *reason, unsigned long long *raw0, unsigned long long *raw1,
    unsigned long long *caller);
void k70_cs_get(unsigned int *count, int *pid, unsigned long long *vaddr, unsigned long long *csflags);

void k70_dw_try_begin(uintptr_t thread, uintptr_t input_object, uintptr_t dw_caller,
    int dw_count, struct k70_dw_token *tok);
void k70_dw_note(struct k70_dw_token *tok, uintptr_t m, uintptr_t object,
    uint64_t offset, uint32_t ppn, uint32_t dw_mask, uint32_t dw_index,
    uint32_t wire_count, uint32_t flags, uint32_t flags_known);
void k70_dw_end(struct k70_dw_token *tok);
uint32_t k70_dw_lookup(const struct k70_dw_token *tok, uintptr_t mem, uint32_t ppn,
    uintptr_t thread, struct k70_dw_snapshot *snap);

#endif /* K70_DW_ORIGIN_H */
