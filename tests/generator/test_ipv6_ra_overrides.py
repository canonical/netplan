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

    def assert_ipv6_ra_overrides_bool(self, override_name, networkd_name):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      ipv6-ra-overrides:
        %s: yes
''' % override_name)
        # silently ignored since yes is the default
        self.assert_networkd({'engreen.network': '''\
[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6
'''})

        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      ipv6-ra-overrides:
        %s: no
''' % override_name)
        self.assert_networkd({'engreen.network': '''\
[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6

[IPv6AcceptRA]
%s=false
''' % networkd_name})

    def assert_ipv6_ra_overrides_string(self, override_name, networkd_name):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      ipv6-ra-overrides:
        %s: foo
''' % override_name)
        self.assert_networkd({'engreen.network': '''\
[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6

[IPv6AcceptRA]
%s=foo
''' % networkd_name})

    def assert_ipv6_ra_overrides_guint(self, override_name, networkd_name):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      ipv6-ra-overrides:
        %s: 727
''' % override_name)
        self.assert_networkd({'engreen.network': '''\
[Match]
Name=engreen

[Network]
LinkLocalAddressing=ipv6

[IPv6AcceptRA]
%s=727
''' % networkd_name})

    def test_ipv6_ra_overrides_use_dns(self):
        self.assert_ipv6_ra_overrides_bool('use-dns', 'UseDNS')

    def test_ipv6_ra_overrides_use_domains(self):
        self.assert_ipv6_ra_overrides_string('use-domains', 'UseDomains')

    def test_ipv6_ra_overrides_table(self):
        self.assert_ipv6_ra_overrides_guint('route-table', 'RouteTable')
