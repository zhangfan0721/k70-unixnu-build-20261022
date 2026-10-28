import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BASE, ENTRY, CHECKPOINT, TRAMP = 0x880004000, 0x8803f9488, 0x8803fb05c, 0x881604000
ARGS, TREE, FB, ROW = 0x881548000, 0x881549000, 0xb8000000, 5760


class BlobFixture:
    @classmethod
    def setUpClass(cls):
        cls.b = None
        if not (HERE / 'blobs.py').exists(): return
        spec = importlib.util.spec_from_file_location('entry_blobs', HERE / 'blobs.py')
        cls.b = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.b)
        cls.kernel = Path(os.environ.get('K70_KERNEL', HERE.parents[1] / 'k70-xnu-kernel/kernel.development.vermeer-build.macho'))
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.out = Path(cls.temp.name) / 'blobs'
        cls.header, cls.report = cls.b.build(cls.kernel, cls.out)
        cls.stub = (cls.out / 'checkpoint.bin').read_bytes()
        cls.transition = (cls.out / 'transition.bin').read_bytes()

    def setUp(self):
        self.assertIsNotNone(self.b, 'entry assembly artifact builder not implemented')


class AssemblyProofTests(BlobFixture, unittest.TestCase):
    def test_original_entry_branch_preserved_and_patch_is_bounded(self):
        self.assertEqual(self.report['original_entry_pa'], ENTRY)
        self.assertEqual(self.report['checkpoint_pa'], CHECKPOINT)
        self.assertEqual(self.report['original_entry_instruction'], '0x140006f5')
        self.assertLessEqual(len(self.stub), 4096 - 0x5c)
        self.assertLessEqual(len(self.transition), 4096)
        self.assertEqual(self.report['stub_sha256'], hashlib.sha256(self.stub).hexdigest())
        self.assertEqual(self.report['transition_sha256'], hashlib.sha256(self.transition).hexdigest())
        self.assertFalse(self.report['hardware_tested']); self.assertFalse(self.report['original_cpu_init_executed'])
        sys.path.insert(0, str(HERE.parent / 'xnu-preflight'))
        from payload import materialize
        _, original = materialize(self.kernel.read_bytes()); changed = bytearray(original)
        changed[0x3f705c:0x3f705c + len(self.stub)] = self.stub
        self.assertEqual(changed[0x3f5488:0x3f548c], original[0x3f5488:0x3f548c])
        self.assertEqual(hashlib.sha256(changed).hexdigest(), self.report['instrumented_mapped_sha256'])
        self.assertEqual(changed[:0x3f705c], original[:0x3f705c])
        self.assertEqual(changed[0x3f705c + len(self.stub):], original[0x3f705c + len(self.stub):])

    def test_elf_machine_bounds_and_relocations_rejected(self):
        data = (self.out / 'checkpoint.elf').read_bytes()
        code, symbols = self.b.extract_elf(data)
        self.assertEqual(code, self.stub); self.assertEqual(symbols['kernel_checkpoint_begin'], 0)
        for bad in [data[:50], b'bad' + data[3:]]:
            with self.assertRaises(ValueError): self.b.extract_elf(bad)
        bad = bytearray(data); struct.pack_into('<H', bad, 18, 62)
        with self.assertRaises(ValueError): self.b.extract_elf(bad)
        bad = bytearray(data); struct.pack_into('<Q', bad, 40, len(data) + 64)
        with self.assertRaises(ValueError): self.b.extract_elf(bad)
        shoff = struct.unpack_from('<Q', data, 40)[0]
        count = struct.unpack_from('<H', data, 60)[0]
        for i in range(count):
            at = shoff + 64 * i
            if struct.unpack_from('<Q', data, at + 32)[0]:
                bad = bytearray(data); struct.pack_into('<I', bad, at + 4, 4)
                with self.assertRaises(ValueError): self.b.extract_elf(bad)
                break

    def test_wrong_kernel_refused_before_output(self):
        path = Path(self.temp.name) / 'wrong'; path.write_bytes(b'wrong')
        out = Path(self.temp.name) / 'wrong-output'
        with self.assertRaises(ValueError): self.b.build(path, out)
        self.assertFalse(out.exists())

    def test_string_path_from_command_line_is_supported(self):
        _, report = self.b.build(str(self.kernel), Path(self.temp.name) / 'cli-path-output')
        self.assertEqual(report['original_entry_pa'], ENTRY)


