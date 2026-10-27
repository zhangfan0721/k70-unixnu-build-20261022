# K70 UEFI CPU / framebuffer / free-memory probe

This is an experimental firmware candidate for Redmi K70 (vermeer, SM8550).
It has no iOS system image and does not run XNU. A passing build is not a hardware test.

The original platform package is preserved. A separate vermeerProbePkg disables the vendor hardware stack and Chinese menu, removes UniXNU/DarwinBoot and disk/filesystem/mass-storage modules, and makes the embedded observation app its platform boot option. The application reads CPU registers, the GOP display mode and the UEFI free-memory map; it does not call ExitBootServices or disk APIs. This describes the configured probe scope, not a universal guarantee about all inherited firmware behavior.

The UEFI port currently exposes only a subset of installed RAM. LARGEST WINDOW describes that firmware map; it cannot by itself determine the capacity of a 12 GB phone or the feasibility of a full RAM-only iOS root image. The framebuffer values and display handoff still require a real K70 observation.

Pinned firmware: yyx2025/uefi-vermeer da38b23cc7b3b3716cf7c72c42866bd73c978dd3.
Pinned input DTB: yyx2025/UniXNU-vermeer 4d1572a93d15f5596309c0687fdc85d20ebf2e24, scripts/data/vermeer.dtb. The stock splash node is added for ABL display handoff and validated during packing. The pinned port's Gic-Spurious.patch is applied with an applicability check, as its bring-up documentation requires. No phone partition content, personal data or platform seed is uploaded.

Probe C/INF source and the base boot-option recipe originate from mansar1337/UniXNU-vermeer d4dbb3683023a17bb468b9774f52c87f3060e739, under BSD-2-Clause-Patent. The workflow uses the pinned firmware's pack_boot.py to verify the boot header, ARM64 shim, gzip payload, empty ramdisk and appended DTB.

Expected artifacts: K70-UEFI-probe.img, firmware FD, DTB, source/format reports and SHA256SUMS. Coordinate hardware testing after reviewing these files. Use only a matched, verified image for a temporary boot session; the workflow itself does not operate a phone or modify partitions. Preserve important phone data before experimenting. Photograph the CPU/GOP/LARGEST WINDOW lines if they appear. Any key returns from the app; hardware recovery key behavior must be checked on the device before the session.
