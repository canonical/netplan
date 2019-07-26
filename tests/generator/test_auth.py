#
# Tests for network authentication config generated via netplan
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

from .base import TestBase, ND_DHCP4, ND_WIFI_DHCP4


class TestNetworkd(TestBase):

    def test_auth_wifi_detailed(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s3kr1t"
        "Luke's Home":
          auth:
            key-management: psk
            password: "4lsos3kr1t"
        workplace:
          auth:
            key-management: eap
            method: ttls
            anonymous-identity: "@internal.example.com"
            identity: "joe@internal.example.com"
            password: "v3ryS3kr1t"
        workplace2:
          auth:
            key-management: eap
            method: peap
            identity: "joe@internal.example.com"
            password: "v3ryS3kr1t"
            ca-certificate: /etc/ssl/work2-cacrt.pem
        workplacehashed:
          auth:
            key-management: eap
            method: ttls
            anonymous-identity: "@internal.example.com"
            identity: "joe@internal.example.com"
            password: hash:9db1636cedc5948537e7bee0cc1e9590
        customernet:
          auth:
            key-management: eap
            method: tls
            anonymous-identity: "@cust.example.com"
            identity: "cert-joe@cust.example.com"
            ca-certificate: /etc/ssl/cust-cacrt.pem
            client-certificate: /etc/ssl/cust-crt.pem
            client-key: /etc/ssl/cust-key.pem
            client-key-password: "d3cryptPr1v4t3K3y"
        opennet:
          auth:
            key-management: none
        peer2peer:
          mode: adhoc
          auth: {}
      dhcp4: yes
      ''')

        self.assert_networkd({'wl0.network': ND_WIFI_DHCP4 % 'wl0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:wl0,''')
        self.assert_nm_udev(None)

        # generates wpa config and enables wpasupplicant unit
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-wl0.conf')) as f:
            new_config = f.read()
            self.assertIn('ctrl_interface=/run/wpa_supplicant', new_config)
            self.assertIn('''
network={
  ssid="peer2peer"
  mode=1
  key_mgmt=NONE
}
''', new_config)
            self.assertIn('''
network={
  ssid="Luke's Home"
  key_mgmt=WPA-PSK
  psk="4lsos3kr1t"
}
''', new_config)
            self.assertIn('''
network={
  ssid="workplace2"
  key_mgmt=WPA-EAP
  eap=PEAP
  identity="joe@internal.example.com"
  password="v3ryS3kr1t"
  ca_cert="/etc/ssl/work2-cacrt.pem"
}
''', new_config)
            self.assertIn('''
network={
  ssid="workplace"
  key_mgmt=WPA-EAP
  eap=TTLS
  identity="joe@internal.example.com"
  anonymous_identity="@internal.example.com"
  password="v3ryS3kr1t"
}
''', new_config)
            self.assertIn('''
network={
  ssid="workplacehashed"
  key_mgmt=WPA-EAP
  eap=TTLS
  identity="joe@internal.example.com"
  anonymous_identity="@internal.example.com"
  password=hash:9db1636cedc5948537e7bee0cc1e9590
}
''', new_config)
            self.assertIn('''
network={
  ssid="customernet"
  key_mgmt=WPA-EAP
  eap=TLS
  identity="cert-joe@cust.example.com"
  anonymous_identity="@cust.example.com"
  ca_cert="/etc/ssl/cust-cacrt.pem"
  client_cert="/etc/ssl/cust-crt.pem"
  private_key="/etc/ssl/cust-key.pem"
  private_key_passwd="d3cryptPr1v4t3K3y"
}
''', new_config)
            self.assertIn('''
network={
  ssid="opennet"
  key_mgmt=NONE
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

    def test_auth_wired(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      auth:
        key-management: 802.1x
        method: tls
        anonymous-identity: "@cust.example.com"
        identity: "cert-joe@cust.example.com"
        ca-certificate: /etc/ssl/cust-cacrt.pem
        client-certificate: /etc/ssl/cust-crt.pem
        client-key: /etc/ssl/cust-key.pem
        client-key-password: "d3cryptPr1v4t3K3y"
      dhcp4: yes
      ''')

        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_nm_udev(None)

        # generates wpa config and enables wpasupplicant unit
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-eth0.conf')) as f:
            self.assertEqual(f.read(), '''ctrl_interface=/run/wpa_supplicant

network={
  key_mgmt=IEEE8021X
  eap=TLS
  identity="cert-joe@cust.example.com"
  anonymous_identity="@cust.example.com"
  ca_cert="/etc/ssl/cust-cacrt.pem"
  client_cert="/etc/ssl/cust-crt.pem"
  private_key="/etc/ssl/cust-key.pem"
  private_key_passwd="d3cryptPr1v4t3K3y"
}
''')
            self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        self.assertTrue(os.path.islink(os.path.join(
            self.workdir.name, 'run/systemd/system/systemd-networkd.service.wants/netplan-wpa@eth0.service')))


