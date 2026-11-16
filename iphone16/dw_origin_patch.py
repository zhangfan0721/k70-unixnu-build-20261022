"""Install the v2.1a explicit-token DW page origin recorder into a build copy."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def _replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError("DW origin anchor changed: " + before[:90])
    return text.replace(before, after, 1)


WRAPPERS = (
    "\n__attribute__((noinline)) void\n"
    "vm_page_free_list(vm_page_t freeq, boolean_t prepare_object)\n"
    "{\n"
    "\tk70_free_list_impl(freeq, prepare_object,\n"
    "\t    (uintptr_t)__builtin_return_address(0), NULL);\n"
    "}\n"
    "\n"
    "__attribute__((noinline)) void\n"
    "k70_vm_page_free_list_origin(vm_page_t freeq, boolean_t prepare_object,\n"
    "    struct k70_dw_token *tok)\n"
    "{\n"
    "\tk70_free_list_impl(freeq, prepare_object,\n"
    "\t    (uintptr_t)__builtin_return_address(0), tok);\n"
    "}\n"
)

DIAG_WRAPPER = (
    "__attribute__((noinline)) void\nk70_pmap_assert_free_from_list_diag(uint32_t ppnum, uintptr_t free_caller,\n"
    "    const struct k70_dw_snapshot *snap)\n{\n"
    "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0),\n"
    "\t    free_caller, snap);\n}\n"
)


def install(root):
    for name in ("K70DwOrigin.h",):
        shutil.copy2(HERE / name, root / "pexpert/arm" / name)
        shutil.copy2(HERE / name, root / "osfmk/kern" / name)
    shutil.copy2(HERE / "K70DwOrigin.c", root / "pexpert/arm" / "K70DwOrigin.c")
    mk = root / "osfmk/kern/Makefile"
    mtext = mk.read_text()
    if "K70DwOrigin.h" not in mtext:
        mtext = _replace(mtext, "\tK70Flight.h \\\n",
                         "\tK70Flight.h \\\n\tK70DwOrigin.h \\\n")
        mk.write_text(mtext)

    path = root / "pexpert/arm/k70_formal_diag.c"
    text = path.read_text()
    text = _replace(text, '#include "K70FlightKernel.c"\n',
                    '#include "K70FlightKernel.c"\n#include "K70DwOrigin.c"\n')
    path.write_text(text)

    path = root / "osfmk/vm/vm_resident.c"
    text = path.read_text()
    text = _replace(text, "#include <kern/K70Flight.h>\n",
                    "#include <kern/K70Flight.h>\n#include <kern/K70DwOrigin.h>\n#include <kern/thread.h>\n")
    text = _replace(
        text,
        "\nvoid\nvm_page_free_list(\n\tvm_page_t       freeq,\n\tboolean_t       prepare_object)\n{",
        "\nstatic __attribute__((noinline)) void\nk70_free_list_impl(\n"
        "\tvm_page_t       freeq,\n\tboolean_t       prepare_object,\n"
        "\tuintptr_t       k70_free_caller,\n\tstruct k70_dw_token *k70_tok)\n{")
    text = _replace(
        text,
        "#if MACH_ASSERT\n"
        "\t\t\t\tk70_pmap_assert_free_from_list(VM_PAGE_GET_PHYS_PAGE(mem),\n"
        "\t\t\t\t    (uintptr_t)__builtin_return_address(0));\n"
        "#endif\n",
        "#if MACH_ASSERT\n"
        "\t\t\t\t{\n"
        "\t\t\t\t\tstruct k70_dw_snapshot k70_dw_snap;\n"
        "\t\t\t\t\t(void)k70_dw_lookup(k70_tok, (uintptr_t)mem,\n"
        "\t\t\t\t\t    VM_PAGE_GET_PHYS_PAGE(mem), (uintptr_t)current_thread(), &k70_dw_snap);\n"
        "\t\t\t\t\tk70_pmap_assert_free_from_list_diag(VM_PAGE_GET_PHYS_PAGE(mem),\n"
        "\t\t\t\t\t    k70_free_caller, &k70_dw_snap);\n"
        "\t\t\t\t}\n"
        "#endif\n")
    text = _replace(text, "\nvoid\nvm_page_do_delayed_work(",
                    "\n__attribute__((noinline)) void\nvm_page_do_delayed_work(")
    marker = "\n__attribute__((noinline)) void\nvm_page_do_delayed_work("
    pos = text.index(marker)
    text = text[:pos] + WRAPPERS + text[pos:]
    text = _replace(
        text,
        "\tvm_page_t       local_free_q = VM_PAGE_NULL;\n",
        "\tvm_page_t       local_free_q = VM_PAGE_NULL;\n"
        "\tstruct k70_dw_token k70_dw_tok;\n"
        "\n"
        "\tk70_dw_try_begin((uintptr_t)current_thread(), (uintptr_t)object,\n"
        "\t    (uintptr_t)__builtin_return_address(0), dw_count, &k70_dw_tok);\n")
    text = _replace(
        text,
        "\t\tif (dwp->dw_mask & DW_vm_page_free) {\n"
        "\t\t\tvm_page_free_prepare_queues(m);\n",
        "\t\tif (dwp->dw_mask & DW_vm_page_free) {\n"
        "\t\t\tk70_dw_note(&k70_dw_tok, (uintptr_t)m,\n"
        "\t\t\t    (uintptr_t)VM_PAGE_OBJECT(m), (uint64_t)m->vmp_offset,\n"
        "\t\t\t    VM_PAGE_GET_PHYS_PAGE(m), dwp->dw_mask, (uint32_t)j,\n"
        "\t\t\t    m->vmp_wire_count,\n"
        "\t\t\t    (uint32_t)((m->vmp_busy ? K70_DW_PF_BUSY : 0) |\n"
        "\t\t\t        (m->vmp_fictitious ? K70_DW_PF_FICTITIOUS : 0) |\n"
        "\t\t\t        (m->vmp_dirty ? K70_DW_PF_DIRTY : 0) |\n"
        "\t\t\t        (m->vmp_pmapped ? K70_DW_PF_PMAPPED : 0) |\n"
        "\t\t\t        (m->vmp_wpmapped ? K70_DW_PF_WPMAPPED : 0) |\n"
        "\t\t\t        (m->vmp_wire_count != 0 ? K70_DW_PF_WIRED : 0) |\n"
        "\t\t\t        (m->vmp_lopage ? K70_DW_PF_LOPAGE : 0) |\n"
        "\t\t\t        (m->vmp_private ? K70_DW_PF_PRIVATE : 0)),\n"
        "\t\t\t    K70_DW_PF_KNOWN);\n"
        "\t\t\tvm_page_free_prepare_queues(m);\n")
    text = _replace(
        text,
        "\tif (local_free_q) {\n\t\tvm_page_free_list(local_free_q, TRUE);\n\t}\n",
        "\tif (local_free_q) {\n"
        "\t\tk70_vm_page_free_list_origin(local_free_q, TRUE, &k70_dw_tok);\n"
        "\t}\n"
        "\tk70_dw_end(&k70_dw_tok);\n")
    path.write_text(text)

    # v3: record the UPL abort context so the panel can name the abort path.
    # v4: bind the abort context to the physical page the abort is handing to
    # delayed work, so a later lookup by PPN returns this page's abort.
    path = root / 'osfmk/vm/vm_pageout.c'
    text = path.read_text()
    _sig = '\nupl_abort_range(\n'
    assert text.count(_sig) == 1
    _start = text.index(_sig)
    _next = text.index('\nupl_abort(', _start + len(_sig))
    _add = 'VM_PAGE_ADD_DELAYED_WORK(dwp, m, dw_count);'
    assert text.count(_add, _start, _next) == 1
    _at = text.index(_add, _start)
    _inject = ('\t\t\t\t{ extern void k70_abort_page_note(uint32_t, uint32_t, uint32_t, uint32_t, uintptr_t);\n'
               '\t\t\t\t  /* Only pages actually being freed can reach the assertion, so\n'
               '\t\t\t\t   * recording only those keeps the ring from being flushed by a\n'
               '\t\t\t\t   * batch that merely clears busy or wakes pages up. */\n'
               '\t\t\t\t  if (dwp->dw_mask & DW_vm_page_free) {\n'
               '\t\t\t\t  uint32_t _k70_f = 0;\n'
               '\t\t\t\t  if (m->vmp_absent) { _k70_f |= 1u; }\n'
               '\t\t\t\t  if (m->vmp_clustered) { _k70_f |= 2u; }\n'
               '\t\t\t\t  if (m->vmp_busy) { _k70_f |= 4u; }\n'
               '\t\t\t\t  if (m->vmp_wire_count != 0) { _k70_f |= 8u; }\n'
               '\t\t\t\t  k70_abort_page_note((uint32_t)VM_PAGE_GET_PHYS_PAGE(m), (uint32_t)error,\n'
               '\t\t\t\t      _k70_f, (uint32_t)dwp->dw_mask,\n'
               '\t\t\t\t      (uintptr_t)__builtin_return_address(0)); }\n'
               '\t\t\t\t  }\n'
               '\t\t\t\t')
    path.write_text(text[:_at] + _inject + text[_at:])

    # v5: name the UBC caller that asked for the abort. ubc_upl_abort_range sits
    # directly above upl_abort_range on the stack, so recording its return address
    # before the nested call is enough for the per-page note to pick it up.
    path = root / 'bsd/kern/ubc_subr.c'
    text = path.read_text()
    _sig = '\nubc_upl_abort_range(\n'
    assert text.count(_sig) == 1
    _start = text.index(_sig)
    _brace = text.index('\n{\n', _start) + len('\n{\n')
    _inject = ('\t{ extern void k70_abort_ubc_note(uintptr_t);\n'
               '\t  k70_abort_ubc_note((uintptr_t)__builtin_return_address(0)); }\n')
    path.write_text(text[:_brace] + _inject + text[_brace:])
    # v10: record every synchronous exception at the single entry point, so a
    # user-classified fault cannot hide from the samples the way it did before.
    path = root / 'osfmk/arm64/sleh.c'
    text = path.read_text()
    _sig = '\nsleh_synchronous(arm_context_t *context, uint32_t esr, vm_offset_t far)\n{'
    assert text.count(_sig) == 1
    _pos = text.index(_sig) + len(_sig)
    _inject = ('\n\t{ extern void k70_kabort_note(uint64_t, uint64_t, uint64_t, uint64_t);\n'
               '\t  k70_kabort_note((uint64_t)esr, (uint64_t)far,\n'
               '\t      (uint64_t)get_saved_state_pc(&context->ss),\n'
               '\t      (uint64_t)get_saved_state_cpsr(&context->ss)); }\n')
    path.write_text(text[:_pos] + _inject + text[_pos:])
    # v35: capture the reason and the saved state of the fatal kernel abort.
    _pwx = '\npanic_with_thread_kernel_state(const char *msg, arm_saved_state_t *ss)\n{\n'
    assert text.count(_pwx) == 1
    text = text.replace(_pwx,
        _pwx + '\t{ extern void k70_pex_note(const char *, uint64_t, uint64_t);\n'
        '\t  if (is_saved_state64(ss)) {\n'
        '\t      arm_saved_state64_t *s64 = saved_state64(ss);\n'
        '\t      k70_pex_note(msg, (uint64_t)s64->pc, (uint64_t)s64->lr);\n'
        '\t  } }\n')
    path.write_text(text)
    # v10: verify_write calls _bcopyout with PAN still set, so a DEBUG guard-page
    # check can never see EFAULT and retries the store forever. Clear and restore
    # PAN around the copy, exactly like copyout() does.
    # v12: a copy that takes a fault can block inside the fault handler; when it
    # resumes, PSTATE comes from the saved state and PAN is set again, so the very
    # next store faults on permission instead of making progress. Hand the copy
    # back with PAN clear, which is what user_access_enable did before the fault.
    path = root / 'osfmk/arm64/sleh.c'
    text = path.read_text()
    _anchor = '\tbool recover = find_copyio_recovery_entry(state) != 0;'
    assert text.count(_anchor) == 1
    _add = (_anchor + '\n'
            '\tif (recover) {\n'
            '\t\tsaved_state64(state)->cpsr = saved_state64(state)->cpsr & ~(1ULL << 22);\n'
            '\t}')
    path.write_text(text.replace(_anchor, _add))
    # v13/v14: record where ml_set_max_cpus stops, and skip its mutex when early
    # boot calls it with preemption disabled (the debug kernel panics otherwise).
    path = root / 'osfmk/arm/machine_routines_common.c'
    text = path.read_text()
    _sig = '\nml_set_max_cpus(unsigned int max_cpus __unused)\n{\n'
    assert text.count(_sig) == 1
    _head = ('\nml_set_max_cpus(unsigned int max_cpus __unused)\n{\n'
             '\t{ extern volatile uint32_t k70_max_cpus_phase; k70_max_cpus_phase = 1; }\n'
             '\tif (get_preemption_level() > 0) {\n'
             '\t\tmax_cpus_initialized = MAX_CPUS_SET;\n'
             '\t\t{ extern volatile uint32_t k70_max_cpus_phase; k70_max_cpus_phase = 3; }\n'
             '\t\treturn;\n'
             '\t}\n')
    text = text.replace(_sig, _head)
    _lock = '\tlck_mtx_lock(&max_cpus_lock);\n\tif (max_cpus_initialized != MAX_CPUS_SET) {'
    assert text.count(_lock) == 1
    text = text.replace(_lock,
        '\tlck_mtx_lock(&max_cpus_lock);\n'
        '\t{ extern volatile uint32_t k70_max_cpus_phase; k70_max_cpus_phase = 2; }\n'
        '\tif (max_cpus_initialized != MAX_CPUS_SET) {')
    path.write_text(text)
    path = root / 'osfmk/arm64/copyio.c'
    text = path.read_text()
    _old = ('\tint rc;\n'
            '\tdisable_preemption();\n'
            '\trc = _bcopyout((const char*)source, (char*)dst, size);\n'
            '\tenable_preemption();\n'
            '\treturn rc;\n')
    assert text.count(_old) == 1
    _new = ('\tint rc;\n'
            '\tuint64_t k70_pan;\n'
            '\tdisable_preemption();\n'
            '\t__asm__ volatile("mrs %0, pan" : "=r"(k70_pan) :: "memory");\n'
            '\tif (k70_pan) { __asm__ volatile("msr pan, #0" ::: "memory"); }\n'
            '\trc = _bcopyout((const char*)source, (char*)dst, size);\n'
            '\tif (k70_pan) { __asm__ volatile("msr pan, #1" ::: "memory"); }\n'
            '\tenable_preemption();\n'
            '\treturn rc;\n')
    path.write_text(text.replace(_old, _new))
    path = root / "osfmk/arm/pmap/pmap.c"
    text = path.read_text()
    text = _replace(text, "#include <kern/K70Flight.h>\n",
                    "#include <kern/K70Flight.h>\n#include <kern/K70DwOrigin.h>\n")
    text = _replace(
        text,
        "pmap_assert_free_recorded(ppnum_t ppnum, uintptr_t caller, uintptr_t free_caller)\n{",
        "pmap_assert_free_recorded(ppnum_t ppnum, uintptr_t caller, uintptr_t free_caller,\n"
        "    const struct k70_dw_snapshot *snap)\n{")
    text = _replace(text, "\t\t    free_caller, va_base_field);",
                    "\t\t    free_caller, va_base_field, snap);")
    text = _replace(text,
                    "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0), 0);",
                    "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0), 0, NULL);")
    text = _replace(
        text,
        "void\nk70_pmap_assert_free_from_list(uint32_t ppnum, uintptr_t free_caller)\n{\n"
        "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0), free_caller);\n}\n",
        "void\nk70_pmap_assert_free_from_list(uint32_t ppnum, uintptr_t free_caller)\n{\n"
        "\tpmap_assert_free_recorded(ppnum, (uintptr_t)__builtin_return_address(0),\n"
        "\t    free_caller, NULL);\n}\n\n" + DIAG_WRAPPER)
    path.write_text(text)

def install_diag(root):
    """Runs after userspace_bootstrap, when the copyout rows exist."""
    # v11: the panel paints once, so its rows go stale. Print the two abort
    # samples into the scrolling log from the diagnostics thread instead.
    path = root / 'pexpert/arm/k70_formal_diag.c'
    text = path.read_text()
    if '"K70DwOrigin.h"' not in text:
        text = '#include "K70DwOrigin.h"\n' + text
    # v15: the diagnostics worker prints several lines a second and buries the
    # real boot log. With k70quiet=1 it stays silent so the last console line is
    # the actual place the boot stopped.
    _w = ('static void k70_formal_worker(void *argument, wait_result_t result)\n'
          '{\n'
          '    (void)argument;\n'
          '    (void)result;\n'
          '    for (;;) {\n')
    assert text.count(_w) == 1
    text = text.replace(_w, _w +
        '        { extern int PE_parse_boot_argn(const char *, void *, int);\n'
        '          static int k70_quiet = -1;\n'
        '          if (k70_quiet < 0) {\n'
        '              int qv = 0;\n'
        '              k70_quiet = PE_parse_boot_argn("k70quiet", &qv, sizeof(qv)) ? (qv != 0) : 0;\n'
        '          }\n'
        '          static unsigned k70_qn;\n'
        '          if (k70_quiet) {\n'
        '              k70_qn++;\n'
        '              if ((k70_qn % 40u) != 0u) { delay(100); continue; }\n'
        '          } }\n')
    # v17: remember the last boot stage text so the heartbeat can show where the
    # boot actually stopped, even after the line itself scrolled away.
    # v21: remember the diagnostic worker so its own blocking does not hide the
    # thread that actually matters.
    _wk = '        thread_deallocate(worker);\n'
    assert text.count(_wk) == 1
    text = text.replace(_wk,
        '        { extern void k70_worker_note(uintptr_t); k70_worker_note((uintptr_t)worker); }\n' + _wk)
    # v18: the caller often passes a stack buffer, so copy the text instead of
    # keeping the borrowed pointer, and print the wait snapshot beside it.
    _bps = 'void boot_progress_stage(const char *s) {\n'
    assert text.count(_bps) == 1
    text = text.replace(_bps,
        'void boot_progress_stage(const char *s) {\n'
        '    { extern void k70_stage_text_note(const char *); k70_stage_text_note(s); }\n')
    _hb = '        char line[BP_MAX_COLS + 1];\n        struct bp_out out;\n'
    assert text.count(_hb) == 1
    text = text.replace(_hb,
        '        { extern const char *k70_stage_text_get(void);\n'
        '          extern uint64_t k70_user_fault_count(void);\n'
        '          extern const struct k70_wait_rec *k70_wait_get(void);\n'
        '          const struct k70_wait_rec *wr = k70_wait_get();\n'
        '          char hl[BP_MAX_COLS + 1];\n'
        '          struct bp_out ho;\n'
        '          bp_out_begin(&ho, hl);\n'
        '          { extern const struct k70_role_rec *k70_role_get(uint32_t);\n'
        '            for (uint32_t ri = 1; ri <= 3u; ri++) {\n'
        '              const struct k70_role_rec *rr = k70_role_get(ri);\n'
        '              bp_out_begin(&ho, hl);\n'
        '              bp_out_puts(&ho, "R");\n'
        '              bp_out_dec(&ho, ri);\n'
        '              bp_out_puts(&ho, " N");\n'
        '              bp_out_dec(&ho, (uint32_t)rr->blocks);\n'
        '              bp_out_puts(&ho, " LR ");\n'
        '              bp_out_hex(&ho, rr->lr, 16);\n'
        '              boot_progress_stage(hl);\n'
        '            } }\n'
        '          { extern void k70_trap_get(uint64_t *, uint32_t *, uint64_t *);\n'
        '            uint64_t tc; uint32_t tp; uint64_t tn;\n'
        '            k70_trap_get(&tc, &tp, &tn);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "TRAPS ");\n'
        '            bp_out_dec(&ho, (uint32_t)tc);\n'
        '            bp_out_puts(&ho, " PID ");\n'
        '            bp_out_dec(&ho, tp);\n'
        '            bp_out_puts(&ho, " SC ");\n'
        '            bp_out_hex(&ho, (uint32_t)tn, 8);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern const struct k70_role_rec *k70_role_get(uint32_t);\n'
        '            for (uint32_t ro = 1; ro <= 3u; ro++) {\n'
        '              const struct k70_role_rec *rr2 = k70_role_get(ro);\n'
        '              bp_out_begin(&ho, hl);\n'
        '              bp_out_puts(&ho, "OR");\n'
        '              bp_out_dec(&ho, ro);\n'
        '              bp_out_puts(&ho, " ");\n'
        '              bp_out_hex(&ho, rr2->outer, 16);\n'
        '              boot_progress_stage(hl);\n'
        '            } }\n'
        '          { extern const struct k70_wire_rec *k70_wire_get(void);\n'
        '            const struct k70_wire_rec *wr2 = k70_wire_get();\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "WRE ");\n'
        '            bp_out_hex(&ho, wr2->map, 12);\n'
        '            bp_out_puts(&ho, "/");\n'
        '            bp_out_hex(&ho, wr2->entry, 12);\n'
        '            bp_out_puts(&ho, " K");\n'
        '            bp_out_dec(&ho, (uint32_t)wr2->is_kernel_map);\n'
        '            bp_out_puts(&ho, " T");\n'
        '            bp_out_dec(&ho, (uint32_t)wr2->is_task_map);\n'
        '            boot_progress_stage(hl);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "WRC ");\n'
        '            bp_out_dec(&ho, (uint32_t)wr2->wired);\n'
        '            bp_out_puts(&ho, "/");\n'
        '            bp_out_dec(&ho, (uint32_t)wr2->user_wired);\n'
        '            bp_out_puts(&ho, " T");\n'
        '            bp_out_dec(&ho, (uint32_t)wr2->in_transition);\n'
        '            bp_out_puts(&ho, " N");\n'
        '            bp_out_dec(&ho, (uint32_t)wr2->needs_wakeup);\n'
        '            boot_progress_stage(hl);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "WRL ");\n'
        '            bp_out_hex(&ho, wr2->caller, 16);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern void k70_obj_get(uintptr_t *, int *, int *);\n'
        '            uintptr_t oa; int op, oq;\n'
        '            k70_obj_get(&oa, &op, &oq);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "OBJ ");\n'
        '            bp_out_hex(&ho, oa, 12);\n'
        '            bp_out_puts(&ho, " P");\n'
        '            bp_out_dec(&ho, (uint32_t)op);\n'
        '            bp_out_puts(&ho, " A");\n'
        '            bp_out_dec(&ho, (uint32_t)oq);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern void k70_rws_read(uintptr_t *, uintptr_t *, uint32_t *, uintptr_t *, uint32_t *);\n'
        '            uintptr_t q1, q2, q3; uint32_t q4, q5;\n'
        '            k70_rws_read(&q1, &q2, &q4, &q3, &q5);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "RWS ");\n'
        '            bp_out_hex(&ho, q1, 16);\n'
        '            bp_out_puts(&ho, " E");\n'
        '            bp_out_hex(&ho, q2, 16);\n'
        '            bp_out_puts(&ho, " A");\n'
        '            bp_out_dec(&ho, q4);\n'
        '            boot_progress_stage(hl);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "RWSC ");\n'
        '            bp_out_hex(&ho, q3, 16);\n'
        '            bp_out_puts(&ho, " W");\n'
        '            bp_out_dec(&ho, q5);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern uintptr_t k70_outer_get(void);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "OLR ");\n'
        '            bp_out_hex(&ho, k70_outer_get(), 16);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern void k70_win_get(uint64_t *, uint64_t *, uint64_t *, int *);\n'
        '            uint64_t wc, wo, wl; int wr;\n'
        '            k70_win_get(&wc, &wo, &wl, &wr);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "WIN ");\n'
        '            bp_out_dec(&ho, (uint32_t)wc);\n'
        '            bp_out_puts(&ho, " OFF=");\n'
        '            bp_out_hex(&ho, (uint32_t)(wo >> 12), 8);\n'
        '            bp_out_puts(&ho, " LEN=");\n'
        '            bp_out_dec(&ho, (uint32_t)wl);\n'
        '            bp_out_puts(&ho, " RC=");\n'
        '            bp_out_dec(&ho, (uint32_t)wr);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern uint32_t k70_exec_last(void);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "MK ");\n'
        '            bp_out_dec(&ho, k70_exec_last());\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern uint32_t k70_exec_bits(void);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "EXB ");\n'
        '            bp_out_hex(&ho, k70_exec_bits(), 8);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern void k70_vn_get(uint32_t *, int *, int64_t *);\n'
        '            uint32_t vs; int ve; int64_t vr;\n'
        '            k70_vn_get(&vs, &ve, &vr);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "VN ");\n'
        '            bp_out_dec(&ho, vs);\n'
        '            bp_out_puts(&ho, "/");\n'
        '            bp_out_dec(&ho, (uint32_t)ve);\n'
        '            bp_out_puts(&ho, "/");\n'
        '            bp_out_dec(&ho, (uint32_t)vr);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern volatile int k70_loadmach_ret;\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "LM ");\n'
        '            bp_out_dec(&ho, (uint32_t)k70_loadmach_ret);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern volatile uint32_t k70_exec_errno;\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "EXER ");\n'
        '            bp_out_dec(&ho, k70_exec_errno);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern volatile uint32_t k70_stage;\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "EXST ");\n'
        '            bp_out_dec(&ho, k70_stage);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          { extern uint32_t k70_stage_mask(void);\n'
        '            bp_out_begin(&ho, hl);\n'
        '            bp_out_puts(&ho, "STAGES ");\n'
        '            bp_out_hex(&ho, k70_stage_mask(), 8);\n'
        '            boot_progress_stage(hl);\n'
        '          }\n'
        '          bp_out_puts(&ho, "LAST ");\n'
        '          bp_out_puts(&ho, k70_stage_text_get());\n'
        '          boot_progress_stage(hl);\n'
        '          bp_out_begin(&ho, hl);\n'
        '          bp_out_begin(&ho, hl);\n'
        '          bp_out_puts(&ho, "FAULTS ");\n'
        '          bp_out_dec(&ho, (uint32_t)k70_user_fault_count());\n'
        '          bp_out_puts(&ho, " BLOCKS ");\n'
        '          bp_out_dec(&ho, (uint32_t)wr->count);\n'
        '          boot_progress_stage(hl);\n'
        '          bp_out_begin(&ho, hl);\n'
        '          bp_out_puts(&ho, "WLR ");\n'
        '          bp_out_hex(&ho, wr->lr, 16);\n'
        '          boot_progress_stage(hl);\n'
        '          bp_out_begin(&ho, hl);\n'
        '          bp_out_puts(&ho, "WEV ");\n'
        '          bp_out_hex(&ho, wr->event, 16);\n'
        '          bp_out_puts(&ho, " TH ");\n'
        '          bp_out_hex(&ho, wr->thread, 16);\n'
        '          boot_progress_stage(hl);\n'
        '        }\n' + _hb)
    _anchor = 'uint32_t vm_count = __atomic_load_n(&k70_copyout_vm_done, __ATOMIC_ACQUIRE);'
    assert text.count(_anchor) == 1
    _print = (
        '        {\n'
        '            const struct k70_kabort_rec *ka = k70_kabort_get();\n'
        '            char kal[BP_MAX_COLS + 1];\n'
        '            struct bp_out ko;\n'
        '            bp_out_begin(&ko, kal);\n'
        '            bp_out_puts(&ko, "KA1 E=");\n'
        '            bp_out_hex(&ko, (uint32_t)ka->esr, 8);\n'
        '            bp_out_puts(&ko, " F=");\n'
        '            bp_out_hex(&ko, ka->far, 16);\n'
        '            bp_out_puts(&ko, " C=");\n'
        '            bp_out_hex(&ko, ka->cpsr, 16);\n'
        '            bp_out_puts(&ko, " N=");\n'
        '            bp_out_dec(&ko, ka->count);\n'
        '            boot_progress_stage(kal);\n'
        '            bp_out_begin(&ko, kal);\n'
        '            bp_out_puts(&ko, "KA2 E=");\n'
        '            bp_out_hex(&ko, (uint32_t)ka->esr2, 8);\n'
        '            bp_out_puts(&ko, " F=");\n'
        '            bp_out_hex(&ko, ka->far2, 16);\n'
        '            bp_out_puts(&ko, " C=");\n'
        '            bp_out_hex(&ko, ka->cpsr2, 16);\n'
        '            bp_out_puts(&ko, " P=");\n'
        '            bp_out_hex(&ko, ka->pc2, 16);\n'
        '            bp_out_puts(&ko, " H=");\n'
        '            bp_out_dec(&ko, ka->have2);\n'
        '            boot_progress_stage(kal);\n'
        '            bp_out_begin(&ko, kal);\n'
        '            { extern volatile uint32_t k70_max_cpus_phase;\n'
        '              bp_out_puts(&ko, "MCP ");\n'
        '              bp_out_dec(&ko, k70_max_cpus_phase); }\n'
        '            boot_progress_stage(kal);\n'
        '        }\n')
    # v25: count every userland trap, not just the first of each kind.
    _ut = 'void k70_user_trap(unsigned kind, int pid, uint64_t pc, uint64_t cpsr, uint64_t code)\n{\n'
    assert text.count(_ut) == 1
    text = text.replace(_ut,
        _ut + '    { extern void k70_trap_note(uint32_t, uint64_t);\n'
        '      k70_trap_note((uint32_t)pid, code); }\n')
    path.write_text(text.replace(_anchor, _print + _anchor))
    # v38: mark the steps inside load_machfile so a stall is never anonymous.
    path = root / 'bsd/kern/mach_loader.c'
    text = path.read_text()
    _lm = ('load_machfile(\n'
           '\tstruct image_params     *imgp,\n'
           '\tstruct mach_header      *header,\n'
           '\tthread_t                thread,\n'
           '\tvm_map_t                *mapp,\n'
           '\tload_result_t           *result\n'
           '\t)\n{\n')
    assert text.count(_lm) == 1, text.count(_lm)
    text = text.replace(_lm, _lm +
        '\t{ extern void k70_exec_mark(uint32_t); k70_exec_mark(5); }\n')
    _pm = ('static\nload_return_t\nparse_machfile(\n'
           '\tstruct vnode            *vp,\n'
           '\tvm_map_t                map,\n'
           '\tthread_t                thread,\n')
    assert text.count(_pm) == 1, text.count(_pm)
    _pmend = text.index(_pm) + len(_pm)
    _brace = text.index('\n{\n', _pmend) + len('\n{\n')
    text = text[:_brace] + '\t{ extern void k70_exec_mark(uint32_t); k70_exec_mark(6); }\n' + text[_brace:]
    _gmv = '\tret = get_macho_vnode(name, cputype, header,\n'
    if text.count(_gmv) == 1:
        text = text.replace(_gmv,
            '\t{ extern void k70_exec_mark(uint32_t); k70_exec_mark(7); }\n' + _gmv)
    _cs = '\t\t\t\tret = load_code_signature(\n'
    if text.count(_cs) == 1:
        text = text.replace(_cs,
            '\t\t\t\t{ extern void k70_exec_mark(uint32_t); k70_exec_mark(8); }\n' + _cs)
    path.write_text(text)
    # # v40: who sleeps on which condition while holding an rw lock.
    # path = root / 'osfmk/kern/lock_rw.c'
    # text = path.read_text()
    # _rws = ('lck_rw_sleep(\n'
    #         '\tlck_rw_t                *lck,\n'
    #         '\tlck_sleep_action_t      lck_sleep_action,\n'
    #         '\tevent_t                 event,\n'
    #         '\twait_interrupt_t        interruptible)\n{\n')
    # assert text.count(_rws) == 1, text.count(_rws)
    # text = text.replace(_rws,
    #     _rws + '\t{ extern void k70_rws_note(uintptr_t, uintptr_t, uint32_t, uintptr_t);\n'
    #     '\t  k70_rws_note((uintptr_t)lck, (uintptr_t)event, (uint32_t)lck_sleep_action,\n'
    #     '\t      (uintptr_t)__builtin_return_address(0)); }\n')
    # path.write_text(text)
    # # v41: count returns from the rw sleep, widen the loader marks and record
    # # every window fetch exit, so a probe value cannot be read two ways.
    # _rwt = text  # unused placeholder to keep the block anchored
    # path = root / 'osfmk/kern/lock_rw.c'
    # text = path.read_text()
    # _sig = 'lck_rw_sleep(\n\tlck_rw_t                *lck,\n'
    # assert text.count(_sig) == 1, text.count(_sig)
    # _start = text.index(_sig)
    # _end = _start + 4000
    # body = text[_start:_end]
    # assert body.count('\treturn res;\n') == 2, body.count('\treturn res;\n')
    # body = body.replace('\treturn res;\n',
    #     '\t{ extern void k70_rws_wake(void); k70_rws_wake(); }\n\treturn res;\n')
    # text = text[:_start] + body + text[_end:]
    # path.write_text(text)

    # path = root / 'bsd/kern/mach_loader.c'
    # text = path.read_text()
    # _badd = '\tif (ubc_cs_blob_add(vp,\n'
    # if text.count(_badd) == 1:
    #     text = text.replace(_badd,
    #         '\t{ extern void k70_exec_mark(uint32_t); k70_exec_mark(9); }\n' + _badd)
    # _vnsite = ('\t{\n'
    #            '\t\t{ extern void k70_vn_note(uint32_t, int, int64_t);\n'
    #            '\t\t  if (error) { k70_vn_note(3u, error, (int64_t)resid); } }')
    # if text.count(_vnsite) == 1:
    #     text = text.replace(_vnsite, _vnsite.replace('if (error) {', 'if (error || resid != 0) {'))
    # path.write_text(text)

    # path = root / 'iokit/bsddev/K70UfsWindow.inc'
    # text = path.read_text()
    # _early = '  if (devid != 0 || gWindowState != 1 || !gWindowScratch || !dst || !length) {\n    return EIO;\n  }'
    # if text.count(_early) == 1:
    #     text = text.replace(_early,
    #         '  if (devid != 0 || gWindowState != 1 || !gWindowScratch || !dst || !length) {\n'
    #         '    { k70_win_note(offset, (uint64_t)length, -2); }\n'
    #         '    return EIO;\n  }')
    # _host = '    gWindowState = 2;\n    return EIO;'
    # if text.count(_host) == 1:
    #     text = text.replace(_host,
    #         '    { k70_win_note(offset, (uint64_t)length, -3); }\n' + _host)
    # _ref = '    return EINVAL;                 // a bad request, not a broken device'
    # if text.count(_ref) == 1:
    #     text = text.replace(_ref,
    #         '    { k70_win_note(offset, (uint64_t)length, 1); }\n' + _ref)
    # path.write_text(text)
    # v44: declare the window probe once at file scope with C linkage. A linkage
    # specification is illegal inside a block, and the include lives in an unnamed
    # namespace, so the declaration must sit in this extern "C" block.
    path = root / 'iokit/bsddev/K70UfsTransport.inc'
    text = path.read_text()
    _ec = 'extern "C" {\n'
    assert text.count(_ec) >= 1, text.count(_ec)
    if 'k70_win_note' not in text:
        text = text.replace(_ec,
            _ec + 'void k70_win_note(unsigned long long, unsigned long long, int);\n', 1)
    path.write_text(text)
    # v53: latch the whole entry at the second delete wait, so one hop tells whether
    # this is our own unmap, an IOKit mapping cleanup or a real map teardown.
    path = root / 'osfmk/vm/vm_map.c'
    text = path.read_text()
    _w = '\t\t\t\tentry->needs_wakeup = TRUE;\n'
    assert text.count(_w) >= 1, text.count(_w)
    _note = ('\t\t\t\t{ extern void k70_wire_note(uintptr_t, uintptr_t, uint64_t, uint64_t,\n'
             '\t\t\t\t      int, int, int, int, uintptr_t, int, int);\n'
             '\t\t\t\t  k70_wire_note((uintptr_t)map, (uintptr_t)entry,\n'
             '\t\t\t\t      (uint64_t)entry->vme_start, (uint64_t)entry->vme_end,\n'
             '\t\t\t\t      entry->wired_count, entry->user_wired_count,\n'
             '\t\t\t\t      (int)entry->in_transition, (int)entry->needs_wakeup,\n'
             '\t\t\t\t      (uintptr_t)__builtin_return_address(0),\n'
             '\t\t\t\t      (map == kernel_map) ? 1 : 0,\n'
             '\t\t\t\t      (map == current_task()->map) ? 1 : 0); }\n')
    text = text.replace(_w, _note + _w, 1)
    path.write_text(text)
    # v55: the scratch page this port wires before execve stays wired while the
    # loader halts and terminates the task map, so the delete waits for that one
    # kernel wiring forever. Unwire the page before the final execve call.
    path = root / 'bsd/kern/kern_exec.c'
    text = path.read_text()
    _ex = '\terror = execve(p, &init_exec_args, retval);\n'
    assert text.count(_ex) == 1, text.count(_ex)
    text = text.replace(_ex,
        '\t{ extern kern_return_t vm_map_unwire(vm_map_t, vm_map_offset_t, vm_map_offset_t, boolean_t);\n'
        '\t  vm_map_offset_t _ps = vm_map_page_size(current_map());\n'
        '\t  vm_map_offset_t _sb = (vm_map_offset_t)scratch_addr & ~(vm_map_offset_t)(_ps - 1);\n'
        '\t  (void) vm_map_unwire(current_map(), _sb, _sb + _ps, FALSE); }\n' + _ex)
    path.write_text(text)
    # v56: without AMFI the entitlement vtable is null, and every kext that asks
    # for an entitlement takes a data abort. Answer negatively instead.
    path = root / 'iokit/bsddev/IOKitBSDInit.cpp'
    text = path.read_text()
    for _call in ('queryEntitlementStringWithProc',
                  'queryEntitlementBooleanWithProc',
                  'copyEntitlementAsOSObjectWithProc'):
        _pat = '\tkern_return_t ret = amfi->OSEntitlements.' + _call + '(\n'
        if text.count(_pat) == 1:
            text = text.replace(_pat,
                '\tif (amfi == (void *)0) { return%s; }\n' %
                (' NULL' if _call.startswith('copy') else ' false') + _pat)
    path.write_text(text)
    # v68: the first bad-Mach-O check compares the declared slice size with the vnode
    # data size, so keep both.
    path = root / 'bsd/kern/mach_loader.c'
    text = path.read_text()
    _bb = ('\tif (os_add_overflow(file_offset, macho_size, &total_size) ||\n'
           '\t    total_size > file_size) {\n'
           '\t\treturn LOAD_BADMACHO;\n')
    assert text.count(_bb) == 1, text.count(_bb)
    text = text.replace(_bb,
        '\tif (os_add_overflow(file_offset, macho_size, &total_size) ||\n'
        '\t    total_size > file_size) {\n'
        '\t\t{ extern void k70_lm_bad_note(unsigned long long, unsigned long long);\n'
        '\t\t  k70_lm_bad_note((unsigned long long)macho_size, (unsigned long long)file_size); }\n'
        '\t\treturn LOAD_BADMACHO;\n')
    path.write_text(text)
    # v76: read the loader return before and after the cleanup helpers, so a caller
    # saved register that does not survive them shows up directly.
    _close = chr(9) + '(void) VNOP_CLOSE(vp, FREAD, ctx);' + chr(10)
    assert text.count(_close) == 1, text.count(_close)
    text = text.replace(_close, chr(9) + '{ extern void k70_rc_note(int, int); k70_rc_note(1, error); }' + chr(10) + _close)
    _put = chr(9) + 'vnode_put(vp);' + chr(10) + chr(9) + 'return error;' + chr(10)
    assert text.count(_put) == 1, text.count(_put)
    text = text.replace(_put, chr(9) + 'vnode_put(vp);' + chr(10) +
        chr(9) + '{ extern void k70_rc_note(int, int); k70_rc_note(2, error); }' + chr(10) +
        chr(9) + 'return error;' + chr(10))
    path.write_text(text)
    # v74: name the exact check inside get_macho_vnode that ends the dyld lookup.
    path = root / 'bsd/kern/mach_loader.c'
    text = path.read_text()
    _gm = (
        (1, chr(9) + 'if ((error = namei(ndp)) != 0) {' + chr(10)),
        (3, chr(9) + 'if ((error = vnode_size(vp, &fsize, ctx)) != 0) {' + chr(10)),
        (5, chr(9) + 'if ((error = vnode_authorize(vp, NULL, KAUTH_VNODE_EXECUTE | KAUTH_VNODE_READ_DATA, ctx)) != 0) {' + chr(10)),
        (6, chr(9) + 'if ((error = VNOP_OPEN(vp, FREAD, ctx)) != 0) {' + chr(10)),
    )
    for _site, _mark in _gm:
        assert text.count(_mark) == 1, (_site, text.count(_mark))
        text = text.replace(_mark, _mark +
            chr(9) + '\t{ extern void k70_gmv_note(int, int); k70_gmv_note(%d, error); }' % _site + chr(10))
    _rd = chr(9) + 'if ((error = vn_rdwr(UIO_READ, vp, (caddr_t)header, sizeof(*header), 0,' + chr(10)
    assert text.count(_rd) == 1, text.count(_rd)
    _rd2 = _rd + chr(9) + '    UIO_SYSSPACE, IO_NODELOCKED, kerncred, &resid, p)) != 0) {' + chr(10)
    assert text.count(_rd2) == 1, text.count(_rd2)
    text = text.replace(_rd2, _rd2 +
        chr(9) + '\t{ extern void k70_gmv_note(int, int); k70_gmv_note(7, error); }' + chr(10))
    _fb = (chr(9) * 2 + 'if (error != LOAD_SUCCESS) {' + chr(10) +
            chr(9) * 3 + 'goto bad2;' + chr(10) +
            chr(9) * 2 + '}' + chr(10))
    _id_fat = 10
    _start = 0
    for _k in range(2):
        _pos = text.find(_fb, _start)
        assert _pos >= 0, ('fat block', _k)
        _note = chr(9) * 3 + '{ extern void k70_gmv_note(int, int); k70_gmv_note(%d, error); }' % _id_fat + chr(10)
        text = text[:_pos + len(_fb)] + _note + text[_pos + len(_fb):]
        _start = _pos + len(_fb) + len(_note)
        _id_fat = 11
    _ct = chr(9) + 'if ((cpu_type_t)header->mach_header.cputype != cputype) {' + chr(10)
    assert text.count(_ct) == 1, text.count(_ct)
    text = text.replace(_ct, _ct +
        chr(9) + '\t{ extern void k70_gmv_note(int, int); k70_gmv_note(15, 0); }' + chr(10))
    path.write_text(text)
    # v82: explicit exec checkpoints, each with its own id so a stale value is visible.
    kexec = root / 'bsd/kern/kern_exec.c'
    text = kexec.read_text()
    _entry = (chr(9) + 'char *                  userspace_coredump_name = NULL;' + chr(10))
    assert text.count(_entry) == 1, text.count(_entry)
    text = text.replace(_entry, _entry +
        chr(9) + '{ extern void k70_cp_note(int, int, int);' + chr(10) +
        chr(9) + '  extern void k70_formal_cpu_trace(const char *, uint64_t);' + chr(10) +
        chr(9) + '  k70_cp_note(1, (int)imgp->ip_flags, 0);' + chr(10) +
        chr(9) + '  k70_formal_cpu_trace("CP1 exec_mach_imgact flags", (uint64_t)imgp->ip_flags); }' + chr(10))
    _lm = (chr(9) + 'lret = load_machfile(imgp, mach_header, thread, &map, &load_result);' + chr(10))
    assert text.count(_lm) == 1, text.count(_lm)
    text = text.replace(_lm, _lm +
        chr(9) + '{ extern void k70_cp_note(int, int, int);' + chr(10) +
        chr(9) + '  extern void k70_formal_cpu_trace(const char *, uint64_t);' + chr(10) +
        chr(9) + '  k70_cp_note(2, (int)lret, (int)map);' + chr(10) +
        chr(9) + '  k70_formal_cpu_trace("CP2 load_machfile lret", (uint64_t)lret); }' + chr(10))
    _act = (chr(9) + 'lret = activate_exec_state(task, p, thread, &load_result);' + chr(10))
    assert text.count(_act) == 1, text.count(_act)
    text = text.replace(_act, _act +
        chr(9) + '{ extern void k70_cp_note(int, int, int);' + chr(10) +
        chr(9) + '  extern void k70_formal_cpu_trace(const char *, uint64_t);' + chr(10) +
        chr(9) + '  k70_cp_note(4, (int)lret, 0);' + chr(10) +
        chr(9) + '  k70_formal_cpu_trace("CP4 activate_exec_state", (uint64_t)lret); }' + chr(10))
    kexec.write_text(text)

    sysc = root / 'bsd/dev/arm/systemcalls.c'
    text = sysc.read_text()
    _code = (chr(9) + 'code = arm_get_syscall_number(state);' + chr(10))
    assert text.count(_code) == 1, text.count(_code)
    text = text.replace(_code, _code +
        chr(9) + '{ extern void k70_cp_note(int, int, int);' + chr(10) +
        chr(9) + '  static unsigned k70_sc;' + chr(10) +
        chr(9) + '  k70_cp_note(3, (int)code, (int)proc_getpid(proc));' + chr(10) +
        chr(9) + '  if (k70_sc < 8u || (k70_sc % 256u) == 0u) {' + chr(10) +
        chr(9) + '    extern void k70_formal_cpu_trace(const char *, uint64_t);' + chr(10) +
        chr(9) + '    k70_formal_cpu_trace("CP3 syscall code", (uint64_t)code);' + chr(10) +
        chr(9) + '  }' + chr(10) +
        chr(9) + '  k70_sc++; }' + chr(10))
    sysc.write_text(text)

    # v79: integer-only event ring. No user memory is touched, so no copyin faults.
    #   open/openat -> (fd or errno, flags, 'o')
    #   stat/stat64 -> (errno, 0, 's')
    #   mmap        -> (fd, len, 'm')
    #   shared_region_check_np        -> (start_address, 0, 'c')
    #   shared_region_map_and_slide_2 -> (files_count, mappings_count, 'R')
    vfs = root / 'bsd/vfs/vfs_syscalls.c'
    text = vfs.read_text()

    def _wrap(text, old, val_expr, arg_expr, op):
        assert text.count(old) == 1, (op, text.count(old))
        new = (chr(9) + 'int k70_r;' + chr(10) +
               chr(9) + 'k70_r = ' + old.split(chr(9) + 'return ', 1)[1].rstrip(chr(10)) + chr(10) +
               chr(9) + '{ extern void k70_open_note(int, int, int);' + chr(10) +
               chr(9) + '  k70_open_note(' + val_expr + ', ' + arg_expr + ', ' + str(op) + '); }' + chr(10) +
               chr(9) + 'return k70_r;')
        return text.replace(old, new)

    for _arg in ('AT_FDCWD', 'uap->fd'):
        _old = (chr(9) + 'return openat_internal(vfs_context_current(), uap->path, uap->flags,' + chr(10) +
                chr(9) + '           uap->mode, ' + _arg + ', UIO_USERSPACE, retval);' + chr(10))
        text = _wrap(text, _old, 'k70_r', '(int)uap->flags', ord('o'))
    for _flag in ('0', '1'):
        _old = (chr(9) + 'return fstatat_internal(vfs_context_current(), uap->path, uap->ub,' + chr(10) +
                chr(9) + '           0, 0, ' + _flag + ', UIO_USERSPACE, AT_FDCWD, 0);' + chr(10))
        text = _wrap(text, _old, 'k70_r', '0', ord('s'))
    vfs.write_text(text)

    mman = root / 'bsd/kern/kern_mman.c'
    text = mman.read_text()
    _old = (chr(9) + 'int fd = uap->fd;' + chr(10))
    assert text.count(_old) == 1, text.count(_old)
    text = text.replace(_old, _old +
        chr(9) + '{ extern void k70_open_note(int, int, int);' + chr(10) +
        chr(9) + '  k70_open_note((int)uap->fd, (int)uap->len, ' + str(ord('m')) + '); }' + chr(10))
    mman.write_text(text)

    vmunix = root / 'bsd/vm/vm_unix.c'
    text = vmunix.read_text()
    _old = (chr(9) + 'int                     error = 0;' + chr(10) +
            chr(9) + 'kern_return_t           kr;' + chr(10) +
            chr(9) + 'task_t                  task = current_task();' + chr(10))
    assert text.count(_old) == 1, text.count(_old)
    text = text.replace(_old, _old +
        chr(9) + '{ extern void k70_open_note(int, int, int);' + chr(10) +
        chr(9) + '  k70_open_note((int)uap->start_address, 0, ' + str(ord('c')) + '); }' + chr(10))
    _old2 = (chr(9) + 'files_count = uap->files_count;' + chr(10) +
             chr(9) + 'mappings_count = uap->mappings_count;' + chr(10))
    assert text.count(_old2) == 1, text.count(_old2)
    text = text.replace(_old2, _old2 +
        chr(9) + '{ extern void k70_open_note(int, int, int);' + chr(10) +
        chr(9) + '  k70_open_note((int)files_count, (int)mappings_count, ' + str(ord('R')) + '); }' + chr(10))
    vmunix.write_text(text)

    # v76: keep the boot task's stderr text, the only place dyld explains itself.
    path = root / 'bsd/kern/sys_generic.c'
    text = path.read_text()
    _wn = (chr(9) + 'return write_internal(p, uap->fd, uap->cbuf, uap->nbyte, (off_t)-1, 0,' + chr(10) +
           chr(9) + '           NULL, retval);' + chr(10))
    assert text.count(_wn) == 1, text.count(_wn)
    text = text.replace(_wn,
        chr(9) + '{ extern void k70_err_note(const char *, int);' + chr(10) +
        chr(9) + '  if ((uap->fd == 1 || uap->fd == 2) && uap->nbyte > 0) {' + chr(10) +
        chr(9) + '    char kb[96];' + chr(10) +
        chr(9) + '    int kn = (int)uap->nbyte;' + chr(10) +
        chr(9) + '    if (kn > 95) { kn = 95; }' + chr(10) +
        chr(9) + '    if (copyin(uap->cbuf, kb, (size_t)kn) == 0) { k70_err_note(kb, kn); }' + chr(10) +
        chr(9) + '  } }' + chr(10) + _wn)
    path.write_text(text)
    # v71: the dyld lookup and the recursive dyld parse returns, so a failure can be
    # placed before the main image parse instead of being inferred.
    path = root / 'bsd/kern/mach_loader.c'
    text = path.read_text()
    _g = chr(9) + 'ret = get_macho_vnode(name, cputype, header,' + chr(10)
    _g2 = chr(9) + '    &file_offset, &macho_size, macho_data, &vp, imgp);' + chr(10)
    assert text.count(_g + _g2) == 1, text.count(_g + _g2)
    text = text.replace(_g + _g2, _g + _g2 +
        chr(9) + '{ extern void k70_bd_note(int, int, unsigned long long, unsigned long long);' + chr(10) +
        chr(9) + '  k70_bd_note(1, (int)ret, (unsigned long long)file_offset,' + chr(10) +
        chr(9) + '      ((unsigned long long)(unsigned)header->cputype << 32) | (unsigned)header->cpusubtype); }' + chr(10))
    _p = chr(9) + 'ret = parse_machfile(vp, map, thread, header, file_offset,' + chr(10)
    _p2 = chr(9) + '    macho_size, depth, slide, 0, myresult, result, imgp);' + chr(10)
    assert text.count(_p + _p2) == 1, text.count(_p + _p2)
    text = text.replace(_p + _p2, _p + _p2 +
        chr(9) + '{ extern void k70_bd_note(int, int, unsigned long long, unsigned long long);' + chr(10) +
        chr(9) + '  k70_bd_note(2, (int)ret, (unsigned long long)macho_size, (unsigned long long)depth); }' + chr(10))
    path.write_text(text)
    # v70: every loader failure that ends as LOAD_BADMACHO is marked at the point it
    # is produced, whichever variable carries it, across the loader and the fat reader.
    _hdr = root / 'bsd/kern/mach_loader.h'
    _ht = _hdr.read_text()
    if 'k70lm_mark' not in _ht:
        _ht += ('\n#ifndef K70LM_MARK_DEF\n#define K70LM_MARK_DEF\n'
                'extern void k70_lm_site(int);\n'
                '#define k70lm_mark(s, v) (k70_lm_site(s), (v))\n'
                '#endif\n')
        _hdr.write_text(_ht)
    _id = 1
    for _name in ('bsd/kern/mach_loader.c', 'bsd/kern/mach_fat.c'):
        _p = root / _name
        _t = _p.read_text()
        for _pat, _repl in (('return LOAD_BADMACHO;', 'return k70lm_mark(%d, LOAD_BADMACHO);'),
                             ('ret = LOAD_BADMACHO;', 'ret = k70lm_mark(%d, LOAD_BADMACHO);'),
                             ('error = LOAD_BADMACHO;', 'error = k70lm_mark(%d, LOAD_BADMACHO);')):
            _parts = _t.split(_pat)
            if len(_parts) == 1:
                continue
            _out = _parts[0]
            for _tail in _parts[1:]:
                _out += (_repl % _id) + _tail
                _id += 1
            _t = _out
        _p.write_text(_t)
    # v64: keep the raw load_machfile result and the image cpu subtype, the two
    # inputs behind the BAD_MACHO failure reason.
    path = root / 'bsd/kern/kern_exec.c'
    text = path.read_text()
    _ld = chr(9) + 'lret = load_machfile(imgp, mach_header, thread, &map, &load_result);' + chr(10)
    assert text.count(_ld) == 1, text.count(_ld)
    text = text.replace(_ld, _ld +
        chr(9) + '{ extern void k70_load_note(int, unsigned int);' + chr(10) +
        chr(9) + '  k70_load_note((int)lret, (unsigned int)imgp->ip_origcpusubtype); }' + chr(10))
    path.write_text(text)

    # v63: the signature pass after the image activation can kill the boot task
    # without going through the two exec failure exits, so latch that site too.
    path = root / 'bsd/kern/kern_exec.c'
    text = path.read_text()
    _s3 = '\t\t\tpsignal_with_reason(p, SIGKILL, signature_failure_reason);\n'
    assert text.count(_s3) == 1, text.count(_s3)
    text = text.replace(_s3,
        '\t\t\t{ extern void k70_exec_fail_note(int, int, long long, int);\n'
        '\t\t\t  k70_exec_fail_note(3, (int)signature_failure_reason->osr_namespace,\n'
        '\t\t\t      (long long)signature_failure_reason->osr_code, error); }\n' + _s3)
    _s4 = '\t\t\tpsignal_vfork_with_reason(p, proc_task(p), imgp->ip_new_thread,\n'
    assert text.count(_s4) == 1, text.count(_s4)
    text = text.replace(_s4,
        '\t\t\t{ extern void k70_exec_fail_note(int, int, long long, int);\n'
        '\t\t\t  k70_exec_fail_note(4, (int)signature_failure_reason->osr_namespace,\n'
        '\t\t\t      (long long)signature_failure_reason->osr_code, error); }\n' + _s4)
    path.write_text(text)
    # v60: latch the exec failure that ends the boot task, with its site, reason
    # namespace/code and the error the exec returned.
    path = root / 'bsd/kern/kern_exec.c'
    text = path.read_text()
    _f1 = '\t\t\tpsignal_with_reason(current_proc(), SIGKILL, exec_failure_reason);\n'
    _f2 = '\t\tpsignal_with_reason(p, SIGKILL, exec_failure_reason);\n'
    assert text.count(_f1) == 1 and text.count(_f2) == 1, (text.count(_f1), text.count(_f2))
    text = text.replace(_f1,
        '\t\t\t{ extern void k70_exec_fail_note(int, int, long long, int);\n'
        '\t\t\t  k70_exec_fail_note(1, (int)exec_failure_reason->osr_namespace,\n'
        '\t\t\t      (long long)exec_failure_reason->osr_code, error); }\n' + _f1)
    text = text.replace(_f2,
        '\t\t{ extern void k70_exec_fail_note(int, int, long long, int);\n'
        '\t\t  k70_exec_fail_note(2, (int)exec_failure_reason->osr_namespace,\n'
        '\t\t      (long long)exec_failure_reason->osr_code, error); }\n' + _f2)
    path.write_text(text)
    # v57: latch who kills initproc, with the exit-reason namespace/code and the
    # owning code-signing flags, and count code-signing page faults.
    path = root / 'bsd/kern/kern_sig.c'
    text = path.read_text()
    _sig = '\tif (signum == SIGKILL && p == initproc) {\n'
    assert text.count(_sig) == 1, text.count(_sig)
    text = text.replace(_sig,
        _sig +
        '\t\t{ extern void k70_psignal_note(int, int, unsigned long long, unsigned long long,\n'
        '\t\t      unsigned long long, unsigned long long, unsigned long long);\n'
        '\t\t  unsigned long long *raw = (unsigned long long *)((char *)signal_reason + 0x20);\n'
        '\t\t  k70_psignal_note(p->p_pid, signum, (unsigned long long)proc_getcsflags(p),\n'
        '\t\t      (unsigned long long)(uintptr_t)signal_reason,\n'
        '\t\t      signal_reason ? raw[0] : 0, signal_reason ? raw[1] : 0,\n'
        '\t\t      (unsigned long long)(uintptr_t)__builtin_return_address(0)); }\n')
    path.write_text(text)
    path = root / 'bsd/kern/kern_cs.c'
    text = path.read_text()
    _cs = '\tflags = proc_getcsflags(p);\n'
    assert text.count(_cs) >= 1, text.count(_cs)
    text = text.replace(_cs,
        _cs + '\t{ extern void k70_cs_note(int, unsigned long long, unsigned long long);\n'
        '\t  k70_cs_note(proc_getpid(p), vaddr, (unsigned long long)flags); }\n', 1)
    path.write_text(text)
    # v51: record the two counters the object paging wait watches.
    path = root / 'osfmk/vm/vm_object.c'
    text = path.read_text()
    _pw = '\tvm_object_paging_wait(src_object, THREAD_UNINT);\n'
    assert text.count(_pw) >= 1, text.count(_pw)
    text = text.replace(_pw,
        '\t{ extern void k70_obj_note(uintptr_t, int, int);\n'
        '\t  k70_obj_note((uintptr_t)src_object, src_object->paging_in_progress,\n'
        '\t      src_object->activity_in_progress); }\n' + _pw, 1)
    path.write_text(text)
    # v49: the rw sleep now names its own caller, event and lock. The lock file is
    # plain C, so a block scope declaration is legal here.
    path = root / 'osfmk/kern/lock_rw.c'
    text = path.read_text()
    _sig2 = ('lck_rw_sleep(\n'
             '\tlck_rw_t                *lck,\n'
             '\tlck_sleep_action_t      lck_sleep_action,\n'
             '\tevent_t                 event,\n'
             '\twait_interrupt_t        interruptible)\n{\n')
    assert text.count(_sig2) == 1, text.count(_sig2)
    if 'k70_rws_entry' not in text:
        text = text.replace(_sig2, _sig2 +
            '\t{ extern void k70_rws_entry(uintptr_t, uintptr_t, uintptr_t, uint32_t, uintptr_t);\n'
            '\t  k70_rws_entry((uintptr_t)current_thread(), (uintptr_t)lck, (uintptr_t)event,\n'
            '\t      (uint32_t)lck_sleep_action, (uintptr_t)__builtin_return_address(0)); }\n')
        _start2 = text.index(_sig2)
        body2 = text[_start2:_start2 + 4000]
        assert body2.count('\treturn res;\n') == 2, body2.count('\treturn res;\n')
        body2 = body2.replace('\treturn res;\n',
            '\t{ extern void k70_rws_wake(void); k70_rws_wake(); }\n\treturn res;\n')
        text = text[:_start2] + body2 + text[_start2 + 4000:]
    path.write_text(text)
    # v39: record every ram-window fetch, so a read that never completes shows up.
    path = root / 'iokit/bsddev/K70UfsWindow.inc'
    text = path.read_text()
    _sig = 'static int k70WindowFetch (int devid, uint64_t offset, void *dst, size_t length)\n{\n'
    _ok = '  if (served == K70Window::kServed) {\n    return 0;\n  }'
    _poison = '  gWindowState = 2;                // poison: never retry a half-served root\n  return EIO;'
    # The file may already carry the probe when it was synced back from a build,
    # so each injection is skipped once rather than asserted.
    if 'k70_win_note' not in text:
        assert text.count(_sig) == 1, text.count(_sig)
        text = text.replace(_sig, _sig +
            '  {\n'
            '    k70_win_note(offset, (uint64_t)length, -1); }\n')
        assert text.count(_ok) == 1, text.count(_ok)
        text = text.replace(_ok,
            '  if (served == K70Window::kServed) {\n'
            '    { k70_win_note(offset, (uint64_t)length, 0); }\n'
            '    return 0;\n  }')
        assert text.count(_poison) == 1, text.count(_poison)
        text = text.replace(_poison,
            '  { k70_win_note(offset, (uint64_t)length, 9); }\n' + _poison)
    path.write_text(text)
    # v37: this kernel runs without AMFI, so the amfi vtable is null and the
