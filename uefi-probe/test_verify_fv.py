import importlib.util
from pathlib import Path
import struct
import unittest
import uuid

HERE = Path(__file__).resolve().parent
GUID = "4E746B99-462F-4C10-8A77-C3F83E5D4F72"


def firmware_file(guid, kind, body):
    size = 24 + len(body)
    header = uuid.UUID(guid).bytes_le + b"\0\0" + bytes([kind, 0]) + size.to_bytes(3, "little") + b"\x07"
    return header + body


def firmware_volume(ffs):
    header = bytearray(72)
    header[40:44] = b"_FVH"
    struct.pack_into("<Q", header, 32, 72 + len(ffs))
    struct.pack_into("<H", header, 48, 72)
    return bytes(header) + ffs


class FirmwareProofTests(unittest.TestCase):
    def test_verifier_is_available(self):
        self.assertTrue((HERE / "verify_fv.py").is_file(), "Firmware-volume verifier is not implemented")

    def verify(self, blob):
        if not (HERE / "verify_fv.py").is_file():
            self.skipTest("Verifier not implemented yet")
        spec = importlib.util.spec_from_file_location("verify_fv", HERE / "verify_fv.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.probe_pe(blob)

    def test_finds_real_application_pe_section(self):
        pe = b"MZ-probe-payload"
        section = (4 + len(pe)).to_bytes(3, "little") + b"\x10" + pe
        self.assertEqual(self.verify(firmware_volume(firmware_file(GUID, 9, section))), pe)

    def test_guid_in_another_files_payload_is_not_proof(self):
        other = "00000000-0000-0000-0000-000000000001"
        with self.assertRaises(ValueError):
            self.verify(firmware_volume(firmware_file(other, 7, uuid.UUID(GUID).bytes_le)))

    def test_matching_guid_without_pe_section_is_rejected(self):
        section = b"\x08\0\0\x15UI!!"
        with self.assertRaises(ValueError):
            self.verify(firmware_volume(firmware_file(GUID, 9, section)))


if __name__ == "__main__":
    unittest.main()
