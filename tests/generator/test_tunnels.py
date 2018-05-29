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

    if mode == "ip6gre" \
            or mode == "ip6ip6" \
            or mode == "vti6" \
            or mode == "ipip6" \
            or mode == "ip6gretap":
        local_ip = "fe80::dead:beef"
        remote_ip = "2001:fe:ad:de:ad:be:ef:1"
    else:
        local_ip = "10.10.10.10"
        remote_ip = "20.20.20.20"

    config += """
  tunnels:
    tun0:
      mode: {}
      local: {}
      remote: {}
      addresses: [ 15.15.15.15/24 ]
      gateway4: 20.20.20.21
""".format(mode, local_ip, remote_ip)

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
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=sit

[Tunnel]
Independent=true
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

    def test_sit_he(self):
        """[networkd] Validate generation of SIT tunnels (HE example)"""
        # Test specifically a config like one that would enable Hurricane
        # Electric IPv6 tunnels.
        config = '''network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      addresses:
        - 1.1.1.1/24
        - "2001:cafe:face::1/64"  # provided by HE as routed /64
      gateway4: 1.1.1.254
  tunnels:
    he-ipv6:
      mode: sit
      remote: 2.2.2.2
      local: 1.1.1.1
      addresses:
        - "2001:dead:beef::2/64"
      gateway6: "2001:dead:beef::1"
'''
        self.generate(config)
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=ipv6
Address=1.1.1.1/24
Address=2001:cafe:face::1/64
Gateway=1.1.1.254
''',
                              'he-ipv6.netdev': '''[NetDev]
Name=he-ipv6
Kind=sit

[Tunnel]
Independent=true
Local=1.1.1.1
Remote=2.2.2.2
''',
                              'he-ipv6.network': '''[Match]
Name=he-ipv6

[Network]
LinkLocalAddressing=ipv6
Address=2001:dead:beef::2/64
Gateway=2001:dead:beef::1
ConfigureWithoutCarrier=yes
'''})

    def test_vti(self):
        """[networkd] Validate generation of VTI tunnels"""
        config = prepare_config_for_mode('networkd', 'vti')
        self.generate(config)
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=vti

[Tunnel]
Independent=true
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

    def test_vti_with_key_str(self):
        """[networkd] Validate generation of VTI tunnels with input/output keys"""
        config = prepare_config_for_mode('networkd', 'vti', key='1.1.1.1')
        self.generate(config)
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=vti

[Tunnel]
Independent=true
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

    def test_vti_with_key_dict(self):
        """[networkd] Validate generation of VTI tunnels with key dict"""
        config = prepare_config_for_mode('networkd', 'vti', key={'input': 1234, 'output': 5678})
        self.generate(config)
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=vti

[Tunnel]
Independent=true
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

    def test_vti_invalid_key(self):
        """[networkd] Validate VTI tunnel generation key handling"""
        config = prepare_config_for_mode('networkd', 'vti', key='invalid')
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: invalid tunnel key 'invalid'", out)

    def test_vti6(self):
        """[networkd] Validate generation of VTI6 tunnels"""
        config = prepare_config_for_mode('networkd', 'vti6')
        self.generate(config)
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=vti6

[Tunnel]
Independent=true
Local=fe80::dead:beef
Remote=2001:fe:ad:de:ad:be:ef:1
''',
                              'tun0.network': '''[Match]
Name=tun0

[Network]
LinkLocalAddressing=ipv6
Address=15.15.15.15/24
Gateway=20.20.20.21
ConfigureWithoutCarrier=yes
'''})

    def test_vti6_with_key(self):
        """[networkd] Validate generation of VTI6 tunnels with input/output keys"""
        config = prepare_config_for_mode('networkd', 'vti6', key='1.1.1.1')
        self.generate(config)
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=vti6

[Tunnel]
Independent=true
Local=fe80::dead:beef
Remote=2001:fe:ad:de:ad:be:ef:1
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

    def test_vti6_invalid_key(self):
        """[networkd] Validate VTI6 tunnel generation key handling"""
        config = prepare_config_for_mode('networkd', 'vti6', key='invalid')
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: invalid tunnel key 'invalid'", out)

    def test_ipip6(self):
        """[networkd] Validate generation of IPIP6 tunnels"""
        config = prepare_config_for_mode('networkd', 'ipip6')
        self.generate(config)
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ip6tnl

[Tunnel]
Independent=true
Mode=ipip6
Local=fe80::dead:beef
Remote=2001:fe:ad:de:ad:be:ef:1
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
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ipip

[Tunnel]
Independent=true
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

    def test_gre(self):
        """[networkd] Validate generation of GRE tunnels"""
        config = prepare_config_for_mode('networkd', 'gre')
        self.generate(config)
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=gre

