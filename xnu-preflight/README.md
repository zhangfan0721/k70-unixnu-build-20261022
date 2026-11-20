# Redmi K70 XNU materialization preflight

This stage copies the pinned source-built ARM64 Mach-O into UEFI-owned RAM, zero-fills its mapped span and checks SHA-256 against a host-generated expected image. It calculates the physical entry and then waits. It does not execute XNU, build a boot_args/ADT handoff, call ExitBootServices or change MMU/cache/GIC settings. It is not an iOS boot image.

The original verified hardware-probe workflow remains separate. This app reuses its 12 GB K70 memory limits and excluded auto-expansion driver. It must allocate at 0x880004000 using AllocateAddress before any copy. Allocation or digest failure stops at a result page. Current kernel mapping spans about 21.27 MiB; that does not estimate full kernel/userland RAM needs.

The kernel is carried in a 128-byte envelope in the boot image ramdisk, requested at 0xAA000000. Bootloader FDT and initrd pointers are accepted only inside the preserved 0xA8000000..0xB8000000 kernel reservation, and must not overlap. Unexpected placement is reported and rejected. No filesystem or storage driver is needed, and VermeerBootMemoryDxe is not restored.

Pinned kernel: source build 40518851995, artifact k70-source-platform-40518851995-1; SHA256 5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8. Its platform profile uses 4 KiB pages and has no UFS/RAM block/display/GPU driver configuration enabled. The existing artifact expires on 2026-11-03; builds fail if it is unavailable rather than silently selecting a different kernel. A local verified copy is retained by the research task.

Only this app overrides the platform's null crypto backend with its pinned OpenSSL SHA-256 implementation. Its null RNG dependency is unused for hashing; platform security settings stay as configured. The OpenSSL constructor only initializes CPU capability flags. Binary integrity checks cover both the input kernel and the materialized bytes.

Host tests compile and exercise the same C core used in firmware, including malformed headers, range overflow, segment overlap, bad entry points, insufficient output capacity, source bounds, envelope metadata and byte corruption. Real-device materialization is unverified until a photo shows MATERIALIZED SHA256 OK and PREFLIGHT PASS. Even those messages do not prove kernel execution or a RAM stress test.

Expected artifacts include K70-XNU-preflight.img, payload.bin, FD, DTB, ExpectedPayload.h, reports and SHA256SUMS. Use only a matched and verified candidate with fastboot boot. Keep the result screen for a photograph; a key frees the owned destination allocation and returns to UEFI. Power plus volume down returns to fastboot on the tested phone.
