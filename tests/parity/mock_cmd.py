#!/usr/bin/python3
# Stand-in for an external command (systemctl, ip, nmcli, ...) inside the
# parity sandbox. Logs every invocation and replays canned output.
#
# Invoked as: mock_cmd.py <command-name> [args...]
#
# Rules are read from $PARITY_MOCK_SPEC: {"<command>": [rule, ...]} where a
# rule is {"argv": [...]} (exact match) or {"prefix": [...]} (prefix match) or
# neither (matches anything), plus optional "stdout", "stderr" and "exit".
# The first matching rule wins; no match means exit 0 with no output.
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
import sys


def matches(rule, args):
    if 'argv' in rule:
        return rule['argv'] == args
    if 'prefix' in rule:
        return args[:len(rule['prefix'])] == rule['prefix']
    return True


def main():
    name, args = sys.argv[1], sys.argv[2:]

    with open(os.environ['PARITY_CALL_LOG'], 'a') as f:
        f.write(json.dumps({'cmd': name, 'argv': args}) + '\n')

    with open(os.environ['PARITY_MOCK_SPEC']) as f:
        rules = json.load(f).get(name, [])
    for rule in rules:
        if matches(rule, args):
            sys.stdout.write(rule.get('stdout', ''))
            sys.stderr.write(rule.get('stderr', ''))
            sys.exit(rule.get('exit', 0))
    sys.exit(0)


if __name__ == '__main__':
    main()