class TestNetworkManager(TestBase):

    def test_auth_wifi_detailed(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s3kr1t"
        "Luke's Home":
          auth:
            key-management: psk
            password: "4lsos3kr1t"
        workplace:
          auth:
            key-management: eap
            method: ttls
            anonymous-identity: "@internal.example.com"
            identity: "joe@internal.example.com"
            password: "v3ryS3kr1t"
        workplace2:
          auth:
            key-management: eap
            method: peap
            identity: "joe@internal.example.com"
            password: "v3ryS3kr1t"
            ca-certificate: /etc/ssl/work2-cacrt.pem
        workplacehashed:
          auth:
            key-management: eap
            method: ttls
            anonymous-identity: "@internal.example.com"
            identity: "joe@internal.example.com"
            password: hash:9db1636cedc5948537e7bee0cc1e9590
        customernet:
          auth:
            key-management: 802.1x
            method: tls
            anonymous-identity: "@cust.example.com"
            identity: "cert-joe@cust.example.com"
            ca-certificate: /etc/ssl/cust-cacrt.pem
            client-certificate: /etc/ssl/cust-crt.pem
            client-key: /etc/ssl/cust-key.pem
            client-key-password: "d3cryptPr1v4t3K3y"
        opennet:
          auth:
            key-management: none
        peer2peer:
          mode: adhoc
          auth: {}
      dhcp4: yes
      ''')

        self.assert_networkd({})
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
                        'wl0-Luke%27s%20Home': '''[connection]
id=netplan-wl0-Luke's Home
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=Luke's Home
mode=infrastructure

[wifi-security]
key-mgmt=wpa-psk
psk=4lsos3kr1t
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
key-mgmt=wpa-eap

[802-1x]
eap=ttls
identity=joe@internal.example.com
anonymous-identity=@internal.example.com
password=v3ryS3kr1t
''',
                        'wl0-workplace2': '''[connection]
id=netplan-wl0-workplace2
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=workplace2
mode=infrastructure

[wifi-security]
key-mgmt=wpa-eap

[802-1x]
eap=peap
identity=joe@internal.example.com
password=v3ryS3kr1t
ca-cert=/etc/ssl/work2-cacrt.pem
''',
                        'wl0-workplacehashed': '''[connection]
id=netplan-wl0-workplacehashed
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=workplacehashed
mode=infrastructure

[wifi-security]
key-mgmt=wpa-eap

[802-1x]
eap=ttls
identity=joe@internal.example.com
anonymous-identity=@internal.example.com
password=hash:9db1636cedc5948537e7bee0cc1e9590
''',
                        'wl0-customernet': '''[connection]
id=netplan-wl0-customernet
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=customernet
mode=infrastructure

[wifi-security]
key-mgmt=ieee8021x

[802-1x]
eap=tls
identity=cert-joe@cust.example.com
anonymous-identity=@cust.example.com
ca-cert=/etc/ssl/cust-cacrt.pem
client-cert=/etc/ssl/cust-crt.pem
private-key=/etc/ssl/cust-key.pem
private-key-password=d3cryptPr1v4t3K3y
''',
                        'wl0-opennet': '''[connection]
id=netplan-wl0-opennet
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=opennet
mode=infrastructure
''',
                        'wl0-peer2peer': '''[connection]
id=netplan-wl0-peer2peer
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=peer2peer
mode=adhoc
'''})
        self.assert_nm_udev(None)

    def test_auth_wired(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      auth:
        key-management: 802.1x
        method: tls
        anonymous-identity: "@cust.example.com"
        identity: "cert-joe@cust.example.com"
        ca-certificate: /etc/ssl/cust-cacrt.pem
        client-certificate: /etc/ssl/cust-crt.pem
        client-key: /etc/ssl/cust-key.pem
        client-key-password: "d3cryptPr1v4t3K3y"
      dhcp4: yes
      ''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=ignore

[802-1x]
eap=tls
identity=cert-joe@cust.example.com
anonymous-identity=@cust.example.com
ca-cert=/etc/ssl/cust-cacrt.pem
client-cert=/etc/ssl/cust-crt.pem
private-key=/etc/ssl/cust-key.pem
private-key-password=d3cryptPr1v4t3K3y
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)


class TestConfigErrors(TestBase):

    def test_auth_invalid_key_mgmt(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      auth:
        key-management: bogus''', expect_fail=True)
        self.assertIn("unknown key management type 'bogus'", err)

    def test_auth_invalid_eap_method(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      auth:
        method: bogus''', expect_fail=True)
        self.assertIn("unknown EAP method 'bogus'", err)
