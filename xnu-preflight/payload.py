"""Build a pinned, no-jump envelope using the firmware's real C materializer."""
import atexit
import ctypes as C
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile

PINNED_SHA = "5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8"
HEADER = struct.Struct("<8sIIQII32s32sQQQQ")
HERE = Path(__file__).resolve().parent
_CORE = None


class Segment(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ["Offset", "Size", "FileOffset", "FileSize"]] + [
        ("Protection", C.c_uint32), ("Name", C.c_char * 17)]


class Plan(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ["VmBase", "Span", "EntryOffset"]] + [
        ("Count", C.c_uint32), ("Segments", Segment * 32)]


def core():
    global _CORE
    if _CORE is None:
        temp = tempfile.TemporaryDirectory(prefix="k70-core-")
        atexit.register(temp.cleanup)
        binary = Path(temp.name) / "core.so"
        subprocess.run([os.environ.get("CC", "cc"), "-DK70_HOST", "-std=c11", "-Wall", "-Wextra",
                        "-Werror", "-O2", "-shared", "-fPIC", str(HERE / "MachoCore.c"), "-o", str(binary)], check=True)
        lib = C.CDLL(str(binary))
        lib.K70ParseMachO.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Plan)]
        lib.K70LoadMachO.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.POINTER(Plan)]
        lib.K70InspectPayload.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, C.POINTER(Plan)]
        _CORE = lib, temp
    return _CORE[0]


def materialize(kernel):
    lib = core()
    source = C.create_string_buffer(kernel)
    plan = Plan()
    status = lib.K70ParseMachO(source, len(kernel), C.byref(plan))
    if status:
        raise ValueError(f"Mach-O rejected: status {status}")
    mapped = C.create_string_buffer(plan.Span)
    status = lib.K70LoadMachO(source, len(kernel), mapped, plan.Span, C.byref(plan))
    if status:
        raise ValueError(f"Mach-O materialization rejected: status {status}")
    return plan, mapped.raw


def make_payload(kernel, expected_sha=PINNED_SHA):
    digest = hashlib.sha256(kernel).hexdigest()
    if digest != expected_sha:
        raise ValueError("Kernel SHA-256 differs from the pinned input")
    plan, mapped = materialize(kernel)
    mapped_sha = hashlib.sha256(mapped).hexdigest()
    header = HEADER.pack(b"K70XNU01", 1, 128, len(kernel), 4096, 1,
                         bytes.fromhex(digest), bytes.fromhex(mapped_sha),
                         plan.VmBase, plan.Span, plan.EntryOffset, 0)
    report = {"kernel_sha256": digest, "mapped_sha256": mapped_sha, "kernel_bytes": len(kernel),
              "vm_base": plan.VmBase, "span": plan.Span, "entry_offset": plan.EntryOffset,
              "page_bytes": 4096, "jump_disabled": True,
              "segments": [{"name": s.Name.decode(errors="replace"), "offset": s.Offset,
                            "size": s.Size, "file_offset": s.FileOffset, "file_bytes": s.FileSize,
                            "protection": s.Protection} for s in plan.Segments[:plan.Count]]}
    return header + kernel, report


def verify_payload(blob, expected_sha=PINNED_SHA):
    if len(blob) < HEADER.size:
        raise ValueError("Truncated payload header")
    kernel = blob[HEADER.size:]
    if hashlib.sha256(kernel).hexdigest() != expected_sha:
        raise ValueError("Payload kernel SHA-256 mismatch")
    plan, mapped = materialize(kernel)
    mapped_sha = hashlib.sha256(mapped).digest()
    status = core().K70InspectPayload(C.create_string_buffer(blob), len(blob),
                                      bytes.fromhex(expected_sha), mapped_sha, C.byref(plan))
    if status:
        raise ValueError(f"Payload envelope rejected: status {status}")
    return {"kernel_sha256": expected_sha, "mapped_sha256": mapped_sha.hex(),
            "vm_base": plan.VmBase, "span": plan.Span, "entry_offset": plan.EntryOffset}


def expected_header(report):
    lines = ["// Generated from the pinned kernel. No boot_args/ADT or kernel jump.",
             f"#define K70_EXPECTED_KERNEL_BYTES {report['kernel_bytes']}ULL",
             f"#define K70_EXPECTED_VM_BASE 0x{report['vm_base']:X}ULL",
             f"#define K70_EXPECTED_SPAN 0x{report['span']:X}ULL",
             f"#define K70_EXPECTED_ENTRY_OFFSET 0x{report['entry_offset']:X}ULL"]
    for name, field in [("mExpectedKernelHash", "kernel_sha256"), ("mExpectedMappedHash", "mapped_sha256")]:
        values = ",".join(f"0x{x:02x}" for x in bytes.fromhex(report[field]))
        lines.append(f"STATIC CONST UINT8 {name}[32] = {{{values}}};")
    return "\n".join(lines) + "\n"
