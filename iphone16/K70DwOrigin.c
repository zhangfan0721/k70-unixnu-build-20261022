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
	if (s[0] == 'E' && s[1] == 'X') {
		return 0;
	}
	if (s[0] == 'S' && s[1] == 'T') {
		return 0;
	}
	if (s[0] == 'T' && s[1] == 'R') {
		return 0;
	}
	if (s[0] == 'R' && s[1] >= '1' && s[1] <= '3') {
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
char k70_pex_msg[41];
uint64_t k70_pex_pc, k70_pex_lr;

void
k70_pex_note(const char *msg, uint64_t pc, uint64_t lr)
{
	unsigned i = 0;
	k70_pex_pc = pc;
	k70_pex_lr = lr;
	if (msg == 0) {
		k70_pex_msg[0] = 0;
		return;
	}
	for (unsigned k = 0; k < 40u; k++) {
		char c = msg[k];
		if (c == 0) {
			break;
		}
		k70_pex_msg[i++] = (c >= 32 && c < 127) ? c : '?';
	}
	k70_pex_msg[i] = 0;
}

static struct k70_role_rec k70_role_state[4];
static volatile uint32_t k70_stage_bits;
/* v28: the return value of load_machfile during the PID1 exec. */
volatile int k70_loadmach_ret = -1;
static volatile uint32_t k70_exec_bit_mask;
static volatile uint32_t k70_vn_site;
static volatile int k70_vn_err = -1;
static volatile int64_t k70_vn_resid;

static volatile uint32_t k70_exec_last_bit;
static volatile uint64_t k70_win_count, k70_win_off, k70_win_len;
static volatile int k70_win_rc = -1;
static volatile uintptr_t k70_rws_lck, k70_rws_event, k70_rws_caller;
static volatile uint32_t k70_rws_action;

void
k70_rws_note(uintptr_t lck, uintptr_t event, uint32_t action, uintptr_t caller)
{
	k70_rws_lck = lck;
	k70_rws_event = event;
	k70_rws_action = action;
	k70_rws_caller = caller;
}

static volatile uintptr_t k70_outer_lr;

void
k70_outer_note(uintptr_t thread, uintptr_t lr)
{
	/* v48: keep the caller per role, so one role's blocking cannot overwrite
	 * the one that matters. */
	for (uint32_t i = 1; i <= 3u; i++) {
		volatile struct k70_role_rec *r = &k70_role_state[i];
		if (r->thread == thread && thread != 0) {
			if (lr >= 0xfffffff000000000ull) {
				r->outer = lr;
			}
			return;
		}
	}
}

uintptr_t
k70_outer_get(void)
{
	return k70_outer_lr;
}

static struct k70_wire_rec k70_wire_state;

static volatile int k70_rc_a, k70_rc_b;

void
k70_rc_note(int stage, int rc)
{
	if (stage == 1) {
		k70_rc_a = rc;
	} else {
		k70_rc_b = rc;
	}
}

void
k70_rc_get(int *a, int *b)
{
	*a = k70_rc_a;
	*b = k70_rc_b;
}




static volatile int k70_cp_id_h[4], k70_cp_v1_h[4], k70_cp_v2_h[4];

static volatile unsigned k70_work_seq;
static volatile unsigned k70_log_drop_n;

void
k70_log_drop(void)
{
	k70_log_drop_n++;
}

unsigned
k70_log_drop_get(void)
{
	return k70_log_drop_n;
}

void
k70_work_tick(void)
{
	k70_work_seq++;
}

unsigned
k70_work_seq_get(void)
{
	return k70_work_seq;
}

static volatile unsigned k70_cp_w;
static volatile int k70_cp_n;
static volatile int k70_err_sid, k70_err_sv, k70_err_set;

void
k70_cp_note(int id, int v1, int v2)
{
	k70_cp_w = (k70_cp_w + 1u) & 3u;
	k70_cp_id_h[k70_cp_w] = id;
	k70_cp_v1_h[k70_cp_w] = v1;
	k70_cp_v2_h[k70_cp_w] = v2;
	k70_cp_n++;
	if (!k70_err_set && v1 != 0) {
		k70_err_sid = id;
		k70_err_sv = v1;
		k70_err_set = 1;
	}
}

int
k70_cp_count(void)
{
	return k70_cp_n;
}

int
k70_cp_hist_id(int slot)
{
	return k70_cp_id_h[(k70_cp_w - (unsigned)slot) & 3u];
}

int
k70_cp_hist_v1(int slot)
{
	return k70_cp_v1_h[(k70_cp_w - (unsigned)slot) & 3u];
}

int
k70_cp_hist_v2(int slot)
{
	return k70_cp_v2_h[(k70_cp_w - (unsigned)slot) & 3u];
}

int
k70_err_id(void)
{
	return k70_err_sid;
}

int
k70_err_val(void)
{
	return k70_err_sv;
}

int
k70_cp_last_id(void)
{
	return k70_cp_hist_id(0);
}

int
k70_cp_last_v1(void)
{
	return k70_cp_hist_v1(0);
}

int
k70_cp_last_v2(void)
{
	return k70_cp_hist_v2(0);
}

static volatile int k70_ev_val[8];
static volatile int k70_ev_arg[8];
static volatile int k70_ev_op[8];
static volatile int k70_open_n;
static volatile int k70_open_w;
static volatile int k70_open_total;
static volatile int k70_op_o, k70_op_s, k70_op_m, k70_op_c, k70_op_R;

void
k70_open_note(int val, int arg, int op)
{
	k70_open_total++;
	if (op == 0x6f) { k70_op_o++; }
	else if (op == 0x73) { k70_op_s++; }
	else if (op == 0x6d) { k70_op_m++; }
	else if (op == 0x63) { k70_op_c++; }
	else if (op == 0x52) { k70_op_R++; }
	k70_open_w = (k70_open_w + 1) % 8;
	k70_ev_val[k70_open_w] = val;
	k70_ev_arg[k70_open_w] = arg;
	k70_ev_op[k70_open_w] = op & 0xff;
	if (k70_open_n < 8) {
		k70_open_n++;
	}
}

int
k70_op_count(int which)
{
	switch (which) {
	case 0x6f: return k70_op_o;
	case 0x73: return k70_op_s;
	case 0x6d: return k70_op_m;
	case 0x63: return k70_op_c;
	case 0x52: return k70_op_R;
	}
	return 0;
}

int
k70_open_total_count(void)
{
	return k70_open_total;
}

int
k70_open_count(void)
{
	return k70_open_n;
}

int
k70_open_w_idx(void)
{
	return k70_open_w;
}

int
k70_ev_val_at(int slot)
{
	return k70_ev_val[slot % 8];
}

int
k70_ev_arg_at(int slot)
{
	return k70_ev_arg[slot % 8];
}

int
k70_ev_op_at(int slot)
{
	return k70_ev_op[slot % 8];
}

static volatile char k70_err_buf[160];
static volatile int k70_err_size;

void
k70_err_note(const char *buf, int len)
{
	int i;
	if (len > 159) {
		len = 159;
	}
	for (i = 0; i < len; i++) {
		k70_err_buf[i] = buf[i];
	}
	k70_err_buf[len] = 0;
	k70_err_size = len;
}

int
k70_err_len(void)
{
	return k70_err_size;
}

char
k70_err_at(int i)
{
	if (i < 0 || i >= k70_err_size) {
		return 0;
	}
	return k70_err_buf[i];
}

static volatile int k70_gmv_site, k70_gmv_err;

void
k70_gmv_note(int site, int err)
{
	if (k70_gmv_site == 0) {
		k70_gmv_site = site;
		k70_gmv_err = err;
	}
}

void
k70_gmv_get(int *site, int *err)
{
	*site = k70_gmv_site;
	*err = k70_gmv_err;
}

static volatile int k70_bd_ret[4];
static volatile unsigned long long k70_bd_x[4], k70_bd_y[4];

void
k70_bd_note(int id, int ret, unsigned long long x, unsigned long long y)
{
	if (id > 0 && id < 4) {
		k70_bd_ret[id] = ret;
		k70_bd_x[id] = x;
		k70_bd_y[id] = y;
	}
}

void
k70_bd_get(int id, int *ret, unsigned long long *x, unsigned long long *y)
{
	int i = (id > 0 && id < 4) ? id : 0;
	*ret = k70_bd_ret[i];
	*x = k70_bd_x[i];
	*y = k70_bd_y[i];
}

static volatile unsigned long long k70_lmb_macho, k70_lmb_file;

void
k70_lm_bad_note(unsigned long long macho_size, unsigned long long file_size)
{
	k70_lmb_macho = macho_size;
	k70_lmb_file = file_size;
}

void
k70_lm_bad_get(unsigned long long *macho_size, unsigned long long *file_size)
{
	*macho_size = k70_lmb_macho;
	*file_size = k70_lmb_file;
}

static volatile int k70_lms_site, k70_lms_count;

void
k70_lm_site(int site)
{
	k70_lms_site = site;
	k70_lms_count++;
}

void
k70_lm_site_get(int *site, int *count)
{
	*site = k70_lms_site;
	*count = k70_lms_count;
}

static volatile int k70_ld_lret;
static volatile unsigned int k70_ld_subtype;

void
k70_load_note(int lret, unsigned int subtype)
{
	k70_ld_lret = lret;
	k70_ld_subtype = subtype;
}

void
k70_load_get(int *lret, unsigned int *subtype)
{
	*lret = k70_ld_lret;
	*subtype = k70_ld_subtype;
}

static volatile int k70_act_kr;

void
k70_act_note(int kr)
{
	k70_act_kr = kr;
}

int
k70_act_get(void)
{
	return k70_act_kr;
}

static volatile int k70_xf_site;
static volatile int k70_xf_ns;
static volatile long long k70_xf_code;
static volatile int k70_xf_err;

void
k70_exec_fail_note(int site, int ns, long long code, int err)
{
	if (k70_xf_site == 0) {
		k70_xf_site = site;
		k70_xf_ns = ns;
		k70_xf_code = code;
		k70_xf_err = err;
	}
}

void
k70_exec_fail_get(int *site, int *ns, long long *code, int *err)
{
	*site = k70_xf_site;
	*ns = k70_xf_ns;
	*code = k70_xf_code;
	*err = k70_xf_err;
}

static volatile int k70_ps_pid, k70_ps_sig;
static volatile unsigned long long k70_ps_cs;
static volatile unsigned long long k70_ps_reason, k70_ps_raw0, k70_ps_raw1, k70_ps_caller;
static volatile unsigned int k70_cs_count;
static volatile int k70_cs_pid;
static volatile unsigned long long k70_cs_va, k70_cs_flags;

void
k70_psignal_note(int pid, int signum, unsigned long long csflags, unsigned long long reason,
    unsigned long long raw0, unsigned long long raw1, unsigned long long caller)
{
	if (k70_ps_pid == 0) {
		k70_ps_pid = pid;
		k70_ps_sig = signum;
		k70_ps_cs = csflags;
		k70_ps_reason = reason;
		k70_ps_raw0 = raw0;
		k70_ps_raw1 = raw1;
		k70_ps_caller = caller;
	}
}

void
k70_psignal_get(int *pid, int *signum, unsigned long long *csflags,
    unsigned long long *reason, unsigned long long *raw0, unsigned long long *raw1,
    unsigned long long *caller)
{
	*pid = k70_ps_pid;
	*signum = k70_ps_sig;
	*csflags = k70_ps_cs;
	*reason = k70_ps_reason;
	*raw0 = k70_ps_raw0;
	*raw1 = k70_ps_raw1;
	*caller = k70_ps_caller;
}

void
k70_cs_note(int pid, unsigned long long vaddr, unsigned long long csflags)
{
	k70_cs_count++;
	if (k70_cs_pid == 0) {
		k70_cs_pid = pid;
		k70_cs_va = vaddr;
		k70_cs_flags = csflags;
	}
}

void
k70_cs_get(unsigned int *count, int *pid, unsigned long long *vaddr, unsigned long long *csflags)
{
	*count = k70_cs_count;
	*pid = k70_cs_pid;
	*vaddr = k70_cs_va;
	*csflags = k70_cs_flags;
}

void
k70_wire_note(uintptr_t map, uintptr_t entry, uint64_t start, uint64_t end,
    int wired, int user_wired, int in_transition, int needs_wakeup,
    uintptr_t caller, int is_kernel_map, int is_task_map)
{
	volatile struct k70_wire_rec *w = &k70_wire_state;
	w->map = map;
	w->entry = entry;
	w->start = start;
	w->end = end;
	w->wired = wired;
	w->user_wired = user_wired;
	w->in_transition = in_transition;
	w->needs_wakeup = needs_wakeup;
	w->caller = caller;
	w->is_kernel_map = is_kernel_map;
	w->is_task_map = is_task_map;
}

const struct k70_wire_rec *
k70_wire_get(void)
{
	return &k70_wire_state;
}

static volatile uintptr_t k70_obj_addr;
static volatile int k70_obj_paging, k70_obj_activity;

void
k70_obj_note(uintptr_t object, int paging, int activity)
{
	k70_obj_addr = object;
	k70_obj_paging = paging;
	k70_obj_activity = activity;
}

void
k70_obj_get(uintptr_t *object, int *paging, int *activity)
{
	*object = k70_obj_addr;
	*paging = k70_obj_paging;
	*activity = k70_obj_activity;
}

static volatile uintptr_t k70_rws_lck2, k70_rws_event2, k70_rws_caller2;
static volatile uint32_t k70_rws_action2;
static volatile uint32_t k70_rws_wake_count;

void
k70_rws_entry(uintptr_t thread, uintptr_t lck, uintptr_t event, uint32_t action, uintptr_t caller)
{
	/* v49: only a boot-role thread's wait is interesting here. */
	for (uint32_t i = 1; i <= 3u; i++) {
		if (k70_role_state[i].thread == thread && thread != 0) {
			k70_rws_lck2 = lck;
			k70_rws_event2 = event;
			k70_rws_action2 = action;
			k70_rws_caller2 = caller;
			return;
		}
	}
}

void
k70_rws_read(uintptr_t *lck, uintptr_t *event, uint32_t *action, uintptr_t *caller, uint32_t *wakes)
{
	*lck = k70_rws_lck2;
	*event = k70_rws_event2;
	*action = k70_rws_action2;
	*caller = k70_rws_caller2;
	*wakes = k70_rws_wake_count;
}

void
k70_rws_wake(void)
{
	k70_rws_wake_count = k70_rws_wake_count + 1u;
}

uint32_t
k70_rws_wakes(void)
{
	return k70_rws_wake_count;
}

void
k70_rws_get(uintptr_t *lck, uintptr_t *event, uint32_t *action, uintptr_t *caller)
{
	*lck = k70_rws_lck;
	*event = k70_rws_event;
	*action = k70_rws_action;
	*caller = k70_rws_caller;
}

void
k70_win_note(uint64_t offset, uint64_t length, int rc)
{
	k70_win_off = offset;
	k70_win_len = length;
	k70_win_rc = rc;
	k70_win_count = k70_win_count + 1ull;
}

void
k70_win_get(uint64_t *count, uint64_t *offset, uint64_t *length, int *rc)
{
	*count = k70_win_count;
	*offset = k70_win_off;
	*length = k70_win_len;
	*rc = k70_win_rc;
}

void
k70_exec_mark(uint32_t bit)
{
	if (bit < 32u) {
		k70_exec_bit_mask = k70_exec_bit_mask | (1u << bit);
		k70_exec_last_bit = bit;
	}
}

uint32_t
k70_exec_last(void)
{
	return k70_exec_last_bit;
}

uint32_t
k70_exec_bits(void)
{
	return k70_exec_bit_mask;
}

void
k70_vn_note(uint32_t site, int err, int64_t resid)
{
	if (k70_vn_err >= 0) {
		return;
	}
	k70_vn_site = site;
	k70_vn_err = err;
	k70_vn_resid = resid;
}

void
k70_vn_get(uint32_t *site, int *err, int64_t *resid)
{
	*site = k70_vn_site;
	*err = k70_vn_err;
	*resid = k70_vn_resid;
}
static volatile uint64_t k70_trap_count, k70_trap_number;
static volatile uint32_t k70_trap_pid;

void
k70_trap_note(uint32_t pid, uint64_t number)
{
	k70_trap_pid = pid;
	k70_trap_number = number;
	k70_trap_count = k70_trap_count + 1ull;
}

void
k70_trap_get(uint64_t *count, uint32_t *pid, uint64_t *number)
{
	*count = k70_trap_count;
	*pid = k70_trap_pid;
	*number = k70_trap_number;
}

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
