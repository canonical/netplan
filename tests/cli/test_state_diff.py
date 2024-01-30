#!/usr/bin/python3
# Closed-box tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2023 Canonical, Ltd.
# Authors: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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

import json
import os
import tempfile
import unittest

from unittest.mock import Mock
from netplan.netdef import NetplanRoute
from netplan_cli.cli.state import Interface, NetplanConfigState, SystemConfigState
from netplan_cli.cli.state_diff import DiffJSONEncoder, NetplanDiffState


class TestNetplanDiff(unittest.TestCase):
    '''Test netplan state NetplanDiffState class'''

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory(prefix='netplan_')
        self.file = '90-netplan.yaml'
        self.path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'etc', 'netplan'))

        self.diff_state = NetplanDiffState(Mock(spec=SystemConfigState), Mock(spec=NetplanConfigState))

    def test_get_full_state(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynic:
      match:
        name: eth0
      dhcp4: true
      dhcp6: false''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)
        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynic',
                'index': 2,
                'type': 'ethernet',
                'addresses': [
                    {
                        '1.2.3.4': {
                            'prefix': 24,
                            'flags': ['dhcp'],
                        }
                    },
                ],
            }
        }
        system_state.interface_list = []
        diff_state = NetplanDiffState(system_state, netplan_state)

        full_state = diff_state.get_full_state()
        expected = {
            'interfaces': {
                'eth0': {
                    'system_state': {
                        'type': 'ethernet',
                        'addresses': {
                            '1.2.3.4/24': {
                                'flags': ['dhcp']
                            }
                        },
                        'id': 'mynic',
                        'index': 2,
                    },
                    'netplan_state': {
                        'id': 'mynic',
                        'type': 'ethernet',
                        'dhcp4': True,
                        'dhcp6': False
                    }
                }
            }
        }

        self.assertDictEqual(full_state, expected)

    def test_get_netplan_interfaces(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynic:
      match:
        name: eth0
      dhcp4: false
      dhcp6: false
      macaddress: aa:bb:cc:dd:ee:ff
      routes:
        - to: default
          via: 1.2.3.4
      nameservers:
        addresses:
          - 1.1.1.1
          - 2.2.2.2
        search:
          - mydomain.local
      addresses:
        - 192.168.0.2/24:
            label: myip
            lifetime: forever
        - 192.168.0.1/24''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)
        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynic',
                'index': 2,
            }
        }
        system_state.interface_list = []
        diff_state = NetplanDiffState(system_state, netplan_state)

        interfaces = diff_state._get_netplan_interfaces()
        expected = {
            'eth0': {
                'netplan_state': {
                    'id': 'mynic',
                    'addresses': {
                        '192.168.0.1/24': {
                            'flags': {}
                        },
                        '192.168.0.2/24': {
                            'flags': {'label': 'myip', 'lifetime': 'forever'},
                        }
                    },
                    'dhcp4': False,
                    'dhcp6': False,
                    'nameservers_addresses': ['1.1.1.1', '2.2.2.2'],
                    'nameservers_search': ['mydomain.local'],
                    'macaddress': 'aa:bb:cc:dd:ee:ff',
                    'type': 'ethernet',
                    'routes': [NetplanRoute(to='default', via='1.2.3.4', family=2)],
                }
            }
        }
        self.assertDictEqual(interfaces, expected)

    def test_get_netplan_interfaces_with_match(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    # not matching any physical device
    myeths:
      match:
        name: eth*
    mynics:
      dhcp4: false
      dhcp6: false
      match:
        name: enp0*''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)
        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'enp0s3': {
                'name': 'enp0s3',
                'id': 'mynics',
                'index': 2,
            },
            'enp0s4': {
                'name': 'enp0s4',
                'id': 'mynics',
                'index': 3,
            },
            'enp0s5': {
                'name': 'enp0s5',
                'id': 'mynics',
                'index': 4,
            }
        }
        system_state.interface_list = []
        diff_state = NetplanDiffState(system_state, netplan_state)

        interfaces = diff_state._get_netplan_interfaces()
        expected = {
            'enp0s3': {
                'netplan_state': {
                    'id': 'mynics',
                    'dhcp4': False,
                    'dhcp6': False,
                    'type': 'ethernet',
                }
            },
            'enp0s4': {
                'netplan_state': {
                    'id': 'mynics',
                    'dhcp4': False,
                    'dhcp6': False,
                    'type': 'ethernet',
                }
            },
            'enp0s5': {
                'netplan_state': {
                    'id': 'mynics',
                    'dhcp4': False,
                    'dhcp6': False,
                    'type': 'ethernet',
                },
            },
            'myeths': {
                'netplan_state': {
                    'id': 'myeths',
                    'dhcp4': False,
                    'dhcp6': False,
                    'type': 'ethernet',
                }
            }
        }
        self.assertDictEqual(interfaces, expected)

    def test_get_system_interfaces(self):
        system_state = Mock(spec=SystemConfigState)
        netplan_state = Mock(spec=NetplanConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynic',
                'type': 'ethernet',
                'index': 2,
                'addresses': [
                    {
                        '1.2.3.4': {
                            'prefix': 24,
                            'flags': [],
                        }
                    },
                ],
                'dns_addresses': ['1.1.1.1', '2.2.2.2'],
                'dns_search': ['mydomain.local'],
                'routes': [
                    {
                        'to': 'default',
                        'via': '192.168.5.1',
                        'from': '192.168.5.122',
                        'metric': 100,
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'kernel',
                        'family': 2,
                        'table': 'main'
                    }
                ],
                'macaddress': 'aa:bb:cc:dd:ee:ff',
            }
        }
        system_state.interface_list = []

        diff_state = NetplanDiffState(system_state, netplan_state)
        interfaces = diff_state._get_system_interfaces()
        expected = {
            'eth0': {
                'system_state': {
                    'type': 'ethernet',
                    'id': 'mynic',
                    'index': 2,
                    'addresses': {
                        '1.2.3.4/24': {
                            'flags': []
                        }
                    },
                    'nameservers_addresses': ['1.1.1.1', '2.2.2.2'],
                    'nameservers_search': ['mydomain.local'],
                    'routes': [
                        NetplanRoute(to='default',
                                     via='192.168.5.1',
                                     from_addr='192.168.5.122',
                                     type='unicast',
                                     scope='global',
                                     protocol='kernel',
                                     table=254,
                                     family=2,
                                     metric=100)
                    ],
                    'macaddress': 'aa:bb:cc:dd:ee:ff'
                },
            }
        }
        self.assertDictEqual(interfaces, expected)

    def test_diff_default_table_names_to_number(self):
        self.assertEqual(self.diff_state._default_route_tables_name_to_number('main'), 254)
        self.assertEqual(self.diff_state._default_route_tables_name_to_number('default'), 253)
        self.assertEqual(self.diff_state._default_route_tables_name_to_number('local'), 255)
        self.assertEqual(self.diff_state._default_route_tables_name_to_number('1000'), 1000)
        self.assertEqual(self.diff_state._default_route_tables_name_to_number('blah'), 0)

    def test__system_route_to_netplan_empty_input(self):
        route = self.diff_state._system_route_to_netplan({})
        expected = NetplanRoute()
        self.assertEqual(route, expected)

    def test__system_route_to_netplan(self):
        route = {
            'to': 'default',
            'via': '192.168.5.1',
            'from': '192.168.5.122',
            'metric': 100,
            'type': 'unicast',
            'scope': 'global',
            'protocol': 'kernel',
            'family': 2,
            'table': 'main'
        }

        netplan_route = self.diff_state._system_route_to_netplan(route)
        expected = NetplanRoute(to='default', via='192.168.5.1', from_addr='192.168.5.122',
                                metric=100, type='unicast', scope='global', protocol='kernel',
                                family=2, table=254)
        self.assertEqual(netplan_route, expected)

    def test_diff_missing_netplan_interface(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets: {}''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'index': 2,
            },
            'lo': {
                'name': 'lo',
                'index': 1,
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'lo'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('missing_interfaces_netplan', [])
        self.assertIn('eth0', missing)
        # lo is included
        self.assertIn('lo', missing)

    def test_diff_missing_system_interface(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
    eth1: {}''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
            }
        }
        interface = Mock(spec=Interface)
        interface.name = 'eth0'
        interface.netdef_id = 'eth0'
        system_state.interface_list = [interface]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()
        missing = diff_data.get('missing_interfaces_system', [])
        self.assertIn('eth1', missing)

    def test_diff_missing_system_interface_with_match(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynics:
      dhcp4: false
      match:
        name: eth*''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'enp0s1': {
                'name': 'enp0s1',
                'id': 'enp0s1',
                'index': 2,
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'enp0s1'
        interface1.netdef_id = 'enp0s1'
        system_state.interface_list = [interface1]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()
        missing = diff_data.get('missing_interfaces_system', [])
        self.assertIn('mynics', missing)

    def test_diff_not_missing_system_interface_with_match(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynics:
      dhcp4: false
      match:
        name: eth*''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynics',
                'index': 2,
            },
            'enp0s1': {
                'name': 'enp0s1',
                'id': 'enp0s1',
                'index': 3,
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'mynics'
        interface2 = Mock(spec=Interface)
        interface2.name = 'enp0s1'
        interface2.netdef_id = 'enp0s1'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()
        missing = diff_data.get('missing_interfaces_system', {})
        self.assertDictEqual(missing, {})

    def test__get_comparable_interfaces_empty(self):
        res = self.diff_state._get_comparable_interfaces({})
        self.assertDictEqual(res, {})

    def test__get_comparable_interfaces(self):
        input = {
            'eth0': {
                'system_state': {
                    'id': 'eth0'
                }
            },
            'eth1': {
                'netplan_state': {}
            },
            'eth2': {
                'system_state': {}
            }
        }
        res = self.diff_state._get_comparable_interfaces(input)
        self.assertDictEqual(res, {'eth0': {'system_state': {'id': 'eth0'}}})

    def test__compress_ipv6_address_with_prefix(self):
        self.assertEqual(self.diff_state._compress_ipv6_address('a:b:c:0:0:0::d/64'), 'a:b:c::d/64')

    def test__compress_ipv6_address_without_prefix(self):
        self.assertEqual(self.diff_state._compress_ipv6_address('a:b:c:0:0:0::d'), 'a:b:c::d')

    def test__compress_ipv6_address_ipv4_with_prefix(self):
        self.assertEqual(self.diff_state._compress_ipv6_address('192.168.0.1/24'), '192.168.0.1/24')

    def test__compress_ipv6_address_ipv4_without_prefix(self):
        self.assertEqual(self.diff_state._compress_ipv6_address('192.168.0.1'), '192.168.0.1')

    def test__compress_ipv6_address_not_an_ip(self):
        self.assertEqual(self.diff_state._compress_ipv6_address('default'), 'default')

    def test__normalize_ip_addresses(self):
        ips = {'abcd:0:0:0::1/64', '1:2:0:0::123', '1.2.3.4/24', '1.2.3.4'}
        expected = {'abcd::1/64', '1:2::123', '1.2.3.4/24', '1.2.3.4'}
        result = self.diff_state._normalize_ip_addresses(ips)
        self.assertSetEqual(expected, result)

    def test_diff_missing_system_address(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      dhcp4: false
      dhcp6: false
      addresses:
        - 192.168.0.2/24:
            label: myip
            lifetime: forever
        - 192.168.0.1/24''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_addresses', [])
        self.assertIn('192.168.0.1/24', missing)
        self.assertIn('192.168.0.2/24', missing)

    def test_diff_missing_system_address_with_match(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynic:
      match:
        name: "eth*"
      dhcp4: false
      dhcp6: false
      addresses:
        - 192.168.0.2/24:
            label: myip
            lifetime: forever
        - 192.168.0.1/24''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynic',
                'index': 2,
            }
        }

        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'mynic'
        system_state.interface_list = [interface1]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_addresses', [])
        self.assertIn('192.168.0.1/24', missing)
        self.assertIn('192.168.0.2/24', missing)

    def test_diff_dhcp_addresses_are_filtered_out(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      dhcp4: true
      dhcp6: true''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'addresses': [
                    {'192.168.0.1': {'prefix': 24, 'flags': ['dhcp']}},
                    {'192.168.254.1': {'prefix': 24, 'flags': ['dhcp']}},
                    {'abcd:1234::1': {'prefix': 64, 'flags': ['dhcp']}}
                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_addresses', [])
        self.assertEqual(missing, [])

    def test_diff_missing_netplan_address(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      dhcp4: false
      dhcp6: false
      addresses:
        - 192.168.0.1/24''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'addresses': [
                    {'192.168.0.1': {'prefix': 24}},
                    {'192.168.254.1': {'prefix': 24}}
                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)

        diff_data = diff.get_diff()
        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_addresses', [])
        self.assertIn('192.168.254.1/24', missing)

        diff_data = diff.get_diff('eth0')
        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_addresses', [])
        self.assertIn('192.168.254.1/24', missing)

    def test_diff_addresses_compressed_ipv6(self):
        ''' Check if IPv6 address will not mismatch due to their representation'''
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      dhcp4: false
      dhcp6: false
      addresses:
        - 1:2:3:0:0:0::123/64''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'addresses': [
                    {'1:2:3::123': {'prefix': 64}},
                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing_netplan = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_addresses', [])
        missing_system = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_addresses', [])
        self.assertListEqual([], missing_netplan)
        self.assertListEqual([], missing_system)

    def test_diff_missing_system_dhcp_addresses(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      dhcp4: true
      dhcp6: true''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        dhcp4 = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_dhcp4_address')
        dhcp6 = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_dhcp6_address')
        self.assertTrue(dhcp4)
        self.assertTrue(dhcp6)

    def test_diff_missing_system_nameservers(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      nameservers:
        addresses:
          - 1.2.3.4
          - 4.3.2.1''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_nameservers_addresses', [])
        self.assertIn('1.2.3.4', missing)
        self.assertIn('4.3.2.1', missing)

    def test_diff_missing_netplan_nameservers(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'dns_addresses': ['1.2.3.4', '4.3.2.1'],
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        state = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {})
        missing = state.get('missing_nameservers_addresses', [])
        self.assertIn('1.2.3.4', missing)
        self.assertIn('4.3.2.1', missing)

    def test_diff_missing_system_nameservers_with_match(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynic:
      match:
        name: eth0
      nameservers:
        addresses:
          - 1.2.3.4
          - 4.3.2.1''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynic',
                'index': 2,
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'mynic'
        system_state.interface_list = [interface1]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_nameservers_addresses', [])
        self.assertIn('1.2.3.4', missing)
        self.assertIn('4.3.2.1', missing)

    def test_diff_missing_system_nameservers_search(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      nameservers:
        search:
          - mydomain.local
          - anotherdomain.local''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_nameservers_search', [])
        self.assertIn('mydomain.local', missing)
        self.assertIn('anotherdomain.local', missing)

    def test_diff_missing_netplan_nameservers_search(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      dhcp4: false
      dhcp6: false''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'dns_search': ['mydomain.local', 'anotherdomain.local'],
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_nameservers_search', [])
        self.assertIn('mydomain.local', missing)
        self.assertIn('anotherdomain.local', missing)

    def test_diff_missing_system_nameservers_search_with_match(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynic:
      match:
        name: eth0
      nameservers:
        search:
          - mydomain.local
          - anotherdomain.local''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynic',
                'index': 2,
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'mynic'
        system_state.interface_list = [interface1]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_nameservers_search', [])
        self.assertIn('mydomain.local', missing)
        self.assertIn('anotherdomain.local', missing)

    def test_diff_macaddress(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      macaddress: aa:bb:cc:dd:ee:ff''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'macaddress': '11:22:33:44:55:66'
            }
        }

        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'mynic'
        system_state.interface_list = [interface1]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing_system = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_macaddress')
        missing_netplan = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_macaddress')
        self.assertEqual(missing_system, 'aa:bb:cc:dd:ee:ff')
        self.assertEqual(missing_netplan, '11:22:33:44:55:66')

    def test_diff_macaddress_with_match(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynic:
      match:
        name: eth0
      macaddress: aa:bb:cc:dd:ee:ff''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynic',
                'index': 2,
                'macaddress': '11:22:33:44:55:66'
            }
        }

        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'mynic'
        system_state.interface_list = [interface1]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing_system = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_macaddress')
        missing_netplan = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_macaddress')
        self.assertEqual(missing_system, 'aa:bb:cc:dd:ee:ff')
        self.assertEqual(missing_netplan, '11:22:33:44:55:66')

    def test__filter_system_routes_empty_inputs(self):
        filtered = self.diff_state._filter_system_routes(set(), [])
        self.assertSetEqual(filtered, set())

    def test__filter_system_routes_link_scope_routes(self):
        route = NetplanRoute(scope='link')
        filtered = self.diff_state._filter_system_routes({route}, [])
        self.assertSetEqual(filtered, set())

    def test__filter_system_routes_dhcp_ra_routes(self):
        route1 = NetplanRoute(protocol='dhcp')
        route2 = NetplanRoute(protocol='ra')
        filtered = self.diff_state._filter_system_routes({route1, route2}, [])
        self.assertSetEqual(filtered, set())

    def test__filter_system_routes_link_local_routes(self):
        route = NetplanRoute(scope='host', type='local', to='1.2.3.4', from_addr='1.2.3.4')
        system_addresses = ['1.2.3.4/24']
        filtered = self.diff_state._filter_system_routes({route}, system_addresses)
        self.assertSetEqual(filtered, set())

    def test__filter_system_routes_link_local_routes_with_multiple_ips_same_subnet(self):
        # When an interface has multiple IPs in the same subnet the routing table will
        # have routes using one of the IPs as source. Example:
        # local 192.168.0.123 dev eth0 table local proto kernel scope host src 192.168.0.123
        # local 192.168.0.124 dev eth0 table local proto kernel scope host src 192.168.0.123
        route1 = NetplanRoute(scope='host', type='local', to='1.2.3.4', from_addr='1.2.3.4')
        route2 = NetplanRoute(scope='host', type='local', to='1.2.3.5', from_addr='1.2.3.4')
        system_addresses = ['1.2.3.4/24', '1.2.3.5/24']
        filtered = self.diff_state._filter_system_routes({route1, route2}, system_addresses)
        self.assertSetEqual(filtered, set())

    def test__filter_system_routes_ipv6_multicast_routes(self):
        route = NetplanRoute(type='multicast', to='ff00::/8', family=10)
        filtered = self.diff_state._filter_system_routes({route}, [])
        self.assertSetEqual(filtered, set())

    def test__filter_system_routes_ipv6_host_local_routes(self):
        route1 = NetplanRoute(family=10, to='fd42:bc43:e20e:8cf7:216:3eff:feaf:4121')
        route2 = NetplanRoute(family=10, to='fd42:bc43:e20e:8cf7::/64')
        addresses = ['fd42:bc43:e20e:8cf7:216:3eff:feaf:4121/64']
        filtered = self.diff_state._filter_system_routes({route1, route2}, addresses)
        self.assertSetEqual(filtered, set())

    def test__filter_system_routes_should_not_be_filtered(self):
        route1 = NetplanRoute(to='default', via='1.2.3.4')
        route2 = NetplanRoute(to='1.2.3.0/24', via='4.3.2.1')
        route3 = NetplanRoute(to='1:2:3::/64', via='1:2:3::1234')
        filtered = self.diff_state._filter_system_routes({route1, route2, route3}, [])
        self.assertSetEqual(filtered, {route1, route2, route3})

    def test_diff_missing_netplan_routes(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'addresses': [{'fd42:bc43:e20e:8cf7:216:3eff:feaf:4121': {'prefix': 64}}],
                'routes': [
                    {
                        'to': 'default',
                        'via': '192.168.5.1',
                        'from': '192.168.5.122',
                        'metric': 100,
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'kernel',
                        'family': 2,
                        'table': 'main'
                    },
                    {
                        'to': '192.168.5.0',
                        'via': '192.168.5.1',
                        'from': '192.168.5.122',
                        'type': 'unicast',
                        'scope': 'link',
                        'protocol': 'kernel',
                        'family': 2,
                        'table': 'main'
                    },
                    {
                        'to': '1.2.3.0/24',
                        'via': '192.168.5.1',
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'dhcp',
                        'family': 2,
                        'table': 'main'
                    },
                    {
                        'to': 'abcd::/64',
                        'via': 'abcd::1',
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'ra',
                        'family': 10,
                        'table': 'main'
                    },
                    {
                        'to': 'fe80::/64',
                        'protocol': 'kernel',
                        'family': 10,
                        'table': 'main'
                    },
                    {
                        'type': 'multicast',
                        'to': 'ff00::/8',
                        'table': 'local',
                        'protocol': 'kernel',
                        'family': 10
                    },
                    {
                        'type': 'local',
                        'to': '10.86.126.148',
                        'table': 'local',
                        'protocol': 'kernel',
                        'scope': 'host',
                        'from': '10.86.126.148',
                        'family': 2
                    },
                    {
                        'type': 'local',
                        'to': 'fd42:bc43:e20e:8cf7:216:3eff:feaf:4121',
                        'table': 'local',
                        'protocol': 'kernel',
                        'scope': 'global',
                        'family': 10
                    }

                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        expected = {}
        expected['to'] = 'default'
        expected['via'] = '192.168.5.1'
        expected['from_addr'] = '192.168.5.122'
        expected['metric'] = 100
        expected['protocol'] = 'kernel'
        expected['family'] = 2
        expected['table'] = 254
        expected_route = NetplanRoute(**expected)

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_routes', [])
        self.assertIn(expected_route, missing)

    def test_diff_missing_system_routes(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      routes:
        - to: 1.2.3.0/24
          via: 192.168.0.1''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'routes': [
                    {
                        'to': 'default',
                        'via': '192.168.5.1',
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'kernel',
                        'family': 2,
                        'table': 'main'
                    }
                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        expected = {}
        expected['to'] = '1.2.3.0/24'
        expected['via'] = '192.168.0.1'
        expected['family'] = 2
        expected['table'] = 254
        expected_route = NetplanRoute(**expected)

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_routes', [])
        self.assertEqual(expected_route, missing[0])

    def test_diff_missing_system_routes_with_match(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    mynic:
      match:
        name: eth0
      routes:
        - to: 1.2.3.0/24
          via: 192.168.0.1''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'mynic',
                'index': 2,
                'routes': [
                    {
                        'to': 'default',
                        'via': '192.168.5.1',
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'kernel',
                        'family': 2,
                        'table': 'main'
                    }
                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        expected = {}
        expected['to'] = '1.2.3.0/24'
        expected['via'] = '192.168.0.1'
        expected['family'] = 2
        expected['table'] = 254
        expected_route = NetplanRoute(**expected)

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_routes', [])
        self.assertEqual(expected_route, missing[0])

    def test_diff_slash_32_and_128_routes(self):
        ''' /32 and /128 route entries from "ip route show" will not have the prefix
            1.2.3.4 via 10.3.0.1 dev mainif proto static
            1:2:3::4 via 10:3::1 dev mainif proto static metric 1024 pref medium
        '''
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      routes:
        - to: 1:2:3::4/128
          via: 1:2:3::1
        - to: 1.2.3.4/32
          via: 192.168.0.1''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'routes': [
                    {
                        'to': '1.2.3.4',
                        'via': '192.168.0.1',
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'kernel',
                        'family': 2,
                        'table': 'main'
                    },
                    {
                        'to': '1:2:3::4',
                        'via': '1:2:3::1',
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'kernel',
                        'family': 10,
                        'table': 'main'
                    }
                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing_system = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_routes', [])
        missing_netplan = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_routes', [])
        self.assertListEqual([], missing_system)
        self.assertListEqual([], missing_netplan)

    def test_diff_compressed_ipv6_routes(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      routes:
        - to: 1:2:3:0:0:0::4/64
          from: 1:2:3:0:0:0::123
          via: 1:2:3:0:0::1''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'routes': [
                    {
                        'to': '1:2:3::4/64',
                        'via': '1:2:3::1',
                        'from': '1:2:3::123',
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'kernel',
                        'family': 10,
                        'table': 'main'
                    }
                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing_system = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_routes', [])
        missing_netplan = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_routes', [])
        self.assertListEqual([], missing_system)
        self.assertListEqual([], missing_netplan)

    def test_diff_json_encoder(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0:
      routes:
        - to: 1.2.3.0/24
          via: 192.168.0.1''')

        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'routes': [
                    {
                        'to': 'default',
                        'via': '192.168.5.1',
                        'type': 'unicast',
                        'scope': 'global',
                        'protocol': 'kernel',
                        'family': 2,
                        'table': 'main'
                    }
                ]
            }
        }
        system_state.interface_list = []

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        diff_data_str = json.dumps(diff_data, cls=DiffJSONEncoder)
        diff_data_dict = json.loads(diff_data_str)
        self.assertTrue(len(diff_data_dict['interfaces']['eth0']['system_state']['missing_routes']) > 0)
        self.assertTrue(len(diff_data_dict['interfaces']['eth0']['netplan_state']['missing_routes']) > 0)

    def test_diff_present_system_bond_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  bonds:
    bond0:
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'bond': 'bond0'
            },
            'bond0': {
                'name': 'bond0',
                'id': 'bond0',
                'index': 3,
                'interfaces': ['eth0'],
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'bond0'
        interface2.netdef_id = 'bond0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_bond_link')
        self.assertIsNone(missing)

        missing = diff_data.get('interfaces', {}).get('bond0', {}).get('system_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, [])

    def test_diff_missing_system_bond_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  bonds:
    bond0:
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
            },
            'bond0': {
                'name': 'bond0',
                'id': 'bond0',
                'index': 3,
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'bond0'
        interface2.netdef_id = 'bond0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_bond_link')
        self.assertEqual(missing, 'bond0')

        missing = diff_data.get('interfaces', {}).get('bond0', {}).get('system_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, ['eth0'])

    def test_diff_present_system_bridge_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  bridges:
    br0:
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'bridge': 'br0'
            },
            'br0': {
                'name': 'br0',
                'id': 'br0',
                'index': 3,
                'interfaces': ['eth0'],
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'br0'
        interface2.netdef_id = 'br0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_bridge_link')
        self.assertIsNone(missing)

        missing = diff_data.get('interfaces', {}).get('br0', {}).get('system_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, [])

    def test_diff_missing_system_bridge_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  bridges:
    br0:
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
            },
            'br0': {
                'name': 'br0',
                'id': 'br0',
                'index': 3,
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'br0'
        interface2.netdef_id = 'br0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_bridge_link')
        self.assertEqual(missing, 'br0')

        missing = diff_data.get('interfaces', {}).get('br0', {}).get('system_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, ['eth0'])

    def test_diff_present_system_vrf_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  vrfs:
    vrf0:
      table: 1000
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'vrf': 'vrf0'
            },
            'vrf0': {
                'name': 'vrf0',
                'id': 'vrf0',
                'index': 3,
                'interfaces': ['eth0'],
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'vrf0'
        interface2.netdef_id = 'vrf0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_vrf_link')
        self.assertIsNone(missing)

        missing = diff_data.get('interfaces', {}).get('vrf0', {}).get('system_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, [])

    def test_diff_missing_system_vrf_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  vrfs:
    vrf0:
      table: 1000
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
            },
            'vrf0': {
                'name': 'vrf0',
                'id': 'vrf0',
                'index': 3,
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'vrf0'
        interface2.netdef_id = 'vrf0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('system_state', {}).get('missing_vrf_link')
        self.assertEqual(missing, 'vrf0')

        missing = diff_data.get('interfaces', {}).get('vrf0', {}).get('system_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, ['eth0'])

    def test_diff_present_netplan_bond_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  bonds:
    bond0:
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'bond': 'bond0'
            },
            'bond0': {
                'name': 'bond0',
                'id': 'bond0',
                'index': 3,
                'interfaces': ['eth0'],
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'bond0'
        interface2.netdef_id = 'bond0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_bond_link')
        self.assertIsNone(missing)

        missing = diff_data.get('interfaces', {}).get('bond0', {}).get('netplan_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, [])

    def test_diff_missing_netplan_bond_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
    eth1: {}
  bonds:
    bond0:
      interfaces:
        - eth1''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'bond': 'bond0',
            },
            'eth1': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 3,
                'bond': 'bond0',
            },
            'bond0': {
                'name': 'bond0',
                'id': 'bond0',
                'index': 4,
                'interfaces': ['eth0', 'eth1']
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'eth1'
        interface2.netdef_id = 'eth1'
        interface3 = Mock(spec=Interface)
        interface3.name = 'bond0'
        interface3.netdef_id = 'bond0'
        system_state.interface_list = [interface1, interface2, interface3]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_bond_link')
        self.assertEqual(missing, 'bond0')

        missing = diff_data.get('interfaces', {}).get('bond0', {}).get('netplan_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, ['eth0'])

    def test_diff_present_netplan_bridge_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  bridges:
    br0:
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'bridge': 'br0'
            },
            'br0': {
                'name': 'br0',
                'id': 'br0',
                'index': 3,
                'interfaces': ['eth0'],
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'br0'
        interface2.netdef_id = 'br0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_bridge_link')
        self.assertIsNone(missing)

        missing = diff_data.get('interfaces', {}).get('br0', {}).get('netplan_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, [])

    def test_diff_missing_netplan_bridge_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
    eth1: {}
  bridges:
    br0:
      interfaces:
        - eth1''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'bridge': 'br0',
            },
            'eth1': {
                'name': 'eth1',
                'id': 'eth1',
                'index': 3,
                'bridge': 'br0',
            },
            'br0': {
                'name': 'br0',
                'id': 'br0',
                'index': 4,
                'interfaces': ['eth0', 'eth1']
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'eth1'
        interface2.netdef_id = 'eth1'
        interface3 = Mock(spec=Interface)
        interface3.name = 'br0'
        interface3.netdef_id = 'br0'
        system_state.interface_list = [interface1, interface2, interface3]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_bridge_link')
        self.assertEqual(missing, 'br0')

        missing = diff_data.get('interfaces', {}).get('br0', {}).get('netplan_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, ['eth0'])

    def test_diff_present_netplan_vrf_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
  vrfs:
    vrf0:
      table: 1000
      interfaces:
        - eth0''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'vrf': 'vrf0'
            },
            'vrf0': {
                'name': 'vrf0',
                'id': 'vrf0',
                'index': 3,
                'interfaces': ['eth0'],
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'vrf0'
        interface2.netdef_id = 'vrf0'
        system_state.interface_list = [interface1, interface2]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_vrf_link')
        self.assertIsNone(missing)

        missing = diff_data.get('interfaces', {}).get('vrf0', {}).get('netplan_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, [])

    def test_diff_missing_netplan_vrf_link(self):
        with open(self.path, "w") as f:
            f.write('''network:
  ethernets:
    eth0: {}
    eth1: {}
  vrfs:
    vrf0:
      table: 1000
      interfaces:
        - eth1''')
        netplan_state = NetplanConfigState(rootdir=self.workdir.name)
        system_state = Mock(spec=SystemConfigState)

        system_state.get_data.return_value = {
            'netplan-global-state': {},
            'eth0': {
                'name': 'eth0',
                'id': 'eth0',
                'index': 2,
                'vrf': 'vrf0',
            },
            'eth1': {
                'name': 'eth1',
                'id': 'eth1',
                'index': 3,
                'vrf': 'vrf0',
            },
            'vrf0': {
                'name': 'vrf0',
                'id': 'vrf0',
                'index': 4,
                'interfaces': ['eth0', 'eth1']
            }
        }
        interface1 = Mock(spec=Interface)
        interface1.name = 'eth0'
        interface1.netdef_id = 'eth0'
        interface2 = Mock(spec=Interface)
        interface2.name = 'eth1'
        interface2.netdef_id = 'eth1'
        interface3 = Mock(spec=Interface)
        interface3.name = 'vrf0'
        interface3.netdef_id = 'vrf0'
        system_state.interface_list = [interface1, interface2, interface3]

        diff = NetplanDiffState(system_state, netplan_state)
        diff_data = diff.get_diff()

        missing = diff_data.get('interfaces', {}).get('eth0', {}).get('netplan_state', {}).get('missing_vrf_link')
        self.assertEqual(missing, 'vrf0')

        missing = diff_data.get('interfaces', {}).get('vrf0', {}).get('netplan_state', {}).get('missing_interfaces', [])
        self.assertListEqual(missing, ['eth0'])
