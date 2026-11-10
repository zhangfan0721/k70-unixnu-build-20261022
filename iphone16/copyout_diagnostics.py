"""Mark the first PID 1 copyout on the actual Darwin22 ARM64 path."""

HEADER = '#include <kern/k70_copyout_diag.h>\n'
SCOPE = """volatile uintptr_t k70_copyout_thread;
volatile uint32_t k70_copyout_phase, k70_copyout_abort_phase;
volatile uint32_t k70_copyout_abort_count;
volatile int32_t k70_copyout_validate_rc, k70_copyout_fault_rc;
volatile uint32_t k70_copyout_first_esr, k70_copyout_first_phase;
volatile uint64_t k70_copyout_first_far, k70_copyout_first_pc;
volatile uint64_t k70_copyout_dst, k70_copyout_size;
"""

FIRST_COPY = """	extern volatile int32_t k70_copy_rc;
	extern volatile uint32_t k70_stage;
	bool k70_first_copyout = k70_copy_rc == -1;
	if (k70_first_copyout) {
		k70_copyout_dst = argv0;
		k70_copyout_size = path_length;
		k70_copyout_phase = K70_COPY_ARMED;
		k70_copy_rc = -2;
		k70_stage = 12;
		k70_copyout_thread = (uintptr_t)current_thread();
	}
	error = copyout(path, argv0, path_length);
	if (k70_first_copyout) {
		k70_copyout_thread = 0;
		k70_copy_rc = error;
		k70_stage = 13;
	}"""

# x9-x11 are caller-saved and unused by this leaf. Leave the original
# copy recovery table range and both copy loops intact.
ASM_ENTRY = """	adrp	x9, EXT(k70_copyout_thread)@PAGE
	ldr	x9, [x9, EXT(k70_copyout_thread)@PAGEOFF]
	cbz	x9, Lk70_copyout_access_done
	mrs	x10, TPIDR_EL1
	cmp	x9, x10
	b.ne	Lk70_copyout_access_done
	adrp	x9, EXT(k70_copyout_phase)@PAGE
	ldr	w10, [x9, EXT(k70_copyout_phase)@PAGEOFF]
	cmp	w10, #K70_COPY_DISPATCH
	b.ne	Lk70_copyout_access_done
	mov	w11, #K70_COPY_ACCESS
	str	w11, [x9, EXT(k70_copyout_phase)@PAGEOFF]
Lk70_copyout_access_done:
"""

DISPLAY = """        uint32_t copy_phase = k70_copyout_phase;
        uint32_t abort_phase = k70_copyout_abort_phase;
        bp_out_puts(&out, " X");
        bp_out_dec(&out, copy_phase);
        bp_out_puts(&out, " A");
        bp_out_dec(&out, abort_phase);
        if (copy_phase && (k70_formal_thread_turn % 4u) == 0) {
            char detail[BP_MAX_COLS + 1];
            struct bp_out copy;
            bp_out_begin(&copy, detail);
            bp_out_puts(&copy, "COPY V");
            if (copy_phase >= K70_COPY_VALIDATED && copy_phase <= K70_COPY_KERNEL) {
                bp_out_dec(&copy, (uint32_t)k70_copyout_validate_rc);
            } else {
                bp_out_puts(&copy, "-");
            }
            bp_out_puts(&copy, " DST=");
            bp_out_hex(&copy, k70_copyout_dst, 16);
            bp_out_puts(&copy, " N=");
            bp_out_dec(&copy, k70_copyout_size);
            if (abort_phase == K70_COPY_FAST_RETURNED || abort_phase == K70_COPY_VM_RETURNED) {
                bp_out_puts(&copy, " KR=");
                bp_out_hex(&copy, (uint32_t)k70_copyout_fault_rc, 8);
            }
            boot_progress_stage(detail);
            uint32_t count = __atomic_load_n(&k70_copyout_abort_count, __ATOMIC_ACQUIRE);
            if (count) {
                bp_out_begin(&copy, detail);
                bp_out_puts(&copy, "EX ");
                bp_out_hex(&copy, k70_copyout_first_esr, 8);
                bp_out_puts(&copy, " FAR=");
                bp_out_hex(&copy, k70_copyout_first_far, 16);
                bp_out_puts(&copy, " PC=");
                bp_out_hex(&copy, k70_copyout_first_pc, 16);
                bp_out_puts(&copy, " X");
                bp_out_dec(&copy, k70_copyout_first_phase);
                bp_out_puts(&copy, " #");
                bp_out_dec(&copy, count);
                boot_progress_stage(detail);
            }
        }
"""


