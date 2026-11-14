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
    path.write_text(text.replace(_anchor, _print + _anchor))
    # v23: tag the three boot threads by role at their entry points.
    path = root / 'osfmk/kern/startup.c'
    text = path.read_text()
    _kb = 'kernel_bootstrap_thread(void)\n{\n'
    assert text.count(_kb) == 1
    text = text.replace(_kb,
        _kb + '\t{ extern void k70_role_note(uint32_t, uintptr_t);\n'
        '\t  k70_role_note(1u, (uintptr_t)current_thread()); }\n')
    path.write_text(text)

    path = root / 'bsd/kern/bsd_init.c'
    text = path.read_text()
    _bs = '\nbsd_init(void)\n{\n'
    assert text.count(_bs) == 1
    text = text.replace(_bs,
        _bs + '\t{ extern void k70_role_note(uint32_t, uintptr_t);\n'
        '\t  k70_role_note(2u, (uintptr_t)current_thread()); }\n')
    _p1 = '\nbsdinit_task(void)\n{\n'
    assert text.count(_p1) == 1
    text = text.replace(_p1,
        _p1 + '\t{ extern void k70_role_note(uint32_t, uintptr_t);\n'
        '\t  k70_role_note(3u, (uintptr_t)current_thread()); }\n')
    path.write_text(text)
