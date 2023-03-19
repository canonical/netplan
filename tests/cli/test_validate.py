#!/usr/bin/python3
# Functional tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2023 Canonical, Ltd.
# Author: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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
import unittest
from unittest.mock import patch
import tempfile
import shutil
import sys


from netplan.cli.commands.validate import ValidationException
from netplan.cli.core import Netplan

from tests.test_utils import call_cli


class TestValidate(unittest.TestCase):
    '''Test netplan set'''
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory(prefix='netplan_')
        self.file = '70-netplan-set.yaml'
        self.path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'etc', 'netplan'))

    def tearDown(self):
        shutil.rmtree(self.workdir.name)

    def _validate(self, debug=False):
        args = ['validate', '--root-dir', self.workdir.name]
        if debug:
            args.append('--debug')
        return call_cli(args)

    def test_validate_raises_no_exceptions(self):
        with open(self.path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0:
                  dhcp4: false''')

        self._validate()

    def test_validate_raises_exception(self):
        with open(self.path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0:
                  dhcp4: nothanks''')

        with self.assertRaises(ValidationException) as e:
            self._validate()
        self.assertIn('invalid boolean value', str(e.exception))

    def test_validate_raises_exception_main_function(self):
        with open(self.path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0:
                  dhcp4: nothanks''')

        with patch('logging.warning') as log, patch('sys.exit') as exit_mock:
            exit_mock.return_value = 1

            old_argv = sys.argv
            args = ['validate', '--root-dir', self.workdir.name]
            sys.argv = [old_argv[0]] + args

            Netplan().main()

            # The idea was to capture stderr here but for some reason
            # any attempt to mock sys.stderr didn't work with pytest
            args = log.call_args.args
            self.assertIn('invalid boolean value', args[0])

            sys.argv = old_argv

    def test_validate_debug_single_file(self):
        with open(self.path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0:
                  dhcp4: false''')

        output = self._validate(debug=True)
        self.assertIn('70-netplan-set.yaml', output)

    def test_validate_debug_with_shadow(self):
        with open(self.path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0:
                  dhcp4: false''')

        path = os.path.join(self.workdir.name, 'run', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'run', 'netplan'))

        with open(path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0:
                  dhcp4: false''')

        output = self._validate(debug=True)

        lines = output.split('\n')
        highest_priority_file = lines[1]
        self.assertIn('run/netplan/70-netplan-set.yaml', highest_priority_file)

        self.assertIn('The following files were shadowed', output)

    def test_validate_debug_order(self):
        os.makedirs(os.path.join(self.workdir.name, 'run', 'netplan'))
        os.makedirs(os.path.join(self.workdir.name, 'lib', 'netplan'))

        path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        with open(self.path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0: {}''')

        path = os.path.join(self.workdir.name, 'run', 'netplan', '90-config.yaml')
        with open(path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0: {}''')

        path = os.path.join(self.workdir.name, 'lib', 'netplan', '99-zzz.yaml')
        with open(path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0: {}''')

        path = os.path.join(self.workdir.name, 'run', 'netplan', '00-aaa.yaml')
        with open(path, 'w') as f:
            f.write('''network:
              ethernets:
                eth0: {}''')

        output = self._validate(debug=True)
        lines = output.split('\n')

        self.assertIn('run/netplan/00-aaa.yaml', lines[1])
        self.assertIn('etc/netplan/70-netplan-set.yaml', lines[2])
        self.assertIn('run/netplan/90-config.yaml', lines[3])
        self.assertIn('lib/netplan/99-zzz.yaml', lines[4])
