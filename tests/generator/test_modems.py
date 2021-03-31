#
# Tests for gsm/cdma modem devices config generated via netplan
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

from .base import TestBase


class TestNetworkd(TestBase):
    '''networkd output'''

    def test_not_supported(self):
        # does not produce any output, but fails with:
        # "networkd backend does not support GSM modem configuration"
        err = self.generate('''network:
  version: 2
  modems:
    mobilephone:
      auto-config: true''', expect_fail=True)
        self.assertIn("ERROR: mobilephone: networkd backend does not support GSM/CDMA modem configuration", err)

        self.assert_networkd({})
        self.assert_nm({})


class TestNetworkManager(TestBase):
    '''networkmanager output'''

    def test_cdma_config(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      number: "#666"
      username: test-user
      password: s0s3kr1t''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=cdma
interface-name=mobilephone

[cdma]
password=s0s3kr1t
username=test-user
number=#666

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_auto_config(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      auto-config: true''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_auto_config_implicit(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      number: "*99#"
      mtu: 1600
      pin: "1234"''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
mtu=1600
number=*99#
pin=1234

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_apn(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      apn: internet''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
apn=internet

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_apn_username_password(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      apn: internet
      username: some-user
      password: some-pass''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
apn=internet
password=some-pass
username=some-user

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_device_id(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      device-id: test''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
device-id=test

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_network_id(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      network-id: test''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
network-id=test

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_pin(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      pin: 1234''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
pin=1234

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_sim_id(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      sim-id: test''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
sim-id=test

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_sim_operator_id(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      sim-operator-id: test''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
sim-operator-id=test

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_gsm_example(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    cdc-wdm1:
      mtu: 1600
      apn: ISP.CINGULAR
      username: ISP@CINGULARGPRS.COM
      password: CINGULAR1
      number: "*99#"
      network-id: 24005
      device-id: da812de91eec16620b06cd0ca5cbc7ea25245222
      pin: 2345
      sim-id: 89148000000060671234
      sim-operator-id: 310260''')
        self.assert_nm({'cdc-wdm1': '''[connection]
id=netplan-cdc-wdm1
type=gsm
interface-name=cdc-wdm1

[gsm]
apn=ISP.CINGULAR
password=CINGULAR1
username=ISP@CINGULARGPRS.COM
device-id=da812de91eec16620b06cd0ca5cbc7ea25245222
mtu=1600
network-id=24005
number=*99#
pin=2345
sim-id=89148000000060671234
sim-operator-id=310260

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_modem_nm_integration(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  modems:
    mobilephone:
      auto-config: true
      networkmanager:
        uuid: b22d8f0f-3f34-46bd-ac28-801fa87f1eb6''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
uuid=b22d8f0f-3f34-46bd-ac28-801fa87f1eb6
interface-name=mobilephone

[gsm]
auto-config=true

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)

    def test_modem_nm_integration_gsm_cdma(self):
        self.generate('''network:
  version: 2
  modems:
    NM-a08c5805-7cf5-43f7-afb9-12cb30f6eca3:
      renderer: NetworkManager
      match: {}
      apn: internet2.voicestream.com
      networkmanager:
        uuid: a08c5805-7cf5-43f7-afb9-12cb30f6eca3
        name: "T-Mobile Funkadelic 2"
        passthrough:
          connection.type: "bluetooth"
          gsm.apn: "internet2.voicestream.com"
          gsm.device-id: "da812de91eec16620b06cd0ca5cbc7ea25245222"
          gsm.username: "george.clinton.again"
          gsm.sim-operator-id: "310260"
          gsm.pin: "123456"
          gsm.sim-id: "89148000000060671234"
          gsm.password: "parliament2"
          gsm.network-id: "254098"
          ipv4.method: "auto"
          ipv6.method: "auto"''')
        self.assert_nm({'NM-a08c5805-7cf5-43f7-afb9-12cb30f6eca3': '''[connection]
id=T-Mobile Funkadelic 2
#Netplan: passthrough override
type=bluetooth
uuid=a08c5805-7cf5-43f7-afb9-12cb30f6eca3

[gsm]
apn=internet2.voicestream.com
#Netplan: passthrough setting
device-id=da812de91eec16620b06cd0ca5cbc7ea25245222
#Netplan: passthrough setting
username=george.clinton.again
#Netplan: passthrough setting
sim-operator-id=310260
#Netplan: passthrough setting
pin=123456
#Netplan: passthrough setting
sim-id=89148000000060671234
#Netplan: passthrough setting
password=parliament2
#Netplan: passthrough setting
network-id=254098

[ipv4]
#Netplan: passthrough override
method=auto

[ipv6]
#Netplan: passthrough override
method=auto
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)
