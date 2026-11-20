import unittest
import struct
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from payload import handoff
from payload import boot_v0_id
from personalize import fill_identity, build


class FreshIdentityTests(unittest.TestCase):
    def test_updates_only_the_zero_identity_field(self):
        blob=handoff._node('device-tree',children=[handoff._node('chosen',[
            ('unique-chip-id',bytes(8)),('chip-id',struct.pack('<I',0x207)),
            ('random-seed',bytes(64))])])
        fresh=b'new-id01'
        random=b'x'*64
        result=fill_identity(blob,fresh,random)
        self.assertEqual(handoff.parse_tree(result)['/chosen']['unique-chip-id'],fresh)
        self.assertEqual(handoff.parse_tree(result)['/chosen']['random-seed'],random)
        self.assertEqual(result.replace(fresh,bytes(8)).replace(random,bytes(64)),blob)
        with self.assertRaises(ValueError): fill_identity(result,fresh,random)
        with self.assertRaises(ValueError): fill_identity(blob,bytes(8),random)
        with self.assertRaises(ValueError): fill_identity(blob,b'short',random)
        with self.assertRaises(ValueError): fill_identity(blob,fresh,bytes(64))

    @unittest.skipUnless(shutil.which('mcopy') and shutil.which('mformat'),'mtools required')
    def test_real_fat_roundtrip_and_android_id_refresh_without_device_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);volume=root/'volume.img'
            blob=handoff._node('device-tree',children=[handoff._node('chosen',[
                ('unique-chip-id',bytes(8)),('chip-id',struct.pack('<I',0x207)),
                ('random-seed',bytes(64))])])
            adt=root/'kernel.macho.adt';adt.write_bytes(blob)
            subprocess.run(['mformat','-C','-T','8192','-i',str(volume),'::'],check=True)
            subprocess.run(['mmd','-i',str(volume),'::/EFI','::/EFI/UniXNU','::/EFI/UniXNU/Payloads'],check=True)
            subprocess.run(['mcopy','-i',str(volume),str(adt),'::/EFI/UniXNU/Payloads/kernel.macho.adt'],check=True)
            ramdisk=volume.read_bytes()
            original=bytearray(8192+len(ramdisk));original[:8]=b'ANDROID!'
            struct.pack_into('<10I',original,8,4,0x8000,len(ramdisk),0xaa000000,0,0,0x1e00000,4096,0,0)
            original[4096:4100]=b'KERN';original[8192:]=ramdisk
            original[576:608]=boot_v0_id(original)
            template=root/'public.img';template.write_bytes(original)
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'identity_zero':True,'personalization_required':True,
                'template_sha256':hashlib.sha256(original).hexdigest(),
                'adt_sha256':hashlib.sha256(blob).hexdigest()}))
            output=root/'private/candidate.img'
            record=build(template,manifest,output)
            actual=output.read_bytes()
            self.assertEqual(actual[4096:8192],original[4096:8192])
            self.assertEqual(actual[576:608],boot_v0_id(actual))
            self.assertNotEqual(actual[576:608],original[576:608])
            self.assertEqual(template.read_bytes(),original)
            self.assertTrue(record['fresh_random_seed_generated'])
            with self.assertRaises(ValueError): build(template,manifest,output)


if __name__=='__main__': unittest.main()
