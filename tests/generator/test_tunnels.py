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

def prepare_config_for_mode(renderer, mode, key=None):
    config = """network:
  version: 2
  renderer: {}
""".format(renderer)
    config += '''
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

    # Handle key/keys as str or dict as required by the test
    if type(key) is str:
        config += """
      key: {}
""".format(key)
    elif type(key) is dict:
        config += """
      keys:
        input: {}
        output: {}
""".format(key['input'], key['output'])

    return config


class TestNetworkd(TestBase):

    def test_sit(self):
        """[networkd] Validate generation of SIT tunnels"""
        config = prepare_config_for_mode('networkd', 'sit')
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
        """[networkd] Validate generation of GRE tunnels"""
        config = prepare_config_for_mode('networkd', 'gre')
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

    def test_gre_with_key_str(self):
        """[networkd] Validate generation of GRE tunnels with input/output keys"""
        config = prepare_config_for_mode('networkd', 'gre', key='1.1.1.1')
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

    def test_gre_with_key_dict(self):
        """[networkd] Validate generation of GRE tunnels with key dict"""
        config = prepare_config_for_mode('networkd', 'gre', key={'input': 1234, 'output': 5678})
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
InputKey=1234
OutputKey=5678
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
        """[networkd] Validate GRE tunnel generation key handling"""
        config = prepare_config_for_mode('networkd', 'gre', key='invalid')
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: invalid tunnel key 'invalid'", out)

    def test_ip6gre(self):
        """[networkd] Validate generation of IP6GRE tunnels"""
        config = prepare_config_for_mode('networkd', 'ip6gre')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ip6gre

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

    def test_ip6gre_with_key(self):
        """[networkd] Validate generation of IP6GRE tunnels with input/output keys"""
        config = prepare_config_for_mode('networkd', 'ip6gre', key='1.1.1.1')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ip6gre

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

    def test_ip6gre_invalid_key(self):
        """[networkd] Validate IP6GRE tunnel generation key handling"""
        config = prepare_config_for_mode('networkd', 'ip6gre', key='invalid')
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: invalid tunnel key 'invalid'", out)

    def test_ipip6(self):
        """[networkd] Validate generation of IPIP6 tunnels"""
        config = prepare_config_for_mode('networkd', 'ipip6')
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
        """[networkd] Validate generation of IP6IP6 tunnels"""
        config = prepare_config_for_mode('networkd', 'ip6ip6')
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

    def test_ipip(self):
        """[networkd] Validate generation of IPIP tunnels"""
        config = prepare_config_for_mode('networkd', 'ipip')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ipip

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

    def test_isatap(self):
        """[networkd] Warning for ISATAP tunnel generation not supported"""
        config = prepare_config_for_mode('networkd', 'isatap')
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: ISATAP tunnel mode is not supported", out)

    def test_vti(self):
        """[networkd] Validate generation of VTI tunnels"""
        config = prepare_config_for_mode('networkd', 'vti')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=vti

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

    def test_vti6(self):
        """[networkd] Validate generation of VTI6 tunnels"""
        config = prepare_config_for_mode('networkd', 'vti6')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=vti6

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

    def test_gretap(self):
        """[networkd] Validate generation of GRETAP tunnels"""
        config = prepare_config_for_mode('networkd', 'gretap')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=gretap

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

    def test_ip6gretap(self):
        """[networkd] Validate generation of IP6GRETAP tunnels"""
        config = prepare_config_for_mode('networkd', 'ip6gretap')
        self.generate(config)
        self.assert_networkd({'en1.network': '''[Match]
Name=en1

[Network]
LinkLocalAddressing=ipv6
Tunnel=tun0
''',
                              'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ip6gretap

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


class TestNetworkManager(TestBase):

    def test_isatap(self):
        """[NetworkManager] Validate ISATAP tunnel generation"""
        config = prepare_config_for_mode('NetworkManager', 'isatap')
        self.generate(config)
        self.assert_nm({'en1': '''[connection]
id=netplan-en1
type=ethernet
interface-name=en1

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'tun0': '''[connection]
id=netplan-tun0
type=tunnel
interface-name=tun0

[ip-tunnel]
mode=4
local=10.10.10.10
remote=20.20.20.20

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})
