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
import subprocess
import sys


def main():
    with open(sys.argv[1]) as f:
        spec = json.load(f)

    for src, dst in spec['mounts']:
        subprocess.run(['mount', '--bind', src, dst], check=True)

    result = {'timed_out': False}
    try:
        p = subprocess.run(spec['argv'], env=spec['env'], cwd=spec['cwd'],
                           stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=spec['timeout'])
        result['exit'] = p.returncode
        stdout, stderr = p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        result['exit'] = None
        result['timed_out'] = True
        stdout, stderr = e.stdout or b'', e.stderr or b''
    result['stdout'] = stdout.decode('utf-8', errors='replace')
    result['stderr'] = stderr.decode('utf-8', errors='replace')

    with open(spec['result'], 'w') as f:
        json.dump(result, f)


if __name__ == '__main__':
    main()
