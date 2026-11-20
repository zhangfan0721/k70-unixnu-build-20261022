# K70 handoff data audit

Host-only candidate generator for the fixed kernel already materialized by
`xnu-preflight`. It produces Apple boot arguments and a minimal Apple Device
Tree; the latter is distinct from the Linux FDT passed into UEFI.

This tool does not build a boot image or communicate with the phone. Its
256 MiB high-address memory window is a proposed allocation, not memory that
has already been acquired. Every report keeps `allocation_verified=false`
and `execution_ready=false`. Never feed these local candidate files directly
to an arbitrary kernel entry function.

The exact Apple XNU `boot.h` blob is compiled as an independent ABI oracle.
The actual pinned Mach-O entry instruction is decoded and checked against
its `__start` and `_start_first_cpu` symbols. These prove layout and a static
branch target, not hardware execution.

Requirements: Python 3, a 64-bit Linux/WSL C compiler, the existing sibling
`xnu-preflight/` sources, and these local pinned inputs:

- Kernel SHA256 `5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8`.
- Apple XNU commit `d8b80295118ef25ac3a784134bcf95cd8e88109f`,
  `pexpert/pexpert/arm64/boot.h` Git blob
  `eab75014f92bb6475bdd4225b6e074ad82652ae5`.

Run with caller-selected local paths:

```sh
python3 xnu-handoff/handoff.py build --kernel /path/to/kernel.macho --out /new/candidate-directory
python3 xnu-handoff/handoff.py verify /new/candidate-directory
python3 xnu-handoff/audit_abi.py --header /path/to/pinned/boot.h --kernel /path/to/kernel.macho --out /new/proof.json
```

Each local build generates a new 64-byte host OS random seed. The seed is not
printed. Candidate binaries containing the seed should stay local; a future
firmware handoff must generate fresh entropy during that boot. Tests alone
use an explicit fixed seed. Verification checks bytes and shape and makes no
claim about entropy quality or hardware readiness.

The minimal ADT describes one Cortex-A510 boot CPU, the observed19.2 MHz
timer, the board GIC ranges and the planned diagnostic window. It declares
no UFS/root disk, secondary CPU start, iPad identity or security-policy
override. Framebuffer fields match the previously observed BGRA GOP.

Before runtime entry, the firmware must allocate and revalidate the whole
window, copy/recheck both data structures, check executable ranges and prove
the cache/MMU/ExitBootServices path with an early observable checkpoint.
The previous preflight allocated only the kernel span and remains unchanged.
