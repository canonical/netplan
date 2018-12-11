#!/usr/bin/python3
#
# Integration tests for bonds
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

    def test_bond_base(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)

    def test_bond_primary_slave(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s: {}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [%(ec)s, %(e2c)s]
      parameters:
        mode: active-backup
        primary: %(ec)s
      addresses: [ '10.10.10.1/24' ]''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 10.10.10.1/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            result = f.read().strip()
            self.assertIn(self.dev_e_client, result)
            self.assertIn(self.dev_e2_client, result)
        with open('/sys/class/net/mybond/bonding/primary') as f:
            self.assertEqual(f.read().strip(), '%(ec)s' % {'ec': self.dev_e_client})

    def test_bond_all_slaves_active(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        all-slaves-active: true
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/all_slaves_active') as f:
            self.assertEqual(f.read().strip(), '1')

    def test_bond_mode_8023ad(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: 802.3ad
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), '802.3ad 4')

    def test_bond_mode_8023ad_adselect(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: 802.3ad
        ad-select: bandwidth
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/ad_select') as f:
            self.assertEqual(f.read().strip(), 'bandwidth 1')

    def test_bond_mode_8023ad_lacp_rate(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: 802.3ad
        lacp-rate: fast
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/lacp_rate') as f:
            self.assertEqual(f.read().strip(), 'fast 1')

    def test_bond_mode_activebackup_failover_mac(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: active-backup
        fail-over-mac-policy: follow
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'active-backup 1')
        with open('/sys/class/net/mybond/bonding/fail_over_mac') as f:
            self.assertEqual(f.read().strip(), 'follow 2')

    def test_bond_mode_balance_xor(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: balance-xor
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'balance-xor 2')

    def test_bond_mode_balance_rr(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: balance-rr
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'balance-rr 0')

    def test_bond_mode_balance_rr_pps(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: balance-rr
        packets-per-slave: 15
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'balance-rr 0')
        with open('/sys/class/net/mybond/bonding/packets_per_slave') as f:
            self.assertEqual(f.read().strip(), '15')

    def test_bond_resend_igmp(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  bonds:
    mybond:
      interfaces: [ethbn, ethb2]
      parameters:
        mode: balance-rr
        mii-monitor-interval: 50s
        resend-igmp: 100
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            result = f.read().strip()
            self.assertIn(self.dev_e_client, result)
            self.assertIn(self.dev_e2_client, result)
        with open('/sys/class/net/mybond/bonding/resend_igmp') as f:
            self.assertEqual(f.read().strip(), '100')


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    def test_bond_mac(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match:
        name: %(ec)s
        macaddress: %(ec_mac)s
  bonds:
    mybond:
      interfaces: [ethbn]
      macaddress: 00:01:02:03:04:05
      dhcp4: yes''' % {'r': self.backend,
                       'ec': self.dev_e_client,
                       'e2c': self.dev_e2_client,
                       'ec_mac': self.dev_e_client_mac})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24', '00:01:02:03:04:05'])

    def test_bond_down_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: active-backup
        mii-monitor-interval: 5
        down-delay: 10s
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/downdelay') as f:
            self.assertEqual(f.read().strip(), '10000')

    def test_bond_up_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: active-backup
        mii-monitor-interval: 5
        up-delay: 10000
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/updelay') as f:
            self.assertEqual(f.read().strip(), '10000')

    def test_bond_arp_interval(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [ 192.168.5.1 ]
        arp-interval: 50s
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_interval') as f:
            self.assertEqual(f.read().strip(), '50000')

    def test_bond_arp_targets(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-interval: 50000
        arp-ip-targets: [ 192.168.5.1 ]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_ip_target') as f:
            self.assertEqual(f.read().strip(), '192.168.5.1')

    def test_bond_arp_all_targets(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [192.168.5.1]
        arp-interval: 50000
        arp-all-targets: all
        arp-validate: all
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_all_targets') as f:
            self.assertEqual(f.read().strip(), 'all 1')

    def test_bond_arp_validate(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [192.168.5.1]
        arp-interval: 50000
        arp-validate: all
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_validate') as f:
            self.assertEqual(f.read().strip(), 'all 3')


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'

    @unittest.skip("NetworkManager does not support setting MAC for a bond")
    def test_bond_mac(self):
        pass

    def test_bond_down_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: active-backup
        mii-monitor-interval: 5
        down-delay: 10000
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/downdelay') as f:
            self.assertEqual(f.read().strip(), '10000')

    def test_bond_up_delay(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: active-backup
        mii-monitor-interval: 5
        up-delay: 10000
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/updelay') as f:
            self.assertEqual(f.read().strip(), '10000')

    def test_bond_arp_interval(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [ 192.168.5.1 ]
        arp-interval: 50000
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_interval') as f:
            self.assertEqual(f.read().strip(), '50000')

    def test_bond_arp_targets(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-interval: 50000
        arp-ip-targets: [ 192.168.5.1 ]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_ip_target') as f:
            self.assertEqual(f.read().strip(), '192.168.5.1')

    def test_bond_arp_all_targets(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [ethbn]
      parameters:
        mode: balance-xor
        arp-ip-targets: [192.168.5.1]
        arp-interval: 50000
        arp-all-targets: all
        arp-validate: all
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/arp_all_targets') as f:
            self.assertEqual(f.read().strip(), 'all 1')

    def test_bond_mode_balance_tlb_learn_interval(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    %(e2c)s: {}
  bonds:
    mybond:
      parameters:
        mode: balance-tlb
        mii-monitor-interval: 5
        learn-packet-interval: 15
      interfaces: [ethbn]
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond'],
                             ['inet '])
        self.assert_iface_up('mybond',
                             ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:
            self.assertEqual(f.read().strip(), self.dev_e_client)
        with open('/sys/class/net/mybond/bonding/mode') as f:
            self.assertEqual(f.read().strip(), 'balance-tlb 5')
        with open('/sys/class/net/mybond/bonding/lp_interval') as f:
            self.assertEqual(f.read().strip(), '15')


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
