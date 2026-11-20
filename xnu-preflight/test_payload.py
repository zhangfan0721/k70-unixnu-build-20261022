import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest

from test_core import BASE, fixture, pinned_kernel

HERE = Path(__file__).resolve().parent


class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = None
        p = HERE / "payload.py"
        if p.exists():
            spec = importlib.util.spec_from_file_location("preflight_payload", p)
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)

    def setUp(self):
        if self.module is None:
            self.fail("payload.py is not implemented")

    def test_envelope_matches_independent_literal_layout_and_materialization(self):
        data = bytes(fixture()); digest = hashlib.sha256(data).hexdigest()
        blob, report = self.module.make_payload(data, expected_sha=digest)
        fields = struct.unpack_from("<8sIIQII32s32sQQQQ", blob)
        self.assertEqual(fields[:6], (b"K70XNU01", 1, 128, 4100, 4096, 1))
        self.assertEqual(fields[8:], (BASE, 8192, 4096, 0))
        expected = data[:512] + b"\0" * 3584 + data[4096:] + b"\0" * 4092
        self.assertEqual(fields[6], hashlib.sha256(data).digest())
        self.assertEqual(fields[7], hashlib.sha256(expected).digest())
        self.assertEqual(blob[128:], data)
        self.assertEqual(report["mapped_sha256"], hashlib.sha256(expected).hexdigest())

    def test_wrong_kernel_digest_is_rejected(self):
        with self.assertRaises(ValueError):
            self.module.make_payload(bytes(fixture()), expected_sha="0" * 64)

    def test_code_corruption_is_rejected_even_if_macho_headers_still_parse(self):
        data = bytes(fixture()); digest = hashlib.sha256(data).hexdigest()
        blob, _ = self.module.make_payload(data, expected_sha=digest)
        bad = bytearray(blob); bad[128 + 4096] ^= 1
        with self.assertRaises(ValueError):
            self.module.verify_payload(bytes(bad), expected_sha=digest)

    def test_mapped_digest_corruption_is_rejected(self):
        data = bytes(fixture()); digest = hashlib.sha256(data).hexdigest()
        blob, _ = self.module.make_payload(data, expected_sha=digest)
        bad = bytearray(blob); bad[64] ^= 1
        with self.assertRaises(ValueError):
            self.module.verify_payload(bytes(bad), expected_sha=digest)

    def test_truncation_and_wrong_page_profile_are_rejected(self):
        data = bytes(fixture()); digest = hashlib.sha256(data).hexdigest()
        blob, _ = self.module.make_payload(data, expected_sha=digest)
        bad = bytearray(blob); struct.pack_into("<I", bad, 24, 16384)
        for candidate in [blob[:100], blob[:-1], blob + b"\0", bytes(bad)]:
            with self.assertRaises(ValueError):
                self.module.verify_payload(candidate, expected_sha=digest)

    def test_real_kernel_payload_round_trips_and_emits_expected_header(self):
        kernel = pinned_kernel()
        blob, report = self.module.make_payload(kernel)
        decoded = self.module.verify_payload(blob)
        self.assertEqual(len(blob), 21434928)
        self.assertEqual((report["vm_base"], report["span"], report["entry_offset"]),
                         (BASE, 0x1544000, 0x3F5488))
        self.assertEqual(decoded["mapped_sha256"], report["mapped_sha256"])
        header = self.module.expected_header(report)
        self.assertIn("K70_EXPECTED_KERNEL_BYTES 21434800ULL", header)


if __name__ == "__main__":
    unittest.main()
