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

from .base import TestBase, ND_DHCP4, ND_DHCP6, ND_DHCPYES


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

