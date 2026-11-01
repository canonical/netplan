# SPDX-License-Identifier: GPL-3.0-only
# Tests for selecting configured links during apply.
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
from unittest.mock import patch

from netplan_cli.cli.commands.apply import NetplanApply
from netplan_cli.configmanager import ConfigManager


class TestLinkDevices(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        os.makedirs(os.path.join(self.root.name, 'etc/netplan'))

    def config(self, definition, backend='networkd'):
        path = os.path.join(self.root.name, 'etc/netplan/test.yaml')
        with open(path, 'w') as output:
            output.write('network:\n  renderer: ' + backend + '\n  ethernets:' +
                         ('\n' + definition if definition else ' {}\n'))
        os.chmod(path, 0o600)
        manager = ConfigManager(self.root.name)
        manager.parse()
        self.addCleanup(manager.cleanup)
        return manager

    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    def test_exact_name_avoids_attribute_queries(self, driver, mac):
        for backend in ['networkd', 'NetworkManager']:
            with self.subTest(backend=backend):
                manager = self.config('    eth42: {}\n', backend)
                self.assertEqual(NetplanApply._get_link_devices(['veth0', 'eth42', 'veth1'], manager), ['eth42'])
        driver.assert_not_called()
        mac.assert_not_called()

    @patch('netplan_cli.cli.utils.get_interface_macaddress')
    @patch('netplan_cli.cli.utils.get_interface_driver_name')
    def test_matchers_and_rename(self, driver, mac):
        driver.side_effect = lambda name: 'virtio_net' if name == 'enp0' else 'veth'
        mac.side_effect = lambda name: '00:11:22:33:44:55' if name == 'mac0' else '00:00:00:00:00:00'
        definitions = [
            ('    id: {match: {name: "eth*"}}\n', ['eth0', 'eth1']),
            ('    id: {match: {macaddress: "00:11:22:33:44:55"}}\n', ['mac0']),
            ('    id: {match: {driver: "virtio*"}}\n', ['enp0']),
            ('    id: {match: {name: "en*", driver: ["other", "virtio*"]}}\n', ['enp0']),
            ('    id: {match: {name: old0}, set-name: renamed0}\n', ['renamed0']),
        ]
        interfaces = ['eth0', 'veth0', 'mac0', 'eth1', 'enp0', 'renamed0']
        for backend in ['networkd', 'NetworkManager']:
            for definition, expected in definitions:
                with self.subTest(backend=backend, definition=definition):
                    manager = self.config(definition, backend)
                    self.assertEqual(NetplanApply._get_link_devices(interfaces, manager), expected)

    @patch('netplan_cli.cli.utils.get_interface_macaddress', return_value=None)
    @patch('netplan_cli.cli.utils.get_interface_driver_name', return_value=None)
    def test_missing_attributes(self, driver, mac):
        manager = self.config('    id: {match: {driver: missing}}\n')
        self.assertEqual(NetplanApply._get_link_devices(['eth0'], manager), [])

    @patch('netplan_cli.cli.utils.get_interface_macaddress', return_value='00:00:00:00:00:00')
    @patch('netplan_cli.cli.utils.get_interface_driver_name', return_value='veth')
    def test_attributes_are_cached_across_definitions(self, driver, mac):
        manager = self.config('    id0: {match: {driver: missing}}\n    id1: {match: {driver: veth}}\n')
        self.assertEqual(NetplanApply._get_link_devices(['eth0'], manager), ['eth0'])
        driver.assert_called_once_with('eth0')
        mac.assert_called_once_with('eth0')

    def test_empty_configuration(self):
        manager = self.config('')
        self.assertEqual(NetplanApply._get_link_devices(['eth0'], manager), [])
