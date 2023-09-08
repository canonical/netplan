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

import os
import tempfile
import unittest

from unittest.mock import Mock
from netplan.netdef import NetplanRoute
from netplan_cli.cli.state import Interface, NetplanConfigState, SystemConfigState
from netplan_cli.cli.state_diff import NetplanDiffState


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
        missing = diff_data.get('missing_interfaces_system', [])
        self.assertListEqual(missing, [])

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
