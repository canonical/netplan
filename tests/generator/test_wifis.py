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

from .base import TestBase, ND_WIFI_DHCP4


class TestNetworkd(TestBase):

    def test_wifi(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s0s3kr1t"
          bssid: 00:11:22:33:44:55
          band: 2.4GHz
          channel: 11
        workplace:
          password: "c0mpany1"
          bssid: de:ad:be:ef:ca:fe
          band: 5GHz
          channel: 100
        peer2peer:
          mode: adhoc
        channel-no-band:
          channel: 7
        band-no-channel:
          band: 2.4G
        band-no-channel2:
          band: 5G
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
  ssid="band-no-channel2"
  freq_list=5610 5250 5500 5805 5640 5280 5530 5170 5060 5310 5560 5200 5755 5700 5340 5035 5230 5480 5590 5785 5620 5260 5510 \
5670 5040 5290 5540 5180 5845 5680 5320 5570 5210 5765 5710 5045 5600 5240 5795 5630 5270 5520 5160 5865 5660 5300 5550 5190 \
5745 5080 5690 5580 5220 5775 5720 5055 5825
  key_mgmt=NONE
}
''', new_config)
            self.assertIn('''
network={
  ssid="band-no-channel"
  freq_list=2472 2437 2467 2432 2462 2427 2457 2422 2452 2412 2417 2447 2442 2484
  key_mgmt=NONE
}
''', new_config)
            self.assertIn('''
network={
  ssid="channel-no-band"
  key_mgmt=NONE
}
''', new_config)
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
  bssid=de:ad:be:ef:ca:fe
  freq_list=5500
  key_mgmt=WPA-PSK
  psk="c0mpany1"
}
''', new_config)
            self.assertIn('''
network={
  ssid="Joe's Home"
  bssid=00:11:22:33:44:55
  freq_list=2462
  key_mgmt=WPA-PSK
  psk="s0s3kr1t"
}
''', new_config)
            self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        self.assertTrue(os.path.isfile(os.path.join(
            self.workdir.name, 'run/systemd/system/netplan-wpa-wl0.service')))
        self.assertTrue(os.path.islink(os.path.join(
            self.workdir.name, 'run/systemd/system/systemd-networkd.service.wants/netplan-wpa-wl0.service')))

    def test_wifi_route(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          password: "c0mpany1"
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
          password: "c0mpany1"
      dhcp4: yes''', expect_fail=True)
        self.assertIn('networkd backend does not support wifi with match:', err)

    def test_wifi_ap(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          password: "c0mpany1"
          mode: ap
      dhcp4: yes''', expect_fail=True)
        self.assertIn('networkd does not support wifi in access point mode', err)

    def test_wifi_wowlan(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      wakeonwlan:
        - any
        - disconnect
        - magic_pkt
        - gtk_rekey_failure
        - eap_identity_req
        - four_way_handshake
        - rfkill_release
      access-points:
        homenet: {mode: infrastructure}''')

        self.assert_networkd({'wl0.network': '''[Match]
Name=wl0

[Network]
LinkLocalAddressing=ipv6
'''})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:wl0,''')
        self.assert_nm_udev(None)

        # generates wpa config and enables wpasupplicant unit
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-wl0.conf')) as f:
            new_config = f.read()
            self.assertIn('''
wowlan_triggers=any disconnect magic_pkt gtk_rekey_failure eap_identity_req four_way_handshake rfkill_release
network={
  ssid="homenet"
  key_mgmt=NONE
}
''', new_config)
            self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        self.assertTrue(os.path.isfile(os.path.join(
            self.workdir.name, 'run/systemd/system/netplan-wpa-wl0.service')))
        self.assertTrue(os.path.islink(os.path.join(
            self.workdir.name, 'run/systemd/system/systemd-networkd.service.wants/netplan-wpa-wl0.service')))

    def test_wifi_wowlan_default(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      wakeonwlan: [default]
      access-points:
        homenet: {mode: infrastructure}''')

        self.assert_networkd({'wl0.network': '''[Match]
Name=wl0

[Network]
LinkLocalAddressing=ipv6
'''})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:wl0,''')
        self.assert_nm_udev(None)

        # generates wpa config and enables wpasupplicant unit
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-wl0.conf')) as f:
            new_config = f.read()
            self.assertIn('''
network={
  ssid="homenet"
  key_mgmt=NONE
}
''', new_config)
            self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        self.assertTrue(os.path.isfile(os.path.join(
            self.workdir.name, 'run/systemd/system/netplan-wpa-wl0.service')))
        self.assertTrue(os.path.islink(os.path.join(
            self.workdir.name, 'run/systemd/system/systemd-networkd.service.wants/netplan-wpa-wl0.service')))


class TestNetworkManager(TestBase):

    def test_wifi_default(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s0s3kr1t"
          bssid: 00:11:22:33:44:55
          band: 2.4GHz
          channel: 11
        workplace:
          password: "c0mpany1"
          bssid: de:ad:be:ef:ca:fe
          band: 5GHz
          channel: 100
        channel-no-band:
          channel: 22
        band-no-channel:
          band: 5GHz
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
bssid=00:11:22:33:44:55
band=bg
channel=11

[wifi-security]
key-mgmt=wpa-psk
psk=s0s3kr1t
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
bssid=de:ad:be:ef:ca:fe
band=a
channel=100

[wifi-security]
key-mgmt=wpa-psk
psk=c0mpany1
''',
                        'wl0-channel-no-band': '''[connection]
id=netplan-wl0-channel-no-band
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=channel-no-band
mode=infrastructure
''',
                        'wl0-band-no-channel': '''[connection]
id=netplan-wl0-band-no-channel
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=band-no-channel
mode=infrastructure
band=a
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
          password: s0s3cret''')

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
psk=s0s3cret
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

    def test_wifi_wowlan(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      wakeonwlan: [any, tcp, four_way_handshake, magic_pkt]
      access-points:
        homenet: {mode: infrastructure}''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[802-11-wireless]
wake-on-wlan=330

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=infrastructure
'''})

    def test_wifi_wowlan_default(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      wakeonwlan: [default]
      access-points:
        homenet: {mode: infrastructure}''')

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
mode=infrastructure
'''})


class TestConfigErrors(TestBase):

    def test_wifi_invalid_wowlan(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      wakeonwlan: [bogus]
      access-points:
        homenet: {mode: infrastructure}''', expect_fail=True)
        self.assertIn("Error in network definition: invalid value for wakeonwlan: 'bogus'", err)

    def test_wifi_wowlan_unsupported(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      wakeonwlan: [tcp]
      access-points:
        homenet: {mode: infrastructure}''', expect_fail=True)
        self.assertIn("ERROR: unsupported wowlan_triggers mask: 0x100", err)

    def test_wifi_wowlan_exclusive(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      wakeonwlan: [default, magic_pkt]
      access-points:
        homenet: {mode: infrastructure}''', expect_fail=True)
        self.assertIn("Error in network definition: 'default' is an exclusive flag for wakeonwlan", err)
