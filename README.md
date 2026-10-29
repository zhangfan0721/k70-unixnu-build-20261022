# K70 XNU source build

## Current checkpoint status (2026-10-30)

The K70 passed stage14's controlled real synchronous exception capture.
Local phone evidence shows ESR F2004B14, ELR FFFFFFF0086086C4, vector0,
SP0-to-SP1 switch and verified phase2. The probe halts without ERET, before
the original relocation conditional. Stage13's caller/empty RET and header
read remain preserved. Full XNU, drivers, scheduler and iOS userspace have
not run; counter progression and timer IRQ remain separate next gates.
Stage12 established the C prologue; stage10 established virtual entry.
[Stage10 workflow](.github/workflows/k70-c-entry-checkpoint.yml) runs 131 test
instances, including inherited package tests; its original successful build was
[40802153897](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40802153897).

Six checkpoint workflows now restore the same tested source kernel from
[preserved original public artifacts](pinned-inputs/40518851995/README.md).
The original ZIP and kernel SHA-256 checks remain enforced, without depending
on an expiring Actions artifact download. Preserved bytes do not prove that a
new macOS compilation would reproduce the same bytes.

[Stage12](xnu-c-prologue-checkpoint/README.md) runs every prior checkpoint suite
and the preserved-input checks: all171 test instances and19 build steps passed
in [40846393171](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40846393171).
Actual FD/FV/PE verification preceded one fresh-seed temporary boot. A local
phone photo then established the bounded hardware result; private evidence
remains local. Stage13 subsequently established the first call and return.

[Stage13](xnu-first-call-checkpoint/README.md) passed after actual artifact
verification and one fresh-seed temporary boot. Its27 new host tests and171
prior regression instances all passed in19 steps in
[40862768553](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40862768553).
The hardware photo is local evidence, separate from those counts. Stage14
has since established controlled real exception capture. Before deeper C
initialization, counter progression and a separately scoped timer IRQ remain.
Stage and
test counts are not percentages of OS readiness.

Device tests use temporary `fastboot boot` images. Public checkpoint templates
require a freshly generated private local seed before each boot. Private images,
phone photos, raw phone data and seeds must stay local. Checkpoint progress is
experimental and does not imply a usable operating system.

[Stage14](xnu-exception-checkpoint/README.md) passed a controlled synchronous
`BRK #0x4B14` exception after the same bounded stage13 path. It captures the
syndrome, triggering PC, saved state and SP0-to-SP1 switch, checks the one-shot
contract, and halts without exception return. FAR is displayed as raw data,
not a valid BRK fault address. Its20 new host tests and198 prior regression
instances passed in19 steps in
[40906124944](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40906124944).
Actual26-file FD/FV/PE/ELF/opcode/template verification preceded one fresh-seed
temporary boot. A local3472x4624 original photo established the bounded result;
private image/photos stay local. It does not establish general exception return
or recovery. Counter progression and timer interrupts remain future gates.

## Original source-build baseline

Manual macOS CI for pinned public UniXNU and Redmi K70 source repositories.

The `platform` build passed on 2026-10-22: [run 39801380604](https://github.com/xyyyds0106/k70-unixnu-build-20261022/actions/runs/39801380604),
build commit `ecc325019f99d9491c15893f89c5e3703543b8ae`.
Compilation, real ArmDTPlatform/ArmCpu linking, source-crypto HMAC and symbol
collection, and artifact upload completed successfully on macos-15.

Run **K70 pinned source kernel** in Actions. `platform` builds the source kernel
with real ArmDTPlatform, ArmCpu and architectural timer support; `source` builds
the smaller source-only baseline. Logs, symbols, HMAC evidence and checksums are
retained with the kernel candidate.

This repository contains no phone partition backups, platform seed or user data.
The workflow does not build a complete OS image, run a phone or flash partitions.
Successful compilation does not establish K70 boot, root, display, touch or GPU support.
Separately, the connected K70 reached the UniXNU UEFI menu. That firmware test
does not show this XNU kernel executing.

The workflow pins the device and core source revisions and records the actual
macOS/Xcode/SDK/compiler versions for each run.

Public DriverKit and TrustCache header listings are fetched with the workflow's
read-only GitHub token to avoid the shared runner's anonymous API rate limit.
Their source tags still come from the pinned feeds, and the unchanged upstream
header preparer verifies each downloaded file against its recorded Git blob hash.
The token is not stored in artifacts or added to the source repositories.
