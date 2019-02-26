#
# Tests for VLAN devices config generated via netplan
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel.lapierre@canonical.com>
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
import stat
import sys

from .base import TestBase, ND_WIFI_DHCP4


class TestNetworkd(TestBase):

    def test_wifi(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s3kr1t"
        workplace:
          password: "c0mpany"
        peer2peer:
          mode: adhoc
      dhcp4: yes''')

        self.assert_networkd({'wl0.network': ND_WIFI_DHCP4 % 'wl0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:wl0,''')
        self.assert_nm_udev(None)

        # generates wpa config and enables wpasupplicant unit
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-wl0.conf')) as f:
            new_config = f.read()
            self.assertIn('''
network={
  ssid="peer2peer"
  mode=1
  key_mgmt=NONE
}
''', new_config)
            self.assertIn('''
network={
  ssid="workplace"
  key_mgmt=WPA-PSK
  psk="c0mpany"
}
''', new_config)
            self.assertIn('''
network={
  ssid="Joe's Home"
  key_mgmt=WPA-PSK
  psk="s3kr1t"
}
''', new_config)
            self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        self.assertTrue(os.path.islink(os.path.join(
            self.workdir.name, 'run/systemd/system/systemd-networkd.service.wants/netplan-wpa@wl0.service')))

    def test_wifi_route(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          password: "c0mpany"
      dhcp4: yes
      routes:
        - to: 10.10.10.0/24
          via: 8.8.8.8''')

        self.assert_networkd({'wl0.network': '''[Match]
Name=wl0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[Route]
Destination=10.10.10.0/24
Gateway=8.8.8.8

[DHCP]
RouteMetric=600
UseMTU=true
'''})

        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:wl0,''')
        self.assert_nm_udev(None)

    def test_wifi_match(self):
        err = self.generate('''network:
  version: 2
  wifis:
    somewifi:
      match:
        driver: foo
      access-points:
        workplace:
          password: "c0mpany"
      dhcp4: yes''', expect_fail=True)
        self.assertIn('networkd backend does not support wifi with match:', err)

    def test_wifi_ap(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          password: "c0mpany"
          mode: ap
      dhcp4: yes''', expect_fail=True)
        self.assertIn('networkd does not support wifi in access point mode', err)


class TestNetworkManager(TestBase):

    def test_wifi_default(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s3kr1t"
        workplace:
          password: "c0mpany"
      dhcp4: yes''')

        self.assert_nm({'wl0-Joe%27s%20Home': '''[connection]
id=netplan-wl0-Joe's Home
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=Joe's Home
mode=infrastructure

[wifi-security]
key-mgmt=wpa-psk
psk=s3kr1t
''',
                        'wl0-workplace': '''[connection]
id=netplan-wl0-workplace
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=workplace
mode=infrastructure

[wifi-security]
key-mgmt=wpa-psk
psk=c0mpany
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_wifi_match_mac(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    all:
      match:
        macaddress: 11:22:33:44:55:66
      access-points:
        workplace: {}''')

        self.assert_nm({'all-workplace': '''[connection]
id=netplan-all-workplace
type=wifi

[ethernet]
wake-on-lan=0

[802-11-wireless]
mac-address=11:22:33:44:55:66

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=workplace
mode=infrastructure
'''})

    def test_wifi_match_all(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    all:
      match: {}
      access-points:
        workplace: {mode: infrastructure}''')

        self.assert_nm({'all-workplace': '''[connection]
id=netplan-all-workplace
type=wifi

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=workplace
mode=infrastructure
'''})

    def test_wifi_ap(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        homenet:
          mode: ap
          password: s3cret''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=shared

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=ap

[wifi-security]
key-mgmt=wpa-psk
psk=s3cret
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_wifi_adhoc(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        homenet:
          mode: adhoc''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=adhoc
'''})

