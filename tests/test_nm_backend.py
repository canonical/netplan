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

    def _template_render_keyfile(self, nm_type, nd_type):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        file = '[connection]\ntype={}\nuuid={}'.format(nm_type, UUID)
        self.assertTrue(lib._netplan_render_yaml_from_nm_keyfile_str(file.encode(), self.workdir.name.encode()))
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
  version: 2
  {}:
    NM-{}:
      renderer: NetworkManager
      networkmanager:
        uuid: {}
        passthrough:
          connection.type: "{}"
          connection.uuid: "{}"
'''.format(nd_type, UUID, UUID, nm_type, UUID))

    def test_render_keyfile_ethernet(self):
        self._template_render_keyfile('ethernet', 'ethernets')

    def test_render_keyfile_ethernet2(self):
        self._template_render_keyfile('802-3-ethernet', 'ethernets')

    def test_render_keyfile_type_modem(self):
        self._template_render_keyfile('gsm', 'modems')

    def test_render_keyfile_type_modem2(self):
        self._template_render_keyfile('cdma', 'modems')

    def test_render_keyfile_type_bridge(self):
        self._template_render_keyfile('bridge', 'bridges')

    def test_render_keyfile_type_bond(self):
        self._template_render_keyfile('bond', 'bonds')

    def test_render_keyfile_type_vlan(self):
        self._template_render_keyfile('vlan', 'vlans')

    def test_render_keyfile_type_tunnel(self):
        self._template_render_keyfile('ip-tunnel', 'tunnels')

    def test_render_keyfile_type_wireguard(self):
        self._template_render_keyfile('wireguard', 'tunnels')

    def test_render_keyfile_type_other(self):
        self._template_render_keyfile('dummy', 'others')

    def test_render_keyfile_missing_uuid(self):
        file = '[connection]\ntype=ethernets'
        self.assertFalse(lib._netplan_render_yaml_from_nm_keyfile_str(file.encode(), self.workdir.name.encode()))

    def test_render_keyfile_missing_type(self):
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        file = '[connection]\nuuid={}'.format(UUID)
        self.assertFalse(lib._netplan_render_yaml_from_nm_keyfile_str(file.encode(), self.workdir.name.encode()))

    def test_render_keyfile_type_wifi(self):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        file = '''[connection]
type=802-11-wireless
uuid={}
permissions=
id=myid with spaces

[802-11-wireless]
ssid=SOME-SSID

[ipv4]
method=auto
dns-search='''.format(UUID)
        self.assertTrue(lib._netplan_render_yaml_from_nm_keyfile_str(file.encode(), self.workdir.name.encode()))
        self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))
        with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID)), 'r') as f:
            self.assertEqual(f.read(), '''network:
  version: 2
  wifis:
    NM-{}:
      renderer: NetworkManager
      access-points:
        "SOME-SSID":
          hidden: false
      networkmanager:
        uuid: {}
        passthrough:
          connection.type: "802-11-wireless"
          connection.uuid: "{}"
          connection.permissions: ""
          connection.id: "myid with spaces"
          802-11-wireless.ssid: "SOME-SSID"
          ipv4.method: "auto"
          ipv4.dns-search: ""
'''.format(UUID, UUID, UUID))

    def test_render_keyfile_type_wifi_missing_ssid(self):
        self.maxDiff = None
        UUID = '87749f1d-334f-40b2-98d4-55db58965f5f'
        file = '''[connection]\ntype=wifi\nuuid={}\nid=myid with spaces'''.format(UUID)
        self.assertFalse(lib._netplan_render_yaml_from_nm_keyfile_str(file.encode(), self.workdir.name.encode()))
        self.assertFalse(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(UUID))))

    def test_fallback_generator(self):
        self.generate('''network:
  version: 2
  ethernets:
    NM-87749f1d-334f-40b2-98d4-55db58965f5f:
      renderer: NetworkManager
      networkmanager:
        uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
        passthrough:
          connection.id: myid with spaces
          connection.uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
          connection.type: wifi
          connection.permissions:
          ipv4.dns-search:
          ipv4.method: auto
          ipv6.addr-gen-mode: stable-privacy
          ipv6.dns-search:
          ipv6.method: auto''')

        self.assert_nm({'NM-87749f1d-334f-40b2-98d4-55db58965f5f': '''[ipv4]
method=auto
dns-search=

[connection]
type=wifi
uuid=87749f1d-334f-40b2-98d4-55db58965f5f
permissions=
id=myid with spaces

[ipv6]
addr-gen-mode=stable-privacy
dns-search=
method=auto
'''})

    def test_fallback_generator_wifi(self):
        self.generate('''network:
  version: 2
  wifis:
    NM-87749f1d-334f-40b2-98d4-55db58965f5f:
      renderer: NetworkManager
      access-points:
        "SOME-SSID":
          hidden: false
        "INVALID-IGNORED":
          hidden: true
      networkmanager:
        uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
        passthrough:
          connection.id: myid with spaces
          connection.uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
          connection.type: wifi
          connection.permissions:
          wifi.ssid: SOME-SSID
          ipv4.dns-search:
          ipv4.method: auto
          ipv6.addr-gen-mode: stable-privacy
          ipv6.dns-search:
          ipv6.method: auto''')

        self.assert_nm({'NM-87749f1d-334f-40b2-98d4-55db58965f5f-SOME-SSID': '''[ipv4]
method=auto
dns-search=

[connection]
type=wifi
permissions=
uuid=87749f1d-334f-40b2-98d4-55db58965f5f
id=myid with spaces

[wifi]
ssid=SOME-SSID

[ipv6]
addr-gen-mode=stable-privacy
dns-search=
method=auto
'''})

    def test_fallback_generator_other(self):
        self.generate('''network:
  others:
    NM-87749f1d-334f-40b2-98d4-55db58965f5f:
      renderer: NetworkManager
      networkmanager:
        passthrough:
          connection.uuid: 87749f1d-334f-40b2-98d4-55db58965f5f''')

        self.assert_nm({'NM-87749f1d-334f-40b2-98d4-55db58965f5f': '[connection]\nuuid=87749f1d-334f-40b2-98d4-55db58965f5f\n'})
