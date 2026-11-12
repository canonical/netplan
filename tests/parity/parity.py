#!/usr/bin/python3
# Differential "parity" test runner: runs every case against both the Python
# netplan CLI (the reference) and the Rust reimplementation, each in its own
# throw-away sandbox, and reports every observable difference.
#
# Each invocation runs in a private user+mount namespace where /etc/netplan,
# /etc/network, /run, /sys/class/net, /sys/bus/pci, /sys/kernel/debug,
# /usr/lib/netplan and /usr/libexec/netplan are replaced by sandbox
# directories and external commands (systemctl, ip, nmcli, devlink, ...) are
# mocked and logged. Compared:
#
#   exit code, stdout, stderr, the resulting sandbox file tree (content,
#   mode, symlinks) and the sequence of external commands called.
#
# Parity rules (agreed requirements for the Rust rewrite):
#   - help/usage output only needs the same exit code
#   - --debug output need not match (stderr is ignored)
#   - where Python crashes with a traceback, only the exit code and the
#     stderr text before the traceback must match
#
# Usage: tests/parity/parity.py [-k SUBSTRING] [-v] [--build-dir DIR] [--rust-bin PATH]
#
# Copyright (C) 2026 Canonical, Ltd.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import concurrent.futures
import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import cases as case_defs  # noqa: E402

# System path -> sandbox subdirectory (relative to <W>/fs). Everything under
# <W>/fs is snapshotted and compared after each run.
MOUNTS = [
    ('/etc/netplan', 'etc/netplan'),
    ('/etc/network', 'etc/network'),
    ('/run', 'run'),
    ('/sys/class/net', 'sys/class/net'),
    ('/usr/lib/netplan', 'usr/lib/netplan'),
    ('/sys/bus/pci', 'sys/bus/pci'),
    ('/sys/kernel/debug', 'sys/kernel/debug'),
]
MOCKED_COMMANDS = ['ip', 'systemctl', 'udevadm', 'networkctl', 'nmcli', 'busctl',
                   'ethtool', 'resolvectl', 'ovs-vsctl', 'iw']
# Commands called by absolute path: the mock is bind-mounted over the binary
# (which must exist on the host to be a mount point).
MOCKED_PATHS = [('devlink', '/usr/sbin/devlink')]
TRACEBACK = 'Traceback (most recent call last):'
# GLib log lines carry a PID and timestamp: "** (netplan:1234): WARNING **: 21:24:59.157: ..."
GLIB_LOG = re.compile(r'\*\* \(([^:)]+):\d+\): ([A-Z-]+) \*\*: \d\d:\d\d:\d\d\.\d+:')
# g_debug() lines on stdout: "** (process:1234): DEBUG: 21:24:59.157: ..."
GLIB_DEBUG = re.compile(r'\*\* \(([^:)]+):\d+\): ([A-Z-]+): \d\d:\d\d:\d\d\.\d+:')


def default_mocks(case):
    '''Mocks every case gets unless it overrides them: "ip --json link"
    lists the interfaces present in the case's /sys/class/net fixture, so
    code reading either source sees the same system.'''
    ifaces = sorted({p.split('/')[4] for p in case.get('files', {})
                     if p.startswith('/sys/class/net/') and len(p.split('/')) > 4})
    link = [{'ifindex': i + 2, 'ifname': name} for i, name in enumerate(ifaces)]
    mocks = {name: list(rules) for name, rules in case.get('mocks', {}).items()}
    mocks.setdefault('ip', []).append({'argv': ['--json', 'link'], 'stdout': json.dumps(link) + '\n'})
    return mocks


def mock_shim(path, name):
    with open(path, 'w') as f:
        f.write('#!/bin/sh\nexec /usr/bin/python3 -I %s %s "$@"\n' % (os.path.join(HERE, 'mock_cmd.py'), name))
    os.chmod(path, 0o755)