[Tunnel]
Independent=true
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

    def test_ip6gre(self):
        """[networkd] Validate generation of IP6GRE tunnels"""
        config = prepare_config_for_mode('networkd', 'ip6gre')
        self.generate(config)
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ip6gre

[Tunnel]
Independent=true
Local=fe80::dead:beef
Remote=2001:fe:ad:de:ad:be:ef:1
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
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=gretap

[Tunnel]
Independent=true
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
        self.assert_networkd({'tun0.netdev': '''[NetDev]
Name=tun0
Kind=ip6gretap

[Tunnel]
Independent=true
Local=fe80::dead:beef
Remote=2001:fe:ad:de:ad:be:ef:1
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
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
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

    def test_sit(self):
        """[NetworkManager] Validate generation of SIT tunnels"""
        config = prepare_config_for_mode('NetworkManager', 'sit')
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=3
local=10.10.10.10
remote=20.20.20.20

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})

    def test_sit_he(self):
        """[NetworkManager] Validate generation of SIT tunnels (HE example)"""
        # Test specifically a config like one that would enable Hurricane
        # Electric IPv6 tunnels.
        config = '''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      addresses:
        - 1.1.1.1/24
        - "2001:cafe:face::1/64"  # provided by HE as routed /64
      gateway4: 1.1.1.254
  tunnels:
    he-ipv6:
      mode: sit
      remote: 2.2.2.2
      local: 1.1.1.1
      addresses:
        - "2001:dead:beef::2/64"
      gateway6: "2001:dead:beef::1"
'''
        self.generate(config)
        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=1.1.1.1/24
gateway=1.1.1.254

[ipv6]
method=manual
address1=2001:cafe:face::1/64
''',
                        'he-ipv6': '''[connection]
id=netplan-he-ipv6
type=ip-tunnel
interface-name=he-ipv6

[ip-tunnel]
mode=3
local=1.1.1.1
remote=2.2.2.2

[ipv4]
method=disabled

[ipv6]
method=manual
address1=2001:dead:beef::2/64
gateway=2001:dead:beef::1
'''})

    def test_vti(self):
        """[NetworkManager] Validate generation of VTI tunnels"""
        config = prepare_config_for_mode('NetworkManager', 'vti')
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=5
local=10.10.10.10
remote=20.20.20.20

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})

    def test_vti6(self):
        """[NetworkManager] Validate generation of VTI6 tunnels"""
        config = prepare_config_for_mode('NetworkManager', 'vti6')
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=9
local=fe80::dead:beef
remote=2001:fe:ad:de:ad:be:ef:1

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})

    def test_ip6ip6(self):
        """[NetworkManager] Validate generation of IP6IP6 tunnels"""
        config = prepare_config_for_mode('NetworkManager', 'ip6ip6')
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=6
local=fe80::dead:beef
remote=2001:fe:ad:de:ad:be:ef:1

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})

    def test_ipip(self):
        """[NetworkManager] Validate generation of IPIP tunnels"""
        config = prepare_config_for_mode('NetworkManager', 'ipip')
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=1
local=10.10.10.10
remote=20.20.20.20

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})

    def test_gre(self):
        """[NetworkManager] Validate generation of GRE tunnels"""
        config = prepare_config_for_mode('NetworkManager', 'gre')
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=2
local=10.10.10.10
remote=20.20.20.20

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})

    def test_gre_with_keys(self):
        """[NetworkManager] Validate generation of GRE tunnels with keys"""
        config = prepare_config_for_mode('NetworkManager', 'gre', key={'input': 1111, 'output': 5555})
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=2
local=10.10.10.10
remote=20.20.20.20
input-key=1111
output-key=5555

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})

    def test_ip6gre(self):
        """[NetworkManager] Validate generation of IP6GRE tunnels"""
        config = prepare_config_for_mode('NetworkManager', 'ip6gre')
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=8
local=fe80::dead:beef
remote=2001:fe:ad:de:ad:be:ef:1

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})

    def test_ip6gre_with_key(self):
        """[NetworkManager] Validate generation of IP6GRE tunnels with key"""
        config = prepare_config_for_mode('NetworkManager', 'ip6gre', key='9999')
        self.generate(config)
        self.assert_nm({'tun0': '''[connection]
id=netplan-tun0
type=ip-tunnel
interface-name=tun0

[ip-tunnel]
mode=8
local=fe80::dead:beef
remote=2001:fe:ad:de:ad:be:ef:1
input-key=9999
output-key=9999

[ipv4]
method=manual
address1=15.15.15.15/24
gateway=20.20.20.21

[ipv6]
method=ignore
'''})


