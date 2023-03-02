#!/usr/bin/python3
#
# Regression tests to catch previously-fixed issues.
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

import json
import os
import sys
import signal
import subprocess
import time
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_empty_yaml_lp1795343(self):
        with open(self.config, 'w') as f:
            f.write('''''')
        self.generate_and_settle([])


@unittest.skipIf("networkd" not in test_backends,
                 "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    def test_lp1802322_bond_mac_rename(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'mybond'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    ethbn1:
      match: {name: %(ec)s}
      dhcp4: no
    ethbn2:
      match: {name: %(e2c)s}
      dhcp4: no
  bonds:
    mybond:
      interfaces: [ethbn1, ethbn2]
      macaddress: 00:0a:f7:72:a7:28
      mtu: 9000
      addresses: [ 192.168.5.9/24 ]
      gateway4: 192.168.5.1
      parameters:
        down-delay: 0
        lacp-rate: fast
        mii-monitor-interval: 100
        mode: 802.3ad
        transmit-hash-policy: layer3+4
        up-delay: 0
      ''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle([self.dev_e_client, self.dev_e2_client, 'mybond'])
        self.assert_iface_up(self.dev_e_client,
                             ['master mybond', '00:0a:f7:72:a7:28'],  # wokeignore:rule=master
                             ['inet '])
        self.assert_iface_up(self.dev_e2_client,
                             ['master mybond', '00:0a:f7:72:a7:28'],  # wokeignore:rule=master
                             ['inet '])
        self.assert_iface_up('mybond', ['inet 192.168.5.[0-9]+/24'])
        with open('/sys/class/net/mybond/bonding/slaves') as f:  # wokeignore:rule=slave
            self.assertIn(self.dev_e_client, f.read().strip())

    def test_try_accept_lp1949095(self):
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2''' % {'r': self.backend})
            os.chmod(self.config, mode=0o600)
        p = subprocess.Popen(['netplan', 'try'], bufsize=1, universal_newlines=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        p.send_signal(signal.SIGUSR1)
        out, err = p.communicate()
        p.wait(10)
        self.assertEqual('', err)
        self.assertNotIn('An error occurred:', out)
        self.assertRegex(out.strip(), r'Do you want to keep these settings\?\n\n\n'
                         r'Press ENTER before the timeout to accept the new configuration\n\n\n'
                         r'(Changes will revert in \d+ seconds\n)+'
                         r'Configuration accepted\.')

    def test_try_reject_lp1949095(self):
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2''' % {'r': self.backend})
            os.chmod(self.config, mode=0o600)
        p = subprocess.Popen(['netplan', 'try'], bufsize=1, universal_newlines=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        p.send_signal(signal.SIGINT)
        out, err = p.communicate()
        p.wait(10)
        self.assertEqual('', err)
        self.assertNotIn('An error occurred:', out)
        self.assertRegex(out.strip(), r'Do you want to keep these settings\?\n\n\n'
                         r'Press ENTER before the timeout to accept the new configuration\n\n\n'
                         r'(Changes will revert in \d+ seconds\n)+'
                         r'Reverting\.')

    def test_apply_networkd_inactive_lp1962095(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    %(ec)s:
      dhcp4: true
    %(e2c)s:
      dhcp4: true
  version: 2''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        # stop networkd to simulate the failure case
        subprocess.check_call(['systemctl', 'stop', 'systemd-networkd.service', 'systemd-networkd.socket'])
        self.generate_and_settle([self.state_dhcp4(self.dev_e_client), self.state_dhcp4(self.dev_e2_client)])
        self.assert_iface_up(self.dev_e_client, ['inet 192.168.5.[0-9]+/24'])
        self.assert_iface_up(self.dev_e2_client, ['inet 192.168.6.[0-9]+/24'])


@unittest.skipIf("NetworkManager" not in test_backends,
                 "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


class TestDbus(IntegrationTestsBase):
    # This test can be dropped when tests/integration/dbus.py is
    # integrated as an autopkgtest in the Debian package
    def test_dbus_config_get_lp1997467(self):

        NETPLAN_YAML = '''network:
  version: 2
  ethernets:
    %(nic)s:
      dhcp4: true
'''
        BUSCTL_CONFIG = [
                'busctl', '-j', 'call', '--system',
                'io.netplan.Netplan', '/io/netplan/Netplan',
                'io.netplan.Netplan', 'Config']

        BUSCTL_CONFIG_GET = [
                'busctl', '-j', 'call', '--system',
                'io.netplan.Netplan', 'PLACEHOLDER',
                'io.netplan.Netplan.Config', 'Get']

        # Terminates netplan-dbus if it is running already
        cmd = ['ps', '-C', 'netplan-dbus', '-o', 'pid=']
        out = subprocess.run(cmd, capture_output=True, universal_newlines=True)
        if out.returncode == 0:
            pid = out.stdout.strip()
            os.kill(int(pid), signal.SIGTERM)

        with open(self.config, 'w') as f:
            f.write(NETPLAN_YAML % {'nic': self.dev_e_client})

        out = subprocess.run(BUSCTL_CONFIG, capture_output=True, universal_newlines=True)
        self.assertEqual(out.returncode, 0, msg=f"Busctl Config() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        config_path = out_dict.get('data')[0]
        self.assertNotEqual(config_path, "", msg="Got an empty response from DBUS")

        # The path has the following format: /io/netplan/Netplan/config/WM6X01
        BUSCTL_CONFIG_GET[5] = config_path

        # Retrieving the config
        out = subprocess.run(BUSCTL_CONFIG_GET, capture_output=True, universal_newlines=True)
        self.assertEqual(out.returncode, 0, msg=f"Busctl Get() failed with error: {out.stderr}")

        out_dict = json.loads(out.stdout)
        netplan_data = out_dict.get('data')[0]

        self.assertNotEqual(netplan_data, "", msg="Got an empty response from DBUS")
        self.assertEqual(netplan_data, NETPLAN_YAML % {'nic': self.dev_e_client},
                         msg="The original YAML is different from the one returned by DBUS")


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
