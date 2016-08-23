#!/usr/bin/python3
# Blackbox tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2016 Canonical, Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
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

import os
import sys
import subprocess
import unittest
import tempfile
import shutil

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe_cli = [os.path.join(rootdir, 'src', 'netplan')]
if shutil.which('python3-coverage'):
    exe_cli = ['python3-coverage', 'run', '--append', '--'] + exe_cli


class TestArgs(unittest.TestCase):
    '''Generic argument parsing tests'''

    def test_global_help(self):
        out = subprocess.check_output(exe_cli + ['--help'])
        self.assertIn(b'Available commands', out)
        self.assertIn(b'generate', out)
        self.assertIn(b'--debug', out)

    def test_command_help(self):
        out = subprocess.check_output(exe_cli + ['generate', '--help'])
        self.assertIn(b'--root-dir', out)

    def test_no_command(self):
        os.environ['NETPLAN_GENERATE_PATH'] = os.path.join(rootdir, 'generate')
        p = subprocess.Popen(exe_cli, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        self.assertEqual(out, b'')
        self.assertIn(b'need to specify a command', err)
        self.assertNotEqual(p.returncode, 0)


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()

    def test_no_config(self):
        out = subprocess.check_output(exe_cli + ['generate', '--root-dir', self.workdir.name])
        self.assertEqual(out, b'')
        self.assertEqual(os.listdir(self.workdir.name), [])

    def test_with_config(self):
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        with open(os.path.join(c, 'a.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    enlol: {dhcp4: yes}''')
        out = subprocess.check_output(exe_cli + ['generate', '--root-dir', self.workdir.name])
        self.assertEqual(out, b'')
        self.assertEqual(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd', 'network')),
                         ['10-netplan-enlol.network'])


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
