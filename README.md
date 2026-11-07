# K70 XNU source build

Manual macOS CI and the pinned source tree for running iOS 16.7.16 (20H392) on the
Redmi K70 (vermeer, SM8550). The chain is the one described in the UniXNU [boot
chain](https://unixnu.com/zh/concepts/boot-chain): Android bootloader → BootShim and
UEFI firmware → UniXNU → DarwinBoot → patched XNU → IPSW userspace.

- [Documentation](https://unixnu.com/zh/)
- [Porting guide](https://unixnu.com/zh/porting/)
- [Build](https://unixnu.com/zh/building)
- Device repository: [UniXNU-vermeer](https://github.com/mansar1337/UniXNU-vermeer)
- [Integration gate workflow](.github/workflows/k70-iphone16.yml)
- [Latest storage build](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42340630197)
- Original source-build baseline: [run 39801380604](https://github.com/xyyyds0106/k70-unixnu-build-20261022/actions/runs/39801380604), commit `ecc325019f99d9491c15893f89c5e3703543b8ae`

## Prerequisites

Every workflow pins its inputs and records the actual macOS/Xcode/SDK/compiler
versions per run. Nothing is fetched from a moving reference:

| Input | Pin |
| --- | --- |
| XNU | `apple-oss-distributions/xnu@1b191cb58250d0705d8a51287127505aa4bc0789` (xnu-8796.141.3) |
| UniXNU core | `UniXNU/UniXNU@b6ae99c17194e6a18fd819d3148e69fe405e91fc` |
| Device | `mansar1337/UniXNU-vermeer@d4dbb3683023a17bb468b9774f52c87f3060e739` |
| UEFI | `yyx2025/uefi-vermeer@da38b23cc7b3b3716cf7c72c42866bd73c978dd3` |
| UFS transport | `UniXNU/ShengUfs@af785c1777161a62931425c2faaa536ce0bebd5b` |
| Generator | Xcode 15.4 DriverKit-286 `iig`, SHA-256 pinned |

A build needs a macOS 15 runner with Xcode 16.4 and the 75 MB `legacy-iig` tool
cache; a clean checkout alone is not sufficient (see gap 3 below). Private inputs —
phone images, photos, seeds and the original Apple kernelcache — stay local and are
never uploaded.

Nothing in this repository is a usable operating system. Every row below is a
checkpoint with its own scope and its own evidence, and no stage count is a
percentage of OS readiness.

## Bring-up stages (2026-11-07)

The rows follow the [bring-up order](https://unixnu.com/zh/porting/bring-up) the
documentation defines, so every line here has a counterpart there.

| Stage | State | Evidence |
| --- | --- | --- |
| 1. UEFI | ✅ | firmware boots from `fastboot boot`, framebuffer has output, block devices are visible |
| 2. UniXNU | ✅ | menu and `unixnu.toml` parse; the kernel receives the configured command line verbatim |
| 3. Payload | ✅ | `kernel.macho` and its ADT sidecar are read and hash-checked |
| 4. DarwinBoot | ✅ | `DARWINBOOT:` base/entry/framebuffer lines, EL1, kernel entered |
| 5. Kernel entry | ✅ | XNU prints its version, pexpert matches the ADT, GIC and timer run, PID 1 task and thread exist |
| 6. Storage and root volume | 🔧 | the read-only UFS window reads real media and claims `md0`; **there is no root volume on the device yet** |
| 7. Userland | ❌ | `launchd` has never run; the HFS RAM disk carries only the two diagnostic files |

✅ verified on the phone or in CI · 🔧 implemented and partly verified · ❌ not available.

### Stage 6 is the only 🔧

Neither missing piece is a kernel question any more.

The window proves the read path. On 2026-11-07 the phone read the first 512 KiB of
LBA 211008 through the transport and produced
`814fb8a9 37515cf0 cd1b10f0 b6870163 9da6e939 4e679fd4 5164783f` — byte for byte the
hash recorded read-only on 2026-11-03. `mdevadd_fetch(0, …)` then returned a device,
so the window is `md0` and `rd=md0` points at UFS instead of RAM.

What is missing is content and a mounted filesystem:

1. **No iOS root is on the device.** The window can read any authorised extent, but
   the APFS volumes of 20H392 are not on it. Placing them means writing 8002 MiB into
   the 9 GiB gap at LBA 211008, which needs its own authorisation.
2. **The APFS prelink set does not boot yet.** Prelinking the original
   `com.apple.kec.corecrypto` next to the kernel's own source corecrypto runs two
   instances, and the first hardware round ended in `Kernel instruction fetch abort`.
   `k70nocc14=1` now leaves initialisation to the kext; that is under test.

## Gaps before a first boot

1. **No iOS root is staged.** The APFS volumes must be written into the 9 GiB gap at
   LBA 211008 (8002 MiB) before any mount can succeed. A wrong extent does not fail
   loudly; it reads the wrong bytes.
2. **The APFS prelink set is unproven.** Two corecrypto instances collided on the
   first attempt. `k70nocc14=1` is the current answer and it has not yet run.
3. **The IIG toolchain fallback is dead.** The workflow restores `legacy-iig` from a
   `trycloudflare` tunnel that no longer resolves; it works only while the branch
   cache survives, and caches expire after seven days without access.
4. **The mount path is not wired for iOS.** The window stops at the block-device
   layer; APFS mounting, `vfs_init` and the root-authentication behaviour are still
   proven only against the HFS RAM disk.

## Checkpoint history

| Checkpoint | Result | Evidence |
| --- | --- | --- |
| Stage10 | virtual entry | [40802153897](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40802153897) |
| Stage12 | C prologue, 171 host tests | [40846393171](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40846393171) |
| Stage13 | first call and return | [40862768553](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40862768553) |
| Stage14 | controlled `BRK #0x4B14` exception | [40906124944](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40906124944) |
| Stage15 | bounded counter progression | [40924679614](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40924679614) |
| Stage16 | one virtual timer IRQ and same-PC ERET | prepared, no hardware result |
| root06 | HFS RAM root, PID1 task and thread creation | local evidence only |
| window01 | read-only UFS window reads LBA 211008, digests match the 2026-11-03 baseline | local evidence only |
| UFS-TAKEOVER05 | one restricted takeover, capacity/GPT, four hashes | [42207233095](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42207233095) |
| iphone16 | APFS prelink + read-only window | [42340630197](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42340630197) |

Per-checkpoint details stay with each directory (for example
[stage16](xnu-timer-irq-checkpoint/README.md)), and six checkpoint workflows restore
the same tested kernel from [preserved original public artifacts](pinned-inputs/40518851995/README.md).
The original ZIP and kernel SHA-256 checks remain enforced; preserved bytes do not
prove that a new macOS compilation reproduces them.

## Repository boundaries

Device tests use temporary `fastboot boot` images. Public checkpoint templates
require a freshly generated private local seed before each boot. Private images,
phone photos, raw phone data and seeds stay local. This repository contains no
phone partition backups, platform seed or user data, and no workflow flashes a
partition or runs a phone.

Successful compilation does not establish boot, root, display, touch or GPU support.
Separately, the connected K70 reached the UniXNU UEFI menu; that firmware test does
not show this XNU kernel executing.

## Building

Run **K70 pinned source kernel** in Actions. `platform` builds the source kernel with
real ArmDTPlatform, ArmCpu and architectural timer support; `source` builds the
smaller source-only baseline. The `k70-iphone16` gate builds the Darwin22 integration
candidate with the storage closure. Logs, symbols, HMAC evidence and checksums are
retained with each kernel candidate, and every workflow pins the device and core
source revisions and records the actual macOS/Xcode/SDK/compiler versions.

Public DriverKit and TrustCache header listings are fetched with the workflow's
read-only GitHub token to avoid the shared runner's anonymous API rate limit. Their
source tags still come from the pinned feeds, and the unchanged upstream header
preparer verifies each downloaded file against its recorded Git blob hash. The token
is not stored in artifacts or added to the source repositories.
