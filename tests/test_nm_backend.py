#!/usr/bin/python3
# Blackbox tests of NetworkManager netplan backend. These are run during
# "make check" and don't touch the system configuration at all.
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
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
import shutil
import ctypes
import ctypes.util

from generator.base import TestBase
from tests.test_utils import MockCmd

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe_cli = os.path.join(rootdir, 'src', 'netplan.script')
# Make sure we can import our development netplan.
os.environ.update({'PYTHONPATH': '.'})

lib = ctypes.CDLL(ctypes.util.find_library('netplan'))
lib.netplan_get_id_from_nm_filename.restype = ctypes.c_char_p


class TestNetworkManagerBackend(TestBase):
    '''Test libnetplan functionality as used by NetworkManager backend'''

    def setUp(self):
        super().setUp()
        os.makedirs(self.confdir)

    def tearDown(self):
        shutil.rmtree(self.workdir.name)
        super().tearDown()

    def test_get_id_from_filename(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_rootdir(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/some/rootdir/run/NetworkManager/system-connections/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_wifi(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID.nmconnection'.encode(), 'SOME-SSID'.encode())
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_wifi_invalid_suffix(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID'.encode(), 'SOME-SSID'.encode())
        self.assertEqual(out, None)

    def test_get_id_from_filename_invalid_prefix(self):
        out = lib.netplan_get_id_from_nm_filename('INVALID/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, None)

    def test_generate(self):
        self.mock_netplan_cmd = MockCmd("netplan")
        os.environ["TEST_NETPLAN_CMD"] = self.mock_netplan_cmd.path
        self.assertTrue(lib.netplan_generate(self.workdir.name.encode()))
        self.assertEquals(self.mock_netplan_cmd.calls(), [
            ["netplan", "generate", "--root-dir", self.workdir.name],
        ])

    def test_delete_connection(self):
        os.environ["TEST_NETPLAN_CMD"] = exe_cli
        FILENAME = os.path.join(self.confdir, 'some-filename.yaml')
        with open(FILENAME, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true''')
        self.assertTrue(os.path.isfile(FILENAME))
        # Parse all YAML and delete 'some-netplan-id' connection file
        self.assertTrue(lib.netplan_delete_connection('some-netplan-id'.encode(), self.workdir.name.encode()))
        self.assertFalse(os.path.isfile(FILENAME))

    def test_delete_connection_id_not_found(self):
        FILENAME = os.path.join(self.confdir, 'some-filename.yaml')
        with open(FILENAME, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true''')
        self.assertTrue(os.path.isfile(FILENAME))
        self.assertFalse(lib.netplan_delete_connection('unknown-id'.encode(), self.workdir.name.encode()))
        self.assertTrue(os.path.isfile(FILENAME))

    def test_delete_connection_two_in_file(self):
        os.environ["TEST_NETPLAN_CMD"] = exe_cli
        FILENAME = os.path.join(self.confdir, 'some-filename.yaml')
        with open(FILENAME, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true
    other-id:
      dhcp6: true''')
        self.assertTrue(os.path.isfile(FILENAME))
        self.assertTrue(lib.netplan_delete_connection('some-netplan-id'.encode(), self.workdir.name.encode()))
        self.assertTrue(os.path.isfile(FILENAME))
        # Verify the file still exists and still contains the other connection
        with open(FILENAME, 'r') as f:
            self.assertEquals(f.read(), 'network:\n  ethernets:\n    other-id:\n      dhcp6: true\n')

    def test_serialize_gsm(self):
        self.maxDiff = None
        UUID = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
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
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('NM-a08c5805-7cf5-43f7-afb9-12cb30f6eca3'.encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
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
'''.format(UUID, UUID))

    def test_serialize_gsm_via_bluetooth(self):
        self.maxDiff = None
        UUID = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
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

[proxy]
''')
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('NM-a08c5805-7cf5-43f7-afb9-12cb30f6eca3'.encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
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
'''.format(UUID, UUID))

    def test_serialize_method_manual(self):
        self.maxDiff = None
        UUID = 'a08c5805-7cf5-43f7-afb9-12cb30f6eca3'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
id=Test
uuid=a08c5805-7cf5-43f7-afb9-12cb30f6eca3
type=ethernet

[ipv4]
dns-search=
method=manual
address1=1.2.3.4/24,8.8.8.8
address2=5.6.7.8/16

[ipv6]
addr-gen-mode=stable-privacy
dns-search=
method=manual
address1=1:2:3::9/128

[proxy]
''')
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('NM-a08c5805-7cf5-43f7-afb9-12cb30f6eca3'.encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
  version: 2
  ethernets:
    NM-{}:
      renderer: NetworkManager
      match: {{}}
      addresses:
      - "1.2.3.4/24"
      - "5.6.7.8/16"
      - "1:2:3::9/128"
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
'''.format(UUID, UUID))

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

    def test_serialize_keyfile_missing_uuid(self):
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('[connection]\ntype=ethernets')
        self.assertFalse(lib.netplan_parse_keyfile(FILE.encode(), None))

    def test_serialize_keyfile_missing_type(self):
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('[connection]\nuuid={}'.format(UUID))
        self.assertFalse(lib.netplan_parse_keyfile(FILE.encode(), None))

    def test_serialize_keyfile_missing_file(self):
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        self.assertFalse(lib.netplan_parse_keyfile(FILE.encode(), None))

    def test_serialize_keyfile_type_wifi(self):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
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
dns-search='''.format(UUID))
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('NM-{}'.format(UUID).encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
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
'''.format(UUID, UUID, UUID))

    def _template_serialize_keyfile_type_wifi(self, nd_mode, nm_mode):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
type=wifi
uuid={}
id=myid with spaces

[ipv4]
method=auto

[wifi]
ssid=SOME-SSID
mode={}'''.format(UUID, nm_mode))
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('NM-{}'.format(UUID).encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        wifi_mode = ''
        ap_mode = ''
        if nm_mode != nd_mode:
            wifi_mode = '\n            passthrough:\n              wifi.mode: "{}"'.format(nm_mode)
        if nd_mode != 'infrastructure':
            ap_mode = '\n          mode: "%s"' % nd_mode
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
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
'''.format(UUID, ap_mode, UUID, wifi_mode, UUID))

    def test_serialize_keyfile_type_wifi_ap(self):
        self._template_serialize_keyfile_type_wifi('ap', 'ap')

    def test_serialize_keyfile_type_wifi_adhoc(self):
        self._template_serialize_keyfile_type_wifi('adhoc', 'adhoc')

    def test_serialize_keyfile_type_wifi_unknown(self):
        self._template_serialize_keyfile_type_wifi('infrastructure', 'mesh')

    def test_serialize_keyfile_type_wifi_missing_ssid(self):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]\ntype=wifi\nuuid={}\nid=myid with spaces'''.format(UUID))
        self.assertFalse(lib.netplan_parse_keyfile(FILE.encode(), None))
        self.assertFalse(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))

    def test_serialize_keyfile_wake_on_lan(self):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
type=ethernet
uuid={}
id=myid with spaces

[ethernet]
wake-on-lan=2

[ipv4]
method=auto'''.format(UUID))
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('NM-{}'.format(UUID).encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
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
'''.format(UUID, UUID))

    def test_serialize_keyfile_wake_on_lan_nm_default(self):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
type=ethernet
uuid={}
id=myid with spaces

[ethernet]

[ipv4]
method=auto'''.format(UUID))
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('NM-{}'.format(UUID).encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
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
'''.format(UUID, UUID))

    def test_serialize_keyfile_modem_gsm(self):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
type=gsm
uuid={}
id=myid with spaces

[ipv4]
method=auto

[gsm]
auto-config=true'''.format(UUID))
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('NM-{}'.format(UUID).encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
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
'''.format(UUID, UUID))

    def test_serialize_keyfile_existing_id(self):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        FILE = os.path.join(self.workdir.name, 'run/NetworkManager/system-connections/netplan-mybr.nmconnection')
        os.makedirs(os.path.dirname(FILE))
        with open(FILE, 'w') as file:
            file.write('''[connection]
type=bridge
uuid={}
id=renamed netplan bridge

[ipv4]
method=auto'''.format(UUID))
        lib.netplan_parse_keyfile(FILE.encode(), None)
        lib._write_netplan_conf('mybr'.encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
  version: 2
  bridges:
    mybr:
      renderer: NetworkManager
      dhcp4: true
      networkmanager:
        uuid: "{}"
        name: "renamed netplan bridge"
'''.format(UUID))

    def test_keyfile_yaml_wifi_hotspot(self):
        self.maxDiff = None
        UUID = 'ff9d6ebc-226d-4f82-a485-b7ff83b9607f'
        FILE_KF = os.path.join(self.workdir.name, 'tmp/Hotspot.nmconnection')
        CONTENT_KF = '''[connection]
id=Hotspot-1
type=wifi
uuid={}
interface-name=wlan0
#Netplan: passthrough setting
autoconnect=false
#Netplan: passthrough setting
permissions=

[ipv4]
method=shared
#Netplan: passthrough setting
dns-search=

[ipv6]
method=ignore
#Netplan: passthrough setting
addr-gen-mode=stable-privacy
#Netplan: passthrough setting
dns-search=

[wifi]
ssid=my-hotspot
mode=ap
#Netplan: passthrough setting
mac-address-blacklist=

[wifi-security]
#Netplan: passthrough setting
group=ccmp;
#Netplan: passthrough setting
key-mgmt=wpa-psk
#Netplan: passthrough setting
pairwise=ccmp;
#Netplan: passthrough setting
proto=rsn;
#Netplan: passthrough setting
psk=test1234

[proxy]
'''.format(UUID)
        os.makedirs(os.path.dirname(FILE_KF))
        with open(FILE_KF, 'w') as file:
            file.write(CONTENT_KF)
        # Convert Keyfile to YAML and compare
        lib.netplan_parse_keyfile(FILE_KF.encode(), None)
        lib._write_netplan_conf('NM-{}'.format(UUID).encode(), self.workdir.name.encode())
        lib.netplan_clear_netdefs()
        FILE_YAML = os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))
        CONTENT_YAML = '''network:
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
'''.format(UUID)
        self.assertTrue(os.path.isfile(FILE_YAML))
        with open(FILE_YAML, 'r') as f:
            self.assertEqual(f.read(), CONTENT_YAML)

        # Convert YAML back to Keyfile and compare to original KF
        os.remove(FILE_YAML)
        self.generate(CONTENT_YAML)
        self.assert_nm({'NM-ff9d6ebc-226d-4f82-a485-b7ff83b9607f-my-hotspot': CONTENT_KF})
