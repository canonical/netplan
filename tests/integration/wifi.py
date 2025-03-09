#!/usr/bin/python3
#
# Integration tests for wireless devices
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

from base import IntegrationTestsWifi, test_backends


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
        self.generate_and_settle([self.state_dhcp4(self.dev_w_client)])
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
        self.generate_and_settle([self.state_dhcp4(self.dev_w_client)])
        self.assert_iface_up(self.dev_w_client, ['inet 192.168.5.[0-9]+/24'])
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_w_client]))
        if self.backend == 'NetworkManager':
            out = subprocess.check_output(['nmcli', 'dev', 'show', self.dev_w_client],
                                          text=True)
            self.assertRegex(out, 'GENERAL.CONNECTION.*netplan-%s-fake net' % self.dev_w_client)
            self.assertRegex(out, 'IP4.DNS.*192.168.5.1')
        else:
            out = subprocess.check_output(['networkctl', 'status', self.dev_w_client],
                                          text=True)
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
        self.generate_and_settle([self.state_dhcp4(self.dev_w_client)])
        self.assert_iface_up(self.dev_w_client, ['inet 192.168.5.[0-9]+/24'])
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_w_client]))
        if self.backend == 'NetworkManager':
            out = subprocess.check_output(['nmcli', 'dev', 'show', self.dev_w_client],
                                          text=True)
            self.assertRegex(out, 'GENERAL.CONNECTION.*netplan-%s-fake net' % self.dev_w_client)
            self.assertRegex(out, 'IP4.DNS.*192.168.5.1')
        else:
            out = subprocess.check_output(['networkctl', 'status', self.dev_w_client],
                                          text=True)
            self.assertRegex(out, 'DNS.*192.168.5.1')

    def test_wifi_ipv4_wpa2_psk_sha256_only(self):
        self.setup_ap('''hw_mode=g
channel=1
ssid=fake net
wpa=2
wpa_key_mgmt=WPA-PSK-SHA256
wpa_pairwise=CCMP
ieee80211w=2
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
          auth:
            key-management: psk-sha256
            password: 12345678
        decoy: {}''' % {'r': self.backend, 'wc': self.dev_w_client})
        self.generate_and_settle([self.state_dhcp4(self.dev_w_client)])
        self.assert_iface_up(self.dev_w_client, ['inet 192.168.5.[0-9]+/24'])
        self.assertIn(b'default via 192.168.5.1',  # from DHCP
                      subprocess.check_output(['ip', 'route', 'show', 'dev', self.dev_w_client]))
        if self.backend == 'NetworkManager':
            out = subprocess.check_output(['nmcli', 'dev', 'show', self.dev_w_client],
                                          text=True)
            self.assertRegex(out, 'GENERAL.CONNECTION.*netplan-%s-fake net' % self.dev_w_client)
            self.assertRegex(out, 'IP4.DNS.*192.168.5.1')
        else:
            out = subprocess.check_output(['networkctl', 'status', self.dev_w_client],
                                          text=True)
            self.assertRegex(out, 'DNS.*192.168.5.1')

    def test_wifi_regdom(self):
        self.setup_ap('''hw_mode=g
channel=1
ssid=fake net
wpa=1
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
wpa_passphrase=12345678
''', None)

        out = subprocess.check_output(['iw', 'reg', 'get'], text=True)
        self.assertNotIn('country GB', out)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  wifis:
    %(wc)s:
      addresses: ["192.168.1.42/24"]
      regulatory-domain: GB
      access-points:
        "fake net":
          password: 12345678''' % {'r': self.backend, 'wc': self.dev_w_client})
        self.generate_and_settle([self.dev_w_client])
        self.assert_iface_up(self.dev_w_client, ['inet 192.168.1.42/24'])
        out = subprocess.check_output(['iw', 'reg', 'get'], text=True)
        self.assertIn('global\ncountry GB', out)


@unittest.skipIf("networkd" not in test_backends,
                 "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsWifi, _CommonTests):
    backend = 'networkd'


@unittest.skipIf("NetworkManager" not in test_backends,
                 "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsWifi, _CommonTests):
    backend = 'NetworkManager'

    def test_wifi_ap_open(self):
        # we use dev_w_client and dev_w_ap in switched roles here, to keep the
        # existing device denylisting in NM; i. e. dev_w_client is the
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
        self.generate_and_settle([self.state(self.dev_w_client, 'inet 10.')])
        out = subprocess.check_output(['iw', 'dev', self.dev_w_client, 'info'],
                                      text=True)
        self.assertIn('type AP', out)
        self.assertIn('ssid fake net', out)

        # connect the other end
        subprocess.check_call(['ip', 'link', 'set', self.dev_w_ap, 'up'])
        subprocess.check_call(['iw', 'dev', self.dev_w_ap, 'connect', 'fake net'])
        out = subprocess.check_output(['dhcpcd', '-w', '-d', self.dev_w_ap],
                                      stderr=subprocess.STDOUT, text=True)
        self.assertIn('acknowledged 10.', out)
        out = subprocess.check_output(['iw', 'dev', self.dev_w_ap, 'info'],
                                      text=True)
        self.assertIn('type managed', out)
        self.assertIn('ssid fake net', out)
        self.assert_iface_up(self.dev_w_ap, ['inet 10.'])

    @unittest.skip("Test if flaky. NM might generate a different MAC address.")
    def test_wifi_cloned_macaddress_stable_ssid(self):
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
  renderer: NetworkManager
  wifis:
    %(wc)s:
      addresses: ["192.168.1.42/24"]
      dhcp4: false
      dhcp6: false
      macaddress: stable-ssid
      access-points:
        "fake net":
          password: 12345678''' % {'wc': self.dev_w_client})

        subprocess.check_call(['systemctl', 'start', 'NetworkManager'])

        # Make the generated MAC address predictable
        # See nm_utils_hw_addr_gen_stable_eth() in NM for details
        # TODO: save and restore these files to avoid any impact on the
        # entire test suite.
        with open('/etc/machine-id', 'w') as f:
            f.write('ee7ac3602b6306061bd984a41eb1c045\n')
        with open('/var/lib/NetworkManager/secret_key', 'w') as f:
            f.write('nm-v2:hnIHoHp4p9kaEWU5/+dO+gFREirN1AsMoO1MPaoYxCc=')

        subprocess.check_call(['systemctl', 'restart', 'NetworkManager'])

        self.generate_and_settle([self.state_up(self.dev_w_client)])
        self.assert_iface_up(self.dev_w_client, ['ether 5e:ba:fe:fd:89:03'])


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
