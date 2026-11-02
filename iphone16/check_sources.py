"""Bounded source-presence check for the selected XNU22 configuration.

Uses the pinned doconf feature expansion and files' AND/not selectors. This
checks missing inputs, not compiler or runtime compatibility.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess


def check(source, overlay):
    def read(name):
        path = overlay / name
        return (path if path.is_file() else source / name).read_text()
    text = read('config/MASTER') + '\n' + read('config/MASTER.arm64.bcm2837')
    p = subprocess.run(['unifdef', '-t', '-DPLATFORM_iPhoneOS', '-DCPU_arm64',
        '-DSOC_CONFIG_bcm2837', '-DSYS_DEVELOPMENT', '-USOC_IS_VIRTUALIZED', '-'],
        input=text, text=True, capture_output=True)
    if p.returncode not in (0, 1):
        raise ValueError(p.stderr)
    macros = {}
    for name, values in re.findall(r'^#\s*(\w+)\s*=\s*\[([^\]]*)\]', p.stdout, re.M):
        macros.setdefault(name, []).extend(values.split())
    features, pending = set(), ['DEVELOPMENT']
    while pending:
        name = pending.pop()
        if name in macros:
            pending.extend(macros[name])
        else:
            features.add(name)
    options = set()
    for line in p.stdout.splitlines():
        if not line or line.startswith('#'):
            continue
        tag = re.search(r'#\s*<(!?)([^>]*)>\s*$', line)
        if tag:
            selected = any(x in features for x in tag[2].split(','))
            if selected == bool(tag[1]):
                continue
        words = line.split('#', 1)[0].split()
        if len(words) >= 2 and words[0] in ('options', 'pseudo-device'):
            if words[0] == 'pseudo-device' or '=' not in words[1]:
                options.add(words[1].strip('"').lower())
    selected, missing, generated = [], [], []
    for component in ('osfmk', 'bsd', 'iokit', 'libkern', 'pexpert', 'security'):
        for suffix in ('', '.arm64'):
            path = source / component / 'conf' / ('files' + suffix)
            if not path.is_file():
                continue
            content = read(path.relative_to(source).as_posix())
            for line in content.splitlines():
                words = line.split('#', 1)[0].split()
                if len(words) < 2 or words[0].startswith(('OPTIONS/', 'osfmk/OPTIONS/')):
                    continue
                name, kind = words[:2]
                if kind not in ('standard', 'optional'):
                    raise ValueError('Unexpected file selector: ' + line)
                enabled, negate = True, False
                for word in words[2:]:
                    if word.startswith('|') or word in ('device-driver', 'profiling-routine'):
                        break
                    if word in ('xnu-library', 'bound-checks'):
                        continue
                    if word == 'not':
                        negate = not negate
                        continue
                    if kind == 'optional' and ((word in options) == negate):
                        enabled = False
                    negate = False
                if not enabled:
                    continue
                selected.append(name)
                if not (source / name).is_file() and not (overlay / name).is_file():
                    if name.startswith('./') or '|' in line or '/' not in name:
                        generated.append(name)
                    else:
                        missing.append(name)
    sampling_calls = []
    if 'kpc' not in options and 'kperf' not in options:
        for name in sorted(set(selected)):
            if name.startswith('./'):
                continue
            path = overlay / name
            if not path.is_file():
                path = source / name
            if not path.is_file():
                continue
            text = path.read_text()
            if 'kperf_' not in text and 'kpc_' not in text:
                continue
            p = subprocess.run(['unifdef', '-t', '-DKPERF=0', '-DKPC=0', '-'],
                input=text, text=True, capture_output=True)
            if p.returncode not in (0, 1):
                raise ValueError('Cannot preprocess disabled sampling hooks: ' + name)
            text = re.sub(r'/\*.*?\*/', '', p.stdout, flags=re.S)
            for line in text.splitlines():
                line = line.split('//', 1)[0].strip()
                line = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
                if not line.startswith('extern ') and re.search(r'\b(?:kperf|kpc)_\w+\b', line):
                    sampling_calls.append({'file': name, 'line': line})
        if sampling_calls:
            raise ValueError('Disabled sampling symbol still referenced: ' + str(sampling_calls))
    return {'machine': 'BCM2837', 'configuration': 'DEVELOPMENT',
        'kpc_enabled': 'kpc' in options, 'kperf_enabled': 'kperf' in options,
        'selected_source_count': len(selected), 'selected_sources': sorted(set(selected)),
        'disabled_sampling_active_references': sampling_calls,
        'missing': sorted(set(missing)), 'generated_inputs': sorted(set(generated)),
        'scope': 'source presence only; not compilation, ABI or boot proof'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--overlay', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = check(args.source, args.overlay)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result['missing']))
