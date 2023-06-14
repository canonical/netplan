#
# Tests for Virtual Ethernet (veth) devices config generated via netplan
#
# Copyright (C) 2023 Canonical, Ltd.
# Author: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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


from .base import ND_VETH, ND_EMPTY, TestBase


class _CommonTests():
    def test_missing_peer_key_should_fail(self):
        out = self.generate('''network:
  version: 2
  renderer: %(r)s
  virtual-ethernets:
    veth0: {}''' % {'r': self.backend}, expect_fail=True)

        self.assertIn('virtual-ethernet missing \'peer\' property', out)

    def test_veth_peer_is_not_a_veth_interface(self):
        out = self.generate('''network:
  version: 2
  renderer: %(r)s
  virtual-ethernets:
    veth0:
      peer: eth0
  ethernets:
    eth0: {}
      ''' % {'r': self.backend}, expect_fail=True)

        self.assertIn('\'eth0\' is not a virtual-ethernet interface', out)

    def test_veth_peer_is_anothers_interface_peer_already(self):
        out = self.generate('''network:
  version: 2
  renderer: %(r)s
  virtual-ethernets:
    veth2:
      peer: veth1
    veth0:
      peer: veth1
    veth1:
      peer: veth2''' % {'r': self.backend}, expect_fail=True)

        self.assertIn('virtual-ethernet peer \'veth1\' is another virtual-ethernet\'s (veth2) peer already', out)

    def test_veth_peer_is_itself(self):
        out = self.generate('''network:
  version: 2
  renderer: %(r)s
  virtual-ethernets:
    veth1:
      peer: veth1''' % {'r': self.backend}, expect_fail=True)

        self.assertIn('virtual-ethernet peer cannot be itself', out)

    def test_basic(self):
        self.generate('''network:
  version: 2
  renderer: %(r)s
  virtual-ethernets:
    veth0:
      peer: veth1
    veth1:
      peer: veth0''' % {'r': self.backend})

        if self.backend == 'NetworkManager':
            self.assert_nm({'veth0': '''[connection]
id=netplan-veth0
type={}
interface-name=veth0

[veth]
peer=veth1

[ipv4]
method=link-local

[ipv6]
method=ignore
'''.format(('veth')), 'veth1': '''[connection]
id=netplan-veth1
type={}
interface-name=veth1

[veth]
peer=veth0

[ipv4]
method=link-local

[ipv6]
method=ignore
'''.format(('veth'))})

        if self.backend == 'networkd':
            self.assert_networkd({'veth0.network': ND_EMPTY % ('veth0', 'ipv6'),
                                  'veth1.network': ND_EMPTY % ('veth1', 'ipv6'),
                                  'veth0.netdev': ND_VETH % ('veth0', 'veth1')})


class NetworkManager(TestBase, _CommonTests):
    backend = 'NetworkManager'

    def test_veth_peer_is_not_a_veth_interface_validation_stage(self):
        out = self.generate('''network:
  version: 2
  renderer: NetworkManager
  virtual-ethernets:
    veth0:
      peer: eth0''', confs={'b': '''network:
  renderer: NetworkManager
  ethernets:
    eth0: {}'''}, expect_fail=True)

        self.assertIn('\'eth0\' is not a virtual-ethernet interface', out)

    def test_veth_peer_has_no_peer_itself(self):
        out = self.generate('''network:
  version: 2
  renderer: NetworkManager
  virtual-ethernets:
    veth0:
      peer: veth1
    veth1:
      peer: abc''', expect_fail=True)

        self.assertIn('virtual-ethernet peer \'veth1\' does not have a peer itself', out)

    def test_veth_peer_has_no_peer_itself_validation_stage(self):
        out = self.generate('''network:
  version: 2
  renderer: NetworkManager
  virtual-ethernets:
    veth0:
      peer: veth1''', confs={'b': '''network:
  version: 2
  renderer: NetworkManager
  virtual-ethernets:
    veth1:
      peer: asd'''}, expect_fail=True)

        self.assertIn('virtual-ethernet peer \'veth1\' does not have a peer itself', out)

    def test_veth_peer_is_anothers_interface_peer_already_validation_stage(self):
        out = self.generate('''network:
  version: 2
  renderer: NetworkManager
  virtual-ethernets:
    veth0:
      peer: veth1
      ''', confs={'b': '''network:
  renderer: NetworkManager
  virtual-ethernets:
    veth1:
      peer: veth2
    veth2:
      peer: veth1'''}, expect_fail=True)

        self.assertIn('virtual-ethernet peer \'veth1\' is another virtual-ethernet\'s (veth2) peer already', out)


class TestNetworkd(TestBase, _CommonTests):
    backend = 'networkd'

    def test_basic_missing_peer(self):
        ''' When networkd is the renderer, both peers are required '''
        out = self.generate('''network:
  version: 2
  virtual-ethernets:
    veth0:
      peer: veth1''', expect_fail=True)

        self.assertIn('veth0: interface \'veth1\' is not defined', out)

    def test_veth_peer_of_a_peer_was_not_defined(self):
        out = self.generate('''network:
  version: 2
  renderer: networkd
  virtual-ethernets:
    veth0:
      peer: veth1
    veth1:
      peer: abc''', expect_fail=True)

        self.assertIn('veth1: interface \'abc\' is not defined', out)
