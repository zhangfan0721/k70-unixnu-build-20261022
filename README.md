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
- [Latest storage build](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42462954404)
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

## Bring-up stages (2026-11-10)

The rows follow the [bring-up order](https://unixnu.com/zh/porting/bring-up) the
documentation defines, so every line here has a counterpart there.

| Stage | State | Evidence |
| --- | --- | --- |
| 1. UEFI | ✅ | firmware boots from `fastboot boot`, framebuffer has output, block devices are visible |
| 2. UniXNU | ✅ | menu and `unixnu.toml` parse; the kernel receives the configured command line verbatim |
| 3. Payload | ✅ | `kernel.macho` and its ADT sidecar are read and hash-checked |
| 4. DarwinBoot | ✅ | `DARWINBOOT:` base/entry/framebuffer lines, EL1, kernel entered |
| 5. Kernel entry | ✅ | XNU prints its version, pexpert matches the ADT, GIC and timer run, PID 1 task and thread exist |
| 6. Storage and root volume | ✅ | a real HFS+ volume in the userdata gap is the root filesystem: `vfs_mountroot mounted; root policy check next`, `root filesystem mount result value=0x0` |
| 7. Userland | 🔧 | PID 1 runs its first continuation, `bsdinit_task` reaches `load_init_program`, and the first user page fault of the argv copyout stalls inside `pmap` before any exec result exists. The board does not reset |

✅ verified on the phone or in CI · 🔧 implemented and partly verified · ❌ not available.

### Stage 6: a real root filesystem, served read-only from media

Two separate results carry this row.

**The window reads the volume.** `k70rd=0x33840,0x240000` declares 2,359,296 blocks
(9 GiB) starting at LBA 211008. `mdevadd_fetch(0, …)` turns that extent into a BSD
device (`dev_t 0x10`, not `md0`), and the first 512 KiB that come back hash to
`d82ff631 35e98d07 6d442cfb afe43d00 c10da229 4f3a6ffa` — the same blocks read on the
host from the same image.

**HFS+ mounts it as the root.** With `rootdevice` unset, `vfs_mountroot` tries each
registered filesystem in turn. APFS rejects the extent (`apfs value=0x4f`), HFS accepts
it, and the boot continues with `bsd_init: calling VFS_ROOT?`. The HFS path needs no
IOMedia: it consumes the BSD device that the fetch callback registered.

The volume itself is built offline and written into the 9 GiB gap between LBA 211008
and LBA 2570303, which held no partition before:

1. `7z x` the 20H392 OS volume (APFS, 5.25 GiB) into a staging tree.
2. Trim what early boot cannot need — `LinguisticData`, `PreinstalledAssetsV2`,
   `Assistant` — and add the dyld shared cache extracted from the SystemCryptex
   (`System/Library/Caches/com.apple.dyld`, 2,485 MiB, 50 files).
3. `mkfs.hfsplus -b 4096` an 9 GiB image, then populate it with `hfsplus addall`
   in verified chunks. The stock tool descends symlinks and guesses modes, so the
   local copy uses `lstat`, `makeSymlink` and the real mode of each entry.
4. `dd` the image to LBA 211008 from recovery, then read the head back and compare.

### Stage 7: the first exec has no result

Earlier revisions of this row said the board reset five seconds after the
transport began reading files, and that the exec probe never printed. Both
observations were real, but the cause was elsewhere: the console had scrolled
the probe away, and the kernel had stalled rather than reset. The measured
state follows.

The launch parameters that matter for this stage, all recorded with their reason:

| Argument | Why |
| --- | --- |
| `k70rd=0x33840,0x240000` | declares the root volume extent |
| `k70nocc14=1` | leaves corecrypto initialisation to the prelinked kext only |
| `unentitled_ios_sim_launch=1` | the `XNU_TARGET_OS_OSX` build rejects an iOS binary whose initial exec carries no spawn platform unless this switch is set |
| ADT `darwinboot-memory-size=0x80000000` | 2 GiB owned window; the default runs out of memory around launchd |
| ADT `/defaults/vmm-present=0` | no hypervisor is present, and the watchdog path assumes one otherwise |

### Stage 7: where the first user page stops

The row above is no longer "a reset before the probe prints". PID 1 runs, and the
kernel stops on the very first user mapping it tries to create.

| Question | Answer measured on the phone |
| --- | --- |
| Does the PID 1 thread run? | yes: a flag written in its first instruction reads 1 |
| How far does it get? | `task_wait_to_return` then `bsdinit_task` then `load_init_program` |
| What stops it? | the `copyout` of the init path faults in the new task map at VA `0x1000` |
| Is it spinning? | no: the timer thread keeps printing one status line per second |
| pmap bounds and levels | `min=0`, `max=0x4000000000`, root table `0xfffffff04d653800`, leaf 3 / root 1 |
| Free memory | `vm_page_free_count = 0x7e73c`, about 2 GiB, so not exhaustion |

The fault walks the whole way into `pmap_enter`: the leaf entry is found, the pv hash
lock is taken, and then the per-cpu pv free list has to be refilled. That refill drops
the pmap lock and asks for a page, but the fault path runs with preemption disabled,
where the allocator refuses to allocate, so the retry never completes.

Two things found on the way stay in the tree. A user pmap was created with a zero
upper bound, so every walk failed and the page-table expand loop consumed pages until
it blocked. And the question "does the PID 1 thread run at all" was answered only
after the busy console was quieted: the thread had been running the whole time.

## Gaps before userland

1. **The first exec has no reported result.** See stage 7: the argv page fault never
   completes, so `execve` is never reached and there is no errno to print. The next
   step is either a page the fault already finds resident, or a pv refill that works
   with preemption disabled. Wiring the page from the boot thread was tried and the
   board reset, so the wire tag it passed is the first suspect.
2. **The staging tree is a subset.** It carries `launchd`, `dyld`, the dyld shared
   cache, `Frameworks`, `CoreServices`, `LaunchDaemons`, `Extensions` and a
   skeleton `/private/var`. It has no Data volume, no trust cache and no AppOS
   cryptex, so even a successful exec would meet missing pieces immediately.
3. **The IIG toolchain fallback is dead.** The workflow restores `legacy-iig` from a
   `trycloudflare` tunnel that no longer resolves; it works only while the branch
   cache survives, and caches expire after seven days without access.
4. **The root is read-only.** Nothing in the image is written back. Writes are a
   separate change with its own risk, and they are not needed to find out what the
   first exec returns.

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
| hfsroot01 | 9 GiB HFS+ root in the userdata gap mounts: `vfs_mountroot mounted` | local evidence only |
| pid1-01 | PID 1 created, `bsd_init: done`; reset arrives before any exec result | local evidence only |
| pid1-02 | PID 1 thread runs; `bsdinit_task` reaches `load_init_program`; the first user fault stalls in the pmap pv refill | local evidence only |
| UFS-TAKEOVER05 | one restricted takeover, capacity/GPT, four hashes | [42207233095](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42207233095) |
| iphone16 | APFS prelink + read-only window | [42340630197](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42340630197) |
| iphone16-root | APFS prelink with the HFS root path in the same component set | [42462954404](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42462954404) |

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
preparer verifies each one.
