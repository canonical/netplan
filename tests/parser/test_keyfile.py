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


# TODO: make sure a KEYFILE input generates the same KEYFILE output, matching some given intermediary YAML
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
uuid=a08c5805-7cf5-43f7-afb9-12cb30f6eca3
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

[ipv4]
dns-search=
method=auto

[ipv6]
addr-gen-mode=stable-privacy
dns-search=
method=auto
''')
        self.assert_netplan({uuid: '''network:
  version: 2
  modems:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      dhcp4: true
      dhcp6: true
      apn: "internet2.voicestream.com"
      device-id: "da812de91eec16620b06cd0ca5cbc7ea25245222"
      network-id: "254098"
      pin: "123456"
      sim-id: "89148000000060671234"
      sim-operator-id: "310260"
      networkmanager:
        uuid: "{}"
        name: "T-Mobile Funkadelic 2"
        passthrough:
          gsm.home-only: "true"
          gsm.password: "parliament2"
          gsm.username: "george.clinton.again"
          ipv4.dns-search: ""
          ipv6.addr-gen-mode: "stable-privacy"
          ipv6.dns-search: ""
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
addr-gen-mode=stable-privacy
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
          ipv6.addr-gen-mode: "stable-privacy"
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

[ipv4]
dns-search=
method=auto
ignore-auto-routes=true
never-default=true
route-metric=4242

[ipv6]
addr-gen-mode=stable-privacy
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
      networkmanager:
        uuid: "{}"
        name: "Test"
        passthrough:
          ipv4.dns-search: ""
          ipv6.addr-gen-mode: "stable-privacy"
          ipv6.dns-search: ""
          proxy._: ""
'''.format(uuid, uuid)})

    def test_serialize_method_manual(self):
        uuid = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        self.generate('''[connection]
id=Test
uuid=a08c5805-7cf5-43f7-afb9-12cb30f6eca3
type=ethernet

[ipv4]
dns-search=
method=manual
address1=1.2.3.4/24,8.8.8.8
address2=5.6.7.8/16
gateway=6.6.6.6

[ipv6]
addr-gen-mode=stable-privacy
dns-search=
method=manual
address1=1:2:3::9/128
gateway=6:6::6

[proxy]
''')
        self.assert_netplan({uuid: '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      addresses:
      - "1.2.3.4/24"
      - "5.6.7.8/16"
      - "1:2:3::9/128"
      gateway4: 6.6.6.6
      gateway6: 6:6::6
      networkmanager:
        uuid: "{}"
        name: "Test"
        passthrough:
          ipv4.dns-search: ""
          ipv4.method: "manual"
          ipv4.address1: "1.2.3.4/24,8.8.8.8"
          ipv6.addr-gen-mode: "stable-privacy"
          ipv6.dns-search: ""
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
      access-points:
        "SOME-SSID":
          hidden: true
          networkmanager:
            uuid: "{}"
            name: "myid with spaces"
            passthrough:
              connection.permissions: ""
              ipv4.dns-search: ""
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(uuid, uuid, uuid)})

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
      access-points:
        "SOME-SSID":{}
          networkmanager:
            uuid: "{}"
            name: "myid with spaces"{}
      networkmanager:
        uuid: "{}"
        name: "myid with spaces"
'''.format(uuid, ap_mode, uuid, wifi_mode, uuid)})

    def test_serialize_keyfile_type_wifi_ap(self):
        self._template_serialize_keyfile_type_wifi('ap', 'ap')

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
          ethernet._: ""
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
        self.generate('''[connection]
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
addr-gen-mode=stable-privacy
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

[proxy]'''.format(uuid))
        self.assert_netplan({uuid: '''network:
  version: 2
  wifis:
    NM-ff9d6ebc-226d-4f82-a485-b7ff83b9607f:
      renderer: NetworkManager
      match:
        name: "wlan0"
      access-points:
        "my-hotspot":
          mode: "ap"
          networkmanager:
            uuid: "ff9d6ebc-226d-4f82-a485-b7ff83b9607f"
            name: "Hotspot-1"
            passthrough:
              connection.autoconnect: "false"
              connection.permissions: ""
              ipv4.method: "shared"
              ipv4.dns-search: ""
              ipv6.method: "ignore"
              ipv6.addr-gen-mode: "stable-privacy"
              ipv6.dns-search: ""
              wifi.mac-address-blacklist: ""
              wifi-security.group: "ccmp;"
              wifi-security.key-mgmt: "wpa-psk"
              wifi-security.pairwise: "ccmp;"
              wifi-security.proto: "rsn;"
              wifi-security.psk: "test1234"
              proxy._: ""
      networkmanager:
        uuid: "{}"
        name: "Hotspot-1"
'''.format(uuid)})

        # FIXME: uncomment those checks
        # Convert YAML back to Keyfile and compare to original KF
        #os.remove(FILE_YAML)
        #self.generate(CONTENT_YAML)
        #self.assert_nm({'NM-ff9d6ebc-226d-4f82-a485-b7ff83b9607f-my-hotspot': CONTENT_KF})
