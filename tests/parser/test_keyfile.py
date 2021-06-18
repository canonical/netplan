#!/usr/bin/python3
# Blackbox tests of NetworkManager netplan backend. These are run during
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

from .base import TestBase

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe_cli = os.path.join(rootdir, 'src', 'netplan.script')
# Make sure we can import our development netplan.
os.environ.update({'PYTHONPATH': '.'})

lib = ctypes.CDLL(ctypes.util.find_library('netplan'))
lib.netplan_get_id_from_nm_filename.restype = ctypes.c_char_p

class TestNetworkManagerBackend(TestBase):
    '''Test libnetplan functionality as used by NetworkManager backend'''

    def test_serialize_keyfile_missing_uuid(self):
        err = self.generate('[connection]\ntype=ethernets', expect_fail=True)
        self.assertIn('netplan: Keyfile: cannot find connection.uuid', err)

    def test_serialize_keyfile_missing_type(self):
        err = self.generate('[connection]\nuuid=87749f1d-334f-40b2-98d4-55db58965f5f', expect_fail=True)
        self.assertIn('netplan: Keyfile: cannot find connection.type', err)

    def test_serialize_gsm(self):
        uuid = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        self.generate('''[connection]
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
'''.format(uuid))
        self.assert_netplan({uuid: '''network:
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
'''.format(uuid, uuid)})

    def test_serialize_cdma(self):
        uuid = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        self.generate('''[connection]
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
'''.format(uuid))
        self.assert_netplan({uuid: '''network:
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
'''.format(uuid, uuid)})

    def test_serialize_gsm_via_bluetooth(self):
        uuid = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        self.generate('''[connection]
id=T-Mobile Funkadelic 2
uuid=a08c5805-7cf5-43f7-afb9-12cb30f6eca3
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

[proxy]''')
        self.assert_netplan({uuid: '''network:
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
'''.format(uuid, uuid)})

    def test_serialize_method_auto(self):
        uuid = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        self.generate('''[connection]
id=Test
uuid=a08c5805-7cf5-43f7-afb9-12cb30f6eca3
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
token=1234::3
dns-search=
method=auto
ignore-auto-routes=true
never-default=true
route-metric=4242

[proxy]
''')
        self.assert_netplan({uuid: '''network:
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
      ipv6-address-token: "1234::3"
      mtu: 1500
      networkmanager:
        uuid: "{}"
        name: "Test"
        passthrough:
          proxy._: ""
'''.format(uuid, uuid)})

    def test_serialize_method_manual(self):
        uuid = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        self.generate('''[connection]
id=Test
uuid=a08c5805-7cf5-43f7-afb9-12cb30f6eca3
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
address1=1:2:3::9/128
gateway=6:6::6
route1=dead:beef::1/128,2001:1234::2
route1_options=unknown=invalid,

[proxy]
''')
        self.assert_netplan({uuid: '''network:
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
        search:
        - foo.local
        - bar.remote
        - bar.local
      gateway4: 6.6.6.6
      gateway6: 6:6::6
      ipv6-address-generation: "stable-privacy"
      routes:
      - metric: 42
        table: 102
        mtu: 1024
        congestion-window: 44
        advertised-receive-window: 33
        on-link: "true"
        from: "10.10.10.11"
        to: "1.1.2.2/16"
        via: "8.8.8.8"
      - to: "2.2.3.3/24"
        via: "4.4.4.4"
      - to: "dead:beef::1/128"
        via: "2001:1234::2"
      wakeonlan: true
      networkmanager:
        uuid: "{}"
        name: "Test"
        passthrough:
          ipv4.method: "manual"
          ipv4.address1: "1.2.3.4/24,8.8.8.8"
          ipv6.route1: "dead:beef::1/128,2001:1234::2"
          ipv6.route1_options: "unknown=invalid,"
          proxy._: ""
'''.format(uuid, uuid)})

    def _template_serialize_keyfile(self, nd_type, nm_type, supported=True):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('[connection]\ntype={}\nuuid={}'.format(nm_type, UUID))
        self.assertEqual(lib.netplan_clear_netdefs(), 0)
        lib.netplan_parse_keyfile(FILE.encode(), None)
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

    def test_serialize_keyfile_ethernet(self):
        self._template_serialize_keyfile('ethernets', 'ethernet')

    def test_serialize_keyfile_type_modem_gsm(self):
        self._template_serialize_keyfile('modems', 'gsm')

    def test_serialize_keyfile_type_modem_cdma(self):
        self._template_serialize_keyfile('modems', 'cdma')

    def test_serialize_keyfile_type_bridge(self):
        self._template_serialize_keyfile('bridges', 'bridge')

    def test_serialize_keyfile_type_bond(self):
        self._template_serialize_keyfile('bonds', 'bond')

    def test_serialize_keyfile_type_vlan(self):
        self._template_serialize_keyfile('vlans', 'vlan')

    def test_serialize_keyfile_type_tunnel(self):
        self._template_serialize_keyfile('tunnels', 'ip-tunnel', False)

    def test_serialize_keyfile_type_wireguard(self):
        self._template_serialize_keyfile('tunnels', 'wireguard', False)

    def test_serialize_keyfile_type_other(self):
        self._template_serialize_keyfile('nm-devices', 'dummy', False)

    def test_serialize_keyfile_type_wifi(self):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        self.generate('''[connection]
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
dns-search='''.format(uuid))
        self.assert_netplan({uuid: '''network:
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
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(uuid, uuid, uuid)})

    def _template_serialize_keyfile_type_wifi_eap(self, method):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        self.generate('''[connection]
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
dns-search='''.format(uuid, method))
        self.assert_netplan({uuid: '''network:
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
      networkmanager:
        uuid: "{}"
        name: "testnet"
'''.format(uuid, method, uuid, uuid)})

    def test_serialize_keyfile_type_wifi_eap_peap(self):
        self._template_serialize_keyfile_type_wifi_eap('peap')

    def test_serialize_keyfile_type_wifi_eap_tls(self):
        self._template_serialize_keyfile_type_wifi_eap('tls')

    def test_serialize_keyfile_type_wifi_eap_ttls(self):
        self._template_serialize_keyfile_type_wifi_eap('ttls')

    def _template_serialize_keyfile_type_wifi(self, nd_mode, nm_mode):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        self.generate('''[connection]
type=wifi
uuid={}
id=myid with spaces

[ipv4]
method=auto

[wifi]
ssid=SOME-SSID
wake-on-wlan=24
band=bg
mode={}'''.format(uuid, nm_mode))
        wifi_mode = ''
        ap_mode = ''
        if nm_mode != nd_mode:
            wifi_mode = '\n            passthrough:\n              wifi.mode: "{}"'.format(nm_mode)
        if nd_mode != 'infrastructure':
            ap_mode = '\n          mode: "%s"' % nd_mode
        self.assert_netplan({uuid: '''network:
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
'''.format(uuid, ap_mode, uuid, wifi_mode, uuid)})

    def test_serialize_keyfile_type_wifi_ap(self):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        self.generate('''[connection]
type=wifi
uuid={}
id=myid with spaces

[ipv4]
method=shared

[wifi]
ssid=SOME-SSID
wake-on-wlan=24
band=bg
mode=ap'''.format(uuid))
        self.assert_netplan({uuid: '''network:
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
'''.format(uuid, uuid, uuid)})

    def test_serialize_keyfile_type_wifi_adhoc(self):
        self._template_serialize_keyfile_type_wifi('adhoc', 'adhoc')

    def test_serialize_keyfile_type_wifi_unknown(self):
        self._template_serialize_keyfile_type_wifi('infrastructure', 'mesh')

    def test_serialize_keyfile_type_wifi_missing_ssid(self):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        err = self.generate('''[connection]\ntype=wifi\nuuid={}\nid=myid with spaces'''.format(uuid), expect_fail=True)
        self.assertFalse(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(uuid))))
        self.assertIn('netplan: Keyfile: cannot find SSID for WiFi connection', err)

    def test_serialize_keyfile_wake_on_lan(self):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        self.generate('''[connection]
type=ethernet
uuid={}
id=myid with spaces

[ethernet]
wake-on-lan=2

[ipv4]
method=auto'''.format(uuid))
        self.assert_netplan({uuid: '''network:
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
'''.format(uuid, uuid)})

    def test_serialize_keyfile_wake_on_lan_nm_default(self):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        self.generate('''[connection]
type=ethernet
uuid={}
id=myid with spaces

[ethernet]
wake-on-lan=0

[ipv4]
method=auto'''.format(uuid))
        self.assert_netplan({uuid: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(uuid, uuid)})

    def test_serialize_keyfile_modem_gsm(self):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        self.generate('''[connection]
type=gsm
uuid={}
id=myid with spaces

[ipv4]
method=auto

[gsm]
auto-config=true'''.format(uuid))
        self.assert_netplan({uuid: '''network:
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
'''.format(uuid, uuid)})

    def test_serialize_keyfile_existing_id(self):
        uuid = '87749f1d-334f-40b2-98d4-55db58965f5f'
        self.generate('''[connection]
type=bridge
interface-name=mybr
uuid={}
id=renamed netplan bridge

[ipv4]
method=auto'''.format(uuid), netdef_id='mybr')
        self.assert_netplan({uuid: '''network:
  version: 2
  bridges:
    mybr:
      renderer: NetworkManager
      dhcp4: true
      networkmanager:
        uuid: "{}"
        name: "renamed netplan bridge"
'''.format(uuid)})

    def test_keyfile_yaml_wifi_hotspot(self):
        uuid = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        keyfile = '''[connection]
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

[wifi]
ssid=my-hotspot
mode=ap
mac-address-blacklist=

[wifi-security]
group=ccmp;
key-mgmt=wpa-psk
pairwise=ccmp;
proto=rsn;
psk=test1234

[proxy]'''.format(uuid)
        self.generate(keyfile)
        self.assert_netplan({uuid: '''network:
  version: 2
  wifis:
    NM-ff9d6ebc-226d-4f82-a485-b7ff83b9607f:
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
            uuid: "ff9d6ebc-226d-4f82-a485-b7ff83b9607f"
            name: "Hotspot-1"
            passthrough:
              connection.autoconnect: "false"
              connection.permissions: ""
              ipv6.addr-gen-mode: "1"
              wifi.mac-address-blacklist: ""
              wifi-security.group: "ccmp;"
              wifi-security.pairwise: "ccmp;"
              wifi-security.proto: "rsn;"
              proxy._: ""
      networkmanager:
        uuid: "{}"
        name: "Hotspot-1"
'''.format(uuid)})

    def test_keyfile_ip4_linklocal_ip6_ignore(self):
        uuid = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        self.generate('''[connection]
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
'''.format(uuid))

        self.assert_netplan({uuid: '''network:
  version: 2
  ethernets:
    NM-ff9d6ebc-226d-4f82-a485-b7ff83b9607f:
      renderer: NetworkManager
      match:
        name: "eth1"
      networkmanager:
        uuid: "{}"
        name: "netplan-eth1"
'''.format(uuid)})

    def test_keyfile_vlan(self):
        uuid = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        self.generate('''[connection]
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
'''.format(uuid), netdef_id='enblue', expect_fail=False, filename="some.keyfile")

        self.assert_netplan({uuid: '''network:
  version: 2
  vlans:
    enblue:
      renderer: NetworkManager
      addresses:
      - "1.2.3.4/24"
      id: 1
      networkmanager:
        uuid: "{}"
        name: "netplan-enblue"
        passthrough:
          vlan.parent: "en1"
'''.format(uuid)})

    def test_keyfile_bridge(self):
        uuid = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        self.generate('''[connection]
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
'''.format(uuid), netdef_id='br0', expect_fail=False, filename="netplan-br0.nmconnection")

        self.assert_netplan({uuid: '''network:
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
'''.format(uuid)})

    def test_keyfile_bridge_default_stp(self):
        uuid = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        self.generate('''[connection]
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
'''.format(uuid), netdef_id='br0')

        self.assert_netplan({uuid: '''network:
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
'''.format(uuid)})


    def test_keyfile_bond(self):
        uuid = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        self.generate('''[connection]
uuid={}
id=netplan-bn0
type=bond
interface-name=bn0

[bond]
mode=802.3ad
lacp_rate=10
miimon=10
min_links=10
xmit_hash_policy=none
ad_select=none
all_slaves_active=1
arp_interval=10
arp_ip_target=10.10.10.10,20.20.20.20
arp_validate=all
arp_all_targets=all
updelay=10
downdelay=10
fail_over_mac=none
num_grat_arp=10
num_unsol_na=10
packets_per_slave=10
primary_reselect=none
resend_igmp=10
lp_interval=10

[ipv4]
method=auto

[ipv6]
method=ignore
'''.format(uuid), netdef_id='bn0')

        self.assert_netplan({uuid: '''network:
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
        lacp-rate: "10"
        transmit-hash-policy: "none"
        ad-select: "none"
        arp-validate: "all"
        arp-all-targets: "all"
        fail-over-mac-policy: "none"
        primary-reselect-policy: "none"
        learn-packet-interval: "10"
        arp-interval: "10"
        min-links: 10
        all-slaves-active: true
        gratuitous-arp: 10
        packets-per-slave: 10
        resend-igmp: 10
        arp-ip-targets:
        - 10.10.10.10
        - 20.20.20.20
      networkmanager:
        uuid: "{}"
        name: "netplan-bn0"
'''.format(uuid)})

    def test_keyfile_customer_A1(self):
        uuid = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        self.generate('''[connection]
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
'''.format(uuid))

        self.assert_netplan({uuid: '''network:
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
'''.format(uuid, uuid)})


    def test_keyfile_customer_A2(self):
        uuid = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        self.generate('''[connection]
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
dns=8.8.8.8;8.8.4.4;8.8.8.8;8.8.4.4;8.8.8.8;8.8.4.4;

[ipv6]
method=auto
addr-gen-mode=1
'''.format(uuid))

        self.assert_netplan({uuid: '''network:
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
        - 8.8.8.8
        - 8.8.4.4
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
'''.format(uuid, uuid)})
