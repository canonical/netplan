#!/usr/bin/python3
#
# Integration tests for bonds
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
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

import sys
import subprocess
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_bond_base(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovsbr'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'mybond'])
        # XXX: Temporary bridge setup, until netplan-ovs can do it itself
        subprocess.call(['ovs-vsctl', 'add-br', 'ovsbr'])
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    %(ec)s: {}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [%(ec)s, %(e2c)s]
      parameters:
        mode: balance-slb
      openvswitch:
        lacp: off
  bridges:
    ovsbr:
      addresses: [192.170.1.1/24]
      interfaces: [mybond]
      openvswitch: {}''' % {'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge ovsbr', out)
        self.assertIn(b'        Port mybond', out)
        self.assertIn(b'            Interface eth42', out)
        self.assertIn(b'            Interface eth43', out)
        # Verify the bridge was tagged 'netplan:true' correctly
        out = subprocess.check_output(['ovs-vsctl', '--columns=name,external-ids', 'list', 'Port'])
        self.assertIn(b'mybond\nexternal_ids        : {netplan="true"}', out)
        # Verify bond params
        out = subprocess.check_output(['ovs-appctl', 'bond/show', 'mybond'])
        self.assertIn(b'---- mybond ----', out)
        self.assertIn(b'bond_mode: balance-slb', out)
        self.assertIn(b'lacp_status: off', out)
        self.assertIn(b'slave eth42: enabled', out)
        self.assertIn(b'slave eth43: enabled', out)


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestOVS(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
