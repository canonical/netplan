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

from .base import TestBase, ND_WIFI_DHCP4, SD_WPA, NM_MANAGED, NM_UNMANAGED


class TestNetworkd(TestBase):

    def test_wifi(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      regulatory-domain: "DE"
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
        hidden-y:
          hidden: y
          password: "0bscur1ty"
        hidden-n:
          hidden: n
          password: "5ecur1ty"
        channel-no-band:
          channel: 7
        band-no-channel:
          band: 2.4G
        band-no-channel2:
          band: 5G
      dhcp4: yes''')

        self.assert_networkd({'wl0.network': ND_WIFI_DHCP4 % 'wl0'})
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'wl0')

        # generates wpa config and enables wpasupplicant unit
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-wl0.conf')) as f:
            new_config = f.read()

            network = 'ssid="{}"\n  freq_list='.format('band-no-channel2')
            freqs_5GHz = [5610, 5310, 5620, 5320, 5630, 5640, 5340, 5035, 5040, 5045, 5055, 5060, 5660, 5680, 5670, 5080, 5690,
                          5700, 5710, 5720, 5825, 5745, 5755, 5805, 5765, 5160, 5775, 5170, 5480, 5180, 5795, 5190, 5500, 5200,
                          5510, 5210, 5520, 5220, 5530, 5230, 5540, 5240, 5550, 5250, 5560, 5260, 5570, 5270, 5580, 5280, 5590,
                          5290, 5600, 5300, 5865, 5845, 5785]
            freqs = new_config.split(network)
            freqs = freqs[1].split('\n')[0]
            self.assertEqual(len(freqs.split(' ')), len(freqs_5GHz))
            for freq in freqs_5GHz:
                self.assertRegex(new_config, '{}[ 0-9]*{}[ 0-9]*\n'.format(network, freq))

            network = 'ssid="{}"\n  freq_list='.format('band-no-channel')
            freqs_24GHz = [2412, 2417, 2422, 2427, 2432, 2442, 2447, 2437, 2452, 2457, 2462, 2467, 2472, 2484]
            freqs = new_config.split(network)
            freqs = freqs[1].split('\n')[0]
            self.assertEqual(len(freqs.split(' ')), len(freqs_24GHz))
            for freq in freqs_24GHz:
                self.assertRegex(new_config, '{}[ 0-9]*{}[ 0-9]*\n'.format(network, freq))

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
  ssid="hidden-y"
  scan_ssid=1
  key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE
  ieee80211w=1
  psk="0bscur1ty"
}
''', new_config)
            self.assertIn('''
network={
  ssid="hidden-n"
  key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE
  ieee80211w=1
  psk="5ecur1ty"
}
''', new_config)
            self.assertIn('''
network={
  ssid="workplace"
  bssid=de:ad:be:ef:ca:fe
  freq_list=5500
  key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE
  ieee80211w=1
  psk="c0mpany1"
}
''', new_config)
            self.assertIn('''
network={
  ssid="Joe's Home"
  bssid=00:11:22:33:44:55
  freq_list=2462
  key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE
  ieee80211w=1
  psk="s0s3kr1t"
}
''', new_config)
            self.assertIn('country=DE\n', new_config)
            self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        self.assertTrue(os.path.isfile(os.path.join(
            self.workdir.name, 'run/systemd/system/netplan-wpa-wl0.service')))
        with open(os.path.join(self.workdir.name, 'run/systemd/system/netplan-wpa-wl0.service')) as f:
            self.assertEqual(f.read(), SD_WPA % {'iface': 'wl0', 'drivers': 'nl80211,wext'})
            self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o640)
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

        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'wl0')

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
        self.assertIn('wl0: workplace: networkd does not support this wifi mode', err)

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
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'wl0')

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
        self.assert_nm(None)
        self.assert_nm_udev(NM_UNMANAGED % 'wl0')

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

    def test_wifi_wpa3_personal(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: sae
            password: "********"''')

        self.assert_wpa_supplicant("wl0", """ctrl_interface=/run/wpa_supplicant

network={
  ssid="homenet"
  key_mgmt=SAE
  ieee80211w=2
  psk="********"
}
""")

    def test_wifi_wpa3_enterprise_eap_sha256(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: eap-sha256
            method: tls
            anonymous-identity: "@cust.example.com"
            identity: "cert-joe@cust.example.com"
            ca-certificate: /etc/ssl/cust-cacrt.pem
            client-certificate: /etc/ssl/cust-crt.pem
            client-key: /etc/ssl/cust-key.pem
            client-key-password: "**********"''')

        self.assert_wpa_supplicant("wl0", """ctrl_interface=/run/wpa_supplicant

network={
  ssid="homenet"
  key_mgmt=WPA-EAP WPA-EAP-SHA256
  eap=TLS
  ieee80211w=1
  identity="cert-joe@cust.example.com"
  anonymous_identity="@cust.example.com"
  ca_cert="/etc/ssl/cust-cacrt.pem"
  client_cert="/etc/ssl/cust-crt.pem"
  private_key="/etc/ssl/cust-key.pem"
  private_key_passwd="**********"
}
""")

    def test_wifi_wpa3_enterprise_eap_suite_b_192(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: eap-suite-b-192
            method: tls
            anonymous-identity: "@cust.example.com"
            identity: "cert-joe@cust.example.com"
            ca-certificate: /etc/ssl/cust-cacrt.pem
            client-certificate: /etc/ssl/cust-crt.pem
            client-key: /etc/ssl/cust-key.pem
            client-key-password: "**********"''')

        self.assert_wpa_supplicant("wl0", """ctrl_interface=/run/wpa_supplicant

network={
  ssid="homenet"
  key_mgmt=WPA-EAP-SUITE-B-192
  eap=TLS
  ieee80211w=2
  identity="cert-joe@cust.example.com"
  anonymous_identity="@cust.example.com"
  ca_cert="/etc/ssl/cust-cacrt.pem"
  client_cert="/etc/ssl/cust-crt.pem"
  private_key="/etc/ssl/cust-key.pem"
  private_key_passwd="**********"
}
""")

    def test_wifi_ieee8021x_eap_leap(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: 802.1x
            method: leap
            identity: some-id
            password: "********"''')

        self.assert_wpa_supplicant("wl0", """ctrl_interface=/run/wpa_supplicant

network={
  ssid="homenet"
  key_mgmt=IEEE8021X
  eap=LEAP
  identity="some-id"
  password="********"
}
""")

    def test_wifi_ieee8021x_eap_pwd(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: 802.1x
            method: pwd
            identity: some-id
            password: "********"''')

        self.assert_wpa_supplicant("wl0", """ctrl_interface=/run/wpa_supplicant

network={
  ssid="homenet"
  key_mgmt=IEEE8021X
  eap=PWD
  identity="some-id"
  password="********"
}
""")

    def test_wifi_ieee8021x_eap_and_psk(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          password: psk_password
          auth:
            key-management: eap
            method: leap
            identity: some-id
            password: "********"''')

        self.assert_wpa_supplicant("wl0", """ctrl_interface=/run/wpa_supplicant

network={
  ssid="homenet"
  key_mgmt=WPA-EAP
  eap=LEAP
  ieee80211w=1
  identity="some-id"
  psk="psk_password"
  password="********"
}
""")


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
        hidden-y:
          hidden: y
          password: "0bscur1ty"
        hidden-n:
          hidden: n
          password: "5ecur1ty"
        channel-no-band:
          channel: 22
        band-no-channel:
          band: 5GHz
      dhcp4: yes''')

        self.assert_nm({'wl0-Joe%27s%20Home': '''[connection]
