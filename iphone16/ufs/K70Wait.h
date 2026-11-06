// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
// Local early-UFS pacing only. IODelay may block in this XNU's early-boot
// configuration, preventing its caller from checking an outer deadline.
// No sleep, WFE, interrupt-mask change, scheduler dependency, or MMIO here.
enum class K70WaitCode : uint32_t { Elapsed=0, Frozen=1, Regressed=2, Budget=3 };
struct K70WaitRecord {
    uint64_t start=0,deadline=0,last=0;
    uint32_t spins=0;
    K70WaitCode code=K70WaitCode::Elapsed;
};
static K70WaitRecord gK70Wait;
[[maybe_unused]] static void hostTimebaseTrace() {
#if defined(__aarch64__)
    uint64_t frequency,counter;
    __asm__ volatile("mrs %0, cntfrq_el0\n\tisb\n\tmrs %1, cntvct_el0"
        : "=r"(frequency),"=r"(counter) :: "memory");
    k70_formal_cpu_trace("UFS CNTFRQ",frequency);
    k70_formal_cpu_trace("UFS CNTVCT",counter);
#endif
    k70_formal_cpu_trace("UFS mach time",mach_absolute_time());
}
static bool hostWaitPause(uint32_t microseconds) {
    gK70Wait=K70WaitRecord{};
    clock_interval_to_deadline(microseconds,kMicrosecondScale,&gK70Wait.deadline);
    gK70Wait.start=gK70Wait.last=mach_absolute_time();
    uint32_t stationary=0;
    for(uint32_t n=0;n<0x1000000U;++n) {
        uint64_t current=mach_absolute_time();gK70Wait.spins=n+1;
        if(current<gK70Wait.last) {
            gK70Wait.last=current;gK70Wait.code=K70WaitCode::Regressed;return false;
        }
        if(current>=gK70Wait.deadline) {gK70Wait.last=current;return true;}
        if(current==gK70Wait.last) {
            if(++stationary==4096) {gK70Wait.code=K70WaitCode::Frozen;return false;}
        } else stationary=0;
        gK70Wait.last=current;
#if defined(__aarch64__)
        __asm__ volatile("yield" ::: "memory");
#elif defined(__x86_64__)
        __asm__ volatile("pause" ::: "memory");
#endif
    }
    gK70Wait.code=K70WaitCode::Budget;return false;
}
static void hostWaitTrace(const char *label,const K70WaitRecord &record=gK70Wait) {
    boot_progress_stage(label);
    k70_formal_cpu_trace("UFS wait start",record.start);
    k70_formal_cpu_trace("UFS wait deadline",record.deadline);
    k70_formal_cpu_trace("UFS wait last",record.last);
    k70_formal_cpu_trace("UFS wait code/count",(uint64_t(record.code)<<32)|record.spins);
}
