#!/usr/bin/python3
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
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

import unittest

from unittest.mock import patch, call
from netplan.cli.ovs import OPENVSWITCH_OVS_VSCTL as OVS

import netplan.cli.ovs as ovs

from utils import state_from_yaml
import tempfile


class TestOVS(unittest.TestCase):

    @patch('subprocess.check_call')
    def test_clear_settings_tag(self, mock):
        ovs.clear_setting('Bridge', 'ovs0', 'netplan/external-ids/key', 'value')
        mock.assert_called_with([OVS, 'remove', 'Bridge', 'ovs0', 'external-ids', 'netplan/external-ids/key'])

    @patch('subprocess.check_output')
    @patch('subprocess.check_call')
    def test_clear_global_ssl(self, mock, mock_out):
        mock_out.return_value = '''
Private key: /private/key.pem
Certificate: /another/cert.pem
CA Certificate: /some/ca-cert.pem
Bootstrap: false'''
        ovs.clear_setting('Open_vSwitch', '.', 'netplan/global/set-ssl', '/private/key.pem,/another/cert.pem,/some/ca-cert.pem')
        mock_out.assert_called_once_with([OVS, 'get-ssl'], universal_newlines=True)
        mock.assert_has_calls([
            call([OVS, 'del-ssl']),
            call([OVS, 'remove', 'Open_vSwitch', '.', 'external-ids', 'netplan/global/set-ssl'])
        ])

    @patch('subprocess.check_output')
    @patch('subprocess.check_call')
    def test_no_clear_global_ssl_different(self, mock, mock_out):
        mock_out.return_value = '''
Private key: /private/key.pem
Certificate: /another/cert.pem
CA Certificate: /some/ca-cert.pem
Bootstrap: false'''
        ovs.clear_setting('Open_vSwitch', '.', 'netplan/global/set-ssl', '/some/key.pem,/other/cert.pem,/some/cert.pem')
        mock_out.assert_called_once_with([OVS, 'get-ssl'], universal_newlines=True)
        mock.assert_has_calls([
            call([OVS, 'remove', 'Open_vSwitch', '.', 'external-ids', 'netplan/global/set-ssl'])
        ])

    def test_clear_global_unknown(self):
        with self.assertRaises(Exception):
            ovs.clear_setting('Bridge', 'ovs0', 'netplan/global/set-something', 'INVALID')

    @patch('subprocess.check_output')
    @patch('subprocess.check_call')
    def test_clear_global(self, mock, mock_out):
        mock_out.return_value = 'tcp:127.0.0.1:1337\nunix:/some/socket'
        ovs.clear_setting('Bridge', 'ovs0', 'netplan/global/set-controller', 'tcp:127.0.0.1:1337,unix:/some/socket')
        mock_out.assert_called_once_with([OVS, 'get-controller', 'ovs0'], universal_newlines=True)
        mock.assert_has_calls([
            call([OVS, 'del-controller', 'ovs0']),
            call([OVS, 'remove', 'Bridge', 'ovs0', 'external-ids', 'netplan/global/set-controller'])
        ])

    @patch('subprocess.check_output')
    @patch('subprocess.check_call')
    def test_no_clear_global_different(self, mock, mock_out):
        mock_out.return_value = 'unix:/var/run/openvswitch/ovs0.mgmt'
        ovs.clear_setting('Bridge', 'ovs0', 'netplan/global/set-controller', 'tcp:127.0.0.1:1337,unix:/some/socket')
        mock_out.assert_called_once_with([OVS, 'get-controller', 'ovs0'], universal_newlines=True)
        mock.assert_has_calls([
            call([OVS, 'remove', 'Bridge', 'ovs0', 'external-ids', 'netplan/global/set-controller'])
        ])

    @patch('subprocess.check_call')
    def test_clear_dict(self, mock):
        ovs.clear_setting('Bridge', 'ovs0', 'netplan/other-config/key', 'value')
        mock.assert_has_calls([
            call([OVS, 'remove', 'Bridge', 'ovs0', 'other-config', 'key', 'value']),
            call([OVS, 'remove', 'Bridge', 'ovs0', 'external-ids', 'netplan/other-config/key'])
        ])

    @patch('subprocess.check_call')
    def test_clear_col(self, mock):
        ovs.clear_setting('Port', 'bond0', 'netplan/bond_mode', 'balance-tcp')
        mock.assert_has_calls([
            call([OVS, 'remove', 'Port', 'bond0', 'bond_mode', 'balance-tcp']),
            call([OVS, 'remove', 'Port', 'bond0', 'external-ids', 'netplan/bond_mode'])
        ])

    @patch('subprocess.check_call')
    def test_clear_col_default(self, mock):
        ovs.clear_setting('Bridge', 'ovs0', 'netplan/rstp_enable', 'true')
        mock.assert_has_calls([
            call([OVS, 'set', 'Bridge', 'ovs0', 'rstp_enable=false']),
            call([OVS, 'remove', 'Bridge', 'ovs0', 'external-ids', 'netplan/rstp_enable'])
        ])

    @patch('subprocess.check_call')
    def test_clear_dict_colon(self, mock):
        ovs.clear_setting('Bridge', 'ovs0', 'netplan/other-config/key', 'fa:16:3e:4b:19:3a')
        mock.assert_has_calls([
            call([OVS, 'remove', 'Bridge', 'ovs0', 'other-config', 'key', r'fa\:16\:3e\:4b\:19\:3a']),
            call([OVS, 'remove', 'Bridge', 'ovs0', 'external-ids', 'netplan/other-config/key'])
        ])
        mock.mock_calls

    def test_is_ovs_interface(self):
        with tempfile.TemporaryDirectory() as root:
            state = state_from_yaml(root, '''network:
  ethernets:
    ovs0:
      openvswitch: {}''')
            self.assertTrue(ovs.is_ovs_interface('ovs0', state.all_defs))

    def test_is_ovs_interface_false(self):
        with tempfile.TemporaryDirectory() as root:
            state = state_from_yaml(root, '''network:
  ethernets:
    eth0: {}
    eth1: {}
  bridges:
    br0:
      interfaces:
        - eth0
        - eth1''')
        self.assertFalse(ovs.is_ovs_interface('br0', state.all_defs))

    def test_is_ovs_interface_recursive(self):
        with tempfile.TemporaryDirectory() as root:
            state = state_from_yaml(root, '''network:
  version: 2
  openvswitch:
    ports:
      - [patch0-1, patch1-0]
  ethernets:
    eth0: {}
  bonds:
    bond0:
      interfaces: [patch1-0, eth0]''')
        self.assertTrue(ovs.is_ovs_interface('bond0', state.all_defs))
