# K70 stage16: one bounded virtual timer IRQ

Status: implementation/host checks in progress; **no stage16 hardware result**.
One virtual timer IRQ (INTID27), level deassert before EOI, unchanged interrupted-PC
ERET, continued execution and restoration of changed configuration. Stop before
the original relocation conditional and deeper C initialization.

The pinned kernel SHA256 remains
5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8.
The three interception words,16 vector branches, original76-byte caller/4-byte RET,
208-byte Cframe/124-byte writes,8 RO+X pages and existing bootstrap map remain.
DIAG881608000 and TRANS881604000 each fit4KiB. No XNU MMIO mapping is added.
GIC MMIO setup/restoration runs only in the copied transition while M/C/I are off.

## Runtime gates

GICD17100000, GICR17180000..17380000, virtualPPI27 follow pinned firmware and local
runtimeDTB. At most16 redistributor frames are scanned by MPIDR affinity. Require
bounds/version/awake/noLPI, no active private IRQs and all private/classicSPI/ESPI
enables off; firmware's existing Group1, levelPPI27, priority/PMR, ICC_SRE, ARE
and EOI mode0. No security, affinity, priority, group or wake changes.
Only target27 pending history is drained; it is not replayed. Save disabled timer
CTL writable bits/CVAL, distributor and CPUGroup1 before mutation. RWP polls are
bounded65536. Only GICD_CTLR and target27 W1S/W1C enable/pending MMIO writes occur.

Stack-free IRQ entry holds x0..x2 temporarily in initially-zero TPIDR registers,
proves the owned record's full AT/PAR identity, then saves all31GP to fixed RAM.
SP1 is never written; neither stack is used for saves. Require armed token,
bounded interrupted-PC range, valid SPSR/SP, asserted timer and valid timestamp.
Disable/mask timer before EOIR1, require idle running priority, validate shadows
and cookie, restore full raw SPSR/originalELR/all31GP, then ERET. ESR/FAR are not
used as IRQ proof. The instruction model checks31GP exactly at every permitted
interrupted wait instruction. Hardware continuation checks27 stable GP; four wait
scratch registers may change and are not falsely claimed independently verified.

Waiting has65536-poll and counter-deadline bounds, noWFI/WFE. No IRQ, stopped counter,
wrong ID, bad state, nested/unarmed entry or failed restore can PASS. Reject wrap.
CNTFRQ is firmware metadata, not calibrated time. Cleanup masks IRQs, disables
timer/CPUGroup1, validates/cleans original Cframe and complete record, disablesMCI,
then restores timer/CVAL, target enable/inactive state, distributor and CPU gate.
PASS is painted only after successful configuration readback. Unusable AT/frame/cache
state haltsMCIon after timer/CPU quiesce. HigherEL traps, fetch loss and unusable
physical output may prevent visible diagnostics. This is not general IRQ recovery.

## Visible virtual-timer-irq-v1 record

Eight bands;36 words at rows704..1384;footer1440.
00kind,01detail/vector,02postEL,03SCTLR,04VBAR;
05IAR,06IRQ_ELR,07IRQ_SPSR,08SP0,09LR,0AIRQcount;
0Bfreq,0Cstart,0Dcompare,0EIRQcounter,0Freturnedcounter;
10CTLirq,11CTLdisabled,12EOI,13EOImode,14returnverified;
15/16/17SP1before/IRQ/after,18stableGPmask,19pollsused;
1AGICR,1B/1C/1DGICDoriginal/armed/restored;
1E/1F/20CPUGroup1original/armed/restored;
21configurationrestored,22Cframeverified,23verified.
PASS: kind0/detail0,14/21/22/23=1,IRQcount1,IAR/EOI27.
Absolute samples/registers/photos remain local.

## Cloud proof and temporary boot

Five isolated groups at the same source revision: lightweight103, memory68,
call47,counter20,newIRQ suite. All238 prior test instances run exactly once.
Per-suite full logs/count/status/SHA256/commit are verified before firmware;
failed/skipped/missing/duplicate/tampered evidence blocks build. Firmware does not
rerun suites. Always-run collector preserves group/firmware evidence on failure.
Tool versions, pinned inputs/submodules, QA raster and build logs are retained.

Model/cloud success is not hardware evidence. Verify actual FD/FV/PE/code bytes,
then create one local OS-random seed/private image for exactly one temporary boot.
No partition flash/erase, private seed/image publication, image reuse or automatic
retry. After HALT, hold Power+VolumeDown for FASTBOOT.

Primary pinned sources:
[TimerDxe](https://github.com/microsoft/mu_basecore/blob/cfb93724a06ff86ff5ba971413368a7809ee42a5/ArmPkg/Drivers/TimerDxe/TimerDxe.c),
[GICv3](https://github.com/microsoft/mu_basecore/blob/cfb93724a06ff86ff5ba971413368a7809ee42a5/ArmPkg/Drivers/ArmGicDxe/GicV3/ArmGicV3Dxe.c),
[Arm timer](https://documentation-service.arm.com/static/65fac6957bcc0c1c661b36c0),
[Arm GIC](https://documentation-service.arm.com/static/6012f824773bb020e3de7aad).
