import gzip
import importlib.util
from pathlib import Path
import struct
import unittest

HERE = Path(__file__).resolve().parent


def boot_fixture():
    combined = bytearray(192 + 0x300000); combined[56:60] = b"ARMd"
    tree, payload = b"fixed-dtb", b"pinned-no-jump-payload"
    kernel = gzip.compress(bytes(combined), mtime=0) + tree
    header = bytearray(4096); header[:8] = b"ANDROID!"
    struct.pack_into("<10I", header, 8, len(kernel), 0x8000, len(payload), 0xAA000000,
                     0, 0, 0x1E00000, 4096, 0, 0)
    data = header + kernel + b"\0" * (-len(kernel) % 4096)
    data += payload + b"\0" * (-len(payload) % 4096)
    return bytearray(data), bytes(combined), tree, payload


class BootImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = None
        p = HERE / "pack_boot.py"
        if p.exists():
            spec = importlib.util.spec_from_file_location("preflight_pack", p)
            cls.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.module)

    def setUp(self):
        if self.module is None:
            self.fail("Preflight packer is not implemented")

    def test_exact_nonempty_ramdisk_and_load_address_round_trip(self):
        data, combined, tree, payload = boot_fixture()
        report = self.module.verify_image(bytes(data), combined, tree, payload)
        self.assertEqual((report["ramdisk_bytes"], report["ramdisk_address"], report["page_size"]),
                         (22, "0xaa000000", 4096))

    def test_wrong_ramdisk_address_fails(self):
        data, c, t, p = boot_fixture(); struct.pack_into("<I", data, 20, 0x1000000)
        with self.assertRaises(ValueError): self.module.verify_image(bytes(data), c, t, p)

    def test_truncated_or_extended_file_fails(self):
        data, c, t, p = boot_fixture()
        for bad in [data[:-1], data[:4096], data + b"\0"]:
            with self.assertRaises(ValueError): self.module.verify_image(bytes(bad), c, t, p)

    def test_wrong_ramdisk_bytes_and_declared_length_fail(self):
        data, c, t, p = boot_fixture()
        with self.assertRaises(ValueError): self.module.verify_image(bytes(data), c, t, p + b"x")
        k = struct.unpack_from("<I", data, 8)[0]; at = 4096 * (1 + (k + 4095) // 4096)
        data[at] ^= 1
        with self.assertRaises(ValueError): self.module.verify_image(bytes(data), c, t, p)

    def test_gzip_corruption_and_changed_dtb_fail(self):
        data, c, t, p = boot_fixture(); data[4096] = 0
        with self.assertRaises(ValueError): self.module.verify_image(bytes(data), c, t, p)
        data, c, t, p = boot_fixture()
        with self.assertRaises(ValueError): self.module.verify_image(bytes(data), c, b"other-tree", p)

    def test_nonzero_padding_and_unsupported_header_fail(self):
        data, c, t, p = boot_fixture(); data[-1] = 1
        with self.assertRaises(ValueError): self.module.verify_image(bytes(data), c, t, p)
        for off, value in [(32, 512), (36, 3), (40, 3), (24, 1)]:
            data, c, t, p = boot_fixture(); struct.pack_into("<I", data, off, value)
            with self.assertRaises(ValueError): self.module.verify_image(bytes(data), c, t, p)


if __name__ == "__main__":
    unittest.main()
