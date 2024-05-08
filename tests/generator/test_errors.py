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
        self.assertIn("Invalid MAC address '00:11:ZZ', must be XX:XX:XX:XX:XX:XX "
                      "or XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX", err)

    def test_invalid_ipoib_mode(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    ib0:
      dhcp4: true
      infiniband-mode: invalid''', expect_fail=True)
        self.assertIn("Value of 'infiniband-mode' needs to be 'datagram' or 'connected'", err)

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

    def test_wifi_ap_unknown_band(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          band: bogus''', expect_fail=True)
        self.assertIn("unknown wifi band 'bogus'", err)

    def test_wifi_ap_invalid_freq24(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wl0:
      access-points:
        workplace:
          band: 2.4GHz
          channel: 15''', expect_fail=True)
        self.assertIn("ERROR: invalid 2.4GHz WiFi channel: 15", err)

    def test_wifi_ap_invalid_freq5(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          band: 5GHz
          channel: 14''', expect_fail=True)
        self.assertIn("ERROR: invalid 5GHz WiFi channel: 14", err)

    def test_wifi_invalid_hidden(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        hidden:
          hidden: maybe''', expect_fail=True)
        self.assertIn("invalid boolean value 'maybe'", err)

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

    def test_invalid_addr_gen_mode(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      ipv6-address-generation: 0''', expect_fail=True)
        self.assertIn("unknown ipv6-address-generation '0'", err)

    def test_addr_gen_mode_not_supported(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      ipv6-address-generation: stable-privacy''', expect_fail=True)
        self.assertIn("ERROR: engreen: ipv6-address-generation mode is not supported by networkd", err)

    def test_addr_gen_mode_and_addr_gen_token(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      ipv6-address-token: "::2"
      ipv6-address-generation: eui64''', expect_fail=True)
        self.assertIn("engreen: ipv6-address-generation and ipv6-address-token are mutually exclusive", err)

    def test_invalid_addr_gen_token(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      ipv6-address-token: INVALID''', expect_fail=True)
        self.assertIn("invalid ipv6-address-token 'INVALID'", err)

    def test_nm_devices_missing_passthrough(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  nm-devices:
    engreen:
      networkmanager:
        passthrough:
          connection.uuid: "123456"''', expect_fail=True)
        self.assertIn("engreen: network type 'nm-devices:' needs to provide a 'connection.type' via passthrough", err)

    def test_invalid_address_node_type(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: [[192.168.1.15]]''', expect_fail=True)
        self.assertIn("expected either scalar or mapping (check indentation)", err)

    def test_invalid_address_option_value(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
      - 0.0.0.0.0/24:
          lifetime: 0''', expect_fail=True)
        self.assertIn("malformed address '0.0.0.0.0/24', must be X.X.X.X/NN or X:X:X:X:X:X:X:X/NN", err)

    def test_invalid_address_option_lifetime(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
      - 192.168.1.15/24:
          lifetime: 1''', expect_fail=True)
        self.assertIn("invalid lifetime value '1'", err)

    def test_invalid_nm_options(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses:
      - 192.168.1.15/24:
          lifetime: 0''', expect_fail=True)
        self.assertIn('NetworkManager does not support address options', err)

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

    def test_multiple_ip4_gateways(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: [192.168.22.78/24]
      gateway4: 192.168.22.1
    enblue:
      addresses: [10.49.34.4/16]
      gateway4: 10.49.2.38''', expect_fail=False)
        self.assertIn("Problem encountered while validating default route consistency", err)
        self.assertIn("Conflicting default route declarations for IPv4 (table: main, metric: default)", err)
        self.assertIn("engreen", err)
        self.assertIn("enblue", err)

    def test_multiple_ip6_gateways(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: [2001:FFfe::1/62]
      gateway6: 2001:FFfe::2
    enblue:
      addresses: [2001:FFfe::33/62]
      gateway6: 2001:FFfe::34''', expect_fail=False)
        self.assertIn("Problem encountered while validating default route consistency", err)
        self.assertIn("Conflicting default route declarations for IPv6 (table: main, metric: default)", err)
        self.assertIn("engreen", err)
        self.assertIn("enblue", err)

    def test_gateway_and_default_route(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: [10.49.34.4/16]
      gateway4: 10.49.2.38
      routes:
      - to: default
        via: 10.49.65.89''', expect_fail=False)
        self.assertIn("Problem encountered while validating default route consistency", err)
        self.assertIn("Conflicting default route declarations for IPv4 (table: main, metric: default)", err)
        self.assertIn("engreen", err)

    def test_multiple_default_routes_on_other_table(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: [10.49.34.4/16]
      routes:
      - to: default
        via: 10.49.65.89
    enblue:
      addresses: [10.50.35.3/16]
      routes:
      - to: default
        via: 10.49.65.89
        table: 23
    enred:
      addresses: [172.137.1.4/24]
      routes:
      - to: default
        via: 172.137.1.1
        table: 23
        ''', expect_fail=False)
        self.assertIn("Problem encountered while validating default route consistency", err)
        self.assertIn("Conflicting default route declarations for IPv4 (table: 23, metric: default)", err)
        self.assertIn("enblue", err)
        self.assertIn("enred", err)
        self.assertNotIn("engreen", err)

    def test_multiple_default_routes_on_specific_metrics(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: [10.49.34.4/16]
      routes:
      - to: default
        via: 10.49.65.89
        metric: 100
    enblue:
      addresses: [10.50.35.3/16]
      routes:
      - to: default
        via: 10.49.65.89
        metric: 600
    enred:
      addresses: [172.137.1.4/24]
      routes:
      - to: default
        via: 172.137.1.1
        metric: 600
        ''', expect_fail=False)
        self.assertIn("Problem encountered while validating default route consistency", err)
        self.assertIn("Conflicting default route declarations for IPv4 (table: main, metric: 600)", err)
        self.assertIn("enblue", err)
        self.assertIn("enred", err)
        self.assertNotIn("engreen", err)

    def test_default_route_and_0(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: [10.49.34.4/16]
      routes:
      - to: default
        via: 10.49.65.89
      - to: 0.0.0.0/0
        via: 10.49.65.67''', expect_fail=False)
        self.assertIn("Problem encountered while validating default route consistency", err)
        self.assertIn("Conflicting default route declarations for IPv4 (table: main, metric: default)", err)
        self.assertIn("engreen", err)

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

    def test_vlan_unknown_renderer(self):
        err = self.generate('''network:
  version: 2
  ethernets: {en1: {}}
  vlans:
    ena: {id: 1, link: en1, renderer: foo}''', expect_fail=True)
        self.assertIn("unknown renderer 'foo'", err)

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

    def test_device_bad_route_mtu(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - to: 10.10.0.0/16
          via: 10.1.1.1
          mtu: -1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

        self.assertIn("invalid unsigned int value '-1'", err)

    def test_device_bad_route_congestion_window(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - to: 10.10.0.0/16
          via: 10.1.1.1
          congestion-window: -1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

        self.assertIn("invalid unsigned int value '-1'", err)

    def test_device_bad_route_advertised_receive_window(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      routes:
        - to: 10.10.0.0/16
          via: 10.1.1.1
          advertised-receive-window: -1
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''', expect_fail=True)

        self.assertIn("invalid unsigned int value '-1'", err)

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
          scope: global
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

    def test_invalid_activation_mode(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    engreen:
      activation-mode: invalid''', expect_fail=True)
        self.assertIn("needs to be 'manual' or 'off'", err)

    def test_nm_only_supports_unicast_routes(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  vrfs:
    vrf100:
      table: 100
      routes:
        - to: 1.2.3.4/24
          type: throw
      routing-policy:
        - to: 1.2.3.4/24''', expect_fail=True)
        self.assertIn("NetworkManager only supports unicast routes", err)

    def test_ignore_errors(self):
        ''' Test if a bad netdef (eth1 in this case) will be ignored '''
        out = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
    eth1:
      dhcp4: yesplease
    eth2:
      renderer: NetworkManager
      dhcp4: false''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

        self.assertTrue(self.file_exists('10-netplan-eth0.network'))
        self.assertTrue(self.file_exists('10-netplan-eth1.network'))
        self.assertTrue(self.file_exists('netplan-eth2.nmconnection', backend='NetworkManager'))

        self.assertIn('Skipping definition due to parsing errors. eth1:', out)

    def test_ignore_errors_multiple_files(self):
        ''' Test that a bad YAML file will be ignored '''
        out = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''', confs={'b': '''network:
  ethernets:
    eth1: {}''',
                             'c': ''':''',
                             'd': '''network:
  ethernets:
    eth2: {}'''}, expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

        self.assertTrue(self.file_exists('10-netplan-eth0.network'))
        self.assertTrue(self.file_exists('10-netplan-eth1.network'))
        self.assertTrue(self.file_exists('10-netplan-eth2.network'))
        self.assertIn('Skipping YAML file due to parsing errors.', out)
        self.assertIn('/etc/netplan/c.yaml:1:1: Invalid YAML: did not find expected key', out)

    def test_ignore_syntax_errors(self):
        ''' Test that an error in the same netdef in the next file will not remove the netdef '''
        out = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''', confs={'b': '''network:
  ethernets:
    eth0:
      abc: 123'''}, expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

        self.assertTrue(self.file_exists('10-netplan-eth0.network'))
        self.assertIn('Skipping definition due to parsing errors. eth0:', out)

    def test_ignore_errors_dependencies(self):
        ''' Test that an interface that depends on a bad interface will still have configuration generated '''
        out = self.generate('''network:
  version: 2
  ethernets:
    eth123:
      dhcp4: true
    eth321:
      dhcp4: 1''', confs={'b': '''network:
  bridges:
    br0:
      interfaces: [ eth123 ]
    br1:
      interfaces: [ eth321 ]'''}, expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

        self.assertTrue(self.file_exists('10-netplan-eth123.network'))
        self.assertTrue(self.file_exists('10-netplan-br0.network'))
        self.assertFalse(self.file_exists('10-netplan-321.network'))
        self.assertTrue(self.file_exists('10-netplan-br1.network'))
        self.assertIn('Skipping definition due to parsing errors. eth321:', out)

    def test_ignore_errors_bad_bond(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {}
  bonds:
    bond0:
      interfaces: [eth0]
      badkey: badvalue''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=no
Bond=bond0
''',
                              'bond0.network': '''[Match]
Name=bond0

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'bond0.netdev': '''[NetDev]
Name=bond0
Kind=bond
'''})

    def test_ignore_errors_bad_bridge(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {}
  bridges:
    br0:
      interfaces: [eth0]
      badkey: badvalue''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=no
Bridge=br0
''',
                              'br0.network': '''[Match]
Name=br0

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'br0.netdev': '''[NetDev]
Name=br0
Kind=bridge
'''})

    def test_ignore_errors_bad_vrf(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {}
  vrfs:
    vrf0:
      interfaces: [eth0]
      table: 1000
      badkey: badvalue''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=ipv6
VRF=vrf0
''',
                              'vrf0.network': '''[Match]
Name=vrf0

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'vrf0.netdev': '''[NetDev]
Name=vrf0
Kind=vrf

[VRF]
Table=1000
'''})

    def test_ignore_errors_bad_veth(self):
        self.generate('''network:
  version: 2
  virtual-ethernets:
    veth0:
      peer: veth1
    veth1:
      peer: veth0
      badkey: badvalue''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)
        self.assert_networkd({'veth0.network': '''[Match]
Name=veth0

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'veth1.network': '''[Match]
Name=veth1

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'veth0.netdev': '''[NetDev]
Name=veth0
Kind=veth

[Peer]
Name=veth1
'''})

    def test_ignore_errors_bad_veth_peer(self):
        self.generate('''network:
  version: 2
  virtual-ethernets:
    veth0:
      badkey: badvalue
      peer: veth1
    veth1:
      badkey: badvalue
      peer: veth0''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)
        self.assert_networkd({'veth0.network': '''[Match]
Name=veth0

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'veth1.network': '''[Match]
Name=veth1

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'veth0.netdev': '''[NetDev]
Name=veth0
Kind=veth
''',
                              'veth1.netdev': '''[NetDev]
Name=veth1
Kind=veth
'''})

    def test_ignore_errors_bad_vlan(self):
        self.generate('''network:
  version: 2
  vlans:
    vlan100:
      link: eth0
      id: 100
  ethernets:
    eth0:
      badkey: badvalue''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)
        self.assert_networkd({'vlan100.network': '''[Match]
Name=vlan100

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
''',
                              'vlan100.netdev': '''[NetDev]
Name=vlan100
Kind=vlan

[VLAN]
Id=100
''',
                             'eth0.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=ipv6
VLAN=vlan100
'''})

    def test_ignore_errors_bad_sriov_pf(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      embedded-switch-mode: switchdev
      badkey: badvalue
    ethvf0:
      link: eth0''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)
        self.assert_networkd({'ethvf0.network': '''[Match]
Name=ethvf0

[Network]
LinkLocalAddressing=ipv6
''',
                              'eth0.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=ipv6
'''})

    def test_ignore_errors_bad_wifi_nd(self):
        self.generate('''network:
  version: 2
  wifis:
    wlan0:
      badkey: badvalue
      access-points:
        ssid:
          password: abcdefgh''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

    def test_ignore_errors_bad_wifi_nm(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wlan0:
      badkey: badvalue
      access-points:
        ssid:
          password: abcdefgh''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

    def test_ignore_errors_bad_ap_nd(self):
        self.generate('''network:
  version: 2
  wifis:
    wlan0:
      access-points:
        ssid:
          badkey: badvalue
          password: abcdefgh''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

    def test_ignore_errors_bad_ap_nm(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  wifis:
    wlan0:
      access-points:
        ssid:
          badkey: badvalue
          password: abcdefgh''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

    def test_ignore_errors_bad_wireguard_nd(self):
        self.generate('''network:
  version: 2
  tunnels:
    wg0:
      mode: wireguard
      addresses: [10.10.10.20/24]
      key: 4GgaQCy68nzNsUE5aJ9fuLzHhB65tAlwbmA72MWnOm8=
      mark: 42
      port: 51820
      peers:
        badkey: badvalue''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

    def test_ignore_errors_bad_wireguard_nm(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  tunnels:
    wg0:
      mode: wireguard
      addresses: [10.10.10.20/24]
      key: 4GgaQCy68nzNsUE5aJ9fuLzHhB65tAlwbmA72MWnOm8=
      mark: 42
      port: 51820
      peers:
        badkey: badvalue''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)

    def test_ignore_errors_missing_interface(self):
        self.generate('''network:
  version: 2
  bonds:
    bond0:
      interfaces:
        - eth0''', expect_fail=False, skip_generated_yaml_validation=True, ignore_errors=True)
        self.assert_networkd({'bond0.netdev': '''[NetDev]
Name=bond0
Kind=bond
''',
                              'bond0.network': '''[Match]
Name=bond0

[Network]
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes
'''})
