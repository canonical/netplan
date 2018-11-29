#
# Tests for tunnel devices config generated via netplan
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel.lapierre@canonical.com>
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
import sys

from .base import TestBase


class TestNetworkd(TestBase):

    def prepare_config_for_mode(self, mode, key=None):
        config = '''network:
  version: 2
  ethernets:
    en1: {}
'''
        config += """
  tunnels:
    tun0:
      mode: {}
      parent: en1
      local: 10.10.10.10
      remote: 20.20.20.20
      addresses: [ 15.15.15.15/24 ]
      gateway4: 20.20.20.21
""".format(mode)

        if key is not None:
            config += """
      input-key: {}
      output-key: {}
""".format(key, key)

        return config

    def test_sit(self):
        """Validate generation of SIT tunnels"""
        config = self.prepare_config_for_mode('sit')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=sit

[Tunnel]
Local=10.10.10.10
Remote=20.20.20.20
''',
                              'tun0.network': '''[Match]
Name=tun0

[Network]
LinkLocalAddressing=ipv6
Address=15.15.15.15/24
Gateway=20.20.20.21
ConfigureWithoutCarrier=yes
'''})

    def test_gre(self):
        """Validate generation of GRE tunnels"""
        config = self.prepare_config_for_mode('gre')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=gre

[Tunnel]
Local=10.10.10.10
Remote=20.20.20.20
''',
                              'tun0.network': '''[Match]
Name=tun0

[Network]
LinkLocalAddressing=ipv6
Address=15.15.15.15/24
Gateway=20.20.20.21
ConfigureWithoutCarrier=yes
'''})

    def test_gre_with_key(self):
        """Validate generation of GRE tunnels with input/output keys"""
        config = self.prepare_config_for_mode('gre', key='1.1.1.1')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=gre

[Tunnel]
Local=10.10.10.10
Remote=20.20.20.20
InputKey=1.1.1.1
OutputKey=1.1.1.1
''',
                              'tun0.network': '''[Match]
Name=tun0

[Network]
LinkLocalAddressing=ipv6
Address=15.15.15.15/24
Gateway=20.20.20.21
ConfigureWithoutCarrier=yes
'''})

    def test_gre_invalid_key(self):
        """Validate GRE tunnel generation key handling"""
        config = self.prepare_config_for_mode('gre', key='invalid')
        out = self.generate(config, expect_fail=True)
        self.assertIn("a.yaml:15:18: Error in network definition: invalid tunnel key 'invalid'", out)

    def test_ipip6(self):
        """Validate generation of IPIP6 tunnels"""
        config = self.prepare_config_for_mode('ipip6')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ip6tnl

[Tunnel]
Mode=ipip6
Local=10.10.10.10
Remote=20.20.20.20
''',
                              'tun0.network': '''[Match]
Name=tun0

[Network]
LinkLocalAddressing=ipv6
Address=15.15.15.15/24
Gateway=20.20.20.21
ConfigureWithoutCarrier=yes
'''})

    def test_ip6ip6(self):
        """Validate generation of IP6IP6 tunnels"""
        config = self.prepare_config_for_mode('ip6ip6')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ip6tnl

[Tunnel]
Mode=ip6ip6
Local=10.10.10.10
Remote=20.20.20.20
''',
                              'tun0.network': '''[Match]
Name=tun0

[Network]
LinkLocalAddressing=ipv6
Address=15.15.15.15/24
Gateway=20.20.20.21
ConfigureWithoutCarrier=yes
'''})