def install(root):
    def replace(text, before, after):
        if text.count(before) != 1:
            raise ValueError('Copyout anchor changed: ' + before[:90])
        return text.replace(before, after, 1)

    path = root / 'bsd/kern/kern_exec.c'
    path.write_text(replace(path.read_text(), '#include <kern/boot_progress.h>',
                            HEADER + '#include <kern/boot_progress.h>\n' + SCOPE))

    path = root / 'osfmk/arm64/copyio.c'
    text = path.read_text()
    signature = 'copyout(const void *kernel_addr, user_addr_t user_addr, vm_size_t nbytes)\n{\n'
    start = text.index(signature) + len(signature)
    end = text.index('\n}', start)
    body = text[start:end]
    anchor = '\tint result;\n'
    body = replace(body, anchor, anchor +
                   '\tbool k70_trace = k70_copyout_phase == K70_COPY_ARMED &&\n'
                   '\t    k70_copyout_owned((uintptr_t)current_thread());\n')
    for anchor, indent, phase, before in (
        ('\t\treturn 0;\n', '\t\t', 'EMPTY', True),
        ('\tresult = copy_validate(', '\t', 'VALIDATING', True),
        ('\t    COPYIO_OUT | COPYIO_ALLOW_KERNEL_TO_KERNEL);\n', '\t', 'VALIDATED', False),
        ('\t\treturn copyout_kern(', '\t\t', 'KERNEL', True),
        ('\tresult = _bcopyout(', '\t', 'DISPATCH', True),
        ('\tuser_access_disable();\n', '\t', 'LEAF_RETURNED', True),
    ):
        record = indent + 'if (k70_trace) {\n'
        if phase == 'VALIDATED':
            record += indent + '\tk70_copyout_validate_rc = result;\n'
        record += indent + f'\tk70_copyout_phase = K70_COPY_{phase};\n' + indent + '}\n'
        body = replace(body, anchor, record + anchor if before else anchor + record)
    path.write_text(HEADER + text[:start] + body + text[end:])

    path = root / 'osfmk/arm64/machine_routines_asm.s'
    anchor = 'LEXT(_bcopyout)\n\tARM64_STACK_PROLOG\n\tPUSH_FRAME\n'
    path.write_text(HEADER + replace(path.read_text(), anchor, anchor + ASM_ENTRY))

    path = root / 'osfmk/arm64/sleh.c'
    text = path.read_text()
    anchor = '\tASSERT_CONTEXT_SANITY(context);\n\n\ttask_vtimer_check(thread);'
    text = replace(text, anchor,
                   '\tif (k70_copyout_owned((uintptr_t)thread) &&\n'
                   '\t    !PSR64_IS_USER(get_saved_state_cpsr(state))) {\n'
                   '\t\tk70_copyout_sync(esr, far, get_saved_state_pc(state));\n\t}\n\n' + anchor)
    anchor = '\tbool recover = find_copyio_recovery_entry(state) != 0;'
    text = replace(text, anchor, '\tbool k70_trace = k70_copyout_owned((uintptr_t)thread);\n'
                   '\tif (k70_trace) {\n\t\tk70_copyout_abort_phase = K70_COPY_ABORT;\n\t}\n' + anchor)
    kernel = text.index('\nhandle_kernel_abort(arm_saved_state_t *state,')
    kernel_body = text[kernel:]
    for routine, phase, end in (
        ('arm_fast_fault', 'FAST', 'fault_type, (fault_code == FSC_ACCESS_FLAG_FAULT_L3), FALSE);'),
        ('vm_fault', 'VM', '/* caller_pmap */ NULL, /* caller_pmap_addr */ 0);'),
    ):
        anchor = '\t\t\tresult = ' + routine + '(map'
        kernel_body = replace(kernel_body, anchor,
                              '\t\t\tif (k70_trace) {\n'
                              f'\t\t\t\tk70_copyout_abort_phase = K70_COPY_{phase}_FAULT;\n\t\t\t}}\n' + anchor)
        kernel_body = replace(kernel_body, end, end + '\n'
                              '\t\t\tif (k70_trace) {\n'
                              '\t\t\t\tk70_copyout_fault_rc = result;\n'
                              f'\t\t\t\tk70_copyout_abort_phase = K70_COPY_{phase}_RETURNED;\n\t\t\t}}')
    text = text[:kernel] + kernel_body
    anchor = '\tthread->machine.recover_esr = esr;'
    text = replace(text, anchor,
                   '\tif (k70_copyout_owned((uintptr_t)thread)) {\n'
                   '\t\tk70_copyout_abort_phase = K70_COPY_RECOVER;\n\t}\n' + anchor)
    path.write_text(HEADER + text)

    path = root / 'pexpert/arm/k70_formal_diag.c'
    anchor = '        bp_out_puts(&out, " T");\n        bp_out_dec(&out, (uint32_t)k70_tt_fail);'
    path.write_text(HEADER + replace(path.read_text(), anchor, DISPLAY + anchor))
