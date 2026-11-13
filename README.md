# K70 XNU source build

Pinned XNU sources and macOS CI for bringing up iPhone X iOS 16.7.16 (20H392) on
the Redmi K70 (vermeer, SM8550). The [UniXNU boot chain](https://unixnu.com/zh/concepts/boot-chain)
uses the Android bootloader, BootShim, UEFI, UniXNU and DarwinBoot to start XNU.

On the test K70, XNU boots on one CPU, handles timer interrupts, and mounts an
HFS+ root from a read-only UFS window. PID 1 reaches kernel-side setup. A later
hardware run panicked in `pmap_assert_free` during early boot. Apple `launchd`
execution and an iOS interface remain unverified. The latest code checkpoint is
[`799f65f`](https://github.com/zhangfan0721/k70-unixnu-build-20261022/commit/799f65f37eb1bc4f5bf6e5451d427f6c543988fc),
which passed the [integration build](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/43032291821)
and has local image verification. Its new diagnostics await a hardware run.

- [UniXNU documentation](https://unixnu.com/zh/)
- [Porting guide](https://unixnu.com/zh/porting/)
- [Build guide](https://unixnu.com/zh/building)
- [Device repository](https://github.com/mansar1337/UniXNU-vermeer)
- [Integration workflow](.github/workflows/k70-iphone16.yml)
- [Branch integration PR](https://github.com/zhangfan0721/k70-unixnu-build-20261022/pull/1)
- Original source-build baseline: [run 39801380604](https://github.com/xyyyds0106/k70-unixnu-build-20261022/actions/runs/39801380604), commit `ecc325019f99d9491c15893f89c5e3703543b8ae`

## Bring-up stages

The table follows the UniXNU [bring-up order](https://unixnu.com/zh/porting/bring-up).
Hardware observations apply to the recorded test images.

| Stage | State | Evidence |
| --- | --- | --- |
| 1. UEFI | Verified on device | Temporary boot, framebuffer output and block-device discovery |
| 2. UniXNU | Verified on device | Boot menu loads and parses `unixnu.toml` |
| 3. Payload | Verified on device | Loader reads the kernel and its ADT sidecar and verifies their hashes |
| 4. DarwinBoot | Verified on device | Loader hands off to XNU at EL1 |
| 5. Kernel | Verified on device | XNU prints its version, matches the ADT, handles timer interrupts and creates the PID 1 task and thread |
| 6. Storage and root volume | Verified on device | HFS RAM root mounts in `root06`. A separate HFS+ test root mounts through the declared UFS window |
| 7. iOS userland | Blocked | PID 1 reaches `load_init_program`. Later hardware evidence shows a page reclamation assertion before any confirmed `launchd` execution |

### Storage and root volume

The older [UFS-TAKEOVER05 build](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42207233095)
has a matching handset record for capacity, GPT and four read digests. This
branch exposes a declared UFS extent through a BSD block device. The first
512 KiB of the HFS+ volume matched its reference digest, and `vfs_mountroot`
reported a successful mount. APFS is included in the prelink set. Native APFS
root mounting remains unverified.

The test extent is 9 GiB on this handset, outside its active Android `super` and
`userdata` partitions. It was provisioned separately with a repacked HFS+ image
from 20H392 containing selected system files, `launchd`, `dyld` and the shared
cache. The boot path serves that extent read-only, rejects writes, and stops
if the requested root window cannot open. The offset and capacity depend on
the handset's partition history.

### PID 1 and the latest diagnostic

Earlier boots stalled during the first argv `copyout` in `load_init_program`.
A later build used XNU's scoped PAN handling for user copies and reached a
`pmap_assert_free` panic. The [`8fc6792` diagnostic](https://github.com/zhangfan0721/k70-unixnu-build-20261022/commit/8fc67921ae4d1d8949731587f2fd9dea1a80add9)
recorded a live kernel mapping on a page being checked for reclamation, with
`vm_page_free_list` in the call chain. The mapping's origin and any link to the
earlier `copyout` fault remain open.

`799f65f` adds the caller for the specific free-list invocation and the mapping
virtual address when it can be decoded, while preserving the assertion and
panic. CI and image inspection verified the new diagnostic. A handset run is
still needed to capture those fields. The HFS+ repack covers the early boot
experiment. A complete 20H392 userspace and a separate writable iOS Data volume
still need validation.

## Prerequisites

The workflows pin their inputs and record the actual macOS, Xcode, SDK and
compiler versions per run.

| Input | Pin |
| --- | --- |
| XNU | `apple-oss-distributions/xnu@1b191cb58250d0705d8a51287127505aa4bc0789` (xnu-8796.141.3) |
| UniXNU core | `UniXNU/UniXNU@b6ae99c17194e6a18fd819d3148e69fe405e91fc` |
| Device | `mansar1337/UniXNU-vermeer@d4dbb3683023a17bb468b9774f52c87f3060e739` |
| UEFI | `yyx2025/uefi-vermeer@da38b23cc7b3b3716cf7c72c42866bd73c978dd3` |
| UFS transport | `UniXNU/ShengUfs@af785c1777161a62931425c2faaa536ce0bebd5b` |
| Generator | Xcode 15.4 DriverKit-286 `iig`, SHA-256 pinned |

The integration workflow uses a macOS 15 Intel runner with Xcode 16.4. It needs
the pinned `legacy-iig` tool. A cache miss depends on the configured fallback
download being available.

## Checkpoint history

| Checkpoint | Result | Evidence |
| --- | --- | --- |
| Stage10 | Virtual entry | [40802153897](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40802153897) |
| Stage12 | C prologue, 171 host tests | [40846393171](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40846393171) |
| Stage13 | First call and return | [40862768553](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40862768553) |
| Stage14 | Controlled `BRK #0x4B14` exception | [40906124944](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40906124944) |
| Stage15 | Bounded counter progression | [40924679614](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40924679614) |
| Stage16 | Standalone probe for one virtual timer IRQ and same-PC ERET | [Probe scope](xnu-timer-irq-checkpoint/README.md) |
| root06 | HFS RAM root mounts and PID 1 task and thread are created | Local hardware evidence |
| UFS-TAKEOVER05 | Restricted read-only probe checks capacity, GPT and four digests | [Build 42207233095](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42207233095), local hardware evidence |
| window01 | Declared UFS window reads match the baseline | Local hardware evidence |
| hfsroot01 | HFS+ root mounts from the 9 GiB extent | Local hardware evidence |
| iphone16 | APFS prelink and read-only UFS window integration | [Build 42340630197](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42340630197) |
| iphone16-root | APFS prelink and HFS support in the same component set | [Build 42462954404](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/42462954404) |
| PID 1 copy diagnostics | Repeated write-permission fault during the first `copyout` | Local hardware evidence |
| `8fc6792` | Page reclamation assertion with a live kernel mapping | Local hardware evidence |
| `799f65f` | Per-call free-list origin and guarded mapping VA diagnostics | [Build 43032291821](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/43032291821), local image verification |

Six early checkpoint workflows restore the tested kernel from
[preserved original public artifacts](pinned-inputs/40518851995/README.md). The
original ZIP and kernel SHA-256 checks verify the preserved files.

## Repository boundaries

Device tests use temporary `fastboot boot` images. Public checkpoint templates
require a freshly generated private local seed before boot. Phone images,
photos, raw phone data, seeds and the original Apple kernelcache stay local.
The workflows build and inspect artifacts on the host.

## Building

Run **K70 pinned source kernel** in Actions. `platform` builds the source kernel
with ArmDTPlatform, ArmCpu and architectural timer support. `source` builds
the smaller baseline. The **K70 Darwin22 integration gate** builds the Darwin22
candidate with the storage components. Run artifacts include logs, symbols
and checksums.

The integration workflow fetches public DriverKit and TrustCache header
listings with its read-only GitHub token to avoid the shared runner's
anonymous API limit. The source tags come from the pinned feeds, and the
upstream header preparer verifies each one.
