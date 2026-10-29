# K70 first original call and header-read checkpoint (stage13)

This bounded diagnostic executes the original first BL, the pinned arm_set_kernel_tbi callee RET, and the next three caller instructions that read the Mach-O header flags. It intercepts the conditional at VAFFFFFFF0079E5E80 before it executes. No relocation/global writes, later helpers, scheduler, drivers or userland run.

Hardware result2026-10-29: the connected K70 passed after run40862768553,
independent actual-artifact verification and one fresh-seed temporary boot.
The supplied original photo shows eight bands, kind/cause0, liveLR...5E74,
header flags00200001 and check23=1.27 new host tests and171 prior regression
instances are separate from this bounded hardware evidence. Real exception
capture and timer counter/IRQ evidence remain next gates before deeper C.

The actual pinned callee is one RET instruction. Despite its name, it does not configure TBI in this build; TCR must remain22A51A251A. This proves a call/return and header-read boundary, not feature enablement or complete OS boot. The source's conditional implementation and actual four executable bytes are both recorded.

Kernel SHA2565fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8 remains fixed. Patch offsets are3f7290,3f733c,9e1e80 plus16vectorwords. Original76-byte caller prefix,60-byte prologue and4-byte callee are independently hashed before patching. The eighth ROX page8803F2000 joins all existing ownership, rollback and instruction-publication checks. Previous stages remain unchanged.

The original208-byte C frame and124-byte writes are retained. Live LR isFFFFFFF0079E5E74 after BL; the saved original LR remainsFFFFFFF0079E5E34 and is checked against the pre-common snapshot. Existing physical cache-cleanup/emergency fail-closed behavior remains required. Original code writes outside the exact ordered16 callback whitelist are rejected by the model; header reading adds no writes.

Eight color bands remain. Fields00..21 keep their meanings, including new liveLR in09;22 is the loaded header flags00200001,23 is call/header/frame check1.36fields use two18-row columns starting704, pitch38, lastpixel1384; UEFI context starts1440. A stage13 phone photo with kind0 and23=1 is required for hardware PASS. Fastboot OKAY and CI success alone are insufficient.

Bad flags, including bit31, stop in the diagnostic before the original conditional; neither branch can enter relocation. Invalid LR/base/flags, callee/header exceptions, record faults and cache cleanup failures are covered by instruction tests with explicit privileged register/AT/cache models. Such tests do not guarantee recovery from arbitrary higher-EL traps or unavailable instruction fetch.

Build in GitHub Actions, independently verify actual FD/FV/PE/native ELF and zero-seed template, generate a fresh private local OS random seed, and use fastboot boot exactly once. No flashing/erasing. Private images and photos stay local; Power+VolDown returns to FASTBOOT after a halt.

```
python -m unittest discover -s xnu-first-call-checkpoint -v
```

Requires Python3.12, Unicorn2.1.4, LLVM/Clang/LLD and a C compiler; input environment overrides are the same as stage12.
