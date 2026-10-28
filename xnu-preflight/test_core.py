"""Exercise the firmware's actual C parser/materializer on a host compiler."""
import ctypes as C
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
BASE = 0xFFFFFFF007004000


class Segment(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ["Offset", "Size", "FileOffset", "FileSize"]] + [
        ("Protection", C.c_uint32), ("Name", C.c_char * 17)]


class Plan(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ["VmBase", "Span", "EntryOffset"]] + [
        ("Count", C.c_uint32), ("Segments", Segment * 32)]


def fixture():
    data = bytearray(4100)
    struct.pack_into("<8I", data, 0, 0xFEEDFACF, 0x100000C, 0, 2, 3, 432, 0, 0)
    for at, name, va, fo, fs, prot in [
        (32, b"__TEXT", BASE, 0, 512, 1),
        (104, b"__TEXT_EXEC", BASE + 4096, 4096, 4, 5),
    ]:
        struct.pack_into("<II16sQQQQIIII", data, at, 0x19, 72, name, va, 4096, fo, fs, prot, prot, 0, 0)
    struct.pack_into("<4I", data, 176, 5, 288, 6, 68)
    struct.pack_into("<Q", data, 176 + 272, BASE + 4096)
    data[4096:4100] = b"\x1f\x20\x03\xd5"
    return data


def pinned_kernel():
    if os.environ.get("K70_KERNEL"):
        return Path(os.environ["K70_KERNEL"]).read_bytes()
    archive = HERE.parents[2] / "outputs/K70-40518851995/k70-source-platform-40518851995-1.zip"
    if not archive.exists():
        raise unittest.SkipTest("Set K70_KERNEL to the pinned Mach-O")
    with zipfile.ZipFile(archive) as z:
        return z.read("kernel.development.vermeer-build.macho")


class MachoCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = None
        if not (HERE / "MachoCore.c").exists():
            return
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        binary = Path(cls.temp.name) / "core.so"
        subprocess.run([os.environ.get("CC", "cc"), "-DK70_HOST", "-std=c11", "-Wall", "-Wextra",
                        "-Werror", "-O2", "-shared", "-fPIC", str(HERE / "MachoCore.c"), "-o", str(binary)], check=True)
        cls.lib = C.CDLL(str(binary))
        cls.lib.K70ParseMachO.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Plan)]
        cls.lib.K70LoadMachO.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.POINTER(Plan)]
        cls.lib.K70Place.argtypes = [C.POINTER(Plan), C.c_uint64, C.c_uint64, C.POINTER(C.c_uint64)]
        cls.lib.K70RangeInReserved.argtypes = [C.c_uint64, C.c_uint64]

    def setUp(self):
        if self.lib is None:
            self.fail("MachoCore.c is not implemented")

    def parse(self, data):
        plan = Plan()
        buf = C.create_string_buffer(bytes(data))
        return self.lib.K70ParseMachO(buf, len(data), C.byref(plan)), plan

    def rejects(self, data):
        self.assertNotEqual(self.parse(data)[0], 0)

    def test_valid_layout_preserves_64_bit_addresses(self):
        status, plan = self.parse(fixture())
        self.assertEqual(status, 0)
        self.assertEqual((plan.VmBase, plan.Span, plan.EntryOffset, plan.Count), (BASE, 8192, 4096, 2))

    def test_materializes_segments_and_zero_fills_without_crossing_guards(self):
        data = fixture()
        source = C.create_string_buffer(bytes(data))
        dest = C.create_string_buffer(b"\xa5" * 8224, 8224)
        plan = Plan()
        self.assertEqual(self.lib.K70LoadMachO(source, len(data), C.byref(dest, 16), 8192, C.byref(plan)), 0)
        self.assertEqual(dest.raw[:16], b"\xa5" * 16)
        self.assertEqual(dest.raw[-16:], b"\xa5" * 16)
        self.assertEqual(dest.raw[16:528], bytes(data[:512]))
        self.assertEqual(dest.raw[528:4112], b"\0" * 3584)
        self.assertEqual(dest.raw[4112:4116], b"\x1f\x20\x03\xd5")
        self.assertEqual(dest.raw[4116:-16], b"\0" * 4092)

    def test_insufficient_destination_does_not_write(self):
        data = fixture()
        source = C.create_string_buffer(bytes(data))
        dest = C.create_string_buffer(b"\xa5" * 8192, 8192)
        plan = Plan()
        self.assertNotEqual(self.lib.K70LoadMachO(source, len(data), dest, 8191, C.byref(plan)), 0)
        self.assertEqual(dest.raw, b"\xa5" * 8192)

    def test_truncated_header_and_command_area_are_rejected(self):
        self.rejects(b"\xcf\xfa\xed\xfe")
        data = fixture(); struct.pack_into("<I", data, 20, 4096)
        self.rejects(data[:512])

    def test_zero_command_size_is_rejected(self):
        data = fixture(); struct.pack_into("<I", data, 36, 0); self.rejects(data)

    def test_wrong_cpu_and_dynamic_image_are_rejected(self):
        data = fixture(); struct.pack_into("<I", data, 4, 0x1000007); self.rejects(data)
        data = fixture(); struct.pack_into("<I", data, 12, 6); self.rejects(data)

    def test_file_range_outside_input_is_rejected(self):
        data = fixture(); struct.pack_into("<Q", data, 104 + 40, 0xFFFFFFFFFFFFF000); self.rejects(data)

    def test_file_larger_than_memory_segment_is_rejected(self):
        data = fixture(); struct.pack_into("<Q", data, 104 + 48, 8192); self.rejects(data)

    def test_wrapping_virtual_range_is_rejected(self):
        data = fixture(); struct.pack_into("<QQ", data, 104 + 24, 0xFFFFFFFFFFFFF000, 8192); self.rejects(data)

    def test_overlapping_virtual_segments_are_rejected(self):
        data = fixture(); struct.pack_into("<Q", data, 104 + 24, BASE); self.rejects(data)

    def test_overlapping_file_segments_are_rejected(self):
        data = fixture(); struct.pack_into("<Q", data, 104 + 40, 0); self.rejects(data)

    def test_sparse_span_over_budget_is_rejected(self):
        data = fixture(); struct.pack_into("<Q", data, 104 + 24, BASE + 0x4000000)
        struct.pack_into("<Q", data, 176 + 272, BASE + 0x4000000); self.rejects(data)

    def test_entry_in_non_executable_segment_is_rejected(self):
        data = fixture(); struct.pack_into("<Q", data, 176 + 272, BASE); self.rejects(data)

    def test_entry_in_zero_fill_part_is_rejected(self):
        data = fixture(); struct.pack_into("<Q", data, 176 + 272, BASE + 0x1100); self.rejects(data)

    def test_incorrect_thread_state_is_rejected(self):
        data = fixture(); struct.pack_into("<I", data, 176 + 12, 0); self.rejects(data)

    def test_dynamic_dependency_command_is_rejected(self):
        data = fixture(); struct.pack_into("<II", data, 16, 4, 440)
        struct.pack_into("<II", data, 464, 0xC, 8); self.rejects(data)

    def test_unsupported_dynamic_relocation_encryption_and_required_commands_are_rejected(self):
        # Each command is well-sized so this catches dispatch, not truncation.
        for command, size in [(0x20, 24), (0x80000023, 24), (0x80000034, 16),
                               (0x80000022, 48), (0x22, 48), (0x21, 24),
                               (0x2C, 24), (0x80000001, 16), (0x777, 16)]:
            with self.subTest(command=hex(command)):
                data = fixture(); struct.pack_into("<II", data, 16, 4, 432 + size)
                struct.pack_into("<II", data, 464, command, size)
                self.rejects(data)

    def test_physical_entry_remains_above_four_gib(self):
        status, plan = self.parse(fixture()); self.assertEqual(status, 0)
        entry = C.c_uint64()
        self.assertEqual(self.lib.K70Place(C.byref(plan), 0x880004000, 0x8B9D00000, C.byref(entry)), 0)
        self.assertEqual(entry.value, 0x880005000)
        self.assertNotEqual(self.lib.K70Place(C.byref(plan), 0x880004000, 0x880005000, C.byref(entry)), 0)
        self.assertNotEqual(self.lib.K70Place(C.byref(plan), 0x880000000, 0x8B9D00000, C.byref(entry)), 0)

    def test_source_requires_the_reserved_kernel_area_and_no_wrap(self):
        for base, size in [(0xAA000000, 128), (0xA8000000, 0x10000000)]:
            self.assertEqual(self.lib.K70RangeInReserved(base, size), 1)
        for base, size in [(0xB8000000, 128), (0xA7FFFFF0, 128), (0xAA000000, 0),
                           (0xFFFFFFFFFFFFFFF0, 128), (0xAA000000, 0x10000000)]:
            self.assertEqual(self.lib.K70RangeInReserved(base, size), 0)

    def test_pinned_real_kernel_layout(self):
        data = pinned_kernel()
        self.assertEqual(hashlib.sha256(data).hexdigest(), "5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8")
        status, plan = self.parse(data)
        self.assertEqual(status, 0)
        self.assertEqual((plan.VmBase, plan.Span, plan.EntryOffset), (BASE, 0x1544000, 0x3F5488))

    def test_payload_envelope_requires_exact_lengths_profile_hashes_and_layout(self):
        self.assertTrue(hasattr(self.lib, "K70InspectPayload"), "Envelope inspection is not implemented")
        fn = self.lib.K70InspectPayload
        fn.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, C.POINTER(Plan)]
        kernel = bytes(fixture())
        loaded = kernel[:512] + b"\0" * 3584 + kernel[4096:] + b"\0" * 4092
        kh, lh = hashlib.sha256(kernel).digest(), hashlib.sha256(loaded).digest()
        header = struct.pack("<8sIIQII32s32sQQQQ", b"K70XNU01", 1, 128, 4100,
                             4096, 1, kh, lh, BASE, 8192, 4096, 0)
        good = header + kernel
        plan = Plan()
        def inspect(blob):
            return fn(C.create_string_buffer(bytes(blob)), len(blob), kh, lh, C.byref(plan))
        self.assertEqual(inspect(good), 0)
        self.assertEqual((plan.Span, plan.EntryOffset), (8192, 4096))
        for offset, fmt, value in [(8, "I", 2), (12, "I", 64), (16, "Q", 4101),
                                   (24, "I", 16384), (28, "I", 0), (96, "Q", 0),
                                   (104, "Q", 4096), (112, "Q", 0), (120, "Q", 1)]:
            bad = bytearray(good); struct.pack_into("<" + fmt, bad, offset, value)
            self.assertNotEqual(inspect(bad), 0, f"Accepted invalid envelope field at {offset}")
        for offset in [0, 32, 64]:
            bad = bytearray(good); bad[offset] ^= 1; self.assertNotEqual(inspect(bad), 0)
        self.assertNotEqual(inspect(good[:-1]), 0)
        self.assertNotEqual(inspect(good + b"\0"), 0)


if __name__ == "__main__":
    unittest.main()
