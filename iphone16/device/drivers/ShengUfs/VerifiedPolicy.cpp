// Generated: VerifiedRoot policy table with two owner-signed envelopes.
// Every length comes from the assembler's "end - start"; nothing is typed twice.
//
// The whole table is emitted by the assembler because inline asm on ld64 rejects
// a quoted "segment,section" pair while the C++ attribute form cannot express an
// assembler-computed length. Emitting into the default text section keeps both
// toolchains happy; the archive member is linked into a read-only kernel segment.
#include <stdint.h>
#include "verified_root.h"
#include "VerifiedBlockPolicy.h"

__asm__(
    ".p2align 12\n"
    ".globl _k70_vr_os_manifest_start\n"
    "_k70_vr_os_manifest_start:\n"
    ".incbin \"VR_OS_MANIFEST\"\n"
    ".globl _k70_vr_os_manifest_end\n"
    "_k70_vr_os_manifest_end:\n"

    ".p2align 12\n"
    ".globl _k70_vr_sys_manifest_start\n"
    "_k70_vr_sys_manifest_start:\n"
    ".incbin \"VR_SYS_MANIFEST\"\n"
    ".globl _k70_vr_sys_manifest_end\n"
    "_k70_vr_sys_manifest_end:\n"

    ".p2align 3\n"
    ".globl _verified_root_key\n"
    "_verified_root_key:\n"
    ".incbin \"VR_KEY_BLOB\"\n"

    ".p2align 3\n"
    ".globl _verified_root_policies\n"
    "_verified_root_policies:\n"
    ".quad _k70_vr_os_manifest_start\n"
    ".quad _k70_vr_os_manifest_end - _k70_vr_os_manifest_start\n"
    ".quad _k70_vr_sys_manifest_start\n"
    ".quad _k70_vr_sys_manifest_end - _k70_vr_sys_manifest_start\n"

    ".p2align 3\n"
    ".globl _verified_root_policy_count\n"
    "_verified_root_policy_count:\n"
    ".quad 2\n"
);
