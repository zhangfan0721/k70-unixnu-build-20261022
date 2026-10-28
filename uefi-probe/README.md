# K70 UEFI CPU / framebuffer / free-memory probe

This is an experimental firmware candidate for Redmi K70 (vermeer, SM8550).
It has no iOS system image and does not run XNU. A passing build is not a hardware test.

The original platform package is preserved. A separate vermeerProbePkg disables the vendor hardware stack and Chinese menu, removes UniXNU/DarwinBoot and disk/filesystem/mass-storage modules, and makes the embedded observation app its platform boot option. The application reads CPU registers, the GOP display mode and the UEFI free-memory map; it does not call ExitBootServices or disk APIs. This describes the configured probe scope, not a universal guarantee about all inherited firmware behavior.

The UEFI port exposes only a subset of installed RAM. This probe's memory profile is specific to the tested 12 GB K70 and its current firmware, not a generic profile for every vermeer variant. Root-assisted read-only inspection of that phone's runtime device tree and Android System RAM map found two unsafe inherited extents. The isolated package trims the low gap to 0xE7CB0000..0xFF800000 and the first high bank to 0x880000000..0x8B9D00000. The old high window crossed a 2 MiB non-RAM hole at 0x8B9D00000..0x8B9F00000. It is no longer used. The segment beyond that hole is deliberately not added.

VermeerBootMemoryDxe is excluded from this probe so automatic expansion from its different boot DT cannot reintroduce unverified ranges. Its initrd block-device service is not needed by this empty-ramdisk probe. All five conventional SYS_MEM entries must fit within the observed Android System RAM bounds; generation checks the pinned memory-map source hash and tests reject a changed source. The original board package is preserved.

LARGEST WINDOW still describes a firmware map, not a RAM write/read test, full 12 GB support, or feasibility of a RAM-only iOS root image. The application uses one framebuffer debug output channel after a real-device test exposed overlapping DEBUG and ConOut cursors. Earlier CPU/GOP observations do not replace a new hardware test after changing the memory profile. Runtime DT and full phone logs remain local; only the small memory bounds and source changes belong in this build repository.

Keep CapsuleRuntimeDxe in the firmware: DxeCore requires its architectural protocol before entering BDS. The pinned platform binds CapsuleLib to DxeCapsuleLibNull, whose processing functions return EFI_UNSUPPORTED, and uses emulated nonvolatile variables. Removing this protocol provider stopped the first hardware attempt at DxeCore's required-protocol assertion; the assertion remains enabled and the provider is restored. Storage modules remain excluded.

Pinned firmware: yyx2025/uefi-vermeer da38b23cc7b3b3716cf7c72c42866bd73c978dd3.
Pinned input DTB: yyx2025/UniXNU-vermeer 4d1572a93d15f5596309c0687fdc85d20ebf2e24, scripts/data/vermeer.dtb. The stock splash node is added for ABL display handoff and validated during packing. The pinned port's Gic-Spurious.patch is applied with an applicability check, as its bring-up documentation requires. No phone partition content, personal data or platform seed is uploaded.

Probe C/INF source and the base boot-option recipe originate from mansar1337/UniXNU-vermeer d4dbb3683023a17bb468b9774f52c87f3060e739, under BSD-2-Clause-Patent. The workflow uses the pinned firmware's pack_boot.py to verify the boot header, ARM64 shim, gzip payload, empty ramdisk and appended DTB.

Expected artifacts: K70-UEFI-probe.img, firmware FD, DTB, source/format reports and SHA256SUMS. Coordinate hardware testing after reviewing these files. Use only a matched, verified image for a temporary boot session; the workflow itself does not operate a phone or modify partitions. Preserve important phone data before experimenting. Photograph the CPU/GOP/LARGEST WINDOW lines if they appear. Any key returns from the app; hardware recovery key behavior must be checked on the device before the session.
