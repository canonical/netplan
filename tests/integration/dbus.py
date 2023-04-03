#!/usr/bin/python3
#
# Integration tests for netplan-dbus
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2018-2023 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
# Author: Lukas Märdian <slyon@ubuntu.com>
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

import json
import os
import signal
import sys
import subprocess
import unittest

from base import IntegrationTestsBase

BUSCTL_CONFIG = [
        'busctl',
        '-j',
        'call',
        '--system',
        'io.netplan.Netplan',
        '/io/netplan/Netplan',
        'io.netplan.Netplan',
        'Config'
        ]

BUSCTL_CONFIG_GET = [
        'busctl',
        '-j',
        'call',
        '--system',
        'io.netplan.Netplan',
        'PLACEHOLDER',
        'io.netplan.Netplan.Config',
        'Get'
        ]

BUSCTL_CONFIG_APPLY = [
        'busctl',
        '-j',
        'call',
        '--system',
        'io.netplan.Netplan',
        'PLACEHOLDER',
        'io.netplan.Netplan.Config',
        'Apply'
        ]


class _CommonTests():

    def setUp(self):
        super().setUp()

        # If netplan-dbus is already running let's terminate it to
        # be sure the process is not from a binary from an old package
        # (before the installation of the one being tested)
        cmd = ['ps', '-C', 'netplan-dbus', '-o', 'pid=']
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode == 0:
            pid = out.stdout.strip()
            os.kill(int(pid), signal.SIGTERM)

    def test_dbus_config_get(self):
        NETPLAN_YAML = '''network:
  version: 2
  ethernets:
    %(nic)s:
      dhcp4: true
'''

        with open(self.config, 'w') as f:
            f.write(NETPLAN_YAML % {'nic': self.dev_e_client})

        out = subprocess.run(BUSCTL_CONFIG, capture_output=True, text=True)

        self.assertEqual(out.returncode, 0, msg=f"Busctl Config() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        config_path = out_dict.get('data')[0]
        self.assertNotEqual(config_path, "", msg="Got an empty response from DBUS")

        # The path has the following format: /io/netplan/Netplan/config/WM6X01
        BUSCTL_CONFIG_GET[5] = config_path

        # Retrieving the config
        out = subprocess.run(BUSCTL_CONFIG_GET, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, msg=f"Busctl Get() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        netplan_data = out_dict.get('data')[0]

        self.assertNotEqual(netplan_data, "", msg="Got an empty response from DBUS")
        self.assertEqual(netplan_data, NETPLAN_YAML % {'nic': self.dev_e_client},
                         msg="The original YAML is different from the one returned by DBUS")

    def test_dbus_config_set(self):
        BUSCTL_CONFIG_SET = [
            'busctl',
            '-j',
            'call',
            '--system',
            'io.netplan.Netplan',
            'PLACEHOLDER',
            'io.netplan.Netplan.Config',
            'Set',
            'ss',
            'ethernets.%(nic)s.dhcp4=false' % {'nic': self.dev_e_client},
            '',
        ]

        NETPLAN_YAML_BEFORE = '''network:
  version: 2
  ethernets:
    %(nic)s:
      dhcp4: true
'''

        NETPLAN_YAML_AFTER = '''network:
  version: 2
  ethernets:
    %(nic)s:
      dhcp4: false
'''
        with open(self.config, 'w') as f:
            f.write(NETPLAN_YAML_BEFORE % {'nic': self.dev_e_client})

        out = subprocess.run(BUSCTL_CONFIG, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, msg=f"Busctl Config() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        config_path = out_dict.get('data')[0]

        self.assertNotEqual(config_path, "", msg="Got an empty response from DBUS")

        # The path has the following format: /io/netplan/Netplan/config/WM6X01
        BUSCTL_CONFIG_GET[5] = config_path
        BUSCTL_CONFIG_SET[5] = config_path

        # Changing the configuration
        out = subprocess.run(BUSCTL_CONFIG_SET, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, msg=f"Busctl Set() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        self.assertEqual(out_dict.get('data')[0], True, msg="Set command failed")

        # Retrieving the configuration
        out = subprocess.run(BUSCTL_CONFIG_GET, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, msg=f"Busctl Get() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        netplan_data = out_dict.get('data')[0]

        self.assertNotEqual(netplan_data, "", msg="Got an empty response from DBUS")
        self.assertEqual(NETPLAN_YAML_AFTER % {'nic': self.dev_e_client},
                         netplan_data, msg="The final YAML is different than expected")

    def test_dbus_config_apply(self):
        NETPLAN_YAML = '''network:
  version: 2
  bridges:
    br1234:
      dhcp4: false
'''

        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br1234'], stderr=subprocess.DEVNULL)

        with open(self.config, 'w') as f:
            f.write(NETPLAN_YAML)

        out = subprocess.run(BUSCTL_CONFIG, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, msg=f"Busctl Config() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        config_path = out_dict.get('data')[0]

        self.assertNotEqual(config_path, "", msg="Got an empty response from DBUS")

        # The path has the following format: /io/netplan/Netplan/config/WM6X01
        BUSCTL_CONFIG_APPLY[5] = config_path

        # Applying the configuration
        out = subprocess.run(BUSCTL_CONFIG_APPLY, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, msg=f"Busctl Apply() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        self.assertEqual(out_dict.get('data')[0], True, msg="Apply command failed")

        self.assert_iface('br1234')


class TestNetworkd(IntegrationTestsBase, _CommonTests):
    pass


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
