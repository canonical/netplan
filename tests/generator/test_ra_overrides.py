#
# Tests for IPv6 Router Advertisement (RA) override handling in
# netplan generator
#
# Copyright (C) 2024 Canonical, Ltd.
# Author: Khoo Hao Yit <khoohaoyit16@gmail.com>
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

    def assert_ra_overrides_key_value(
        self,
        yaml_field_name,
        yaml_field_value,
        networkd_field_name,
        networkd_field_value
    ):
        yaml_config = '''\
network:
  version: 2
  ethernets:
    engreen:
      ra-overrides:
        %s: %s
''' % (yaml_field_name, yaml_field_value)
        networkd_config = '''\
[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
'''
        if networkd_field_value is not None:
            networkd_config += '''
[IPv6AcceptRA]
%s=%s
''' % (networkd_field_name, networkd_field_value)
        self.generate(yaml_config)
        self.assert_networkd({'engreen.network': networkd_config})

    def assert_ra_overrides_all_fields(self):
        yaml_config = '''\
network:
  version: 2
  ethernets:
    engreen:
      ra-overrides:
        use-dns: false
        use-domains: route
        table: 701
'''
        networkd_config = '''\
[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6

[IPv6AcceptRA]
UseDNS=false
UseDomains=route
RouteTable=701
'''
        self.generate(yaml_config)
        self.assert_networkd({'engreen.network': networkd_config})

    def test_ra_overrides_use_dns(self):
        self.assert_ra_overrides_key_value('use-dns', 'false', 'UseDNS', 'false')
        self.assert_ra_overrides_key_value('use-dns', 'true', 'UseDNS', 'true')

    def test_ra_overrides_use_domains(self):
        self.assert_ra_overrides_key_value('use-domains', 'false', 'UseDomains', 'false')
        self.assert_ra_overrides_key_value('use-domains', 'true', 'UseDomains', 'true')
        self.assert_ra_overrides_key_value('use-domains', 'route', 'UseDomains', 'route')

    def test_ra_overrides_table(self):
        self.assert_ra_overrides_key_value('table', '727', 'RouteTable', '727')

    def test_ra_overrides_all_fields(self):
        self.assert_ra_overrides_all_fields()


class TestConfigErrors(TestBase):

    def test_ra_overrides_use_domains_invalid_options(self):
        err = self.generate('''\
network:
  version: 2
  ethernets:
    engreen:
      ra-overrides:
        use-domains: invalid-options
''', expect_fail=True)
        self.assertIn("Invalid use-domains options 'invalid-options', must be a boolean, or the special value 'route'.", err)
