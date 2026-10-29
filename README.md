# K70 XNU source build

## Current checkpoint status (2026-10-29)

The K70 passed stage12's original `arm_init` C-prologue hardware checkpoint.
Eight display bands, the expected SP/FP, virtual addresses and frame-check=1
were observed. The original 60-byte prologue established its 208-byte frame
and passed the bounded 124-byte write checks. Execution stopped before the
first helper call; full XNU, drivers, scheduler and iOS userspace have not run.
Stage10 previously established the instrumented virtual entry before any C.
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
remains local. The next research boundary is the first helper call and return.

Stage13's bounded candidate verifies the original empty helper return and the
following header read, stopping before the relocation conditional. Its new
27 host tests are recorded separately from the171 prior regression instances;
hardware evidence is still pending. Before deeper C initialization, the next
quality gates are a controlled real exception with register capture, observed
counter progression, and a separately scoped timer interrupt path. Stage and
test counts are not percentages of OS readiness.

Device tests use temporary `fastboot boot` images. Public checkpoint templates
require a freshly generated private local seed before each boot. Private images,
phone photos, raw phone data and seeds must stay local. Checkpoint progress is
experimental and does not imply a usable operating system.

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
