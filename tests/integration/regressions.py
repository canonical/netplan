#!/usr/bin/python3
# 
# Regression tests to catch previously-fixed issues.
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

import sys
import subprocess
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_empty_yaml_lp1795343(self):
        with open(self.config, 'w') as f:
            f.write('''''')
        self.generate_and_settle()


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    def test_lp1802322_bond_mac_rename(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn1:
      match: {name: %(ec)s}
      dhcp4: no
    ethbn2:
      match: {name: %(e2c)s}
      dhcp4: no
  bonds:
    mybond:
      interfaces: [ethbn1, ethbn2]
      macaddress: 00:0a:f7:72:a7:28
      mtu: 9000
      addresses: [ 192.168.5.9/24 ]
      gateway4: 192.168.5.1
      parameters:
        down-delay: 0
        lacp-rate: fast
        mii-monitor-interval: 100
        mode: 802.3ad
        transmit-hash-policy: layer3+4
        up-delay: 0
      ''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond', '00:0a:f7:72:a7:28'],
                             ['inet '])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybond', '00:0a:f7:72:a7:28'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertIn(self.dev_e_client, f.read().strip())


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
