#!/usr/bin/python3
# Runs inside a private user+mount namespace (see parity.py): bind-mounts the
# sandbox directories over the system paths the netplan CLI touches, runs a
# single CLI invocation and records its exit code and output.
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

import json
import os
import signal
import subprocess
import sys
import time


def main():
    with open(sys.argv[1]) as f:
        spec = json.load(f)

    # Absolute-path mocks: read-only overlays (mock dir above the real one)
    for lower, dst in spec.get('overlays', []):
        subprocess.run(['mount', '-t', 'overlay', 'overlay', '-o', 'lowerdir=%s:%s' % (lower, dst), dst],
                       check=True)
    for src, dst in spec['mounts']:
        subprocess.run(['mount', '--bind', src, dst], check=True)

    result = {'timed_out': False}
    sig = spec.get('signal')
    # With a signal to send, stdin stays open (and empty) so that 'netplan
    # try' keeps waiting for confirmation, as it does under netplan-dbus.
    p = subprocess.Popen(spec['argv'], env=spec['env'], cwd=spec['cwd'],
                         stdin=subprocess.PIPE if sig else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if sig:
        # Send a signal once a file appears, like netplan-dbus does with
        # the 'netplan try' ready stamp (SIGINT: Cancel, SIGUSR1: Apply).
        deadline = time.monotonic() + spec['timeout']
        while not os.path.exists(sig['when_exists']) and p.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if p.poll() is None:
            time.sleep(0.5)  # let it reach the confirmation prompt
            p.send_signal(getattr(signal, sig['signal']))
    try:
        stdout, stderr = p.communicate(timeout=spec['timeout'])
        result['exit'] = p.returncode
    except subprocess.TimeoutExpired:
        p.kill()
        stdout, stderr = p.communicate()
        result['exit'] = None
        result['timed_out'] = True
    result['stdout'] = stdout.decode('utf-8', errors='replace')
    result['stderr'] = stderr.decode('utf-8', errors='replace')

    with open(spec['result'], 'w') as f:
        json.dump(result, f)


if __name__ == '__main__':
    main()
