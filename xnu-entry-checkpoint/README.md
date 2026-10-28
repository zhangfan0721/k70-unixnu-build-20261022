# K70 instrumented kernel-entry checkpoint

Stage 07 is a diagnostic experiment on the pinned ARM64 kernel. It keeps the
original `__start` branch intact, replaces a bounded part of `_start_first_cpu`
in owned RAM with an explicit diagnostic stub, and never runs the original
first-CPU initialization or userland. This is not an iOS boot image.

The stage06 full-window/boot_args/ADT/private-seed checks must succeed first.
Only three owned 4 KiB pages become executable and read-only. A read-only
40-bit/4 KiB EL1 page-table walker, whole-window identity checks, generated
hashes and page-attribute readback gate ExitBootServices. Unknown translation
profiles stop in UEFI. Pre-exit failures restore permissions; failure to
restore retains RAM and halts. Once an exit is attempted, only a fresh map
and bounded exit retry are allowed, followed by the copied transition or halt.

Expected framebuffer bands, from top to bottom:

| Rows | Color | Evidence |
| --- | --- | --- |
| 0–63 | Purple | The copied transition executed after successful UEFI exit |
| 64–127 | Orange | Stores/instructions continued after disabling M/C/I |
| 128–255 | Blue | Original kernel entry branch reached the instrumented kernel-text stub and its contract checks passed |
| 256–383 | White | The diagnostic stub completed its pass marker |
| 128–383 | Red | Kernel-text stub rejected the supplied contract |

Red in rows 0–127 means the transition rejected its inputs. All checkpoint
paths halt. Hold Power + Volume Down to return to FASTBOOT. There is no
post-exit USB log service or automatic return path.

Host assembly tests execute the actual original B instruction, transition
and stub under Unicorn 2.1.4. CurrentEL/SCTLR/cache/system instructions are
explicitly modeled, and the cache loop is accelerated at its first/last line.
These tests prove instruction/control-flow/write bounds, not real cache/MMU
behavior. Only a phone photo with blue and white can confirm the instrumented
kernel-text checkpoint on hardware. Original CPU init remains unexecuted.

Use the existing reviewed `xnu-handoff-probe/seed_image.py` locally to inject
a fresh private 64-byte CSPRNG seed into the zero-seed public template before
**each** boot. Never publish a seeded image or reuse an old seeded image.
Use only `fastboot boot`; no flash/erase/partition operation is part of this
experiment. Logs and photos belong in the central stage07 directory.

Build: `python xnu-entry-checkpoint/prepare.py --uefi UEFI --dtb DTB --kernel KERNEL --payload payload.bin --blobs NEW_DIRECTORY`.
The separate Actions workflow records blob ELF/disassembly, hashes, generated
sources, firmware build logs, the embedded AArch64 PE proof and a zero-seed
template. The input kernel remains unchanged.
