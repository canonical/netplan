#!/usr/bin/python3
# Closed-box tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2024 Canonical, Ltd.
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

import io
import unittest

from contextlib import redirect_stdout
from netplan_cli.cli.commands.status import NetplanStatus
from netplan.netdef import NetplanRoute


class TestStatusDiff(unittest.TestCase):
    '''Test netplan status --diff'''

    def setUp(self):
        self.maxDiff = None

    def test_only_loopback_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            self.assertFalse(status._is_missing_dhcp6_address('enp5s0'))
            self.assertFalse(status._is_missing_dhcp4_address('enp5s0'))

    def test_only_loopback_diff_verbose(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'dm0': {'index': 4, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'backend': 'networkd', 'id': 'dm0', 'macaddress': 'd2:2d:29:f5:58:e2', 'addresses': [{'fe80::d02d:29ff:fef5:58e2': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::d02d:29ff:fef5:58e2', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'br0': {'index': 6, 'adminstate': 'UP', 'operstate': 'DOWN', 'type': 'bridge', 'backend': 'networkd', 'id': 'br0', 'macaddress': '36:07:3b:d5:56:44', 'addresses': [{'fe80::3407:3bff:fed5:5644': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::3407:3bff:fed5:5644', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}, 'dm0': {'index': 4, 'name': 'dm0', 'id': 'dm0', 'system_state': {}, 'netplan_state': {}}, 'br0': {'index': 6, 'name': 'br0', 'id': 'br0', 'system_state': {}, 'netplan_state': {}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: 127.0.0.0/8 from 127.0.0.1 table local (host, local)
                       127.0.0.1 from 127.0.0.1 table local (host, local)
                       127.255.255.255 from 127.0.0.1 table local (link, broadcast)
                       ::1 metric 256 table main
                       ::1 table local (local)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 table main (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 table main (link)
                       10.86.126.1 from 10.86.126.148 metric 100 table main (dhcp, link)
                       10.86.126.148 from 10.86.126.148 table local (host, local)
                       10.86.126.255 from 10.86.126.148 table local (link, broadcast)
                       ff00::/8 metric 256 table local (multicast)

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
          MAC Address: d2:2d:29:f5:58:e2
            Addresses: fe80::d02d:29ff:fef5:58e2/64 (link)
               Routes: fe80::/64 metric 256 table main
                       fe80::d02d:29ff:fef5:58e2 table local (local)
                       ff00::/8 metric 256 table local (multicast)

  ●  6: br0 bridge DOWN/UP (networkd: br0)
          MAC Address: 36:07:3b:d5:56:44
            Addresses: fe80::3407:3bff:fed5:5644/64 (link)
               Routes: fe80::/64 metric 256 table main
                       fe80::3407:3bff:fed5:5644 table local (local)
                       ff00::/8 metric 256 table local (multicast)

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = True
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_macaddress_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {'missing_macaddress': 'aa:bb:cc:dd:ee:ff'}, 'netplan_state': {'missing_macaddress': '00:16:3e:71:d0:1f'}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
+         MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
-                      aa:bb:cc:dd:ee:ff (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
+         MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
-                      aa:bb:cc:dd:ee:ff (Red Hat, Inc.)
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_addresses_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}, {'1.2.3.4': {'prefix': 24}}, {'4.3.2.1': {'prefix': 24}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '1.2.3.0/24', 'family': 2, 'from': '1.2.3.4', 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '4.3.2.0/24', 'family': 2, 'from': '4.3.2.1', 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '1.2.3.4', 'family': 2, 'from': '1.2.3.4', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '1.2.3.255', 'family': 2, 'from': '1.2.3.4', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '4.3.2.1', 'family': 2, 'from': '4.3.2.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '4.3.2.255', 'family': 2, 'from': '4.3.2.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {'missing_addresses': ['10.20.30.40/24', '40.30.20.10/24']}, 'netplan_state': {'missing_addresses': ['4.3.2.1/24', '1.2.3.4/24']}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
+                      1.2.3.4/24
+                      4.3.2.1/24
-                      10.20.30.40/24
-                      40.30.20.10/24
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       1.2.3.0/24 from 1.2.3.4 (link)
                       4.3.2.0/24 from 4.3.2.1 (link)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
+           Addresses: 1.2.3.4/24
+                      4.3.2.1/24
-                      10.20.30.40/24
-                      40.30.20.10/24
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_addresses_missing_dhcp(self):
        input_data = {'netplan-global-state': {'online': False, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {'missing_dhcp4_address': True, 'missing_dhcp6_address': True}, 'netplan_state': {}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
-           Addresses: 0.0.0.0/0 (dhcp)
-                      ::/0 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
-           Addresses: 0.0.0.0/0 (dhcp)
-                      ::/0 (dhcp)
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_nameserver_addresses_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['1.1.1.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {'missing_nameservers_addresses': ['8.8.8.8']}, 'netplan_state': {'missing_nameservers_addresses': ['1.1.1.1']}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
+       DNS Addresses: 1.1.1.1
-                      8.8.8.8
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
+       DNS Addresses: 1.1.1.1
-                      8.8.8.8
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_nameserver_search_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['extradomain.home', 'test.local'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['extradomain.home', 'test.local'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {'missing_nameservers_search': ['somedomain.local']}, 'netplan_state': {'missing_nameservers_search': ['extradomain.home', 'test.local']}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
+          DNS Search: extradomain.home
+                      test.local
-                      somedomain.local
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
+          DNS Search: extradomain.home
+                      test.local
-                      somedomain.local
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_routes_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '200.200.200.200', 'family': 2, 'via': '10.86.126.254', 'type': 'unicast', 'scope': 'global', 'protocol': 'boot', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {'missing_routes': [NetplanRoute(to='1.2.3.0/24', via='10.86.126.1', from_addr='4.3.2.1', type='unicast', scope='global', protocol=None, table=254, family=2, metric=4294967295, mtubytes=0, congestion_window=0, advertised_receive_window=0, onlink=0)]}, 'netplan_state': {'missing_routes': [NetplanRoute(to='200.200.200.200', via='10.86.126.254', from_addr=None, type='unicast', scope='global', protocol='boot', table=254, family=2, metric=4294967295, mtubytes=0, congestion_window=0, advertised_receive_window=0, onlink=False)]}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)
+                      200.200.200.200 via 10.86.126.254 (boot)
-                      1.2.3.0/24 via 10.86.126.1 from 4.3.2.1

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
+              Routes: 200.200.200.200 via 10.86.126.254 (boot)
-                      1.2.3.0/24 via 10.86.126.1 from 4.3.2.1
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_missing_system_routes_diff_verbose(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {'missing_routes': [NetplanRoute(to='100.200.200.0/0', via='1.1.2.2', from_addr=None, type='unicast', scope='global', protocol=None, table=254, family=2, metric=123, mtubytes=0, congestion_window=0, advertised_receive_window=0, onlink=0), NetplanRoute(to='1.2.3.0/24', via='1.1.2.2', from_addr=None, type='local', scope='host', protocol=None, table=254, family=2, metric=1000, mtubytes=0, congestion_window=0, advertised_receive_window=0, onlink=0)]}, 'netplan_state': {}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: 127.0.0.0/8 from 127.0.0.1 table local (host, local)
                       127.0.0.1 from 127.0.0.1 table local (host, local)
                       127.255.255.255 from 127.0.0.1 table local (link, broadcast)
                       ::1 metric 256 table main
                       ::1 table local (local)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 table main (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 table main (link)
                       10.86.126.1 from 10.86.126.148 metric 100 table main (dhcp, link)
                       10.86.126.148 from 10.86.126.148 table local (host, local)
                       10.86.126.255 from 10.86.126.148 table local (link, broadcast)
                       ff00::/8 metric 256 table local (multicast)
-                      100.200.200.0/0 via 1.1.2.2 metric 123 table main
-                      1.2.3.0/24 via 1.1.2.2 metric 1000 table main (host, local)

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = True
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
-              Routes: 100.200.200.0/0 via 1.1.2.2 metric 123 table main
-                      1.2.3.0/24 via 1.1.2.2 metric 1000 table main (host, local)
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = True
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_with_bridge_no_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'br0': {'index': 3, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'bridge', 'backend': 'networkd', 'id': 'br0', 'macaddress': '36:07:3b:d5:56:44', 'addresses': [{'fe80::3407:3bff:fed5:5644': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::3407:3bff:fed5:5644', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}], 'interfaces': ['dm0']}, 'dm0': {'index': 4, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'backend': 'networkd', 'id': 'dm0', 'macaddress': 'd2:2d:29:f5:58:e2', 'routes': [{'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}], 'bridge': 'br0'}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}, 'br0': {'index': 3, 'name': 'br0', 'id': 'br0', 'system_state': {'missing_addresses': ['192.168.5.1/24']}, 'netplan_state': {}}, 'dm0': {'index': 4, 'name': 'dm0', 'id': 'dm0', 'system_state': {}, 'netplan_state': {}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

  ●  3: br0 bridge UP (networkd: br0)
          MAC Address: 36:07:3b:d5:56:44
            Addresses: fe80::3407:3bff:fed5:5644/64 (link)
-                      192.168.5.1/24
               Routes: fe80::/64 metric 256
           Interfaces: dm0

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
          MAC Address: d2:2d:29:f5:58:e2
               Bridge: br0

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  3: br0 bridge UP (networkd: br0)
-           Addresses: 192.168.5.1/24
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_bridge_interfaces_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'br0': {'index': 3, 'adminstate': 'UP', 'operstate': 'DOWN', 'type': 'bridge', 'backend': 'networkd', 'id': 'br0', 'macaddress': '36:07:3b:d5:56:44', 'addresses': [{'fe80::3407:3bff:fed5:5644': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::3407:3bff:fed5:5644', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}], 'interfaces': ['dm1']}, 'dm0': {'index': 4, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'backend': 'networkd', 'id': 'dm0', 'macaddress': 'd2:2d:29:f5:58:e2', 'routes': [{'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'dm1': {'index': 5, 'adminstate': 'DOWN', 'operstate': 'DOWN', 'type': 'dummy-device', 'macaddress': '16:dd:cc:b7:58:fa', 'bridge': 'br0'}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}, 'br0': {'index': 3, 'name': 'br0', 'id': 'br0', 'system_state': {'missing_interfaces': ['dm0']}, 'netplan_state': {'missing_interfaces': ['dm1']}}, 'dm0': {'index': 4, 'name': 'dm0', 'id': 'dm0', 'system_state': {'missing_bridge_link': 'br0'}, 'netplan_state': {}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'dm1': {'type': 'dummy-device', 'index': 5}, 'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

  ●  3: br0 bridge DOWN/UP (networkd: br0)
          MAC Address: 36:07:3b:d5:56:44
            Addresses: fe80::3407:3bff:fed5:5644/64 (link)
               Routes: fe80::/64 metric 256
+          Interfaces: dm1
-                      dm0

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
          MAC Address: d2:2d:29:f5:58:e2
-              Bridge: br0

+ ●  5: dm1 dummy-device DOWN (unmanaged)
          MAC Address: 16:dd:cc:b7:58:fa
               Bridge: br0

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  3: br0 bridge DOWN/UP (networkd: br0)
+          Interfaces: dm1
-                      dm0

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
-              Bridge: br0

+ ●  5: dm1 dummy-device DOWN (unmanaged)
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_bridge_interfaces_missing_netplan_link(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'dm0': {'index': 4, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'backend': 'networkd', 'id': 'dm0', 'macaddress': 'd2:2d:29:f5:58:e2', 'addresses': [{'fe80::d02d:29ff:fef5:58e2': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::d02d:29ff:fef5:58e2', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}], 'bridge': 'br0'}, 'br0': {'index': 6, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'bridge', 'backend': 'networkd', 'id': 'br0', 'macaddress': '36:07:3b:d5:56:44', 'addresses': [{'fe80::3407:3bff:fed5:5644': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::3407:3bff:fed5:5644', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}], 'interfaces': ['dm0']}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}, 'dm0': {'index': 4, 'name': 'dm0', 'id': 'dm0', 'system_state': {}, 'netplan_state': {'missing_bridge_link': 'br0'}}, 'br0': {'index': 6, 'name': 'br0', 'id': 'br0', 'system_state': {}, 'netplan_state': {'missing_interfaces': ['dm0']}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
          MAC Address: d2:2d:29:f5:58:e2
            Addresses: fe80::d02d:29ff:fef5:58e2/64 (link)
               Routes: fe80::/64 metric 256
+              Bridge: br0

  ●  6: br0 bridge UP (networkd: br0)
          MAC Address: 36:07:3b:d5:56:44
            Addresses: fe80::3407:3bff:fed5:5644/64 (link)
               Routes: fe80::/64 metric 256
+          Interfaces: dm0

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
+              Bridge: br0

  ●  6: br0 bridge UP (networkd: br0)
+          Interfaces: dm0
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_bond_interfaces_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'bond0': {'index': 3, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'bond', 'backend': 'networkd', 'id': 'bond0', 'macaddress': '1a:b2:f0:35:da:4f', 'addresses': [{'fe80::18b2:f0ff:fe35:da4f': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::18b2:f0ff:fe35:da4f', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}], 'interfaces': ['dm1']}, 'dm0': {'index': 4, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'backend': 'networkd', 'id': 'dm0', 'macaddress': 'd2:2d:29:f5:58:e2', 'routes': [{'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'dm1': {'index': 6, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'macaddress': '1a:b2:f0:35:da:4f', 'bond': 'bond0'}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}, 'bond0': {'index': 3, 'name': 'bond0', 'id': 'bond0', 'system_state': {'missing_interfaces': ['dm0']}, 'netplan_state': {'missing_interfaces': ['dm1']}}, 'dm0': {'index': 4, 'name': 'dm0', 'id': 'dm0', 'system_state': {'missing_bond_link': 'bond0'}, 'netplan_state': {}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'dm1': {'type': 'dummy-device', 'index': 6}, 'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

  ●  3: bond0 bond UP (networkd: bond0)
          MAC Address: 1a:b2:f0:35:da:4f
            Addresses: fe80::18b2:f0ff:fe35:da4f/64 (link)
               Routes: fe80::/64 metric 256
+          Interfaces: dm1
-                      dm0

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
          MAC Address: d2:2d:29:f5:58:e2
-                Bond: bond0

+ ●  6: dm1 dummy-device UNKNOWN/UP (unmanaged)
          MAC Address: 1a:b2:f0:35:da:4f
                 Bond: bond0

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  3: bond0 bond UP (networkd: bond0)
+          Interfaces: dm1
-                      dm0

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
-                Bond: bond0

+ ●  6: dm1 dummy-device UNKNOWN/UP (unmanaged)
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_bond_interfaces_missing_netplan_link(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'bond0': {'index': 3, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'bond', 'backend': 'networkd', 'id': 'bond0', 'macaddress': '1a:b2:f0:35:da:4f', 'addresses': [{'fe80::18b2:f0ff:fe35:da4f': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::18b2:f0ff:fe35:da4f', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}], 'interfaces': ['dm0']}, 'dm0': {'index': 4, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'backend': 'networkd', 'id': 'dm0', 'macaddress': '1a:b2:f0:35:da:4f', 'bond': 'bond0'}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}, 'bond0': {'index': 3, 'name': 'bond0', 'id': 'bond0', 'system_state': {}, 'netplan_state': {'missing_interfaces': ['dm0']}}, 'dm0': {'index': 4, 'name': 'dm0', 'id': 'dm0', 'system_state': {}, 'netplan_state': {'missing_bond_link': 'bond0'}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

  ●  3: bond0 bond UP (networkd: bond0)
          MAC Address: 1a:b2:f0:35:da:4f
            Addresses: fe80::18b2:f0ff:fe35:da4f/64 (link)
               Routes: fe80::/64 metric 256
+          Interfaces: dm0

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
          MAC Address: 1a:b2:f0:35:da:4f
+                Bond: bond0

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  3: bond0 bond UP (networkd: bond0)
+          Interfaces: dm0

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
+                Bond: bond0
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_vrf_interfaces_diff(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'dm0': {'index': 3, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'backend': 'networkd', 'id': 'dm0', 'macaddress': 'd2:2d:29:f5:58:e2', 'addresses': [{'fe80::d02d:29ff:fef5:58e2': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': 'fe80::d02d:29ff:fef5:58e2', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'vrf0': {'index': 4, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'vrf', 'backend': 'networkd', 'id': 'vrf0', 'macaddress': '72:1e:4b:7d:ac:5f', 'interfaces': ['dm1']}, 'dm1': {'index': 5, 'adminstate': 'DOWN', 'operstate': 'DOWN', 'type': 'dummy-device', 'macaddress': '16:dd:cc:b7:58:fa', 'vrf': 'vrf0'}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}, 'dm0': {'index': 3, 'name': 'dm0', 'id': 'dm0', 'system_state': {'missing_vrf_link': 'vrf0'}, 'netplan_state': {}}, 'vrf0': {'index': 4, 'name': 'vrf0', 'id': 'vrf0', 'system_state': {'missing_interfaces': ['dm0']}, 'netplan_state': {'missing_interfaces': ['dm1']}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'dm1': {'type': 'dummy-device', 'index': 5}, 'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

  ●  3: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
          MAC Address: d2:2d:29:f5:58:e2
            Addresses: fe80::d02d:29ff:fef5:58e2/64 (link)
               Routes: fe80::/64 metric 256
-                 VRF: vrf0

  ●  4: vrf0 vrf UP (networkd: vrf0)
          MAC Address: 72:1e:4b:7d:ac:5f
+          Interfaces: dm1
-                      dm0

+ ●  5: dm1 dummy-device DOWN (unmanaged)
          MAC Address: 16:dd:cc:b7:58:fa
                  VRF: vrf0

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  3: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
-                 VRF: vrf0

  ●  4: vrf0 vrf UP (networkd: vrf0)
+          Interfaces: dm1
-                      dm0

+ ●  5: dm1 dummy-device DOWN (unmanaged)
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_vrf_interfaces_missing_netplan_link(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'dm0': {'index': 4, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'dummy-device', 'backend': 'networkd', 'id': 'dm0', 'macaddress': 'd2:2d:29:f5:58:e2', 'addresses': [{'fe80::d02d:29ff:fef5:58e2': {'prefix': 64, 'flags': ['link']}}], 'routes': [{'to': 'fe80::d02d:29ff:fef5:58e2', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': '1234'}, {'to': 'fe80::/64', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': '1234'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': '1234'}], 'vrf': 'vrf0'}, 'vrf0': {'index': 5, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'vrf', 'backend': 'networkd', 'id': 'vrf0', 'macaddress': '72:1e:4b:7d:ac:5f', 'interfaces': ['dm0']}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}, 'dm0': {'index': 4, 'name': 'dm0', 'id': 'dm0', 'system_state': {}, 'netplan_state': {'missing_vrf_link': 'vrf0'}}, 'vrf0': {'index': 5, 'name': 'vrf0', 'id': 'vrf0', 'system_state': {}, 'netplan_state': {'missing_interfaces': ['dm0']}}}, 'missing_interfaces_system': {}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
          MAC Address: d2:2d:29:f5:58:e2
            Addresses: fe80::d02d:29ff:fef5:58e2/64 (link)
+                 VRF: vrf0

  ●  5: vrf0 vrf UP (networkd: vrf0)
          MAC Address: 72:1e:4b:7d:ac:5f
+          Interfaces: dm0

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

  ●  4: dm0 dummy-device UNKNOWN/UP (networkd: dm0)
+                 VRF: vrf0

  ●  5: vrf0 vrf UP (networkd: vrf0)
+          Interfaces: dm0
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

    def test_missing_system_interfaces(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}}, 'missing_interfaces_system': {'eth0': {'type': 'ethernet'}, 'eth1': {'type': 'ethernet'}}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)
          MAC Address: 00:00:00:00:00:00
            Addresses: 127.0.0.1/8
                       ::1/128
               Routes: ::1 metric 256

  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

- ●     eth0 ethernet

- ●     eth1 ethernet

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = '''+ ●  1: lo ethernet UNKNOWN/UP (unmanaged)

- ●     eth0 ethernet

- ●     eth1 ethernet
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = None
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

            status.state_diff = None
            self.assertDictEqual(status._get_missing_system_interfaces(), {})

    def test_with_targeted_interfaces(self):
        input_data = {'netplan-global-state': {'online': True, 'nameservers': {'addresses': ['127.0.0.53'], 'search': ['lxd'], 'mode': 'stub'}}, 'lo': {'index': 1, 'adminstate': 'UP', 'operstate': 'UNKNOWN', 'type': 'ethernet', 'macaddress': '00:00:00:00:00:00', 'addresses': [{'127.0.0.1': {'prefix': 8}}, {'::1': {'prefix': 128}}], 'routes': [{'to': '127.0.0.0/8', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.0.0.1', 'family': 2, 'from': '127.0.0.1', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '127.255.255.255', 'family': 2, 'from': '127.0.0.1', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': '::1', 'family': 10, 'metric': 256, 'type': 'unicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'main'}, {'to': '::1', 'family': 10, 'type': 'local', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}, 'enp5s0': {'index': 2, 'adminstate': 'UP', 'operstate': 'UP', 'type': 'ethernet', 'backend': 'networkd', 'id': 'enp5s0', 'macaddress': '00:16:3e:71:d0:1f', 'vendor': 'Red Hat, Inc.', 'addresses': [{'10.86.126.148': {'prefix': 24, 'flags': ['dhcp']}}], 'dns_addresses': ['10.86.126.1'], 'dns_search': ['lxd'], 'routes': [{'to': 'default', 'family': 2, 'via': '10.86.126.1', 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'global', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.0/24', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'kernel', 'table': 'main'}, {'to': '10.86.126.1', 'family': 2, 'from': '10.86.126.148', 'metric': 100, 'type': 'unicast', 'scope': 'link', 'protocol': 'dhcp', 'table': 'main'}, {'to': '10.86.126.148', 'family': 2, 'from': '10.86.126.148', 'type': 'local', 'scope': 'host', 'protocol': 'kernel', 'table': 'local'}, {'to': '10.86.126.255', 'family': 2, 'from': '10.86.126.148', 'type': 'broadcast', 'scope': 'link', 'protocol': 'kernel', 'table': 'local'}, {'to': 'ff00::/8', 'family': 10, 'metric': 256, 'type': 'multicast', 'scope': 'global', 'protocol': 'kernel', 'table': 'local'}]}}  # nopep8
        state_diff = {'interfaces': {'enp5s0': {'index': 2, 'name': 'enp5s0', 'id': 'enp5s0', 'system_state': {}, 'netplan_state': {}}}, 'missing_interfaces_system': {'eth0': {'type': 'ethernet'}, 'eth1': {'type': 'ethernet'}}, 'missing_interfaces_netplan': {'lo': {'type': 'ethernet', 'index': 1}}}  # nopep8

        expected = '''  ●  2: enp5s0 ethernet UP (networkd: enp5s0)
          MAC Address: 00:16:3e:71:d0:1f (Red Hat, Inc.)
            Addresses: 10.86.126.148/24 (dhcp)
        DNS Addresses: 10.86.126.1
           DNS Search: lxd
               Routes: default via 10.86.126.1 from 10.86.126.148 metric 100 (dhcp)
                       10.86.126.0/24 from 10.86.126.148 metric 100 (link)
                       10.86.126.1 from 10.86.126.148 metric 100 (dhcp, link)

Use "--diff-only" to omit the information that is consistent between the system and Netplan.
'''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = 'enp5s0'
            status.verbose = False
            status.diff = True
            status.diff_only = False
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

        # Same test for --diff-only

        expected = ''

        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = 'enp5s0'
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

            status.state_diff = None
            self.assertDictEqual(status._get_missing_system_interfaces(), {})

        # Same test with an interface missing in the system

        expected = '- ●     eth0 ethernet\n'
        f = io.StringIO()
        with redirect_stdout(f):
            status = NetplanStatus()
            status.ifname = 'eth0'
            status.verbose = False
            status.diff = True
            status.diff_only = True
            status.state_diff = state_diff
            status.pretty_print(input_data, 2, _console_width=130)
            out = f.getvalue()
            self.assertEqual(out, expected)

            status.state_diff = None
            self.assertDictEqual(status._get_missing_system_interfaces(), {})
