#!/usr/bin/python3
#
# Integration tests for routing functions
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

    @unittest.skip("fails due to networkd bug setting routes with dhcp")
    def test_routes_v4_with_dhcp(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: yes
      routes:
          - to: 10.10.10.0/24
            via: 192.168.5.254
            metric: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'10.10.10.0/24 via 192.168.5.254',  # from static route
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 99',  # check metric from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_routes_v4(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses:
          - 192.168.5.99/24
      gateway4: 192.168.5.1
      routes:
          - to: 10.10.10.0/24
            via: 192.168.5.254
            metric: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'10.10.10.0/24 via 192.168.5.254',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 99',  # check metric from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_routes_v6(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses: ["9876:BBBB::11/70"]
      gateway6: "9876:BBBB::1"
      routes:
          - to: 2001:f00f:f00f::1/64
            via: 9876:BBBB::5
            metric: 799''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet6 9876:bbbb::11/70'])
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'via 9876:bbbb::1',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'default']))
        self.assertIn(b'2001:f00f:f00f::/64 via 9876:bbbb::5',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 799',
                      subprocess.check_output(['ip', '-6', 'route', 'show', '2001:f00f:f00f::/64']))



@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    def test_link_route_v4(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses:
          - 192.168.5.99/24
      gateway4: 192.168.5.1
      routes:
          - to: 10.10.10.0/24
            scope: link
            metric: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'10.10.10.0/24 proto static scope link',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 99',  # check metric from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    @unittest.skip("networkd does not handle non-unicast routes correctly yet (Invalid argument)")
    def test_route_type_blackhole(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      addresses: [ "10.20.10.1/24" ]
      routes:
        - to: 10.10.10.0/24
          via: 10.20.10.100
          type: blackhole''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet '])
        self.assertIn(b'blackhole 10.10.10.0/24',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))

    def test_route_on_link(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      dhcp4: no
      addresses: [ "10.20.10.1/24" ]
      routes:
        - to: 20.0.0.0/24
          via: 10.10.10.10
          on-link: true''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet '])
        self.assertIn(b'20.0.0.0/24 via 10.10.10.10 proto static onlink',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))

    def test_route_with_policy(self):
        self.setup_eth(None)
        self.start_dnsmasq(None, self.dev_e2_ap)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      addresses: [ "10.20.10.1/24" ]
      routes:
        - to: 40.0.0.0/24
          via: 10.20.10.55
          metric: 50
        - to: 40.0.0.0/24
          via: 10.20.10.88
          table: 99
          metric: 50
      routing-policy:
        - from: 10.20.10.0/24
          to: 40.0.0.0/24
          table: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle()
        self.assert_iface_up(self.dev_e_client,
                             ['inet '])
        self.assertIn(b'to 40.0.0.0/24 lookup 99',
                      subprocess.check_output(['ip', 'rule', 'show']))
        self.assertIn(b'40.0.0.0/24 via 10.20.10.88',
                      subprocess.check_output(['ip', 'route', 'show', 'table', '99']))


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
