#!/usr/bin/python3
# Functional tests of NetworkManager keyfile parser. These are run during
# "make check" and don't touch the system configuration at all.
#
# Copyright (C) 2021 Canonical, Ltd.
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
import ctypes
import ctypes.util

from .base import TestKeyfileBase

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe_cli = os.path.join(rootdir, 'src', 'netplan.script')

lib = ctypes.CDLL(ctypes.util.find_library('netplan'))
lib.netplan_get_id_from_nm_filename.restype = ctypes.c_char_p
UUID = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'


class TestNetworkManagerKeyfileParser(TestKeyfileBase):
    '''Test NM keyfile parser as used by NetworkManager's YAML backend'''

    def test_keyfile_missing_uuid(self):
        err = self.generate_from_keyfile('[connection]\ntype=ethernets', expect_fail=True)
        self.assertIn('netplan: Keyfile: cannot find connection.uuid', err)

    def test_keyfile_missing_type(self):
        err = self.generate_from_keyfile('[connection]\nuuid=87749f1d-334f-40b2-98d4-55db58965f5f', expect_fail=True)
        self.assertIn('netplan: Keyfile: cannot find connection.type', err)

    def test_keyfile_gsm(self):
        self.generate_from_keyfile('''[connection]
id=T-Mobile Funkadelic 2
uuid={}
type=gsm

[gsm]
apn=internet2.voicestream.com
device-id=da812de91eec16620b06cd0ca5cbc7ea25245222
home-only=true
network-id=254098
password=parliament2
pin=123456
sim-id=89148000000060671234
sim-operator-id=310260
username=george.clinton.again
mtu=1042

[ipv4]
dns-search=
method=auto

[ipv6]
dns-search=
method=auto
ip6-privacy=0
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  modems:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      dhcp6: true
      mtu: 1042
      apn: "internet2.voicestream.com"
      device-id: "da812de91eec16620b06cd0ca5cbc7ea25245222"
      network-id: "254098"
      pin: "123456"
      sim-id: "89148000000060671234"
      sim-operator-id: "310260"
      username: "george.clinton.again"
      password: "parliament2"
      networkmanager:
        uuid: "{}"
        name: "T-Mobile Funkadelic 2"
        passthrough:
          gsm.home-only: "true"
          ipv4.dns-search: ""
          ipv6.dns-search: ""
'''.format(UUID, UUID)})

    def test_keyfile_cdma(self):
        self.generate_from_keyfile('''[connection]
id=T-Mobile Funkadelic 2
uuid={}
type=cdma

[cdma]
number=0123456
username=testuser
password=testpass
mtu=1042

[ipv4]
method=auto

[ipv6]
method=ignore
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  modems:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      mtu: 1042
      username: "testuser"
      password: "testpass"
      number: "0123456"
      networkmanager:
        uuid: "{}"
        name: "T-Mobile Funkadelic 2"
'''.format(UUID, UUID)})

    def test_keyfile_gsm_via_bluetooth(self):
        self.generate_from_keyfile('''[connection]
id=T-Mobile Funkadelic 2
uuid={}
type=bluetooth

[gsm]
apn=internet2.voicestream.com
device-id=da812de91eec16620b06cd0ca5cbc7ea25245222
home-only=true
network-id=254098
password=parliament2
pin=123456
sim-id=89148000000060671234
sim-operator-id=310260
username=george.clinton.again

[ipv4]
dns-search=
method=auto

[ipv6]
dns-search=
method=auto

[proxy]'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  nm-devices:
    NM-{}:
      renderer: NetworkManager
      networkmanager:
        uuid: "{}"
        name: "T-Mobile Funkadelic 2"
        passthrough:
          connection.type: "bluetooth"
          gsm.apn: "internet2.voicestream.com"
          gsm.device-id: "da812de91eec16620b06cd0ca5cbc7ea25245222"
          gsm.home-only: "true"
          gsm.network-id: "254098"
          gsm.password: "parliament2"
          gsm.pin: "123456"
          gsm.sim-id: "89148000000060671234"
          gsm.sim-operator-id: "310260"
          gsm.username: "george.clinton.again"
          ipv4.dns-search: ""
          ipv4.method: "auto"
          ipv6.dns-search: ""
          ipv6.method: "auto"
          proxy._: ""
'''.format(UUID, UUID)})

    def test_keyfile_method_auto(self):
        self.generate_from_keyfile('''[connection]
id=Test
uuid={}
type=ethernet

[ethernet]
wake-on-lan=0
mtu=1500
cloned-mac-address=00:11:22:33:44:55

[ipv4]
dns-search=
method=auto
ignore-auto-routes=true
never-default=true
route-metric=4242

[ipv6]
addr-gen-mode=eui64
dns-search=
method=auto
ip6-privacy=0
ignore-auto-routes=true
never-default=true
route-metric=4242

[proxy]
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      dhcp4-overrides:
        use-routes: false
        route-metric: 4242
      dhcp6: true
      dhcp6-overrides:
        use-routes: false
        route-metric: 4242
      macaddress: "00:11:22:33:44:55"
      ipv6-address-generation: "eui64"
      mtu: 1500
      networkmanager:
        uuid: "{}"
        name: "Test"
        passthrough:
          ipv4.dns-search: ""
          ipv6.dns-search: ""
          proxy._: ""
'''.format(UUID, UUID)})

    def test_keyfile_fail_validation(self):
        err = self.generate_from_keyfile('''[connection]
id=Test
uuid={}
type=ethernet

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
addr-gen-mode=eui64
token=::42
method=auto
'''.format(UUID), expect_fail=True)
        self.assertIn('Error in network definition:', err)

    def test_keyfile_method_manual(self):
        self.generate_from_keyfile('''[connection]
id=Test
uuid={}
type=ethernet

[ethernet]
mac-address=00:11:22:33:44:55

[ipv4]
dns-search=foo.local;bar.remote;
dns=9.8.7.6;5.4.3.2
method=manual
address1=1.2.3.4/24,8.8.8.8
address2=5.6.7.8/16
gateway=6.6.6.6
route1=1.1.2.2/16,8.8.8.8,42
route1_options=onlink=true,initrwnd=33,initcwnd=44,mtu=1024,table=102,src=10.10.10.11
route2=2.2.3.3/24,4.4.4.4

[ipv6]
addr-gen-mode=stable-privacy
dns-search=bar.local
dns=dead:beef::2;
method=manual
ip6-privacy=2
address1=1:2:3::9/128
gateway=6:6::6
route1=dead:beef::1/128,2001:1234::2
route1_options=unknown=invalid,
route2=4:5:6:7:8:9:0:1/63,,5

[proxy]
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match:
        macaddress: "00:11:22:33:44:55"
      addresses:
      - "1.2.3.4/24"
      - "5.6.7.8/16"
      - "1:2:3::9/128"
      nameservers:
        addresses:
        - 9.8.7.6
        - 5.4.3.2
        - dead:beef::2
      gateway4: 6.6.6.6
      gateway6: 6:6::6
      ipv6-address-generation: "stable-privacy"
      ipv6-privacy: true
      routes:
      - metric: 42
        table: 102
        mtu: 1024
        congestion-window: 44
        advertised-receive-window: 33
        on-link: true
        from: "10.10.10.11"
        to: "1.1.2.2/16"
        via: "8.8.8.8"
      - to: "2.2.3.3/24"
        via: "4.4.4.4"
      - to: "dead:beef::1/128"
        via: "2001:1234::2"
      - scope: "link"
        metric: 5
        to: "4:5:6:7:8:9:0:1/63"
      wakeonlan: true
      networkmanager:
        uuid: "{}"
        name: "Test"
        passthrough:
          ipv4.dns-search: "foo.local;bar.remote;"
          ipv4.method: "manual"
          ipv4.address1: "1.2.3.4/24,8.8.8.8"
          ipv6.dns-search: "bar.local"
          ipv6.route1: "dead:beef::1/128,2001:1234::2"
          ipv6.route1_options: "unknown=invalid,"
          proxy._: ""
'''.format(UUID, UUID)})

    def _template_keyfile_type(self, nd_type, nm_type, supported=True):
        self.maxDiff = None
        file = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(file))
        with open(file, 'w') as f:
            f.write('[connection]\ntype={}\nuuid={}'.format(nm_type, UUID))
        self.assertEqual(lib.netplan_clear_netdefs(), 0)
        lib.netplan_parse_keyfile(file.encode(), None)
        lib._write_netplan_conf('NM-{}'.format(UUID).encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        t = '\n        passthrough:\n          connection.type: "{}"'.format(nm_type) if not supported else ''
        match = '\n      match: {}' if nd_type in ['ethernets', 'modems', 'wifis'] else ''
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
  version: 2
  {}:
    NM-{}:
      renderer: NetworkManager{}
      networkmanager:
        uuid: "{}"{}
'''.format(nd_type, UUID, match, UUID, t))

    def test_keyfile_ethernet(self):
        self._template_keyfile_type('ethernets', 'ethernet')

    def test_keyfile_type_modem_gsm(self):
        self._template_keyfile_type('modems', 'gsm')

    def test_keyfile_type_modem_cdma(self):
        self._template_keyfile_type('modems', 'cdma')

    def test_keyfile_type_bridge(self):
        self._template_keyfile_type('bridges', 'bridge')

    def test_keyfile_type_bond(self):
        self._template_keyfile_type('bonds', 'bond')

    def test_keyfile_type_vlan(self):
        self._template_keyfile_type('nm-devices', 'vlan', False)

    def test_keyfile_type_tunnel(self):
        self._template_keyfile_type('tunnels', 'ip-tunnel', False)

    def test_keyfile_type_other(self):
        self._template_keyfile_type('nm-devices', 'dummy', False)  # wokeignore:rule=dummy

    def test_keyfile_type_wifi(self):
        self.generate_from_keyfile('''[connection]
type=wifi
uuid={}
permissions=
id=myid with spaces
interface-name=eth0

[wifi]
ssid=SOME-SSID
mode=infrastructure
hidden=true
mtu=1500
cloned-mac-address=00:11:22:33:44:55
band=a
channel=12
bssid=de:ad:be:ef:ca:fe

[wifi-security]
key-mgmt=ieee8021x

[ipv4]
method=auto
dns-search='''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "eth0"
      dhcp4: true
      macaddress: "00:11:22:33:44:55"
      mtu: 1500
      access-points:
        "SOME-SSID":
          hidden: true
          bssid: "de:ad:be:ef:ca:fe"
          band: "5GHz"
          channel: 12
          auth:
            key-management: "802.1x"
          networkmanager:
            uuid: "{}"
            name: "myid with spaces"
            passthrough:
              connection.permissions: ""
              ipv4.dns-search: ""
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(UUID, UUID, UUID)})

    def _template_keyfile_type_wifi_eap(self, method):
        self.generate_from_keyfile('''[connection]
type=wifi
uuid={}
permissions=
id=testnet
interface-name=wlan0

[wifi]
ssid=testnet
mode=infrastructure

[wifi-security]
key-mgmt=wpa-eap

[802-1x]
eap={}
identity=some-id
anonymous-identity=anon-id
password=v3rys3cr3t!
ca-cert=/some/path.key
client-cert=/some/path.client_cert
private-key=/some/path.key
private-key-password=s0s3cr3t!!111
phase2-auth=chap

[ipv4]
method=auto
dns-search='''.format(UUID, method))
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "wlan0"
      dhcp4: true
      access-points:
        "testnet":
          auth:
            key-management: "eap"
            method: "{}"
            anonymous-identity: "anon-id"
            identity: "some-id"
            ca-certificate: "/some/path.key"
            client-certificate: "/some/path.client_cert"
            client-key: "/some/path.key"
            client-key-password: "s0s3cr3t!!111"
            phase2-auth: "chap"
            password: "v3rys3cr3t!"
          networkmanager:
            uuid: "{}"
            name: "testnet"
            passthrough:
              connection.permissions: ""
              ipv4.dns-search: ""
      networkmanager:
        uuid: "{}"
        name: "testnet"
'''.format(UUID, method, UUID, UUID)})

    def test_keyfile_type_wifi_eap_peap(self):
        self._template_keyfile_type_wifi_eap('peap')

    def test_keyfile_type_wifi_eap_tls(self):
        self._template_keyfile_type_wifi_eap('tls')

    def test_keyfile_type_wifi_eap_ttls(self):
        self._template_keyfile_type_wifi_eap('ttls')

    def _template_keyfile_type_wifi(self, nd_mode, nm_mode):
        self.generate_from_keyfile('''[connection]
type=wifi
uuid={}
id=myid with spaces

[ipv4]
method=auto

[wifi]
ssid=SOME-SSID
wake-on-wlan=24
band=bg
mode={}'''.format(UUID, nm_mode))
        wifi_mode = ''
        ap_mode = ''
        if nm_mode != nd_mode:
            wifi_mode = '''
            passthrough:
              wifi.mode: "{}"'''.format(nm_mode)
        if nd_mode != 'infrastructure':
            ap_mode = '\n          mode: "%s"' % nd_mode
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      wakeonwlan:
      - magic_pkt
      - gtk_rekey_failure
      access-points:
        "SOME-SSID":
          band: "2.4GHz"{}
          networkmanager:
            uuid: "{}"
            name: "myid with spaces"{}
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(UUID, ap_mode, UUID, wifi_mode, UUID)})

    def test_keyfile_type_wifi_ap(self):
        self.generate_from_keyfile('''[connection]
type=wifi
uuid={}
id=myid with spaces

[ipv4]
method=shared

[wifi]
ssid=SOME-SSID
wake-on-wlan=24
band=bg
mode=ap'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      wakeonwlan:
      - magic_pkt
      - gtk_rekey_failure
      access-points:
        "SOME-SSID":
          band: "2.4GHz"
          mode: "ap"
          networkmanager:
            uuid: "{}"
            name: "myid with spaces"
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(UUID, UUID, UUID)})

    def test_keyfile_type_wifi_adhoc(self):
        self._template_keyfile_type_wifi('adhoc', 'adhoc')

    def test_keyfile_type_wifi_unknown(self):
        self._template_keyfile_type_wifi('infrastructure', 'mesh')

    def test_keyfile_type_wifi_missing_ssid(self):
        err = self.generate_from_keyfile('''[connection]\ntype=wifi\nuuid={}\nid=myid with spaces'''
                                         .format(UUID), expect_fail=True)
        self.assertFalse(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        self.assertIn('netplan: Keyfile: cannot find SSID for WiFi connection', err)

    def test_keyfile_wake_on_lan(self):
        self.generate_from_keyfile('''[connection]
type=ethernet
uuid={}
id=myid with spaces

[ethernet]
wake-on-lan=2

[ipv4]
method=auto'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      wakeonlan: true
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
        passthrough:
          ethernet.wake-on-lan: "2"
'''.format(UUID, UUID)})

    def test_keyfile_wake_on_lan_nm_default(self):
        self.generate_from_keyfile('''[connection]
type=ethernet
uuid={}
id=myid with spaces

[ethernet]
wake-on-lan=0

[ipv4]
method=auto'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(UUID, UUID)})

    def test_keyfile_modem_gsm(self):
        self.generate_from_keyfile('''[connection]
type=gsm
uuid={}
id=myid with spaces

[ipv4]
method=auto

[gsm]
auto-config=true'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  modems:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      auto-config: true
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(UUID, UUID)})

    def test_keyfile_existing_id(self):
        self.generate_from_keyfile('''[connection]
type=bridge
interface-name=mybr
uuid={}
id=renamed netplan bridge

[ipv4]
method=auto'''.format(UUID), netdef_id='mybr')
        self.assert_netplan({UUID: '''network:
  version: 2
  bridges:
    mybr:
      renderer: NetworkManager
      dhcp4: true
      networkmanager:
        uuid: "{}"
        name: "renamed netplan bridge"
'''.format(UUID)})

    def test_keyfile_yaml_wifi_hotspot(self):
        self.generate_from_keyfile('''[connection]
id=Hotspot-1
type=wifi
uuid={}
interface-name=wlan0
autoconnect=false
permissions=

[ipv4]
method=shared
dns-search=

[ipv6]
method=ignore
addr-gen-mode=1
dns-search=
ip6-privacy=0

[wifi]
ssid=my-hotspot
mode=ap
mac-address-blacklist= # wokeignore:rule=blacklist

[wifi-security]
group=ccmp;
key-mgmt=wpa-psk
pairwise=ccmp;
proto=rsn;
psk=test1234

[proxy]'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "wlan0"
      access-points:
        "my-hotspot":
          auth:
            key-management: "psk"
            password: "test1234"
          mode: "ap"
          networkmanager:
            uuid: "{}"
            name: "Hotspot-1"
            passthrough:
              connection.autoconnect: "false"
              connection.permissions: ""
              ipv4.dns-search: ""
              ipv6.addr-gen-mode: "1"
              ipv6.dns-search: ""
              wifi.mac-address-blacklist: "" # wokeignore:rule=blacklist
              wifi-security.group: "ccmp;"
              wifi-security.pairwise: "ccmp;"
              wifi-security.proto: "rsn;"
              proxy._: ""
      networkmanager:
        uuid: "{}"
        name: "Hotspot-1"
'''.format(UUID, UUID, UUID)})

    def test_keyfile_ip4_linklocal_ip6_ignore(self):
        self.generate_from_keyfile('''[connection]
id=netplan-eth1
type=ethernet
interface-name=eth1
uuid={}

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "eth1"
      networkmanager:
        uuid: "{}"
        name: "netplan-eth1"
'''.format(UUID, UUID)})

    def test_keyfile_vlan(self):
        self.generate_from_keyfile('''[connection]
id=netplan-enblue
type=vlan
interface-name=enblue
uuid={}

[vlan]
id=1
parent=en1

[ipv4]
method=manual
address1=1.2.3.4/24

[ipv6]
method=ignore
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  nm-devices:
    NM-{}:
      renderer: NetworkManager
      networkmanager:
        uuid: "{}"
        name: "netplan-enblue"
        passthrough:
          connection.type: "vlan"
          connection.interface-name: "enblue"
          vlan.id: "1"
          vlan.parent: "en1"
          ipv4.method: "manual"
          ipv4.address1: "1.2.3.4/24"
          ipv6.method: "ignore"
'''.format(UUID, UUID)})

    def test_keyfile_bridge(self):
        self.generate_from_keyfile('''[connection]
id=netplan-br0
type=bridge
interface-name=br0
uuid={}

[bridge]
ageing-time=50
priority=1000
forward-delay=12
hello-time=6
max-age=24
stp=false

[ipv4]
method=auto

[ipv6]
method=ignore
'''.format(UUID), netdef_id='br0', expect_fail=False, filename="netplan-br0.nmconnection")
        self.assert_netplan({UUID: '''network:
  version: 2
  bridges:
    br0:
      renderer: NetworkManager
      dhcp4: true
      parameters:
        ageing-time: "50"
        forward-delay: "12"
        hello-time: "6"
        max-age: "24"
        priority: 1000
        stp: false
      networkmanager:
        uuid: "{}"
        name: "netplan-br0"
'''.format(UUID)})

    def test_keyfile_bridge_default_stp(self):
        self.generate_from_keyfile('''[connection]
id=netplan-br0
type=bridge
interface-name=br0
uuid={}

[bridge]
hello-time=6

[ipv4]
method=auto

[ipv6]
method=ignore
'''.format(UUID), netdef_id='br0')
        self.assert_netplan({UUID: '''network:
  version: 2
  bridges:
    br0:
      renderer: NetworkManager
      dhcp4: true
      parameters:
        hello-time: "6"
      networkmanager:
        uuid: "{}"
        name: "netplan-br0"
'''.format(UUID)})

    def test_keyfile_bond(self):
        self.generate_from_keyfile('''[connection]
uuid={}
id=netplan-bn0
type=bond
interface-name=bn0

[bond]
mode=802.3ad
lacp_rate=fast
miimon=10
min_links=10
xmit_hash_policy=none
ad_select=none
all_slaves_active=1 # wokeignore:rule=slave
arp_interval=10
arp_ip_target=10.10.10.10,20.20.20.20
arp_validate=all
arp_all_targets=all
updelay=10
downdelay=10
fail_over_mac=none
num_grat_arp=10
num_unsol_na=10
packets_per_slave=10 # wokeignore:rule=slave
primary_reselect=none
resend_igmp=10
lp_interval=10

[ipv4]
method=auto

[ipv6]
method=ignore
'''.format(UUID), netdef_id='bn0', expect_fail=False, filename='some.keyfile')
        self.assert_netplan({UUID: '''network:
  version: 2
  bonds:
    bn0:
      renderer: NetworkManager
      dhcp4: true
      parameters:
        mode: "802.3ad"
        mii-monitor-interval: "10"
        up-delay: "10"
        down-delay: "10"
        lacp-rate: "fast"
        transmit-hash-policy: "none"
        ad-select: "none"
        arp-validate: "all"
        arp-all-targets: "all"
        fail-over-mac-policy: "none"
        primary-reselect-policy: "none"
        learn-packet-interval: "10"
        arp-interval: "10"
        min-links: 10
        all-members-active: true
        gratuitous-arp: 10
        packets-per-member: 10
        resend-igmp: 10
        arp-ip-targets:
        - 10.10.10.10
        - 20.20.20.20
      networkmanager:
        uuid: "{}"
        name: "netplan-bn0"
'''.format(UUID)})

    def test_keyfile_customer_A1(self):
        self.generate_from_keyfile('''[connection]
id=netplan-wlan0-TESTSSID
type=wifi
interface-name=wlan0
uuid={}

[ipv4]
method=auto

[ipv6]
method=ignore

[wifi]
ssid=TESTSSID
mode=infrastructure

[wifi-security]
key-mgmt=wpa-psk
psk=s0s3cr1t
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "wlan0"
      dhcp4: true
      access-points:
        "TESTSSID":
          auth:
            key-management: "psk"
            password: "s0s3cr1t"
          networkmanager:
            uuid: "ff9d6ebc-226d-4f82-a485-b7ff83b9607f"
            name: "netplan-wlan0-TESTSSID"
      networkmanager:
        uuid: "{}"
        name: "netplan-wlan0-TESTSSID"
'''.format(UUID, UUID)})

    def test_keyfile_customer_A2(self):
        self.generate_from_keyfile('''[connection]
id=gsm
type=gsm
uuid={}
interface-name=cdc-wdm1

[gsm]
apn=internet

[ipv4]
method=auto
address1=10.10.28.159/24
address2=10.10.164.254/24
address3=10.10.246.132/24
dns=8.8.8.8;8.8.4.4;

[ipv6]
method=auto
addr-gen-mode=1
ip6-privacy=0
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  modems:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "cdc-wdm1"
      nameservers:
        addresses:
        - 8.8.8.8
        - 8.8.4.4
      dhcp4: true
      dhcp6: true
      apn: "internet"
      networkmanager:
        uuid: "{}"
        name: "gsm"
        passthrough:
          ipv4.address1: "10.10.28.159/24"
          ipv4.address2: "10.10.164.254/24"
          ipv4.address3: "10.10.246.132/24"
          ipv6.addr-gen-mode: "1"
'''.format(UUID, UUID)})

    def test_keyfile_netplan0103_compat(self):
        self.generate_from_keyfile('''[connection]
id=Work Wired
uuid={}
type=ethernet
autoconnect=false
permissions=
timestamp=305419896

[ethernet]
mac-address=99:88:77:66:55:44
mac-address-blacklist= # wokeignore:rule=blacklist
mtu=900

[ipv4]
address1=192.168.0.5/24,192.168.0.1
address2=1.2.3.4/8
dns=4.2.2.1;4.2.2.2;
dns-search=
method=manual
route1=10.10.10.2/24,10.10.10.1,3
route2=1.1.1.1/8,1.2.1.1,1
route3=2.2.2.2/7
route4=3.3.3.3/6,0.0.0.0,4
route4_options=cwnd=10,mtu=1492,src=1.2.3.4

[ipv6]
addr-gen-mode=stable-privacy
address1=abcd::beef/64
address2=dcba::beef/56
dns=1::cafe;2::cafe;
dns-search=wallaceandgromit.com;
method=manual
ip6-privacy=1
route1=1:2:3:4:5:6:7:8/64,8:7:6:5:4:3:2:1,3
route2=2001::1000/56,2001::1111,1
route3=4:5:6:7:8:9:0:1/63,::,5
route4=5:6:7:8:9:0:1:2/62

[proxy]
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match:
        macaddress: "99:88:77:66:55:44"
      addresses:
      - "192.168.0.5/24"
      - "1.2.3.4/8"
      - "abcd::beef/64"
      - "dcba::beef/56"
      nameservers:
        addresses:
        - 4.2.2.1
        - 4.2.2.2
        - 1::cafe
        - 2::cafe
      ipv6-address-generation: "stable-privacy"
      mtu: 900
      routes:
      - metric: 3
        to: "10.10.10.2/24"
        via: "10.10.10.1"
      - metric: 1
        to: "1.1.1.1/8"
        via: "1.2.1.1"
      - scope: "link"
        to: "2.2.2.2/7"
      - scope: "link"
        metric: 4
        mtu: 1492
        from: "1.2.3.4"
        to: "3.3.3.3/6"
      - metric: 3
        to: "1:2:3:4:5:6:7:8/64"
        via: "8:7:6:5:4:3:2:1"
      - metric: 1
        to: "2001::1000/56"
        via: "2001::1111"
      - scope: "link"
        metric: 5
        to: "4:5:6:7:8:9:0:1/63"
      - scope: "link"
        to: "5:6:7:8:9:0:1:2/62"
      wakeonlan: true
      networkmanager:
        uuid: "{}"
        name: "Work Wired"
        passthrough:
          connection.autoconnect: "false"
          connection.permissions: ""
          connection.timestamp: "305419896"
          ethernet.mac-address-blacklist: "" # wokeignore:rule=blacklist
          ipv4.address1: "192.168.0.5/24,192.168.0.1"
          ipv4.dns-search: ""
          ipv4.method: "manual"
          ipv4.route4: "3.3.3.3/6,0.0.0.0,4"
          ipv4.route4_options: "cwnd=10,mtu=1492,src=1.2.3.4"
          ipv6.dns-search: "wallaceandgromit.com;"
          ipv6.ip6-privacy: "1"
          proxy._: ""
'''.format(UUID, UUID)})

    def test_keyfile_tunnel_regression_lp1952967(self):
        self.generate_from_keyfile('''[connection]
id=IP tunnel connection 1
uuid={}
type=ip-tunnel
autoconnect=false
interface-name=gre10
permissions=

[ip-tunnel]
local=10.20.20.1
mode=2
remote=10.20.20.2

[ipv4]
dns-search=
method=auto

[ipv6]
addr-gen-mode=stable-privacy
dns-search=
method=auto

[proxy]
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  tunnels:
    NM-{}:
      renderer: NetworkManager
      dhcp4: true
      dhcp6: true
      ipv6-address-generation: "stable-privacy"
      mode: "gre"
      local: "10.20.20.1"
      remote: "10.20.20.2"
      networkmanager:
        uuid: "{}"
        name: "IP tunnel connection 1"
        passthrough:
          connection.autoconnect: "false"
          connection.interface-name: "gre10"
          connection.permissions: ""
          ipv4.dns-search: ""
          ipv6.dns-search: ""
          ipv6.ip6-privacy: "-1"
          proxy._: ""
'''.format(UUID, UUID)})

    def test_keyfile_ip6_privacy_default_netplan_0104_compat(self):
        self.generate_from_keyfile('''[connection]
id=Test
uuid={}
type=ethernet

[ethernet]
mac-address=99:88:77:66:55:44

[ipv4]
method=auto

[ipv6]
method=auto
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match:
        macaddress: "99:88:77:66:55:44"
      dhcp4: true
      dhcp6: true
      wakeonlan: true
      networkmanager:
        uuid: "{}"
        name: "Test"
        passthrough:
          ipv6.ip6-privacy: "-1"
'''.format(UUID, UUID)})

    def test_keyfile_wpa3_sae(self):
        self.generate_from_keyfile('''[connection]
id=test2
uuid={}
type=wifi
interface-name=wlan0

[wifi]
mode=infrastructure
ssid=ubuntu-wpa2-wpa3-mixed

[wifi-security]
key-mgmt=sae
psk=test1234

[ipv4]
method=auto

[ipv6]
addr-gen-mode=stable-privacy
method=auto

[proxy]
'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "wlan0"
      dhcp4: true
      dhcp6: true
      ipv6-address-generation: "stable-privacy"
      access-points:
        "ubuntu-wpa2-wpa3-mixed":
          auth:
            key-management: "none"
            password: "test1234"
          networkmanager:
            uuid: "ff9d6ebc-226d-4f82-a485-b7ff83b9607f"
            name: "test2"
            passthrough:
              wifi-security.key-mgmt: "sae"
              ipv6.ip6-privacy: "-1"
              proxy._: ""
      networkmanager:
        uuid: "{}"
        name: "test2"
'''.format(UUID, UUID)})

    def test_keyfile_dns_search_ip4_ip6_conflict(self):
        self.generate_from_keyfile('''[connection]
id=Work Wired
type=ethernet
uuid={}
autoconnect=false
timestamp=305419896

[ethernet]
wake-on-lan=1
mac-address=99:88:77:66:55:44
mtu=900

[ipv4]
method=manual
address1=192.168.0.5/24,192.168.0.1
address2=1.2.3.4/8
dns=4.2.2.1;4.2.2.2;

[ipv6]
method=manual
address1=abcd::beef/64
address2=dcba::beef/56
addr-gen-mode=1
dns=1::cafe;2::cafe;
dns-search=wallaceandgromit.com;

[proxy]\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match:
        macaddress: "99:88:77:66:55:44"
      addresses:
      - "192.168.0.5/24"
      - "1.2.3.4/8"
      - "abcd::beef/64"
      - "dcba::beef/56"
      nameservers:
        addresses:
        - 4.2.2.1
        - 4.2.2.2
        - 1::cafe
        - 2::cafe
      mtu: 900
      wakeonlan: true
      networkmanager:
        uuid: "{}"
        name: "Work Wired"
        passthrough:
          connection.autoconnect: "false"
          connection.timestamp: "305419896"
          ethernet.wake-on-lan: "1"
          ipv4.method: "manual"
          ipv4.address1: "192.168.0.5/24,192.168.0.1"
          ipv6.addr-gen-mode: "1"
          ipv6.dns-search: "wallaceandgromit.com;"
          ipv6.ip6-privacy: "-1"
          proxy._: ""
'''.format(UUID, UUID)})

    def test_keyfile_nm_140_default_ethernet_group(self):
        self.generate_from_keyfile('''[connection]
id=Test Write Bridge Main
uuid={}
type=bridge
interface-name=br0

[ethernet]

[bridge]

[ipv4]
address1=1.2.3.4/24,1.1.1.1
method=manual

[ipv6]
addr-gen-mode=default
method=auto

[proxy]\n'''.format(UUID), netdef_id='br0')
        self.assert_netplan({UUID: '''network:
  version: 2
  bridges:
    br0:
      renderer: NetworkManager
      addresses:
      - "1.2.3.4/24"
      dhcp6: true
      networkmanager:
        uuid: "{}"
        name: "Test Write Bridge Main"
        passthrough:
          ethernet._: ""
          bridge._: ""
          ipv4.address1: "1.2.3.4/24,1.1.1.1"
          ipv4.method: "manual"
          ipv6.addr-gen-mode: "default"
          ipv6.ip6-privacy: "-1"
          proxy._: ""
'''.format(UUID)})

    def test_multiple_eap_methods(self):
        self.generate_from_keyfile('''[connection]
id=MyWifi
uuid={}
type=wifi
interface-name=wlp2s0

[wifi]
mode=infrastructure
ssid=MyWifi

[wifi-security]
auth-alg=open
key-mgmt=wpa-eap

[802-1x]
ca-cert=/path/to/my/crt.crt
eap=peap;tls
identity=username
password=123456
phase2-auth=mschapv2

[ipv4]
method=auto\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "wlp2s0"
      dhcp4: true
      access-points:
        "MyWifi":
          auth:
            key-management: "eap"
            method: "peap"
            identity: "username"
            ca-certificate: "/path/to/my/crt.crt"
            phase2-auth: "mschapv2"
            password: "123456"
          networkmanager:
            uuid: "{}"
            name: "MyWifi"
            passthrough:
              wifi-security.auth-alg: "open"
              802-1x.eap: "peap;tls"
      networkmanager:
        uuid: "{}"
        name: "MyWifi"
'''.format(UUID, UUID, UUID)})

    def test_single_eap_method(self):
        self.generate_from_keyfile('''[connection]
id=MyWifi
uuid={}
type=wifi
interface-name=wlp2s0

[wifi]
mode=infrastructure
ssid=MyWifi

[wifi-security]
auth-alg=open
key-mgmt=wpa-eap

[802-1x]
ca-cert=/path/to/my/crt.crt
eap=peap;
identity=username
password=123456
phase2-auth=mschapv2

[ipv4]
method=auto\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      match:
        name: "wlp2s0"
      dhcp4: true
      access-points:
        "MyWifi":
          auth:
            key-management: "eap"
            method: "peap"
            identity: "username"
            ca-certificate: "/path/to/my/crt.crt"
            phase2-auth: "mschapv2"
            password: "123456"
          networkmanager:
            uuid: "{}"
            name: "MyWifi"
            passthrough:
              wifi-security.auth-alg: "open"
      networkmanager:
        uuid: "{}"
        name: "MyWifi"
'''.format(UUID, UUID, UUID)})

    def test_simple_wireguard(self):
        self.generate_from_keyfile('''[connection]
id=wg0
type=wireguard
uuid={}
interface-name=wg0

[ipv4]
method=auto\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  tunnels:
    NM-{}:
      renderer: NetworkManager
      dhcp4: true
      mode: "wireguard"
      networkmanager:
        uuid: "{}"
        name: "wg0"
        passthrough:
          connection.interface-name: "wg0"
'''.format(UUID, UUID)})

    def test_wireguard_with_key(self):
        self.generate_from_keyfile('''[connection]
id=wg0
type=wireguard
uuid={}
interface-name=wg0

[wireguard]
private-key=aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A=

[ipv4]
method=auto\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  tunnels:
    NM-{}:
      renderer: NetworkManager
      dhcp4: true
      mode: "wireguard"
      keys:
        private: "aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A="
      networkmanager:
        uuid: "{}"
        name: "wg0"
        passthrough:
          connection.interface-name: "wg0"
'''.format(UUID, UUID)})

    def test_wireguard_with_key_and_peer(self):
        self.generate_from_keyfile('''[connection]
id=wg0
type=wireguard
uuid={}
interface-name=wg0

[wireguard]
private-key=aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A=

[wireguard-peer.cwkb7k0xDgLSnunZpFIjLJw4u+mJDDr+aBR5DqzpmgI=]
endpoint=1.2.3.4:12345
allowed-ips=192.168.0.0/24;

[ipv4]
method=auto\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  tunnels:
    NM-{}:
      renderer: NetworkManager
      dhcp4: true
      mode: "wireguard"
      keys:
        private: "aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A="
      peers:
      - endpoint: "1.2.3.4:12345"
        keys:
          public: "cwkb7k0xDgLSnunZpFIjLJw4u+mJDDr+aBR5DqzpmgI="
        allowed-ips:
        - "192.168.0.0/24"
      networkmanager:
        uuid: "{}"
        name: "wg0"
        passthrough:
          connection.interface-name: "wg0"
'''.format(UUID, UUID)})

    def test_wireguard_allowed_ips_without_prefix(self):
        '''
        When the IP prefix is not present we should default to /32
        '''
        self.generate_from_keyfile('''[connection]
id=wg0
type=wireguard
uuid={}
interface-name=wg0

[wireguard]
private-key=aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A=

[wireguard-peer.cwkb7k0xDgLSnunZpFIjLJw4u+mJDDr+aBR5DqzpmgI=]
endpoint=1.2.3.4:12345
allowed-ips=192.168.0.10

[ipv4]
method=auto\n'''.format(UUID), regenerate=False)
        self.assert_netplan({UUID: '''network:
  version: 2
  tunnels:
    NM-{}:
      renderer: NetworkManager
      dhcp4: true
      mode: "wireguard"
      keys:
        private: "aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A="
      peers:
      - endpoint: "1.2.3.4:12345"
        keys:
          public: "cwkb7k0xDgLSnunZpFIjLJw4u+mJDDr+aBR5DqzpmgI="
        allowed-ips:
        - "192.168.0.10/32"
      networkmanager:
        uuid: "{}"
        name: "wg0"
        passthrough:
          connection.interface-name: "wg0"
'''.format(UUID, UUID)})

    def test_wireguard_with_key_and_peer_without_allowed_ips(self):
        self.generate_from_keyfile('''[connection]
id=wg0
type=wireguard
uuid={}
interface-name=wg0

[wireguard]
private-key=aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A=

[wireguard-peer.cwkb7k0xDgLSnunZpFIjLJw4u+mJDDr+aBR5DqzpmgI=]
endpoint=1.2.3.4:12345

[ipv4]
method=auto\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  tunnels:
    NM-{}:
      renderer: NetworkManager
      dhcp4: true
      mode: "wireguard"
      keys:
        private: "aPUcp5vHz8yMLrzk8SsDyYnV33IhE/k20e52iKJFV0A="
      peers:
      - endpoint: "1.2.3.4:12345"
        keys:
          public: "cwkb7k0xDgLSnunZpFIjLJw4u+mJDDr+aBR5DqzpmgI="
      networkmanager:
        uuid: "{}"
        name: "wg0"
        passthrough:
          connection.interface-name: "wg0"
'''.format(UUID, UUID)})

    def test_vxlan_with_local_and_remote(self):
        self.generate_from_keyfile('''[connection]
id=vxlan10
type=vxlan
uuid={}
interface-name=vxlan10

[vxlan]
id=10
local=198.51.100.2
remote=203.0.113.1

[ipv4]
method=auto\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  tunnels:
    NM-{}:
      renderer: NetworkManager
      dhcp4: true
      mode: "vxlan"
      local: "198.51.100.2"
      remote: "203.0.113.1"
      id: 10
      networkmanager:
        uuid: "{}"
        name: "vxlan10"
        passthrough:
          connection.interface-name: "vxlan10"
'''.format(UUID, UUID)})

    def test_simple_vxlan(self):
        self.generate_from_keyfile('''[connection]
id=vxlan10
type=vxlan
uuid={}
interface-name=vxlan10

[vxlan]
id=10

[ipv4]
method=auto\n'''.format(UUID))
        self.assert_netplan({UUID: '''network:
  version: 2
  tunnels:
    NM-{}:
      renderer: NetworkManager
      dhcp4: true
      mode: "vxlan"
      id: 10
      networkmanager:
        uuid: "{}"
        name: "vxlan10"
        passthrough:
          connection.interface-name: "vxlan10"
'''.format(UUID, UUID)})

    def test_invalid_tunnel_mode(self):
        out = self.generate_from_keyfile('''[connection]
id=tun0
type=ip-tunnel
uuid={}
interface-name=tun0

[ip-tunnel]
mode=42

[ipv4]
method=auto\n'''.format(UUID), expect_fail=True)

        self.assertIn('missing or invalid \'mode\' property for tunnel', out)
