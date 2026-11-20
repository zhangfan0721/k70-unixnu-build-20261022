"""Observe the registered-but-not-online CPU boundary; never change IRQ policy."""
import hashlib
import json
from pathlib import Path

PHASES = {1: 'start enter', 10: 'controller allocation enter', 11: 'controller allocated',
          12: 'controller init enter', 13: 'controller init returned',
          20: 'controller publication enter', 21: 'controller publication returned',
          30: 'CPU interrupt enable enter', 31: 'CPU interrupt enable returned',
          40: 'client IRQ registration enter', 41: 'client IRQ registration returned',
          50: 'CPU timer/GIC init enter', 51: 'CPU timer/GIC init returned',
          60: 'CPU service publication enter', 61: 'CPU service publication returned'}


def instrument(text):
    if 'volatile uint32_t k70_cpu_start_phase = 0;' in text:
        return text
    anchor = 'bool ArmCpu::start (IOService *provider)\n{'
    begin = text.index(anchor)
    end = text.index('\nvoid ArmCpu::drainPending', begin)
    original = text[begin:end]
    body = original.replace(anchor, anchor + '\n  k70_cpu_phase(1);', 1)
    statements = [
        ('  controller = new IOCPUInterruptController;', 10, 11),
        ('  controller->registerCPUInterruptController ();', 20, 21),
        ('  controller->enableCPUInterrupt (this);', 30, 31),
        ('  initCPU (true);', 50, 51),
        ('  registerService ();', 60, 61),
    ]
    for statement, before, after in statements:
        if body.count(statement) != 1:
            raise ValueError('Pinned CPU start statement changed: ' + statement)
        body = body.replace(statement, f'  k70_cpu_phase({before});\n' + statement +
                            f'\n  k70_cpu_phase({after});')
    for before, after, entry, leave in [
        ('  if ((controller == nullptr)', '    panic ("ArmCpu: CPU interrupt controller allocation failed");\n  }', 12, 13),
        ('  if (controller->registerInterrupt', '    panic ("ArmCpu: CPU IRQ action registration failed");\n  }', 40, 41),
    ]:
        if body.count(before) != 1 or body.count(after) != 1:
            raise ValueError('Pinned CPU controller branch changed')
        body = body.replace(before, f'  k70_cpu_phase({entry});\n' + before)
        body = body.replace(after, after + f'\n  k70_cpu_phase({leave});')
    # Removing only the added statements must recover the complete original
    # function byte-for-byte, including every condition and return value.
    recovered = body
    for phase in PHASES:
        recovered = recovered.replace(f'  k70_cpu_phase({phase});\n', '')
    if recovered != original:
        raise ValueError('CPU observation changed existing control flow')
    body=body.replace('  k70_cpu_phase(10);','  k70_flight_begin();\n  k70_cpu_phase(10);')
    body=body.replace('  k70_cpu_phase(11);','  k70_flight_allocation((uintptr_t)controller);\n  k70_cpu_phase(11);')
    body=body.replace('k70_formal_cpu_online(); return true;','k70_formal_cpu_online(); k70_flight_end(); return true;')
    declaration = '''#include <kern/K70Flight.h>
extern "C" { volatile uint32_t k70_cpu_start_phase = 0; }
static void k70_cpu_phase(uint32_t phase)
{
  __atomic_store_n(&k70_cpu_start_phase, phase, __ATOMIC_RELEASE);
}

'''
    return text[:begin] + declaration + body + text[end:]


def prepare(source):
    source = Path(source)
    original = source.read_text()
    fixed = instrument(original)
    source.write_text(fixed)
    source.with_name('start-boundaries.json').write_text(json.dumps({
        'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
        'after_sha256': hashlib.sha256(fixed.encode()).hexdigest(), 'phases': PHASES,
        'control_flow_changed': False, 'new_mmio': False, 'irq_policy_changed': False,
        'hardware_verified': False}, indent=2) + '\n')
    return source
