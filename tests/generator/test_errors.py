#
# Tests for common invalid syntax/errors in config
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

from .base import TestBase


class TestConfigErrors(TestBase):
    def test_malformed_yaml(self):
        err = self.generate('network:\n  version: %&', expect_fail=True)
        self.assertIn('Invalid YAML', err)
        self.assertIn('found character that cannot start any token', err)

    def test_wrong_indent(self):
        err = self.generate('network:\n  version: 2\n foo: *', expect_fail=True)
        self.assertIn('Invalid YAML', err)
        self.assertIn('inconsistent indentation', err)

    def test_yaml_expected_scalar(self):
        err = self.generate('network:\n  version: {}', expect_fail=True)
        self.assertIn('expected scalar', err)

    def test_yaml_expected_sequence(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: {}''', expect_fail=True)
        self.assertIn('expected sequence', err)

    def test_yaml_expected_mapping(self):
        err = self.generate('network:\n  version', expect_fail=True)
        self.assertIn('expected mapping', err)

    def test_invalid_bool(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    id0:
      wakeonlan: wut
''', expect_fail=True)
        self.assertIn("invalid boolean value 'wut'", err)

    def test_invalid_version(self):
        err = self.generate('network:\n  version: 1', expect_fail=True)
        self.assertIn('Only version 2 is supported', err)

    def test_id_redef_type_mismatch(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    id0:
      wakeonlan: true''',
                            confs={'redef': '''network:
  version: 2
  bridges:
    id0:
      wakeonlan: true'''}, expect_fail=True)
        self.assertIn("Updated definition 'id0' changes device type", err)

    def test_set_name_without_match(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      set-name: lom1
''', expect_fail=True)
        self.assertIn("def1: 'set-name:' requires 'match:' properties", err)

    def test_virtual_set_name(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      set_name: br1''', expect_fail=True)
        self.assertIn("unknown key 'set_name'", err)

    def test_virtual_match(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      match:
        driver: foo''', expect_fail=True)
        self.assertIn("unknown key 'match'", err)

    def test_virtual_wol(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      wakeonlan: true''', expect_fail=True)
        self.assertIn("unknown key 'wakeonlan'", err)

    def test_unknown_global_renderer(self):
        err = self.generate('''network:
  version: 2
  renderer: bogus
''', expect_fail=True)
        self.assertIn("unknown renderer 'bogus'", err)

    def test_unknown_type_renderer(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    renderer: bogus
''', expect_fail=True)
        self.assertIn("unknown renderer 'bogus'", err)

    def test_invalid_id(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    "eth 0":
      dhcp4: true''', expect_fail=True)
        self.assertIn("Invalid name 'eth 0'", err)

    def test_invalid_name_match(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: |
          fo o
          bar
      dhcp4: true''', expect_fail=True)
        self.assertIn("Invalid name 'fo o\nbar\n'", err)

    def test_invalid_mac_match(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        macaddress: 00:11:ZZ
      dhcp4: true''', expect_fail=True)
        self.assertIn("Invalid MAC address '00:11:ZZ', must be XX:XX:XX:XX:XX:XX", err)

    def test_glob_in_id(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    en*:
      dhcp4: true''', expect_fail=True)
        self.assertIn("Definition ID 'en*' must not use globbing", err)

    def test_wifi_duplicate_ssid(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          password: "s3kr1t"
        workplace:
          password: "c0mpany"
      dhcp4: yes''', expect_fail=True)
        self.assertIn("wl0: Duplicate access point SSID 'workplace'", err)

    def test_wifi_no_ap(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      dhcp4: yes''', expect_fail=True)
        self.assertIn('wl0: No access points defined', err)

    def test_wifi_empty_ap(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points: {}
      dhcp4: yes''', expect_fail=True)
        self.assertIn('wl0: No access points defined', err)

    def test_wifi_ap_unknown_key(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          something: false
      dhcp4: yes''', expect_fail=True)
        self.assertIn("unknown key 'something'", err)

    def test_wifi_ap_unknown_mode(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          mode: bogus''', expect_fail=True)
        self.assertIn("unknown wifi mode 'bogus'", err)

    def test_invalid_ipv4_address(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 192.168.14/24
        - 2001:FFfe::1/64''', expect_fail=True)

        self.assertIn("malformed address '192.168.14/24', must be X.X.X.X/NN", err)

    def test_missing_ipv4_prefixlen(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 192.168.14.1''', expect_fail=True)

        self.assertIn("address '192.168.14.1' is missing /prefixlength", err)

    def test_empty_ipv4_prefixlen(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 192.168.14.1/''', expect_fail=True)

        self.assertIn("invalid prefix length in address '192.168.14.1/'", err)

    def test_invalid_ipv4_prefixlen(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 192.168.14.1/33''', expect_fail=True)

        self.assertIn("invalid prefix length in address '192.168.14.1/33'", err)

    def test_invalid_ipv6_address(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 2001:G::1/64''', expect_fail=True)

        self.assertIn("malformed address '2001:G::1/64', must be X.X.X.X/NN", err)

    def test_missing_ipv6_prefixlen(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 2001::1''', expect_fail=True)
        self.assertIn("address '2001::1' is missing /prefixlength", err)

    def test_invalid_ipv6_prefixlen(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
      - 2001::1/129''', expect_fail=True)
        self.assertIn("invalid prefix length in address '2001::1/129'", err)

    def test_empty_ipv6_prefixlen(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 2001::1/''', expect_fail=True)
        self.assertIn("invalid prefix length in address '2001::1/'", err)

    def test_invalid_gateway4(self):
        for a in ['300.400.1.1', '1.2.3', '192.168.14.1/24']:
            err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      gateway4: %s''' % a, expect_fail=True)
            self.assertIn("invalid IPv4 address '%s'" % a, err)

    def test_invalid_gateway6(self):
        for a in ['1234', '1:::c', '1234::1/50']:
            err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      gateway6: %s''' % a, expect_fail=True)
            self.assertIn("invalid IPv6 address '%s'" % a, err)

    def test_invalid_nameserver_ipv4(self):
        for a in ['300.400.1.1', '1.2.3', '192.168.14.1/24']:
            err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      nameservers:
        addresses: [%s]''' % a, expect_fail=True)
            self.assertIn("malformed address '%s'" % a, err)

    def test_invalid_nameserver_ipv6(self):
        for a in ['1234', '1:::c', '1234::1/50']:
            err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      nameservers:
        addresses: ["%s"]''' % a, expect_fail=True)
            self.assertIn("malformed address '%s'" % a, err)

    def test_vlan_missing_id(self):
        err = self.generate('''network:
  version: 2
  ethernets: {en1: {}}
  vlans:
    ena: {link: en1}''', expect_fail=True)
        self.assertIn("missing 'id' property", err)

    def test_vlan_invalid_id(self):
        err = self.generate('''network:
  version: 2
  ethernets: {en1: {}}
  vlans:
    ena: {id: a, link: en1}''', expect_fail=True)
        self.assertIn("invalid unsigned int value 'a'", err)

        err = self.generate('''network:
  version: 2
  ethernets: {en1: {}}
  vlans:
    ena: {id: 4095, link: en1}''', expect_fail=True)
        self.assertIn("invalid id '4095'", err)

    def test_vlan_missing_link(self):
        err = self.generate('''network:
  version: 2
  vlans:
    ena: {id: 1}''', expect_fail=True)
        self.assertIn("ena: missing 'link' property", err)

    def test_vlan_unknown_link(self):
        err = self.generate('''network:
  version: 2
  vlans:
    ena: {id: 1, link: en1}''', expect_fail=True)
        self.assertIn("ena: interface 'en1' is not defined", err)

    def test_device_bad_route_to(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - to: badlocation
          via: 192.168.14.20
          metric: 100
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_bad_route_via(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - to: 10.10.0.0/16
          via: badgateway
          metric: 100
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_bad_route_metric(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - to: 10.10.0.0/16
          via: 10.1.1.1
          metric: -1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_family_mismatch_ipv6_to(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - to: 2001:dead:beef::0/16
          via: 10.1.1.1
          metric: 1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_family_mismatch_ipv4_to(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - via: 2001:dead:beef::2
          to: 10.10.10.0/24
          metric: 1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_missing_to(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - via: 2001:dead:beef::2
          metric: 1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_missing_via(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - to: 2001:dead:beef::2
          metric: 1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_type_missing_to(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - via: 2001:dead:beef::2
          type: prohibit
          metric: 1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_scope_link_missing_to(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - via: 2001:dead:beef::2
          scope: link
          metric: 1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_invalid_onlink(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - via: 2001:dead:beef::2
          to: 2000:cafe:cafe::1/24
          on-link: 1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_invalid_table(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - via: 2001:dead:beef::2
          to: 2000:cafe:cafe::1/24
          table: -1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_invalid_type(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - via: 2001:dead:beef::2
          to: 2000:cafe:cafe::1/24
          type: thisisinvalidtype
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_route_invalid_scope(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - via: 2001:dead:beef::2
          to: 2000:cafe:cafe::1/24
          scope: linky
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_ip_rule_mismatched_addresses(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routing-policy:
        - from: 10.10.10.0/24
          to: 2000:dead:beef::3/64
          table: 50
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_ip_rule_missing_address(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routing-policy:
        - table: 50
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_ip_rule_invalid_tos(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routing-policy:
        - from: 10.10.10.0/24
          type-of-service: 256
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_ip_rule_invalid_prio(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routing-policy:
        - from: 10.10.10.0/24
          priority: -1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_ip_rule_invalid_table(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routing-policy:
        - from: 10.10.10.0/24
          table: -1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_ip_rule_invalid_fwmark(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routing-policy:
        - from: 10.10.10.0/24
          mark: -1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_device_ip_rule_invalid_address(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routing-policy:
        - to: 10.10.10.0/24
          from: someinvalidaddress
          mark: 1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

    def test_invalid_dhcp_identifier(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp-identifier: invalid''', expect_fail=True)

    def test_invalid_accept_ra(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      accept-ra: j''', expect_fail=True)
        self.assertIn('invalid boolean', err)

    def test_invalid_link_local_set(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp6: yes
      link-local: invalid''', expect_fail=True)

    def test_invalid_link_local_value(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      dhcp6: yes
      link-local: [ invalid, ]''', expect_fail=True)

    def test_invalid_yaml_tabs(self):
        err = self.generate('''\t''', expect_fail=True)
        self.assertIn("tabs are not allowed for indent", err)

    def test_invalid_yaml_undefined_alias(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    *engreen:
      dhcp4: yes''', expect_fail=True)
        self.assertIn("aliases are not supported", err)

    def test_invalid_yaml_undefined_alias_at_eof(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: *yes''', expect_fail=True)
        self.assertIn("aliases are not supported", err)