id=netplan-wl0-Joe's Home
type=wifi
interface-name=wl0

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
pmf=2
psk=s0s3kr1t
''',
                        'wl0-workplace': '''[connection]
id=netplan-wl0-workplace
type=wifi
interface-name=wl0

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
pmf=2
psk=c0mpany1
''',
                        'wl0-hidden-y': '''[connection]
id=netplan-wl0-hidden-y
type=wifi
interface-name=wl0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=hidden-y
mode=infrastructure
hidden=true

[wifi-security]
key-mgmt=wpa-psk
pmf=2
psk=0bscur1ty
''',
                        'wl0-hidden-n': '''[connection]
id=netplan-wl0-hidden-n
type=wifi
interface-name=wl0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=hidden-n
mode=infrastructure

[wifi-security]
key-mgmt=wpa-psk
pmf=2
psk=5ecur1ty
''',
                        'wl0-channel-no-band': '''[connection]
id=netplan-wl0-channel-no-band
type=wifi
interface-name=wl0

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
        self.assert_nm_udev(NM_MANAGED % 'wl0')

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

[wifi]
mac-address=11:22:33:44:55:66
ssid=workplace
mode=infrastructure

[ipv4]
method=link-local

[ipv6]
method=ignore
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

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=workplace
mode=infrastructure
'''}, '''[device-netplan.wifis.all]
match-device=type:wifi
managed=1\n\n''')

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

[ipv4]
method=shared

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=ap

[wifi-security]
key-mgmt=wpa-psk
pmf=2
psk=s0s3cret
'''})
        self.assert_networkd({})
        self.assert_nm_udev(NM_MANAGED % 'wl0')

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

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=adhoc
'''})

    def test_wifi_adhoc_wpa_24ghz(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          mode: adhoc
          band: 2.4GHz
          channel: 7
          password: "********"''')

        self.assert_wpa_supplicant("wl0", """ctrl_interface=/run/wpa_supplicant

network={
  ssid="homenet"
  frequency=2442
  mode=1
  key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE
  ieee80211w=1
  psk="********"
}
""")

    def test_wifi_adhoc_wpa_5ghz(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          mode: adhoc
          band: 5GHz
          channel: 7
          password: "********"''')

        self.assert_wpa_supplicant("wl0", """ctrl_interface=/run/wpa_supplicant

network={
  ssid="homenet"
  frequency=5035
  mode=1
  key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE
  ieee80211w=1
  psk="********"
}
""")

    def test_wifi_wpa3_personal(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: sae
            password: "********"''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=infrastructure

[wifi-security]
key-mgmt=sae
pmf=3
psk=********
'''})

    def test_wifi_wpa3_enterprise_eap_sha256(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: eap-sha256
            method: tls
            anonymous-identity: "@cust.example.com"
            identity: "cert-joe@cust.example.com"
            ca-certificate: /etc/ssl/cust-cacrt.pem
            client-certificate: /etc/ssl/cust-crt.pem
            client-key: /etc/ssl/cust-key.pem
            client-key-password: "**********"''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=infrastructure

[wifi-security]
key-mgmt=wpa-eap
pmf=2

[802-1x]
eap=tls
identity=cert-joe@cust.example.com
anonymous-identity=@cust.example.com
ca-cert=/etc/ssl/cust-cacrt.pem
client-cert=/etc/ssl/cust-crt.pem
private-key=/etc/ssl/cust-key.pem
private-key-password=**********
'''})

    def test_wifi_wpa3_enterprise_eap_suite_b_192(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: eap-suite-b-192
            method: tls
            anonymous-identity: "@cust.example.com"
            identity: "cert-joe@cust.example.com"
            ca-certificate: /etc/ssl/cust-cacrt.pem
            client-certificate: /etc/ssl/cust-crt.pem
            client-key: /etc/ssl/cust-key.pem
            client-key-password: "**********"''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=infrastructure

[wifi-security]
key-mgmt=wpa-eap-suite-b-192
pmf=3

[802-1x]
eap=tls
identity=cert-joe@cust.example.com
anonymous-identity=@cust.example.com
ca-cert=/etc/ssl/cust-cacrt.pem
client-cert=/etc/ssl/cust-crt.pem
private-key=/etc/ssl/cust-key.pem
private-key-password=**********
'''})

    def test_wifi_ieee8021x_leap(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: 802.1x
            method: leap
            identity: "some-id"
            password: "**********"''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=infrastructure

[wifi-security]
key-mgmt=ieee8021x

[802-1x]
eap=leap
identity=some-id
password=**********
'''})

    def test_wifi_ieee8021x_pwd(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        homenet:
          auth:
            key-management: 802.1x
            method: pwd
            identity: "some-id"
            password: "**********"''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=infrastructure

[wifi-security]
key-mgmt=ieee8021x

[802-1x]
eap=pwd
identity=some-id
password=**********
'''})

    def test_wifi_eap_and_psk(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        homenet:
          password: psk_password
          auth:
            key-management: eap
            method: leap
            identity: "some-id"
            password: "**********"''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=infrastructure

[wifi-security]
key-mgmt=wpa-eap
pmf=2
psk=psk_password

[802-1x]
eap=leap
identity=some-id
password=**********
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

[wifi]
wake-on-wlan=330
ssid=homenet
mode=infrastructure

[ipv4]
method=link-local

[ipv6]
method=ignore
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

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=homenet
mode=infrastructure
'''})

    def test_wifi_regdom(self):
        out = self.generate('''network:
  wifis:
    wl0:
      regulatory-domain: GB
      access-points:
        homenet: {mode: infrastructure}
    wl1:
      regulatory-domain: DE
      access-points:
        homenet2: {mode: infrastructure}''')

        self.assertIn('wl1: Conflicting regulatory-domain (GB vs DE)', out)
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-wl0.conf')) as f:
            new_config = f.read()
            self.assertIn('country=GB\n', new_config)
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-wl1.conf')) as f:
            new_config = f.read()
            self.assertIn('country=DE\n', new_config)
        with open(os.path.join(self.workdir.name, 'run/systemd/system/netplan-regdom.service')) as f:
            new_config = f.read()
            self.assertIn('ExecStart=/usr/sbin/iw reg set DE\n', new_config)


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
