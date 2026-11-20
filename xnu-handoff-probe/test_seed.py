import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


class SeedTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = None
        if not (HERE / 'seed_image.py').exists(): return
        spec = importlib.util.spec_from_file_location('seed_image', HERE / 'seed_image.py')
        cls.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.m)
        sys.path.insert(0, str(HERE.parent / 'xnu-preflight'))
        from payload import make_payload
        kernel = Path(os.environ.get('K70_KERNEL', HERE.parents[1] / 'k70-xnu-kernel/kernel.development.vermeer-build.macho'))
        if not kernel.exists(): raise unittest.SkipTest('Pinned kernel is required')
        payload, _ = make_payload(kernel.read_bytes())
        # Synthetic firmware bytes: this tests private patch mechanics, not a
        # claim that these bytes constitute bootable firmware.
        header = bytearray(4096); header[:8] = b'ANDROID!'
        code = b'fixture-firmware'
        struct.pack_into('<10I', header, 8, len(code), 0x8000, len(payload), 0xaa000000,
                         0, 0, 0x1e00000, 4096, 0, 0)
        cls.image = bytes(header) + code + bytes(-len(code) % 4096) + payload + bytes(-len(payload) % 4096)

    def setUp(self):
        self.assertIsNotNone(self.m, 'private seed transport not implemented')

    def test_public_template_seed_is_all_zero_and_not_boot_ready(self):
        image = self.m.template_image(self.image)
        info = self.m.inspect_image(image)
        self.assertEqual(info['ramdisk_bytes'], 21434928 + 112)
        self.assertEqual(image[info['seed_offset']:info['seed_offset'] + 112], bytes(112))
        self.assertEqual(image[4096:8192], self.image[4096:8192])
        with self.assertRaises(ValueError): self.m.verify_seeded_image(image)

    def test_fresh_seed_changes_only_private_trailer(self):
        public = self.m.template_image(self.image); digest = hashlib.sha256(public).hexdigest()
        with patch.object(self.m.secrets, 'token_bytes', return_value=b'A' * 64):
            a, ra = self.m.inject_seed(public, digest)
        with patch.object(self.m.secrets, 'token_bytes', return_value=b'B' * 64):
            b, rb = self.m.inject_seed(public, digest)
        at = self.m.inspect_image(public)['seed_offset']
        self.assertEqual(a[:at], public[:at]); self.assertEqual(a[at + 112:], public[at + 112:])
        self.assertNotEqual(a, b); self.assertNotEqual(ra['seed_sha256'], rb['seed_sha256'])
        self.assertEqual(ra['seed_sha256'], hashlib.sha256(b'A' * 64).hexdigest())
        self.assertEqual(self.m.verify_seeded_image(a)['seed_sha256'], ra['seed_sha256'])
        self.assertNotIn('seed', ra)

    def test_wrong_hash_repeated_or_corrupt_input_rejected(self):
        public = self.m.template_image(self.image); digest = hashlib.sha256(public).hexdigest()
        with self.assertRaises(ValueError): self.m.inject_seed(public, '0' * 64)
        seeded, _ = self.m.inject_seed(public, digest)
        with self.assertRaises(ValueError): self.m.inject_seed(seeded, hashlib.sha256(seeded).hexdigest())
        with self.assertRaises(ValueError): self.m.template_image(public)
        for at in [0, 12, 20, 36, 40, 8192 + 150]:
            bad = bytearray(public); bad[at] ^= 1
            with self.assertRaises(ValueError): self.m.inspect_image(bad)
        for bad in [public[:-1], public + b'\0']:
            with self.assertRaises(ValueError): self.m.inspect_image(bad)

    def test_trailer_metadata_seed_and_digest_tampering_rejected(self):
        public = self.m.template_image(self.image)
        seeded, _ = self.m.inject_seed(public, hashlib.sha256(public).hexdigest())
        at = self.m.inspect_image(seeded)['seed_offset']
        for offset in [0, 8, 12, 16, 79, 80, 111]:
            bad = bytearray(seeded); bad[at + offset] ^= 1
            with self.assertRaises(ValueError): self.m.verify_seeded_image(bad)
        with patch.object(self.m.secrets, 'token_bytes', return_value=bytes(64)):
            with self.assertRaises(ValueError): self.m.inject_seed(public, hashlib.sha256(public).hexdigest())

    def test_image_verification_never_attests_the_seed_generator(self):
        public = self.m.template_image(self.image)
        with patch.object(self.m.secrets, 'token_bytes', return_value=b'A' * 64):
            image, generated = self.m.inject_seed(public, hashlib.sha256(public).hexdigest())
        checked = self.m.verify_seeded_image(image)
        self.assertFalse(checked.get('host_generation_attested', True))
        self.assertNotIn('OS CSPRNG', checked['seed_source'])
        self.assertTrue(generated['host_generation_attested'])


if __name__ == '__main__': unittest.main()