class Arm64ExecutionTests(BlobFixture, unittest.TestCase):
    def run_code(self, *, full=False, el=4, sctlr=0, bad_args=False, bad_tree=False,
                 bad_seed=False, x0=ARGS):
        # System-register values are explicit model inputs. This is instruction
        # and framebuffer-bounds coverage, NOT a real MMU/cache/EL simulation.
        try:
            import unicorn as U
        except ImportError:
            sys.path.insert(0, str(HERE.parents[1] / 'k70-arm64-qa'))
            import unicorn as U
        from unicorn import arm64_const as A
        sys.path.insert(0, str(HERE.parent / 'xnu-handoff'))
        import handoff
        tree = handoff.make_tree(BASE, 0x10000000, b'P' * 64)
        layout = handoff.plan_layout(0x1544000, handoff.KERNEL['vm_base'], 0x3f5488, len(tree))
        args = bytearray(handoff.make_args(layout, len(tree), handoff.GOP, '-v'))
        if bad_args: args[0x10] ^= 1
        tree = bytearray(tree)
        if bad_tree: tree[0] ^= 1
        if bad_seed: tree[0x154:0x194] = bytes(64)
        u = U.Uc(U.UC_ARCH_ARM64, U.UC_MODE_ARM)
        for page in [ENTRY & ~4095, CHECKPOINT & ~4095, TRAMP, ARGS, TREE]: u.mem_map(page, 4096)
        u.mem_map(FB, 0x1194000)
        u.mem_write(ENTRY, struct.pack('<I', 0x140006f5))
        u.mem_write(CHECKPOINT, self.stub); u.mem_write(TRAMP, self.transition)
        u.mem_write(ARGS, bytes(args)); u.mem_write(TREE, bytes(tree))
        state = dict(sctlr=sctlr, writes=0, first=1 << 64, last=0, entered=False, cache_visits=0, sys=[])
        def mrs(uc, reg, cp, _):
            key = (cp.op0, cp.op1, cp.crn, cp.crm, cp.op2)
            values = {(3, 0, 4, 2, 2): el, (3, 0, 1, 0, 0): state['sctlr'],
                      (3, 3, 0, 0, 1): 4 << 16}
            if key not in values: raise AssertionError(('unexpected MRS', key))
            uc.reg_write(reg, values[key]); return True
        def msr(uc, reg, cp, _):
            key = (cp.op0, cp.op1, cp.crn, cp.crm, cp.op2)
            if key != (3, 0, 1, 0, 0): raise AssertionError(('unexpected MSR', key))
            state['sctlr'] = uc.reg_read(reg); state['sys'].append('sctlr'); return True
        def system(uc, reg, cp, _):
            state['sys'].append((cp.op1, cp.crn, cp.crm, cp.op2)); return True
        u.hook_add(U.UC_HOOK_INSN, mrs, aux1=A.UC_ARM64_INS_MRS)
        u.hook_add(U.UC_HOOK_INSN, msr, aux1=A.UC_ARM64_INS_MSR)
        u.hook_add(U.UC_HOOK_INSN, system, aux1=A.UC_ARM64_INS_SYS)
        def read(uc, access, address, size, value, _):
            # Conservative MMU-off Device-memory contract: Unicorn's default
            # Normal-memory mapping otherwise accepts the unaligned seed load.
            if not state['sctlr'] & 1:
                self.assertEqual(address % size, 0,
                    'MMU-off unaligned read at %#x size %d' % (address, size))
        u.hook_add(U.UC_HOOK_MEM_READ, read)
        def write(uc, access, address, size, value, _):
            if not state['sctlr'] & 1: self.assertEqual(address % size, 0)
            self.assertGreaterEqual(address, FB if full else FB + 128 * ROW)
            self.assertLessEqual(address + size, FB + 384 * ROW)
            state['writes'] += 1; state['first'] = min(state['first'], address)
            state['last'] = max(state['last'], address + size)
        u.hook_add(U.UC_HOOK_MEM_WRITE, write)
        def stop(uc, address, size, _): uc.emu_stop()
        halt = CHECKPOINT + self.report['checkpoint_symbols']['kernel_checkpoint_halt']
        u.hook_add(U.UC_HOOK_CODE, stop, begin=halt, end=halt)
        def original_entry(uc, address, size, _): state['entered'] = True
        u.hook_add(U.UC_HOOK_CODE, original_entry, begin=ENTRY, end=ENTRY)
        if full:
            symbols = self.report['transition_symbols']
            # Model DAIF masking; Unicorn's default execution level is EL0.
            at = TRAMP + symbols['transition_mask_interrupts']
            def daif(uc, address, size, _): uc.reg_write(A.UC_ARM64_REG_PC, address + 4)
            u.hook_add(U.UC_HOOK_CODE, daif, begin=at, end=at)
            # Exercise first/last cache-line loop boundaries without millions
            # of emulator callbacks; hardware maintenance is separately tested.
            at = TRAMP + symbols['transition_clean_loop']
            def cache(uc, address, size, _):
                state['cache_visits'] += 1
                if state['cache_visits'] == 2: uc.reg_write(A.UC_ARM64_REG_X6, BASE + 0x10000000 - 64)
            u.hook_add(U.UC_HOOK_CODE, cache, begin=at, end=at)
        registers = [x0, ENTRY, BASE, 0x10000000, FB, 0x1194000]
        for i, v in enumerate(registers): u.reg_write(A.UC_ARM64_REG_X0 + i, v)
        u.emu_start(TRAMP if full else ENTRY, 0, count=4000000)
        self.assertTrue(state['entered'])
        self.assertEqual(u.reg_read(A.UC_ARM64_REG_PC), halt)
        colors = [struct.unpack('<I', u.mem_read(FB + row * ROW, 4))[0] for row in [0, 64, 128, 256, 384]]
        return colors, state

    def test_actual_original_branch_reaches_positive_checkpoint(self):
        colors, state = self.run_code()
        self.assertEqual(colors, [0, 0, 0xff0070ff, 0xffffffff, 0])
        self.assertEqual(state['first'], FB + 128 * ROW)
        self.assertEqual(state['last'], FB + 384 * ROW)

    def test_wrong_boot_contract_paints_only_failure(self):
        for values in [dict(el=8), dict(sctlr=1), dict(sctlr=4), dict(sctlr=0x1000),
                       dict(x0=ARGS + 8), dict(bad_args=True), dict(bad_tree=True), dict(bad_seed=True)]:
            with self.subTest(values=values):
                colors, _ = self.run_code(**values)
                self.assertEqual(colors, [0, 0, 0xffff0000, 0xffff0000, 0])

    def test_transition_stage_order_and_preserved_boot_args(self):
        colors, state = self.run_code(full=True, sctlr=0x1005)
        self.assertEqual(colors, [0xffa000ff, 0xffffa000, 0xff0070ff, 0xffffffff, 0])
        self.assertEqual(state['sctlr'] & 0x1005, 0)
        self.assertEqual(state['cache_visits'], 2)
        self.assertIn('sctlr', state['sys'])


if __name__ == '__main__': unittest.main()
