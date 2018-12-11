#!/usr/bin/python3
#
# Integration tests for wireless devices
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

    @unittest.skip("Unsupported matching by driver / wifi matching makes this untestable for now")
    def test_mapping_for_driver(self):
        self.setup_ap('hw_mode=b\nchannel=1\nssid=fake net', None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  wifis:
    wifi_ifs:
      match:
        driver: mac80211_hwsim
      dhcp4: yes
      access-points:
        "fake net": {}
        decoy: {}''' % {'r': self.backend})
        self.generate_and_settle()
        p = subprocess.Popen(['netplan', 'generate', '--mapping', 'mac80211_hwsim'],
                             stdout=subprocess.PIPE)
        out = p.communicate()[0]
        self.assertEquals(p.returncode, 1)
        self.assertIn(b'mac80211_hwsim', out)

    def test_wifi_ipv4_open(self):
        self.setup_ap('hw_mode=b\nchannel=1\nssid=fake net', None)

        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  wifis:
    %(wc)s:
      dhcp4: yes
      access-points:
        "fake net": {}
        decoy: {}''' % {'r': self.backend, 'wc': self.dev_w_client})
        self.generate_and_settle()
        # nm-online doesn't wait for wifis, argh
        if self.backend == 'NetworkManager':
            self.nm_wait_connected(self.dev_w_client, 60)

        self.assert_iface_up(self.dev_w_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_w_client]))
        if self.backend == 'NetworkManager':
            out = subprocess.check_output(['nmcli', 'dev', 'show', self.dev_w_client],
                                          universal_newlines=True)
            self.assertRegex(out, 'GENERAL.CONNECTION.*netplan-%s-fake net' % self.dev_w_client)
            self.assertRegex(out, 'IP4.DNS.*192.168.5.1')
        else:
            out = subprocess.check_output(['networkctl', 'status', self.dev_w_client],
                                          universal_newlines=True)
            self.assertRegex(out, 'DNS.*192.168.5.1')

    def test_wifi_ipv4_wpa2(self):
        self.setup_ap('''hw_mode=g
channel=1
ssid=fake net
wpa=1
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
wpa_passphrase=12345678
''', None)

        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  wifis:
    %(wc)s:
      dhcp4: yes
      access-points:
        "fake net":
          password: 12345678
        decoy: {}''' % {'r': self.backend, 'wc': self.dev_w_client})
        self.generate_and_settle()
        # nm-online doesn't wait for wifis, argh
        if self.backend == 'NetworkManager':
            self.nm_wait_connected(self.dev_w_client, 60)

        self.assert_iface_up(self.dev_w_client,
                             ['inet 192.168.5.[0-9]+/24'],
                             ['master'])
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_w_client]))
        if self.backend == 'NetworkManager':
            out = subprocess.check_output(['nmcli', 'dev', 'show', self.dev_w_client],
                                          universal_newlines=True)
            self.assertRegex(out, 'GENERAL.CONNECTION.*netplan-%s-fake net' % self.dev_w_client)
            self.assertRegex(out, 'IP4.DNS.*192.168.5.1')
        else:
            out = subprocess.check_output(['networkctl', 'status', self.dev_w_client],
                                          universal_newlines=True)
            self.assertRegex(out, 'DNS.*192.168.5.1')


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'

    def test_wifi_ap_open(self):
        # we use dev_w_client and dev_w_ap in switched roles here, to keep the
        # existing device blacklisting in NM; i. e. dev_w_client is the
        # NM-managed AP, and dev_w_ap the manually managed client
        with open(self.config, 'w') as f:
            f.write('''network:
  wifis:
    renderer: NetworkManager
    %(wc)s:
      dhcp4: yes
      access-points:
        "fake net":
          mode: ap''' % {'wc': self.dev_w_client})
        self.generate_and_settle()

        # nm-online doesn't wait for wifis, argh
        self.nm_wait_connected(self.dev_w_client, 60)

        out = subprocess.check_output(['iw', 'dev', self.dev_w_client, 'info'],
                                      universal_newlines=True)
        self.assertIn('type AP', out)
        self.assertIn('ssid fake net', out)

        # connect the other end
        subprocess.check_call(['ip', 'link', 'set', self.dev_w_ap, 'up'])
        subprocess.check_call(['iw', 'dev', self.dev_w_ap, 'connect', 'fake net'])
        out = subprocess.check_output(['dhclient', '-1', '-v', self.dev_w_ap],
                                      stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertIn('DHCPACK', out)
        out = subprocess.check_output(['iw', 'dev', self.dev_w_ap, 'info'],
                                      universal_newlines=True)
        self.assertIn('type managed', out)
        self.assertIn('ssid fake net', out)
        out = subprocess.check_output(['ip', 'a', 'show', self.dev_w_ap],
                                      universal_newlines=True)
        self.assertIn('state UP', out)
        self.assertIn('inet 10.', out)


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
