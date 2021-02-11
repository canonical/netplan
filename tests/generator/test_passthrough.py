#
# Tests for passthrough config generated via netplan
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

from .base import TestBase


# No passthrough mode (yet) for systemd-networkd
class TestNetworkd(TestBase):
    pass


class TestNetworkManager(TestBase):

    def test_passthrough_basic(self):
        self.generate('''network:
  version: 2
  ethernets:
    NM-87749f1d-334f-40b2-98d4-55db58965f5f:
      renderer: NetworkManager
      match:
        name: "*"
      networkmanager:
        uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
        name: some NM id
        passthrough:
          connection.uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
          connection.type: ethernet
          connection.permissions:''')

        self.assert_nm({'NM-87749f1d-334f-40b2-98d4-55db58965f5f': '''[connection]
id=some NM id
type=ethernet
uuid=87749f1d-334f-40b2-98d4-55db58965f5f
permissions=

[ethernet]
wake-on-lan=0

[match]
interface-name=*;

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})

    def test_passthrough_wifi(self):
        self.generate('''network:
  version: 2
  wifis:
    NM-87749f1d-334f-40b2-98d4-55db58965f5f:
      renderer: NetworkManager
      match:
        name: "*"
      access-points:
        "SOME-SSID":
          networkmanager:
            uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
            name: myid with spaces
            passthrough:
              connection.id: myid with spaces
              connection.uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
              connection.permissions:
              wifi.ssid: SOME-SSID
        "OTHER-SSID":
          hidden: true''')

        self.assert_nm({'NM-87749f1d-334f-40b2-98d4-55db58965f5f-SOME-SSID': '''[connection]
id=myid with spaces
type=wifi
uuid=87749f1d-334f-40b2-98d4-55db58965f5f
permissions=

[match]
interface-name=*;

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=SOME-SSID
mode=infrastructure
''',
                        'NM-87749f1d-334f-40b2-98d4-55db58965f5f-OTHER-SSID': '''[connection]
id=netplan-NM-87749f1d-334f-40b2-98d4-55db58965f5f-OTHER-SSID
type=wifi

[match]
interface-name=*;

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=OTHER-SSID
mode=infrastructure
hidden=true
'''})

    def test_passthrough_type_others(self):
        self.generate('''network:
  others:
    NM-87749f1d-334f-40b2-98d4-55db58965f5f:
      renderer: NetworkManager
      match:
        name: "*"
      networkmanager:
        passthrough:
          connection.uuid: 87749f1d-334f-40b2-98d4-55db58965f5f
          connection.type: dummy''')

        self.assert_nm({'NM-87749f1d-334f-40b2-98d4-55db58965f5f': '''[connection]
id=netplan-NM-87749f1d-334f-40b2-98d4-55db58965f5f
#Netplan: Unsupported connection.type setting, overridden by passthrough
type=dummy
interface-name=NM-87749f1d-334f-40b2-98d4-55db58965f5f
uuid=87749f1d-334f-40b2-98d4-55db58965f5f

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})

    def test_passthrough_dotted_group(self):
        self.generate('''network:
  others:
    dotted-group-test:
      renderer: NetworkManager
      match:
        name: "*"
      networkmanager:
        passthrough:
          connection.type: "wireguard"
          wireguard-peer.some-key.endpoint: 1.2.3.4''')

        self.assert_nm({'dotted-group-test': '''[connection]
id=netplan-dotted-group-test
#Netplan: Unsupported connection.type setting, overridden by passthrough
type=wireguard
interface-name=dotted-group-test

[ipv4]
method=link-local

[ipv6]
method=ignore

[wireguard-peer.some-key]
endpoint=1.2.3.4
'''})

    def test_passthrough_unsupported_setting(self):
        self.generate('''network:
  wifis:
    test:
      renderer: NetworkManager
      match:
        name: "*"
      access-points:
        "SOME-SSID": # implicit "mode: infrasturcutre"
          networkmanager:
            passthrough:
              wifi.mode: "mesh"''')

        self.assert_nm({'test-SOME-SSID': '''[connection]
id=netplan-test-SOME-SSID
type=wifi

[match]
interface-name=*;

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=SOME-SSID
#Netplan: Unsupported setting or value, overridden by passthrough
mode=mesh
'''})
