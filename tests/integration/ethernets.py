#!/usr/bin/python3
#
# Integration tests for ethernet devices and features common to all device
# types.
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

from base import IntegrationTestsBase, nm_uses_dnsmasq, resolved_in_use, test_backends


class _CommonTests():

    def test_eth_mtu(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: yes
    enmtus:
      match: {name: %(e2c)s}
      mtu: 1492
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assert_iface_up(self.dev_e2_client,
                             ['inet 192.168.6.[0-9]+/24'])
        out = subprocess.check_output(['ip', 'a', 'show', self.dev_e2_client],
                                      universal_newlines=True)
        self.assertTrue('mtu 1492' in out, "checking MTU, should be 1492")

    def test_eth_mac(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: yes
    enmac:
      match: {name: %(e2c)s}
      macaddress: 00:01:02:03:04:05
      dhcp4: yes''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e2_client,
                             ['inet 192.168.6.[0-9]+/24', '00:01:02:03:04:05'],
                             ['master'])
        out = subprocess.check_output(['ip', 'link', 'show', self.dev_e2_client],
                                      universal_newlines=True)
        self.assertTrue('ether 00:01:02:03:04:05' in out)
        subprocess.check_call(['ip', 'link', 'set', self.dev_e2_client,
                               'address', self.dev_e2_client_mac])

    def test_manual_addresses(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses: ["172.16.42.99/18", "1234:FFFF::42/64"]
      dhcp4: yes
    %(e2c)s:
      addresses: ["172.16.1.2/24"]
      gateway4: "172.16.1.1"
      nameservers:
        addresses: [172.1.2.3]
        search: ["fakesuffix"]
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        if self.backend == 'NetworkManager':
            self.nm_online_full(self.dev_e_client)
        self.assert_iface_up(self.dev_e_client,
                             ['inet 172.16.42.99/18',
                              'inet6 1234:ffff::42/64',
                              'inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assert_iface_up(self.dev_e2_client,
                             ['inet 172.16.1.2/24'])

        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'default via 172.16.1.1',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e2_client]))
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e2_client]))

        # ensure that they do not get managed by NM for foreign backends
        expected_state = (self.backend == 'NetworkManager') and 'connected' or 'unmanaged'
        out = subprocess.check_output(['nmcli', 'dev'], universal_newlines=True)
        for i in [self.dev_e_client, self.dev_e2_client]:
            self.assertRegex(out, r'%s\s+(ethernet|bridge)\s+%s' % (i, expected_state))

        with open('/etc/resolv.conf') as f:
                resolv_conf = f.read()

        if self.backend == 'NetworkManager' and nm_uses_dnsmasq:
            sys.stdout.write('[NM with dnsmasq] ')
            sys.stdout.flush()
            self.assertRegex(resolv_conf, 'search.*fakesuffix')
            # not easy to peek dnsmasq's brain, so check its logging
            out = subprocess.check_output(['journalctl', '--quiet', '-tdnsmasq', '-ocat', '--since=-30s'],
                                          universal_newlines=True)
            self.assertIn('nameserver 172.1.2.3', out)
        elif resolved_in_use():
            sys.stdout.write('[resolved] ')
            sys.stdout.flush()
            out = subprocess.check_output(['systemd-resolve', '--status'], universal_newlines=True)
            self.assertIn('DNS Servers: 172.1.2.3', out)
            self.assertIn('fakesuffix', out)
        else:
            sys.stdout.write('[/etc/resolv.conf] ')
            sys.stdout.flush()
            self.assertRegex(resolv_conf, 'search.*fakesuffix')
            # /etc/resolve.conf often already has three nameserver entries
            if 'nameserver 172.1.2.3' not in resolv_conf:
                self.assertGreaterEqual(resolv_conf.count('nameserver'), 3)

        # change the addresses, make sure that "apply" does not leave leftovers
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses: ["172.16.5.3/20", "9876:BBBB::11/70"]
      gateway6: "9876:BBBB::1"
    %(e2c)s:
      addresses: ["172.16.7.2/30", "4321:AAAA::99/80"]
      dhcp4: yes
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.start_dnsmasq(None, self.dev_e2_ap)
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 172.16.5.3/20'],
                             ['inet 192.168.5',   # old DHCP
                              'inet 172.16.42',   # old static IPv4
                              'inet6 1234'])      # old static IPv6
        self.assert_iface_up(self.dev_e2_client,
                             ['inet 172.16.7.2/30',
                              'inet6 4321:aaaa::99/80',
                              'inet 192.168.6.[0-9]+/24'],  # from DHCP
                             ['inet 172.16.1'])   # old static IPv4

        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'via 9876:bbbb::1',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'default']))
        self.assertIn(b'default via 192.168.6.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e2_client]))
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e2_client]))

    def test_dhcp6(self):
        self.setup_eth('slaac')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp6: yes
      accept-ra: yes
    %(e2c)s: {}''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client, ['inet6 2600:'], ['inet 192.168'])


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    def test_eth_dhcp6_off(self):
        self.setup_eth('slaac')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp6: no
      accept-ra: yes
      addresses: [ '192.168.1.100/24' ]
    %(e2c)s: {}''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client, ['inet6 2600:'], [])

    def test_eth_dhcp6_off_no_accept_ra(self):
        self.setup_eth('slaac')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp6: no
      accept-ra: no
      addresses: [ '192.168.1.100/24' ]
    %(e2c)s: {}''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client, [], ['inet6 2600:'])


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'

    @unittest.skip("NetworkManager does not disable accept_ra: bug LP: #1704210")
    def test_eth_dhcp6_off(self):
        self.setup_eth('slaac')
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp6: no
      addresses: [ '192.168.1.100/24' ]
    %(e2c)s: {}''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client, [], ['inet6 2600:'])


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
