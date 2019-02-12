#!/usr/bin/python3
#
# Test runner for netplan integration tests.
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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
import glob
import os
import subprocess
import textwrap
import sys

tests_dir = os.path.dirname(os.path.abspath(__file__))

default_backends = [ 'networkd', 'NetworkManager' ]
fixtures = [ "__init__.py", "base.py", "run.py" ]

possible_tests = []
testfiles = glob.glob(os.path.join(tests_dir, "*.py"))
for pyfile in testfiles:
    filename = os.path.basename(pyfile)
    if filename not in fixtures:
        possible_tests.append(filename.split('.')[0])

def dedupe(duped_list):
    deduped = set()
    for item in duped_list:
        real_items = item.split(",")
        for real_item in real_items:
            deduped.add(real_item)
    return deduped

# XXX: omg, this is ugly :)
parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description=textwrap.dedent("""
Test runner for netplan integration tests

Available tests:
{}
""".format("\n".join("    - {}".format(x) for x in sorted(possible_tests)))))

parser.add_argument('--test', action='append', help="List of tests to be run")
parser.add_argument('--backend', action='append', help="List of backends to test (NetworkManager, networkd)")

args = parser.parse_args()

requested_tests = set()
backends = set()

if args.test is not None:
    requested_tests = dedupe(args.test)
else:
    requested_tests.update(possible_tests)

if args.backend is not None:
    backends = dedupe(args.backend)
else:
    backends.update(default_backends)

os.environ["NETPLAN_TEST_BACKENDS"] = ",".join(backends)

returncode = 0
for test in requested_tests:
    ret = subprocess.call(['python3', os.path.join(tests_dir, "{}.py".format(test))])
    if returncode == 0 and ret != 0:
        returncode = ret

sys.exit(returncode)
