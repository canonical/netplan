#!/usr/bin/python3
# Functional tests of certain libnetplan functions. These are run during
# "make check" and don't touch the system configuration at all.
#
# Copyright (C) 2020-2021 Canonical, Ltd.
# Author: Lukas Märdian <slyon@ubuntu.com>
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

import ctypes
import os
import shutil
import tempfile
import io
import yaml

from generator.base import TestBase
from parser.base import capture_stderr
from tests.test_utils import MockCmd

from utils import state_from_yaml
from netplan_cli.cli.commands.set import FALLBACK_FILENAME

import netplan
from netplan.netdef import NetplanRoute

# We still need direct (ctypes) access to libnetplan.so to test certain cases
# that are not covered by the 'netplan' module bindings
lib = ctypes.CDLL(ctypes.util.find_library('netplan'))
# Define some libnetplan.so ABI
lib.netplan_get_id_from_nm_filename.restype = ctypes.c_char_p

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe_cli = os.path.join(rootdir, 'src', 'netplan.script')


class TestRawLibnetplan(TestBase):
    '''Test libnetplan functionality as used by the NetworkManager backend'''

    def setUp(self):
        super().setUp()
        os.makedirs(self.confdir)

    def tearDown(self):
        shutil.rmtree(self.workdir.name)
        lib.netplan_clear_netdefs()
        super().tearDown()

    def test_get_id_from_filename(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_rootdir(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/some/rootdir/run/NetworkManager/system-connections/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_wifi(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID.nmconnection'.encode(), 'SOME-SSID'.encode())
        self.assertEqual(out, b'some-id')

    def test_get_id_from_filename_wifi_invalid_suffix(self):
        out = lib.netplan_get_id_from_nm_filename(
          '/run/NetworkManager/system-connections/netplan-some-id-SOME-SSID'.encode(), 'SOME-SSID'.encode())
        self.assertEqual(out, None)

    def test_get_id_from_filename_invalid_prefix(self):
        out = lib.netplan_get_id_from_nm_filename('INVALID/netplan-some-id.nmconnection'.encode(), None)
        self.assertEqual(out, None)

    def test_parse_keyfile_missing(self):
        f = os.path.join(self.workdir.name, 'tmp/some.keyfile')
        os.makedirs(os.path.dirname(f))
        with capture_stderr() as outf:
            self.assertFalse(lib.netplan_parse_keyfile(f.encode(), None))
            with open(outf.name, 'r') as f:
                self.assertIn('netplan: cannot load keyfile', f.read().strip())

    def test_generate(self):
        self.mock_netplan_cmd = MockCmd("netplan")
        os.environ["TEST_NETPLAN_CMD"] = self.mock_netplan_cmd.path
        self.assertTrue(lib.netplan_generate(self.workdir.name.encode()))
        self.assertEqual(self.mock_netplan_cmd.calls(), [
            ["netplan", "generate", "--root-dir", self.workdir.name],
        ])

    def test_delete_connection(self):
        os.environ["TEST_NETPLAN_CMD"] = exe_cli
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        with open(orig, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true''')
        self.assertTrue(os.path.isfile(orig))
        # Parse all YAML and delete 'some-netplan-id' connection file
        self.assertTrue(lib.netplan_delete_connection('some-netplan-id'.encode(), self.workdir.name.encode()))
        self.assertFalse(os.path.isfile(orig))
        self.assertFalse(os.path.isfile(os.path.join(self.confdir, FALLBACK_FILENAME)))

    def test_delete_connection_id_not_found(self):
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        with open(orig, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true''')
        self.assertTrue(os.path.isfile(orig))
        with capture_stderr() as outf:
            self.assertFalse(lib.netplan_delete_connection('unknown-id'.encode(), self.workdir.name.encode()))
            self.assertTrue(os.path.isfile(orig))
            with open(outf.name, 'r') as f:
                self.assertIn('netplan_delete_connection: Cannot delete unknown-id, does not exist.', f.read().strip())

    def test_delete_connection_two_in_file(self):
        os.environ["TEST_NETPLAN_CMD"] = exe_cli
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        with open(orig, 'w') as f:
            f.write('''network:
  ethernets:
    some-netplan-id:
      dhcp4: true
    other-id:
      dhcp6: true''')
        self.assertTrue(os.path.isfile(orig))
        self.assertTrue(lib.netplan_delete_connection('some-netplan-id'.encode(), self.workdir.name.encode()))
        self.assertTrue(os.path.isfile(orig))
        # Verify the file still exists and still contains the other connection
        with open(orig, 'r') as f:
            self.assertEqual(f.read(), 'network:\n  version: 2\n  ethernets:\n    other-id:\n      dhcp6: true\n')

    def test_delete_connection_invalid(self):
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        with open(orig, 'w') as f:
            f.write('INVALID')
        self.assertTrue(os.path.isfile(orig))
        with capture_stderr() as outf:
            self.assertFalse(lib.netplan_delete_connection('some-netplan-id'.encode(), self.workdir.name.encode()))
            with open(outf.name, 'r') as f:
                self.assertIn('Cannot parse input', f.read())

    def test_write_netplan_conf(self):
        netdef_id = 'some-netplan-id'
        orig = os.path.join(self.confdir, 'some-filename.yaml')
        generated = os.path.join(self.confdir, '10-netplan-{}.yaml'.format(netdef_id))
        with open(orig, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    some-netplan-id:
      renderer: networkd
      match:
        name: "eth42"
''')
        # Parse YAML and and re-write the specified netdef ID into a new file
        self.assertTrue(lib.netplan_parse_yaml(orig.encode(), None))
        lib._write_netplan_conf(netdef_id.encode(), self.workdir.name.encode())
        self.assertEqual(lib.netplan_clear_netdefs(), 1)
        self.assertTrue(os.path.isfile(generated))
        with open(orig, 'r') as f:
            with open(generated, 'r') as new:
                self.assertEqual(f.read(), new.read())


class TestNetdefIterator(TestBase):
    def test_with_empty_netplan(self):
        state = netplan.State()
        self.assertSequenceEqual(list(netplan.netdef.NetDefinitionIterator(state, "ethernets")), [])

    def test_iter_all_types(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
  bridges:
    br0:
      dhcp4: false''')
        self.assertSetEqual(set(["eth0", "br0"]), set(d.id for d in netplan.netdef.NetDefinitionIterator(state, None)))

    def test_iter_ethernets(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
    eth1:
      dhcp4: false
  bridges:
    br0:
      dhcp4: false''')
        self.assertSetEqual(set(["eth0", "eth1"]), set(d.id for d in netplan.netdef.NetDefinitionIterator(state, "ethernets")))


class TestNetdefAddressesIterator(TestBase):
    def test_with_empty_ip_addresses(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: true''')

        netdef = next(netplan.netdef.NetDefinitionIterator(state, "ethernets"))
        self.assertSetEqual(set(), set(ip for ip in netdef.addresses))

    def test_iter_ethernets(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      addresses:
        - 192.168.0.1/24
        - 172.16.0.1/24
        - 1234:4321:abcd::cdef/96
        - abcd::1234/64''')

        expected = set(["1234:4321:abcd::cdef/96", "abcd::1234/64", "192.168.0.1/24", "172.16.0.1/24"])
        netdef = next(netplan.netdef.NetDefinitionIterator(state, "ethernets"))
        self.assertSetEqual(expected, set(ip.address for ip in netdef.addresses))
        self.assertSetEqual(expected, set(str(ip) for ip in netdef.addresses))

    def test_iter_ethernets_with_options(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      addresses:
        - 192.168.0.1/24
        - 172.16.0.1/24:
            lifetime: 0
            label: label1
        - 1234:4321:abcd::cdef/96:
            lifetime: forever
            label: label2''')

        expected_ips = set(["1234:4321:abcd::cdef/96", "192.168.0.1/24", "172.16.0.1/24"])
        expected_lifetime_options = set([None, "0", "forever"])
        expected_label_options = set([None, "label1", "label2"])
        netdef = next(netplan.netdef.NetDefinitionIterator(state, "ethernets"))
        self.assertSetEqual(expected_ips, set(ip.address for ip in netdef.addresses))
        self.assertSetEqual(expected_lifetime_options, set(ip.lifetime for ip in netdef.addresses))
        self.assertSetEqual(expected_label_options, set(ip.label for ip in netdef.addresses))

    def test_drop_iterator_before_finishing(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      addresses:
        - 192.168.0.1/24
        - 1234:4321:abcd::cdef/96''')

        netdef = next(netplan.netdef.NetDefinitionIterator(state, "ethernets"))
        iter = netdef.addresses.__iter__()
        address = next(iter)
        self.assertEqual(address.address, "192.168.0.1/24")
        del iter


class TestNetdefNameserverSearchDomainIterator(TestBase):
    def test_with_empty_nameservers(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0: {}''')

        netdef = next(netplan.netdef.NetDefinitionIterator(state, "ethernets"))
        self.assertSetEqual(set(), set(ip for ip in netdef.nameserver_addresses))
        self.assertSetEqual(set(), set(ip for ip in netdef.nameserver_search))

    def test_iter_ethernets_nameservers_and_domains(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      nameservers:
        search:
          - home.local
          - mynet.local
        addresses:
          - 192.168.0.1
          - 172.16.0.1
          - 1234:4321:abcd::cdef
          - abcd::1234''')

        expected_addresses = set(["1234:4321:abcd::cdef", "abcd::1234", "192.168.0.1", "172.16.0.1"])
        expected_domains = set(["home.local", "mynet.local"])
        netdef = next(netplan.netdef.NetDefinitionIterator(state, "ethernets"))
        self.assertSetEqual(expected_addresses, set(ip for ip in netdef.nameserver_addresses))
        self.assertSetEqual(expected_domains, set(domain for domain in netdef.nameserver_search))


class TestNetdefRouteIterator(TestBase):
    def test_with_empty_routes(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0: {}''')

        netdef = next(netplan.netdef.NetDefinitionIterator(state, "ethernets"))
        self.assertTrue(len([ip for ip in netdef.routes]) == 0)

    def test_iter_routes(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      routes:
        - to: default
          via: 192.168.0.1
        - to: 1.2.3.0/24
          via: 10.20.30.40
          metric: 1000
          table: 1000
          from: 192.168.0.0/24
        - to: 3.2.1.0/24
          via: 10.20.30.40
          metric: 1000
          table: 1000
          on-link: true
          type: local
          scope: host
          mtu: 1500
          congestion-window: 123
          advertised-receive-window: 321
          from: 192.168.0.0/24''')

        netdef = next(netplan.netdef.NetDefinitionIterator(state, "ethernets"))
        routes = [route for route in netdef.routes]
        self.assertSetEqual({routes[0].to, routes[0].via}, {'default', '192.168.0.1'})
        self.assertSetEqual({routes[1].to, routes[1].via, routes[1].metric, routes[1].table, routes[1].from_addr},
                            {'1.2.3.0/24', '10.20.30.40', 1000, 1000, '192.168.0.0/24'})
        self.assertSetEqual({routes[2].to, routes[2].via, routes[2].metric, routes[2].table, routes[2].from_addr,
                             routes[2].onlink, routes[2].type, routes[2].scope, routes[2].mtubytes, routes[2].congestion_window,
                             routes[2].advertised_receive_window},
                            {'3.2.1.0/24', '10.20.30.40', 1000, 1000, True, 'local', 'host', 1500, 123, 321, '192.168.0.0/24'})


class TestRoute(TestBase):
    def test_route_str(self):
        route1 = {}
        route1['to'] = 'default'
        route1['via'] = '192.168.0.1'
        route1['from_addr'] = '192.168.0.1'
        route1['metric'] = 1000

        route = NetplanRoute(**route1)

        expected_str = 'default via 192.168.0.1 type unicast scope global src 192.168.0.1 metric 1000'

        self.assertEqual(str(route), expected_str)

    def test_route_str_with_table(self):
        route1 = {}
        route1['to'] = 'default'
        route1['via'] = '192.168.0.1'
        route1['from_addr'] = '192.168.0.1'
        route1['metric'] = 1000
        route1['table'] = 1234

        route = NetplanRoute(**route1)

        expected_str = 'default via 192.168.0.1 type unicast scope global src 192.168.0.1 metric 1000 table 1234'

        self.assertEqual(str(route), expected_str)

    def test_routes_to_dict(self):
        route1 = {}
        route1['to'] = 'default'
        route1['via'] = '192.168.0.1'
        route1['from_addr'] = '192.168.0.1'
        route1['metric'] = 1000
        route1['table'] = 1234
        route1['family'] = 2

        route = NetplanRoute(**route1)

        expected_dict = {
            'from': '192.168.0.1',
            'metric': 1000,
            'table': 1234,
            'to': 'default',
            'type': 'unicast',
            'via': '192.168.0.1',
            'family': 2,
        }

        self.assertDictEqual(route.to_dict(), expected_dict)


class TestParser(TestBase):
    def test_load_yaml_from_fd_empty(self):
        parser = netplan.Parser()
        # We just don't want it to raise an exception
        with tempfile.TemporaryFile() as f:
            parser.load_yaml(f)

    def test_load_yaml_from_fd_bad_yaml(self):
        parser = netplan.Parser()
        with tempfile.TemporaryFile() as f:
            f.write(b'invalid: {]')
            f.seek(0, io.SEEK_SET)
            with self.assertRaises(netplan.NetplanParserException) as context:
                parser.load_yaml(f)
            self.assertIn('Invalid YAML', str(context.exception))

    def test_load_keyfile(self):
        parser = netplan.Parser()
        state = netplan.State()
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'''[connection]
id=Bridge connection 1
type=bridge
uuid=990548be-01ed-42d7-9f9f-cd4966b25c08
interface-name=bridge0

[ipv4]
method=auto

[ipv6]
method=auto
addr-gen-mode=1''')
            f.seek(0, io.SEEK_SET)
            parser.load_keyfile(f.name)
            state.import_parser_results(parser)
            output = io.StringIO()
            state._dump_yaml(output)
            yaml_data = yaml.safe_load(output.getvalue())
            self.assertIsNotNone(yaml_data.get('network'))


class TestState(TestBase):
    def test_get_netdef(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')
        netdef = state['eth0']
        self.assertEqual("eth0", netdef.id)

    def test_get_netdef_empty_state(self):
        state = netplan.State()
        with self.assertRaises(IndexError):
            state['eth0']

    def test_get_netdef_wrong_id(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')
        with self.assertRaises(IndexError):
            state['eth1']

    def test_get_netdefs_size(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')
        self.assertEqual(1, len(state))

    def test_bad_state(self):
        state = netplan.State()
        parser = netplan.Parser()
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'''network:
  renderer: networkd
  tunnels:
    tun0:
      mode: ipip
      local: 10.10.10.10
      remote: 20.20.20.20
      keys:
        input: 1234
''')
            f.flush()
            parser.load_yaml(f.name)

        with self.assertRaises(netplan.NetplanException):
            state.import_parser_results(parser)

    def test_dump_yaml_bad_file_perms(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')
        bad_file = os.path.join(self.workdir.name, 'bad.yml')
        open(bad_file, 'a').close()
        os.chmod(bad_file, 0o444)
        with self.assertRaises(netplan.NetplanFileException) as context:
            with open(bad_file) as f:
                state._dump_yaml(f)
        self.assertIn('Invalid argument', str(context.exception))
        self.assertEqual(context.exception.error, context.exception.errno)

    def test_dump_yaml_empty_state(self):
        state = netplan.State()
        with tempfile.TemporaryFile() as f:
            state._dump_yaml(f)
            f.flush()
            self.assertEqual(0, f.seek(0, io.SEEK_END))

    def test_write_yaml_file_unremovable_target(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''', filename='target.yml')
        target = os.path.join(self.confdir, 'target.yml')
        os.remove(target)
        os.makedirs(target)

        with self.assertRaises(netplan.NetplanFileException):
            state._write_yaml_file('target.yml', self.workdir.name)

    def test_update_yaml_hierarchy_no_confdir(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')
        shutil.rmtree(self.confdir)
        with self.assertRaises(netplan.NetplanFileException) as context:
            state._update_yaml_hierarchy("bogus", self.workdir.name)
        self.assertIn('No such file or directory', str(context.exception))

    def test_write_yaml_file_remove_directory(self):
        state = netplan.State()
        os.makedirs(self.confdir)
        with tempfile.TemporaryDirectory(dir=self.confdir) as tmpdir:
            hint = os.path.basename(tmpdir)
            with self.assertRaises(netplan.NetplanFileException):
                state._write_yaml_file(hint, self.workdir.name)

    def test_write_yaml_file_file_no_confdir(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''', filename='test.yml')
        shutil.rmtree(self.confdir)
        with self.assertRaises(netplan.NetplanFileException) as context:
            state._write_yaml_file('test.yml', self.workdir.name)
        self.assertIn('No such file or directory', str(context.exception))


class TestNetDefinition(TestBase):
    def test_type(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')

        self.assertEqual(state['eth0'].type, 'ethernets')

    def test_backend(self):
        state = state_from_yaml(self.confdir, '''network:
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: false
    eth1:
      renderer: NetworkManager''')
        self.assertEqual(state['eth0'].backend, 'networkd')
        self.assertEqual(state['eth1'].backend, 'NetworkManager')

    def test_critical(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      critical: true
    eth1: {}''')

        self.assertTrue(state['eth0'].critical)
        self.assertFalse(state['eth1'].critical)

    def test_eq(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
    eth1:
      dhcp4: false''')

        # netplan.State __getitem__ doesn't cache the netdefs,
        # so fetching it twice should create two separate Python objects
        # pointing to the same C struct.
        self.assertEqual(state['eth0'], state['eth0'])
        self.assertNotEqual(state['eth0'], state['eth1'])
        # Test against a weird singleton to ensure consistency against other types
        self.assertNotEqual(state['eth0'], True)

    def test_filepath(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''', filename="a.yaml")
        netdef = state['eth0']
        self.assertEqual(os.path.join(self.confdir, "a.yaml"), netdef.filepath)

    def test_filepath_for_ovs_ports(self):
        state = state_from_yaml(self.confdir, '''network:
  version: 2
  renderer: networkd
  bridges:
    br0:
      interfaces:
        - patch0-2
    br1:
      interfaces:
        - patch2-0
  openvswitch:
    ports:
      - [patch0-2, patch2-0]''', filename="a.yaml")
        netdef_port1 = state["patch2-0"]
        netdef_port2 = state["patch0-2"]
        self.assertEqual(os.path.join(self.confdir, "a.yaml"), netdef_port1.filepath)
        self.assertEqual(os.path.join(self.confdir, "a.yaml"), netdef_port2.filepath)

    def test_filepath_for_ovs_ports_when_conf_is_redefined(self):
        state = netplan.State()
        parser = netplan.Parser()

        with tempfile.NamedTemporaryFile() as f:
            f.write(b'''network:
  version: 2
  renderer: networkd
  bridges:
    br0:
      interfaces:
        - patch0-2
    br1:
      interfaces:
        - patch2-0
  openvswitch:
    ports:
      - [patch0-2, patch2-0]''')
            f.flush()
            parser.load_yaml(f.name)

        with tempfile.NamedTemporaryFile() as f:
            f.write(b'''network:
  version: 2
  renderer: networkd
  bridges:
    br0:
      interfaces:
        - patch0-2
    br1:
      interfaces:
        - patch2-0
  openvswitch:
    ports:
      - [patch0-2, patch2-0]''')
            f.flush()
            parser.load_yaml(f.name)
            yaml_redefinition_filepath = f.name

        state.import_parser_results(parser)
        netdef_port1 = state["patch2-0"]
        netdef_port2 = state["patch0-2"]
        self.assertEqual(os.path.join(self.confdir, yaml_redefinition_filepath), netdef_port1.filepath)
        self.assertEqual(os.path.join(self.confdir, yaml_redefinition_filepath), netdef_port2.filepath)

    def test_set_name(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    mac-match:
      set-name: mymac0
      match:
        macaddress: 11:22:33:AA:BB:FF''')
        self.assertEqual(state['mac-match'].set_name, 'mymac0')

    def test_simple_matches(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    witness: {}
    name-match:
      match:
        name: "eth42"
    driver-match:
      match:
        driver: "e10*"
    mac-match:
      match:
        macaddress: 11:22:33:AA:BB:FF''')
        self.assertFalse(state['witness']._has_match)
        self.assertTrue(state['name-match']._has_match)
        self.assertTrue(state['name-match']._match_interface(iface_name="eth42"))
        self.assertFalse(state['name-match']._match_interface(iface_name="eth32"))
        self.assertTrue(state['driver-match']._match_interface(iface_driver="e1000"))
        self.assertFalse(state['name-match']._match_interface(iface_driver="ixgbe"))
        self.assertFalse(state['driver-match']._match_interface(iface_name="eth42"))
        self.assertTrue(state['mac-match']._match_interface(iface_mac="11:22:33:AA:BB:FF"))
        self.assertFalse(state['mac-match']._match_interface(iface_mac="11:22:33:AA:BB:CC"))

    def test_match_without_match_block(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')

        netdef = state['eth0']
        self.assertTrue(netdef._match_interface('eth0'))
        self.assertFalse(netdef._match_interface('eth000'))

    def test_vlan_props_without_vlan(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')

        self.assertIsNone(state['eth0']._vlan_id)
        self.assertIsNone(state['eth0'].links.get('vlan'))

    def test_is_trivial_compound_itf(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
  bridges:
    br0:
      dhcp4: false
    br1:
      parameters:
        priority: 42
      ''')

        self.assertFalse(state['eth0']._is_trivial_compound_itf)
        self.assertTrue(state['br0']._is_trivial_compound_itf)
        self.assertFalse(state['br1']._is_trivial_compound_itf)

    def test_interface_has_pointer_to_bridge(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
  bridges:
    br0:
      dhcp4: false
      interfaces:
        - eth0
      ''')

        self.assertEqual(state['eth0'].links.get('bridge').id, "br0")

    def test_interface_pointer_to_bridge_is_none(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
      ''')

        self.assertIsNone(state['eth0'].links.get('bridge'))

    def test_interface_has_pointer_to_bond(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
  bonds:
    bond0:
      dhcp4: false
      interfaces:
        - eth0
      ''')

        self.assertEqual(state['eth0'].links.get('bond').id, "bond0")

    def test_interface_pointer_to_bond_is_none(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
      ''')

        self.assertIsNone(state['eth0'].links.get('bond'))

    def test_interface_has_pointer_to_peer(self):
        state = state_from_yaml(self.confdir, '''network:
  openvswitch:
    ports:
      - [patch0-1, patch1-0]
  bonds:
    bond0:
      interfaces:
        - patch1-0
  bridges:
    ovs0:
      interfaces: [patch0-1, bond0]
      ''')

        self.assertEqual(state['patch0-1'].links.get('peer').id, "patch1-0")
        self.assertEqual(state['patch1-0'].links.get('peer').id, "patch0-1")

    def test_dhcp4_dhcp6(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: true
      dhcp6: false
      ''')

        self.assertTrue(state['eth0'].dhcp4)
        self.assertFalse(state['eth0'].dhcp6)

        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
      dhcp6: true
      ''')

        self.assertFalse(state['eth0'].dhcp4)
        self.assertTrue(state['eth0'].dhcp6)

    def test_get_macaddress(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      macaddress: aa:bb:cc:dd:ee:ff
      ''')

        self.assertEqual(state['eth0'].macaddress, 'aa:bb:cc:dd:ee:ff')

        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0: {}''')

        self.assertIsNone(state['eth0'].macaddress)


class TestFreeFunctions(TestBase):
    def test_create_yaml_patch_dict(self):
        with tempfile.TemporaryFile() as patchfile:
            payload = {'ethernets': {
                'eth0': {'dhcp4': True},
                'eth1': {'dhcp4': False}}}
            netplan._create_yaml_patch(['network'], payload, patchfile)
            patchfile.seek(0, io.SEEK_SET)
            self.assertDictEqual(payload, yaml.safe_load(patchfile.read())['network'])

    def test_create_yaml_patch_bad_syntax(self):
        with tempfile.TemporaryFile() as patchfile:
            with self.assertRaises(netplan.NetplanFormatException) as context:
                netplan._create_yaml_patch(['network'], '{invalid_yaml]', patchfile)
            self.assertIn('Error parsing YAML', str(context.exception))
            patchfile.seek(0, io.SEEK_END)
            self.assertEqual(patchfile.tell(), 0)

    def test_dump_yaml_subtree_bad_input_file_perms(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w") as f, tempfile.TemporaryFile() as output:
            with self.assertRaises(netplan.NetplanFileException) as context:
                netplan._dump_yaml_subtree(['network'], f, output)
        self.assertIn('Invalid argument', str(context.exception))

    def test_dump_yaml_subtree_bad_output_file_perms(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        output_file = os.path.join(self.workdir.name, 'output.yaml')
        with open(input_file, 'w') as input, open(output_file, 'w') as output:
            input.write('network: {}')
            output.write('')

        with open(input_file, "r") as f, open(output_file, 'r') as output:
            with self.assertRaises(netplan.NetplanFileException) as context:
                netplan._dump_yaml_subtree(['network'], f, output)
        self.assertIn('Invalid argument', str(context.exception))

    def test_dump_yaml_subtree_bad_yaml_outside(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('{garbage)')
            f.flush()
            with self.assertRaises(netplan.NetplanFormatException) as context:
                netplan._dump_yaml_subtree(['network'], f, output)
        self.assertIn('Error parsing YAML', str(context.exception))

    def test_dump_yaml_subtree_bad_yaml_inside(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''network:
  ethernets:
    {garbage)''')
            f.flush()

            with self.assertRaises(netplan.NetplanFormatException) as context:
                netplan._dump_yaml_subtree(['network'], f, output)
        self.assertIn('Error parsing YAML', str(context.exception))

    def test_dump_yaml_subtree_bad_type(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''[]''')
            f.flush()

            with self.assertRaises(netplan.NetplanFormatException) as context:
                netplan._dump_yaml_subtree(['network'], f, output)
        self.assertIn('Unexpected YAML structure found', str(context.exception))

    def test_dump_yaml_subtree_bad_yaml_ignored(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''network:
  ethernets: null
ignored:
  - [}''')
            f.flush()
            with self.assertRaises(netplan.NetplanFormatException) as context:
                netplan._dump_yaml_subtree(['network'], f, output)
        self.assertIn('Error parsing YAML', str(context.exception))

    def test_dump_yaml_subtree_discard_tail(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''network:
  ethernets: {}
tail:
  - []''')
            f.flush()
            netplan._dump_yaml_subtree(['network', 'ethernets'], f, output)
            output.seek(0)
            self.assertEqual(yaml.safe_load(output), {})

    def test_dump_yaml_absent_key(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''network:
  ethernets: {}
tail:
  - []''')
            f.flush()
            netplan._dump_yaml_subtree(['network', 'ethernets', 'eth0'], f, output)
            output.seek(0)
            self.assertEqual(yaml.safe_load(output), None)

    def test_validation_error_exception(self):
        ''' "set-name" requires "match" so it should fail validation '''
        parser = netplan.Parser()
        with tempfile.TemporaryDirectory() as d:
            full_dir = d + '/etc/netplan'
            os.makedirs(full_dir)
            with tempfile.NamedTemporaryFile(suffix='.yaml', dir=full_dir) as f:
                f.write(b'''network:
  ethernets:
    eth0:
      set-name: abc''')
                f.flush()

                with self.assertRaises(netplan.NetplanValidationException):
                    parser.load_yaml_hierarchy(d)

    def test_validation_exception_with_bad_error_message(self):
        '''
        If the exception's constructor can't parse the error message it will raise
        a ValueError exception.
        This situation should never happen though.
        '''
        with self.assertRaises(ValueError):
            netplan.NetplanValidationException('not the expected file path', 0, 0)

    def test_parser_exception_with_bad_error_message(self):
        '''
        If the exception's constructor can't parse the error message it will raise
        a ValueError exception.
        This situation should never happen though.
        '''
        with self.assertRaises(ValueError):
            netplan.NetplanParserException('not the expected file path, line and column', 0, 0)
