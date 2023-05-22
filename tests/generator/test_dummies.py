#
# Tests for dummy devices config generated via netplan      # wokeignore:rule=dummy
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


from .base import ND_DUMMY, ND_WITHIP, TestBase    # wokeignore:rule=dummy


class NetworkManager(TestBase):

    def test_basic(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  dummy-devices:            # wokeignore:rule=dummy
    dm0:
      addresses:
        - 192.168.1.2/24
      routes:
      - to: 1.2.3.4
        via: 192.168.1.2''')

        self.assert_nm({'dm0': '''[connection]
id=netplan-dm0
type={}
interface-name=dm0

[ipv4]
method=manual
address1=192.168.1.2/24
route1=1.2.3.4,192.168.1.2

[ipv6]
method=ignore
'''.format(('dummy'))})      # wokeignore:rule=dummy


class TestNetworkd(TestBase):

    def test_basic(self):
        self.generate('''network:
  version: 2
  dummy-devices:            # wokeignore:rule=dummy
    dm0:
      addresses:
        - 192.168.1.2/24
      routes:
      - to: 1.2.3.4
        via: 192.168.1.2''')

        self.assert_networkd({'dm0.network': ND_WITHIP % ('dm0', '192.168.1.2/24') + '''
[Route]
Destination=1.2.3.4
Gateway=192.168.1.2
''',
                              'dm0.netdev': ND_DUMMY % ('dm0')})    # wokeignore:rule=dummy


class TestNetplanYAMLv2(TestBase):
    '''No asserts are needed.

    The generate() method implicitly checks the (re-)generated YAML.
    '''

    def test_basic(self):
        self.generate('''network:
  version: 2
  dummy-devices:            # wokeignore:rule=dummy
    dm0: {}''')

    def test_interface_ipv4(self):
        self.generate('''network:
  version: 2
  dummy-devices:            # wokeignore:rule=dummy
    dm0:
      addresses:
        - 192.168.1.2/24
      routes:
      - to: 1.2.3.4
        via: 192.168.1.2''')
