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
        p = subprocess.Popen(['netplan', 'try'], bufsize=1, text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        p.send_signal(signal.SIGUSR1)
        out, err = p.communicate(timeout=10)
        self.assertEqual('', err)
        self.assertNotIn('An error occurred:', out)
        self.assertIn('Configuration accepted.', out)

    def test_try_reject_lp1949095(self):
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2''' % {'r': self.backend})
        p = subprocess.Popen(['netplan', 'try'], bufsize=1, text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        p.send_signal(signal.SIGINT)
        out, err = p.communicate(timeout=10)
        self.assertEqual('', err)
        self.assertNotIn('An error occurred:', out)
        self.assertIn('Reverting.', out)

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

    def test_try_accept_lp1959570(self):
        original_env = dict(os.environ)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'br54'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['mv', '/snap/bin/nmcli', '/usr/bin/nmcli'], stderr=subprocess.DEVNULL)
        self.addCleanup(os.environ.update, original_env)
        os.makedirs('/snap/bin', exist_ok=True)
        subprocess.call(['mv', '/usr/bin/nmcli', '/snap/bin/nmcli'])
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  bridges:
    br54:
      addresses:
      - "10.0.0.20/24"''' % {'r': self.backend})
        del os.environ['PATH']  # clear PATH, to test for LP: #1959570
        p = subprocess.Popen(['/usr/sbin/netplan', 'try'], bufsize=1, text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        p.send_signal(signal.SIGUSR1)
        out, err = p.communicate(timeout=10)
        os.environ = original_env
        self.assertEqual('', err)
        self.assertNotIn('An error occurred:', out)
        self.assertIn('Configuration accepted.', out)


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
