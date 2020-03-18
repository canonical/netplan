#
# Tests for gsm devices config generated via netplan
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

# import os #FIXME

from .base import TestBase


class TestNetworkd(TestBase):
    '''networkd output'''

    def test_not_supported(self):
        # does not produce any output, but fails with:
        # "networkd backend does not support GSM modem configuration"
        err = self.generate('''network:
  version: 2
  gsms:
    mobilephone:
      auto-config: true''', expect_fail=True)
        self.assertIn("ERROR: mobilephone: networkd backend does not support GSM modem configuration", err)

        self.assert_networkd({})
        self.assert_nm({})


class TestNetworkManager(TestBase):
    '''networkmanager output'''

    def test_gsm_auto_config(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  gsms:
    mobilephone:
      auto-config: true''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true

[ethernet]
wake-on-lan=0

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
  gsms:
    mobilephone:
      pin: "1234"''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
pin=1234

[ethernet]
wake-on-lan=0

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
  gsms:
    mobilephone:
      apn: internet''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
apn=internet

[ethernet]
wake-on-lan=0

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
  gsms:
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

[ethernet]
wake-on-lan=0

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
  gsms:
    mobilephone:
      device-id: test''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
device-id=test

[ethernet]
wake-on-lan=0

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
  gsms:
    mobilephone:
      network-id: test''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
network-id=test

[ethernet]
wake-on-lan=0

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
  gsms:
    mobilephone:
      pin: 1234''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
pin=1234

[ethernet]
wake-on-lan=0

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
  gsms:
    mobilephone:
      sim-id: test''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
sim-id=test

[ethernet]
wake-on-lan=0

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
  gsms:
    mobilephone:
      sim-operator-id: test''')
        self.assert_nm({'mobilephone': '''[connection]
id=netplan-mobilephone
type=gsm
interface-name=mobilephone

[gsm]
auto-config=true
sim-operator-id=test

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_nm_udev(None)
