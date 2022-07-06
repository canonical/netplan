#!/usr/bin/python3
#
# Integration tests for routing functions
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2018-2021 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
# Author: Lukas Märdian <slyon@ubuntu.com>
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

    # Supposed to fail if tested against NetworkManager < 1.12/1.18
    # The on-link option was introduced as of NM 1.12+ (for IPv4)
    # The on-link option was introduced as of NM 1.18+ (for IPv6)
    def test_route_on_link(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      addresses: ["9876:BBBB::11/70"]
      routes:
        - to: 2001:f00f:f00f::1/64
          via: 9876:BBBB::5
          on-link: true''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet6 9876:bbbb::11/70'])
        out = subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e_client],
                                      universal_newlines=True)
        # NM routes have a (default) 'metric' in between 'proto static' and 'onlink'
        self.assertRegex(out, r'2001:f00f:f00f::/64 via 9876:bbbb::5 proto static[^\n]* onlink')

    # Supposed to fail if tested against NetworkManager < 1.8
    # The from option was introduced as of NM 1.8+
    def test_route_from(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          from: 192.168.14.2''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet 192.168.14.2'])
        out = subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client],
                                      universal_newlines=True)
        self.assertIn('10.10.10.0/24 via 192.168.14.20 proto static src 192.168.14.2', out)

    # Supposed to fail if tested against NetworkManager < 1.10
    # The table option was introduced as of NM 1.10+
    def test_route_table(self):
        self.setup_eth(None)
        table_id = '255'  # This is the 'local' FIB of /etc/iproute2/rt_tables
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      dhcp4: no
      addresses: [ "10.20.10.2/24" ]
      gateway4: 10.20.10.1
      routes:
        - to: 10.0.0.0/8
          via: 11.0.0.1
          table: %(tid)s
          on-link: true''' % {'r': self.backend, 'ec': self.dev_e_client, 'tid': table_id})
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet '])
        out = subprocess.check_output(['ip', 'route', 'show', 'table', table_id, 'dev',
                                      self.dev_e_client], universal_newlines=True)
        # NM routes have a (default) 'metric' in between 'proto static' and 'onlink'
        self.assertRegex(out, r'10\.0\.0\.0/8 via 11\.0\.0\.1 proto static[^\n]* onlink')

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
        self.generate_and_settle([self.state_dhcp4(self.dev_e_client)])
        self.assert_iface_up(self.dev_e_client, ['inet 192.168.5.[0-9]+/24'])  # from DHCP
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
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet 192.168.5.[0-9]+/24'])  # from DHCP
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
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet6 9876:bbbb::11/70'])
        self.assertNotIn(b'default',
                         subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'via 9876:bbbb::1',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'default']))
        self.assertIn(b'2001:f00f:f00f::/64 via 9876:bbbb::5',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 799',
                      subprocess.check_output(['ip', '-6', 'route', 'show', '2001:f00f:f00f::/64']))

    def test_routes_default(self):
        self.setup_eth(None, False)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses:
          - 192.168.5.99/24
          - "9876:BBBB::11/70"
      routes:
          - to: default
            via: 192.168.5.1
          - to: default
            via: "9876:BBBB::1"
          - to: 10.10.10.0/24
            via: 192.168.5.254
            metric: 99''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet 192.168.5.99/24', 'inet6 9876:bbbb::11/70'])
        # import pdb
        # pdb.set_trace()
        self.assertIn(b'default via 192.168.5.1',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'via 9876:bbbb::1',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'default']))
        self.assertIn(b'10.10.10.0/24 via 192.168.5.254',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 99',  # check metric from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_per_route_mtu(self):
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
            mtu: 777''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assertIn(b'mtu 777',  # check mtu from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_per_route_congestion_window(self):
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
          congestion-window: 16''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assertIn(b'initcwnd 16',  # check initcwnd from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_per_route_advertised_receive_window(self):
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
          advertised-receive-window: 16''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assertIn(b'initrwnd 16',  # check initrwnd from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

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
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet 192.168.5.[0-9]+/24'])  # from DHCP
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'10.10.10.0/24 proto static scope link',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))
        self.assertIn(b'metric 99',  # check metric from static route
                      subprocess.check_output(['ip', 'route', 'show', '10.10.10.0/24']))

    def test_vrf_basic(self):
        self.setup_eth('slaac')
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'vrf0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'route', 'flush', 'table', '1000'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'rule', 'del', 'from', '10.10.10.42', 'table', '1000'],
                        stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      addresses: [10.10.10.22/24]
      routes:
      - to: 11.11.11.0/24
        via: 10.10.10.2
        table: 1000
  vrfs:
    vrf0:
      table: 1000
      interfaces: [%(ec)s]
      routes:
      - to: 10.10.0.0/16
        via: 10.10.10.1
      routing-policy:
      - from: 10.10.10.42
''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet 10.10.10.22', 'master vrf0'])
        self.assert_iface_up('vrf0', ['MASTER'])
        # verify routes didn't leak into the main routing table
        out = subprocess.check_output(['ip', 'route', 'show'], universal_newlines=True)
        self.assertNotIn('10.10.0.0/16', out)
        self.assertNotIn('11.11.11.0/24', out)
        # verify routes were added to the VRF's routing table
        out = subprocess.check_output(['ip', 'route', 'show', 'table', '1000'],
                                      universal_newlines=True)
        self.assertIn('10.10.0.0/16 via 10.10.10.1 dev vrf0', out)
        self.assertIn('11.11.11.0/24 via 10.10.10.2 dev {}'.format(self.dev_e_client), out)

        # verify routing policy was setup correctly to the VRF's table
        # 'routing-policy' is not supported on NetworkManager
        if self.backend == 'networkd':
            out = subprocess.check_output(['ip', 'rule', 'show'], universal_newlines=True)
            self.assertIn('from 10.10.10.42 lookup 1000', out)


@unittest.skipIf("networkd" not in test_backends,
                 "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    @unittest.skip("networkd does not handle non-unicast routes correctly yet (Invalid argument)")
    def test_route_type_blackhole(self):
        self.setup_eth(None)
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
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet '])
        self.assertIn(b'blackhole 10.10.10.0/24',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))

    def test_route_type_local_lp1892272(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      addresses: [ "10.20.10.1/24" ]
      routes:
        - to: 0.0.0.0/0
          type: local
          table: 99
        - to: ::/0
          type: local
          table: 100''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet '])
        self.assertIn(b'local default',
                      subprocess.check_output(['ip', 'route', 'show', 'table', '99', 'dev', self.dev_e_client]))
        self.assertIn(b'local default',
                      subprocess.check_output(['ip', '-6', 'route', 'show', 'table', '100', 'dev', self.dev_e_client]))

    def test_route_scope_link_lp1805038(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      addresses: [ "10.20.0.10/16" ]
      routes:
        - to: 10.96.0.0/24''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet '])
        self.assertIn(b'10.96.0.0/24 proto static scope link',
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_e_client]))

    def test_route_with_policy(self):
        self.setup_eth(None)
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
        self.generate_and_settle([self.dev_e_client])
        self.assert_iface_up(self.dev_e_client, ['inet '])
        self.assertIn(b'to 40.0.0.0/24 lookup 99',
                      subprocess.check_output(['ip', 'rule', 'show']))
        self.assertIn(b'40.0.0.0/24 via 10.20.10.88',
                      subprocess.check_output(['ip', 'route', 'show', 'table', '99']))


@unittest.skipIf("NetworkManager" not in test_backends,
                 "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
