import importlib.util
from pathlib import Path
import struct
import hashlib
import lzma
import uuid
import unittest

HERE=Path(__file__).resolve().parent


class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('formal_payload',HERE/'payload.py')
        cls.module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def adt(self, value=b'\1'+bytes(7), entropy=bytes(range(64))):
        # Use the existing tested ADT serializer/parser, rather than a new format.
        h=self.module.handoff
        return h._node('device-tree',children=[h._node('chosen',[
            ('unique-chip-id',value),('chip-id',struct.pack('<I',0x207)),
            ('random-seed',entropy)])])

    def test_zeroes_only_the_declared_identity_field(self):
        blob=self.adt()
        result,offset=self.module.blank_identity(blob)
        self.assertEqual(result[offset:offset+8],bytes(8))
        self.assertEqual(result,self.adt(bytes(8),bytes(64)))

    def test_rejects_missing_or_malformed_identity(self):
        for blob in (self.adt(b'bad'),self.adt()[:-1],bytes(64)):
            with self.assertRaises(ValueError):
                self.module.blank_identity(blob)

    def test_android_id_covers_actual_unpadded_kernel_and_ramdisk(self):
        image=bytearray(12288)
        image[:8]=b'ANDROID!'
        struct.pack_into('<10I',image,8,4,0x8000,3,0xaa000000,0,0,0x1e00000,4096,0,0)
        image[4096:4100]=b'KERN'
        image[8192:8195]=b'RAM'
        expected=hashlib.sha1(b'KERN\x04\0\0\0RAM\x03\0\0\0\0\0\0\0').digest()+bytes(12)
        self.assertEqual(self.module.boot_v0_id(image),expected)
        image[8194]^=1
        self.assertNotEqual(self.module.boot_v0_id(image),expected)

    def test_final_fd_must_contain_the_exact_checked_fv(self):
        def volume(files):
            header=bytearray(72)
            header[40:44]=b'_FVH'
            struct.pack_into('<Q',header,32,72+len(files))
            struct.pack_into('<H',header,48,72)
            return bytes(header)+files
        expected=volume(b'\xff'*24)
        nested=(4+len(expected)).to_bytes(3,'little')+b'\x17'+expected
        compressed=lzma.compress(nested,format=lzma.FORMAT_ALONE)
        body=uuid.UUID('EE4E5898-3914-4259-9D6E-DC7BD79403CF').bytes_le+struct.pack('<HH',24,1)+compressed
        guided=(4+len(body)).to_bytes(3,'little')+b'\x02'+body
        ffs=bytes(16)+bytes(2)+b'\x0b\0'+(24+len(guided)).to_bytes(3,'little')+b'\x07'+guided
        fd=volume(ffs)
        self.assertTrue(self.module.verify_fd_fv(fd,expected))
        with self.assertRaises(ValueError): self.module.verify_fd_fv(fd,expected+b'old')
        with self.assertRaises(ValueError): self.module.verify_fd_fv(fd[:-1],expected)


if __name__=='__main__':
    unittest.main()
