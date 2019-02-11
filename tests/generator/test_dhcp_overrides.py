#
# Tests for DHCP override handling in netplan generator
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

from .base import (TestBase, ND_DHCP4, ND_DHCP4_NOMTU, ND_DHCP6, ND_DHCP6_NOMTU,
        ND_DHCPYES, ND_DHCPYES_NOMTU)


class TestNetworkd(TestBase):

    # Common tests for dhcp override booleans
    def assert_dhcp_overrides_bool(self, override_name, networkd_name):
        # dhcp4 yes
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: yes
''' % override_name)
        # silently ignored since yes is the default
        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen'})

        # dhcp6 yes
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp6: yes
      dhcp6-overrides:
        %s: yes
''' % override_name)
        # silently ignored since yes is the default
        self.assert_networkd({'engreen.network': ND_DHCP6 % 'engreen'})

        # dhcp4 and dhcp6 both yes
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: yes
      dhcp6: yes
      dhcp6-overrides:
        %s: yes
''' % (override_name, override_name))
        # silently ignored since yes is the default
        self.assert_networkd({'engreen.network': ND_DHCPYES % 'engreen'})

        # dhcp4 no
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: no
''' % override_name)
        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen' + '%s=false\n' % networkd_name})

        # dhcp6 no
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp6: yes
      dhcp6-overrides:
        %s: no
''' % override_name)
        self.assert_networkd({'engreen.network': ND_DHCP6 % 'engreen' + '%s=false\n' % networkd_name})

        # dhcp4 and dhcp6 both no
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: no
      dhcp6: yes
      dhcp6-overrides:
        %s: no
''' % (override_name, override_name))
        self.assert_networkd({'engreen.network': ND_DHCPYES % 'engreen' + '%s=false\n' % networkd_name})

        # mismatched values
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: yes
      dhcp6: yes
      dhcp6-overrides:
        %s: no
''' % (override_name, override_name), expect_fail=True)
        self.assertEqual(err, 'ERROR: engreen: networkd requires that '
                              '%s has the same value in both dhcp4_overrides and dhcp6_overrides\n' % override_name)

    # Common tests for dhcp override strings
    def assert_dhcp_overrides_string(self, override_name, networkd_name):
        # dhcp4 only
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: foo
''' % override_name)
        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen' + '%s=foo\n' % networkd_name})

        # dhcp6 only
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp6: yes
      dhcp6-overrides:
        %s: foo
''' % override_name)
        self.assert_networkd({'engreen.network': ND_DHCP6 % 'engreen' + '%s=foo\n' % networkd_name})

        # dhcp4 and dhcp6
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: foo
      dhcp6: yes
      dhcp6-overrides:
        %s: foo
''' % (override_name, override_name))
        self.assert_networkd({'engreen.network': ND_DHCPYES % 'engreen' + '%s=foo\n' % networkd_name})

        # mismatched values
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: foo
      dhcp6: yes
      dhcp6-overrides:
        %s: bar
''' % (override_name, override_name), expect_fail=True)
        self.assertEqual(err, 'ERROR: engreen: networkd requires that '
                              '%s has the same value in both dhcp4_overrides and dhcp6_overrides\n' % override_name)

    # Common tests for dhcp override booleans
    def assert_dhcp_mtu_overrides_bool(self, override_name, networkd_name):
        # dhcp4 yes
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: yes
''' % override_name)
        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen'})

        # dhcp6 yes
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp6: yes
      dhcp6-overrides:
        %s: yes
''' % override_name)
        # silently ignored since yes is the default
        self.assert_networkd({'engreen.network': ND_DHCP6 % 'engreen'})

        # dhcp4 and dhcp6 both yes
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: yes
      dhcp6: yes
      dhcp6-overrides:
        %s: yes
''' % (override_name, override_name))
        # silently ignored since yes is the default
        self.assert_networkd({'engreen.network': ND_DHCPYES % 'engreen'})

        # dhcp4 no
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: no
''' % override_name)
        self.assert_networkd({'engreen.network': ND_DHCP4_NOMTU % 'engreen'})

        # dhcp6 no
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp6: yes
      dhcp6-overrides:
        %s: no
''' % override_name)
        self.assert_networkd({'engreen.network': ND_DHCP6_NOMTU % 'engreen'})

        # dhcp4 and dhcp6 both no
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: no
      dhcp6: yes
      dhcp6-overrides:
        %s: no
''' % (override_name, override_name))
        self.assert_networkd({'engreen.network': ND_DHCPYES_NOMTU % 'engreen'})

        # mismatched values
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: yes
      dhcp6: yes
      dhcp6-overrides:
        %s: no
''' % (override_name, override_name), expect_fail=True)
        self.assertEqual(err, 'ERROR: engreen: networkd requires that '
                              '%s has the same value in both dhcp4_overrides and dhcp6_overrides\n' % override_name)

    def assert_dhcp_overrides_guint(self, override_name, networkd_name):
        # dhcp4 only
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: 6000
''' % override_name)
        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=6000
UseMTU=true
'''})

        # dhcp6 only
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp6: yes
      dhcp6-overrides:
        %s: 6000
''' % override_name)
        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv6
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=6000
UseMTU=true
'''})

        # dhcp4 and dhcp6
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: 6000
      dhcp6: yes
      dhcp6-overrides:
        %s: 6000
''' % (override_name, override_name))
        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=yes
LinkLocalAddressing=ipv6

[DHCP]
RouteMetric=6000
UseMTU=true
'''})

        # mismatched values
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        %s: 3333
      dhcp6: yes
      dhcp6-overrides:
        %s: 5555
''' % (override_name, override_name), expect_fail=True)
        self.assertEqual(err, 'ERROR: engreen: networkd requires that '
                              '%s has the same value in both dhcp4_overrides and dhcp6_overrides\n' % override_name)

    def test_dhcp_overrides_use_dns(self):
        self.assert_dhcp_overrides_bool('use-dns', 'UseDNS')

    def test_dhcp_overrides_use_ntp(self):
        self.assert_dhcp_overrides_bool('use-ntp', 'UseNTP')

    def test_dhcp_overrides_send_hostname(self):
        self.assert_dhcp_overrides_bool('send-hostname', 'SendHostname')

    def test_dhcp_overrides_use_hostname(self):
        self.assert_dhcp_overrides_bool('use-hostname', 'UseHostname')

    def test_dhcp_overrides_hostname(self):
        self.assert_dhcp_overrides_string('hostname', 'Hostname')

    def test_dhcp_overrides_use_mtu(self):
        self.assert_dhcp_mtu_overrides_bool('use-mtu', 'UseMTU')

    def test_dhcp_overrides_default_metric(self):
        self.assert_dhcp_overrides_guint('route-metric', 'RouteMetric')

    def test_dhcp_overrides_use_routes(self):
        self.assert_dhcp_overrides_bool('use-routes', 'UseRoutes')


class TestNetworkManager(TestBase):

    def test_override_default_metric_v4(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: yes
      dhcp4-overrides:
        route-metric: 3333
''')
        # silently ignored since yes is the default
        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
route-metric=3333

[ipv6]
method=ignore
'''})

    def test_override_default_metric_v6(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: yes
      dhcp6: yes
      dhcp6-overrides:
        route-metric: 6666
''')
        # silently ignored since yes is the default
        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=auto
route-metric=6666
'''})
