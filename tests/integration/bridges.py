#!/usr/bin/python3
#
# Integration tests for bridges
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
import time
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_eth_and_bridge(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: yes
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])

        # ensure that they do not get managed by NM for foreign backends
        expected_state = (self.backend == 'NetworkManager') and 'connected' or 'unmanaged'
        out = subprocess.check_output(['nmcli', 'dev'], universal_newlines=True)
        for i in [self.dev_e_client, self.dev_e2_client, 'mybr']:
            self.assertRegex(out, r'%s\s+(ethernet|bridge)\s+%s' % (i, expected_state))

    def test_bridge_path_cost(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        path-cost:
          ethbr: 50
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/brif/%s/path_cost' % self.dev_e2_client) as f:
            self.assertEqual(f.read().strip(), '50')

    def test_bridge_ageing_time(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        ageing-time: 21
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/ageing_time') as f:
            self.assertEqual(f.read().strip(), '2100')

    def test_bridge_max_age(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        max-age: 12
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/max_age') as f:
            self.assertEqual(f.read().strip(), '1200')

    def test_bridge_hello_time(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        hello-time: 1
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/hello_time') as f:
            self.assertEqual(f.read().strip(), '100')

    def test_bridge_forward_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        forward-delay: 10
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/forward_delay') as f:
            self.assertEqual(f.read().strip(), '1000')

    def test_bridge_stp_false(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        hello-time: 100000
        max-age: 100000
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/stp_state') as f:
            self.assertEqual(f.read().strip(), '0')


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    def test_bridge_mac(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br0'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match:
        name: %(ec)s
        macaddress: %(ec_mac)s
  bridges:
    br0:
      interfaces: [ethbr]
      macaddress: 00:01:02:03:04:05
      dhcp4: yes''' % {'r': self.backend,
                       'ec': self.dev_e_client,
                       'e2c': self.dev_e2_client,
                       'ec_mac': self.dev_e_client_mac})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master br0'], ['inet'])
        self.assert_iface_up('br0',
                             ['inet 192.168.5.[0-9]+/24', '00:01:02:03:04:05'])

    def test_bridge_anonymous(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             [],
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])

    def test_bridge_isolated(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: []
      addresses: [10.10.10.10/24]''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        subprocess.check_call(['netplan', 'apply'])
        time.sleep(1)
        out = subprocess.check_output(['ip', 'a', 'show', 'dev', 'mybr'],
                                      universal_newlines=True)
        self.assertIn('inet 10.10.10.10/24', out)

    def test_bridge_port_priority(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        port-priority:
          ethbr: 42
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/brif/%s/priority' % self.dev_e2_client) as f:
            self.assertEqual(f.read().strip(), '42')


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'

    @unittest.skip("NetworkManager does not support setting MAC for a bridge")
    def test_bridge_mac(self):
        pass

    def test_bridge_priority(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        priority: 16384
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/bridge/priority') as f:
            self.assertEqual(f.read().strip(), '16384')

    def test_bridge_port_priority(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybr'], stderr=subprocess.DEVNULL)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbr:
      match: {name: %(e2c)s}
  bridges:
    mybr:
      interfaces: [ethbr]
      parameters:
        port-priority:
          ethbr: 42
        stp: false
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybr'],
                             ['inet '])
        self.assert_iface_up('mybr',
                             ['inet 192.168.6.[0-9]+/24'])
        lines = subprocess.check_output(['bridge', 'link', 'show', 'mybr'],
                                        universal_newlines=True).splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(self.dev_e2_client, lines[0])
        with open('/sys/class/net/mybr/brif/%s/priority' % self.dev_e2_client) as f:
            self.assertEqual(f.read().strip(), '42')


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