def abs_mock_overlays(case, w):
    '''Mocks at absolute paths (case key "abs_mocks", e.g. ["/usr/bin/ovs-vsctl"]),
    for code that runs a command by its full path rather than via $PATH.
    Each mock is placed in a read-only overlayfs mounted over the closest
    existing ancestor directory of its path, layered above the real
    directory (which stays visible underneath). The mock logs and replays
    exactly like the $PATH mock of the same basename. Returns the
    [lowerdir, target] pairs for sandbox_exec.py.'''
    overlays = {}
    for path in case.get('abs_mocks', []):
        assert os.path.isabs(path), path
        target = os.path.dirname(path)
        while not os.path.isdir(target):
            target = os.path.dirname(target)
        lower = os.path.join(w, 'abs-mocks', target.lstrip('/'))
        overlays[target] = lower
        dest = os.path.join(lower, os.path.relpath(path, target))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        mock_shim(dest, os.path.basename(path))
    # mount parents before children
    return [[overlays[t], t] for t in sorted(overlays, key=lambda t: t.count('/'))]


def run_impl(case, impl, opts):
    '''Run one case against one implementation in a fresh sandbox.'''
    w = tempfile.mkdtemp(prefix='parity-%s-' % impl, dir=opts.workdir)
    fs = os.path.join(w, 'fs')
    root = os.path.join(fs, 'root')
    for _, sub in MOUNTS:
        os.makedirs(os.path.join(fs, sub))
    os.makedirs(root)
    os.makedirs(os.path.join(w, 'home'))

    def resolve(path):
        if path.startswith('{ROOT}/'):
            return os.path.join(root, path[len('{ROOT}/'):])
        for sys_path, sub in MOUNTS:
            if path == sys_path or path.startswith(sys_path + '/'):
                return os.path.join(fs, sub, path[len(sys_path):].lstrip('/'))
        raise ValueError('%s: fixture path %s is outside the sandbox' % (case['id'], path))

    for path, spec in case.get('files', {}).items():
        if isinstance(spec, (str, bytes)):
            spec = {'content': spec}
        dest = resolve(path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if 'symlink' in spec:
            os.symlink(spec['symlink'], dest)
        elif spec.get('dir'):
            os.makedirs(dest, exist_ok=True)
            os.chmod(dest, spec.get('mode', 0o755))
        else:
            content = spec['content']
            with open(dest, 'wb' if isinstance(content, bytes) else 'w') as f:
                f.write(content)
            os.chmod(dest, spec.get('mode', 0o600))

    # The netplan C helpers, as installed under /usr/libexec/netplan
    libexec = os.path.join(w, 'libexec')
    os.makedirs(libexec)
    for name, rel in (('generate', 'src/generate'), ('configure', 'src/configure'),
                      ('netplan-dbus', 'dbus/netplan-dbus')):
        os.symlink(os.path.join(opts.build_dir, rel), os.path.join(libexec, name))

    mocks = os.path.join(w, 'mocks')
    os.makedirs(mocks)
    for name in MOCKED_COMMANDS + [name for name, _ in MOCKED_PATHS]:
        mock_shim(os.path.join(mocks, name), name)
    overlays = abs_mock_overlays(case, w)
    with open(os.path.join(w, 'mock-spec.json'), 'w') as f:
        json.dump(default_mocks(case), f)
    call_log = os.path.join(w, 'calls.jsonl')
    open(call_log, 'w').close()

    env = {
        'PATH': mocks + ':/usr/sbin:/usr/bin:/sbin:/bin',
        'LD_LIBRARY_PATH': os.path.join(opts.build_dir, 'src'),
        'PYTHONPATH': os.path.join(opts.build_dir, 'python-cffi') + ':' + REPO,
        'PYTHONDONTWRITEBYTECODE': '1',
        'LANG': 'C.UTF-8',
        'HOME': os.path.join(w, 'home'),
        'PARITY_CALL_LOG': call_log,
        'PARITY_MOCK_SPEC': os.path.join(w, 'mock-spec.json'),
    }
    env.update(case.get('env', {}))

    argv = [a.replace('{ROOT}', root) for a in case['argv']]
    if impl == 'py':
        argv = ['/usr/bin/python3', os.path.join(REPO, 'src', 'netplan.script')] + argv
    else:
        argv = [opts.rust_bin] + argv

    spec_path = os.path.join(w, 'spec.json')
    result_path = os.path.join(w, 'result.json')
    with open(spec_path, 'w') as f:
        json.dump({
            'mounts': [[os.path.join(fs, sub), sys_path] for sys_path, sub in MOUNTS] +
                      [[libexec, '/usr/libexec/netplan']] +
                      [[os.path.join(mocks, name), path] for name, path in MOCKED_PATHS if os.path.exists(path)],
            'overlays': overlays,
            'argv': argv,
            'env': env,
            'cwd': os.path.join(w, 'home'),
            'timeout': case.get('timeout', 30),
            'result': result_path,
        }, f)
    subprocess.run(['unshare', '--user', '--map-root-user', '--mount', '--propagation', 'private',
                    '/usr/bin/python3', '-I', os.path.join(HERE, 'sandbox_exec.py'), spec_path], check=True)

    with open(result_path) as f:
        result = json.load(f)
    with open(call_log) as f:
        result['calls'] = [json.loads(line) for line in f]
    result['files'] = snapshot(fs)

    def norm(s):
        s = GLIB_LOG.sub(r'** (\1:PID): \2 **: TIME:', s)
        s = GLIB_DEBUG.sub(r'** (\1:PID): \2: TIME:', s)
        return s.replace(root, '<ROOT>').replace(fs, '').replace(w, '<W>')
    result['stdout'] = norm(result['stdout'])
    result['stderr'] = norm(result['stderr'])
    result['calls'] = [norm(json.dumps(c)) for c in result['calls']]
    result['files'] = [norm(line) for line in result['files']]

    if not opts.keep:
        shutil.rmtree(w, ignore_errors=True)
    return result


def snapshot(fs):
    '''Describe a directory tree as sorted text lines (one per entry).'''
    out = []
    for dirpath, dirnames, filenames in os.walk(fs):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            p = os.path.join(dirpath, name)
            rel = '/' + os.path.relpath(p, fs)
            st = os.lstat(p)
            mode = '%04o' % stat.S_IMODE(st.st_mode)
            if stat.S_ISLNK(st.st_mode):
                out.append('%s -> %s' % (rel, os.readlink(p)))
            elif stat.S_ISDIR(st.st_mode):
                out.append('%s/ %s' % (rel, mode))
            else:
                try:
                    with open(p, 'rb') as f:
                        data = f.read()
                except PermissionError:
                    out.append('%s %s <unreadable>' % (rel, mode))
                    continue
                try:
                    text = data.decode('utf-8')
                    body = '\n    | ' + '\n    | '.join(text.split('\n')) if text else ''
                except UnicodeDecodeError:
                    body = ' sha256:' + hashlib.sha256(data).hexdigest()
                out.append('%s %s%s' % (rel, mode, body))
    return out


def compare(case, py, rs):
    '''Return a list of (aspect, python_value, rust_value) differences.'''
    diffs = []
    argv = case['argv']
    usage = (py['exit'] in (2, 64) and 'usage:' in py['stderr']) or \
        any(a in ('-h', '--help', 'help') for a in argv)
    debug = '--debug' in argv

    if py['timed_out'] != rs['timed_out']:
        diffs.append(('timeout', py['timed_out'], rs['timed_out']))
    if py['exit'] != rs['exit']:
        diffs.append(('exit', py['exit'], rs['exit']))
    if not usage:
        if py['stdout'] != rs['stdout']:
            diffs.append(('stdout', py['stdout'], rs['stdout']))
        if TRACEBACK in py['stderr']:
            prefix = py['stderr'].split(TRACEBACK)[0]
            if not rs['stderr'].startswith(prefix):
                diffs.append(('stderr-prefix', prefix, rs['stderr']))
        elif not debug and py['stderr'] != rs['stderr']:
            diffs.append(('stderr', py['stderr'], rs['stderr']))
    if py['files'] != rs['files']:
        diffs.append(('files', '\n'.join(py['files']), '\n'.join(rs['files'])))
    if py['calls'] != rs['calls']:
        diffs.append(('calls', '\n'.join(py['calls']), '\n'.join(rs['calls'])))
    return diffs


def run_case(case, opts):
    py = run_impl(case, 'py', opts)
    rs = run_impl(case, 'rs', opts)
    return case, compare(case, py, rs)


def show_diff(aspect, a, b, limit):
    if not isinstance(a, str) or not isinstance(b, str):
        return ['    python: %r' % (a,), '    rust:   %r' % (b,)]
    lines = list(difflib.unified_diff(a.split('\n'), b.split('\n'), 'python', 'rust', lineterm='', n=2))
    if len(lines) > limit:
        lines = lines[:limit] + ['... (%d more lines)' % (len(lines) - limit)]
    return ['    ' + line for line in lines]


def main():
    ap = argparse.ArgumentParser(description='Compare the Python and Rust netplan CLIs')
    ap.add_argument('-k', dest='filter', help='only run cases whose id contains this substring')
    ap.add_argument('-v', '--verbose', action='store_true', help='show diffs of known differences too')
    ap.add_argument('--build-dir', default=os.path.join(REPO, '_build'), help='meson build directory')
    ap.add_argument('--rust-bin', default=os.path.join(REPO, 'netplan_cli_rs', 'target', 'release', 'netplan'))
    ap.add_argument('--workdir', default=None, help='where to create sandboxes (default: $TMPDIR)')
    ap.add_argument('--keep', action='store_true', help='keep sandboxes for inspection')
    ap.add_argument('--jobs', type=int, default=os.cpu_count())
    ap.add_argument('--diff-lines', type=int, default=40, help='max diff lines shown per aspect')
    opts = ap.parse_args()
    opts.build_dir = os.path.abspath(opts.build_dir)
    opts.rust_bin = os.path.abspath(opts.rust_bin)

    with open(os.path.join(HERE, 'known_diffs.yaml')) as f:
        known = yaml.safe_load(f) or {}

    all_cases = case_defs.all_cases()
    ids = [c['id'] for c in all_cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        sys.exit('duplicate case ids: %s' % ', '.join(sorted(dupes)))
    selected = [c for c in all_cases if not opts.filter or opts.filter in c['id']]

    with concurrent.futures.ThreadPoolExecutor(max_workers=opts.jobs) as pool:
        results = list(pool.map(lambda c: run_case(c, opts), selected))

    unexpected, known_hit, stale = [], [], []
    for case, diffs in results:
        k = known.get(case['id'])
        if diffs and k:
            known_hit.append((case, diffs, k))
        elif diffs:
            unexpected.append((case, diffs))
        elif k:
            stale.append(case)

    for title, items in (('UNEXPECTED DIFFERENCES', unexpected),
                         ('KNOWN DIFFERENCES', known_hit if opts.verbose else [])):
        if items:
            print('==== %s ====' % title)
        for item in items:
            case, diffs = item[0], item[1]
            print('\n--- %s: netplan %s' % (case['id'], ' '.join(case['argv'])))
            if len(item) > 2:
                print('    known: %s' % item[2])
            for aspect, a, b in diffs:
                print('  [%s]' % aspect)
                print('\n'.join(show_diff(aspect, a, b, opts.diff_lines)))
        if items:
            print()

    for case in stale:
        print('NOTE: %s is listed in known_diffs.yaml but now matches; remove it' % case['id'])
    print('%d cases: %d match, %d known differences, %d unexpected differences' % (
        len(results), len(results) - len(unexpected) - len(known_hit), len(known_hit), len(unexpected)))
    sys.exit(1 if unexpected else 0)


if __name__ == '__main__':
    main()
