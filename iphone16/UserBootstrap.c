/* SPDX-License-Identifier: MIT
 * Two bounded observations of actual PID1 traps; no trap or register changes.
 * Included in the existing display adapter translation unit.
 */
void k70_user_trap(unsigned kind, int pid, uint64_t pc, uint64_t cpsr, uint64_t code)
{
    static unsigned seen;
    if (pid != 1 || kind >= 2 || (cpsr & 15) != 0) return;
    unsigned bit = 1u << kind;
    if (__atomic_fetch_or(&seen, bit, __ATOMIC_RELAXED) & bit) return;
    boot_progress_stage(kind ? "PID1 EL0 Mach trap observed" : "PID1 EL0 Unix syscall observed");
    k70_formal_cpu_trace("PID1 EL0 PC", pc);
    k70_formal_cpu_trace("PID1 trap code", code);
}