class TestConfigErrors(TestBase):

    def test_missing_mode(self):
        """Fail if tunnel mode is missing"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      remote: 20.20.20.20
      local: 10.10.10.10
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: missing 'mode' property for tunnel", out)

    def test_invalid_mode(self):
        """Ensure an invalid tunnel mode shows an error message"""
        config = prepare_config_for_mode('networkd', 'invalid')
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: tunnel mode 'invalid' is not supported", out)

    def test_invalid_mode_for_nm(self):
        """Show an error if a mode is selected that can't be handled by the renderer"""
        config = prepare_config_for_mode('NetworkManager', 'gretap')
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: GRETAP tunnel mode is not supported by NetworkManager", out)

    def test_malformed_tunnel_ip(self):
        """Fail if local/remote IP for tunnel are malformed"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: gre
      remote: 20.20.20.20
      local: 10.10.1invalid
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: malformed address '10.10.1invalid', must be X.X.X.X or X:X:X:X:X:X:X:X", out)

    def test_cidr_tunnel_ip(self):
        """Fail if local/remote IP for tunnel include /prefix"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: gre
      remote: 20.20.20.20
      local: 10.10.10.10/21
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: address '10.10.10.10/21' should not include /prefixlength", out)

    def test_missing_local_ip(self):
        """Fail if local IP is missing"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: gre
      remote: 20.20.20.20
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: missing 'local' property for tunnel", out)

    def test_missing_remote_ip(self):
        """Fail if remote IP is missing"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: gre
      local: 20.20.20.20
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: missing 'remote' property for tunnel", out)

    def test_wrong_local_ip_for_mode_v4(self):
        """Show an error when an IPv6 local addr is used for an IPv4 tunnel mode"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: gre
      local: fe80::2
      remote: 20.20.20.20
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: 'local' must be a valid IPv4 address for this tunnel type", out)

    def test_wrong_remote_ip_for_mode_v4(self):
        """Show an error when an IPv6 remote addr is used for an IPv4 tunnel mode"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: gre
      local: 10.10.10.10
      remote: 2006::1
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: 'remote' must be a valid IPv4 address for this tunnel type", out)

    def test_wrong_local_ip_for_mode_v6(self):
        """Show an error when an IPv4 local addr is used for an IPv6 tunnel mode"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: ip6gre
      local: 10.10.10.10
      remote: 2001::3
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: 'local' must be a valid IPv6 address for this tunnel type", out)

    def test_wrong_remote_ip_for_mode_v6(self):
        """Show an error when an IPv4 remote addr is used for an IPv6 tunnel mode"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: ip6gre
      local: 2001::face
      remote: 20.20.20.20
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: 'remote' must be a valid IPv6 address for this tunnel type", out)

    def test_malformed_keys(self):
        """Show an error if tunnel keys stanza is malformed"""
        config = '''network:
  version: 2
  tunnels:
    tun0:
      mode: ipip
      local: 10.10.10.10
      remote: 20.20.20.20
      keys:
        - input: 1234
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: invalid type for 'keys'", out)

    def test_networkd_invalid_input_key_use(self):
        """[networkd] Show an error if input-key is used for a mode that does not support it"""
        config = '''network:
  version: 2
  renderer: networkd
  tunnels:
    tun0:
      mode: ipip
      local: 10.10.10.10
      remote: 20.20.20.20
      keys:
        input: 1234
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: 'input-key' is not required for this tunnel type", out)

    def test_networkd_invalid_output_key_use(self):
        """[networkd] Show an error if output-key is used for a mode that does not support it"""
        config = '''network:
  version: 2
  renderer: networkd
  tunnels:
    tun0:
      mode: ipip
      local: 10.10.10.10
      remote: 20.20.20.20
      keys:
        output: 1234
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: 'output-key' is not required for this tunnel type", out)

    def test_nm_invalid_input_key_use(self):
        """[NetworkManager] Show an error if input-key is used for a mode that does not support it"""
        config = '''network:
  version: 2
  renderer: NetworkManager
  tunnels:
    tun0:
      mode: ipip
      local: 10.10.10.10
      remote: 20.20.20.20
      keys:
        input: 1234
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: 'input-key' is not required for this tunnel type", out)

    def test_nm_invalid_output_key_use(self):
        """[NetworkManager] Show an error if output-key is used for a mode that does not support it"""
        config = '''network:
  version: 2
  renderer: NetworkManager
  tunnels:
    tun0:
      mode: ipip
      local: 10.10.10.10
      remote: 20.20.20.20
      keys:
        output: 1234
'''
        out = self.generate(config, expect_fail=True)
        self.assertIn("Error in network definition: tun0: 'output-key' is not required for this tunnel type", out)
