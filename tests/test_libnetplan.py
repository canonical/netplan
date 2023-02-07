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

import os
import shutil
import tempfile
import io
import yaml

from generator.base import TestBase
from parser.base import capture_stderr
from tests.test_utils import MockCmd

from utils import state_from_yaml
from netplan.cli.commands.set import FALLBACK_FILENAME

import netplan.libnetplan as libnetplan

lib = libnetplan.lib
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
        state = libnetplan.State()
        self.assertSequenceEqual(list(libnetplan._NetdefIterator(state, "ethernets")), [])

    def test_iter_all_types(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
  bridges:
    br0:
      dhcp4: false''')
        self.assertSetEqual(set(["eth0", "br0"]), set(d.id for d in libnetplan._NetdefIterator(state, None)))

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
        self.assertSetEqual(set(["eth0", "eth1"]), set(d.id for d in libnetplan._NetdefIterator(state, "ethernets")))


class TestParser(TestBase):
    def test_load_yaml_from_fd_empty(self):
        parser = libnetplan.Parser()
        # We just don't want it to raise an exception
        with tempfile.TemporaryFile() as f:
            parser.load_yaml(f)

    def test_load_yaml_from_fd_bad_yaml(self):
        parser = libnetplan.Parser()
        with tempfile.TemporaryFile() as f:
            f.write(b'invalid: {]')
            f.seek(0, io.SEEK_SET)
            with self.assertRaises(libnetplan.LibNetplanException) as context:
                parser.load_yaml(f)
            self.assertIn('Invalid YAML', str(context.exception))


class TestState(TestBase):
    def test_get_netdef(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')
        netdef = state['eth0']
        self.assertEqual("eth0", netdef.id)

    def test_get_netdef_empty_state(self):
        state = libnetplan.State()
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
        state = libnetplan.State()
        parser = libnetplan.Parser()
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

        with self.assertRaises(libnetplan.LibNetplanException):
            state.import_parser_results(parser)

    def test_dump_yaml_bad_file_perms(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')
        bad_file = os.path.join(self.workdir.name, 'bad.yml')
        open(bad_file, 'a').close()
        os.chmod(bad_file, 0o444)
        with self.assertRaises(libnetplan.LibNetplanException) as context:
            with open(bad_file) as f:
                state.dump_yaml(f)
        self.assertIn('Invalid argument', str(context.exception))

    def test_dump_yaml_empty_state(self):
        state = libnetplan.State()
        with tempfile.TemporaryFile() as f:
            state.dump_yaml(f)
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

        with self.assertRaises(libnetplan.LibNetplanException):
            state.write_yaml_file('target.yml', self.workdir.name)

    def test_update_yaml_hierarchy_no_confdir(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')
        shutil.rmtree(self.confdir)
        with self.assertRaises(libnetplan.LibNetplanException) as context:
            state.update_yaml_hierarchy("bogus", self.workdir.name)
        self.assertIn('No such file or directory', str(context.exception))

    def test_write_yaml_file_remove_directory(self):
        state = libnetplan.State()
        os.makedirs(self.confdir)
        with tempfile.TemporaryDirectory(dir=self.confdir) as tmpdir:
            hint = os.path.basename(tmpdir)
            with self.assertRaises(libnetplan.LibNetplanException):
                state.write_yaml_file(hint, self.workdir.name)

    def test_write_yaml_file_file_no_confdir(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''', filename='test.yml')
        shutil.rmtree(self.confdir)
        with self.assertRaises(libnetplan.LibNetplanException) as context:
            state.write_yaml_file('test.yml', self.workdir.name)
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

        # libnetplan.State __getitem__ doesn't cache the netdefs,
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
        state = libnetplan.State()
        parser = libnetplan.Parser()

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
        self.assertFalse(state['witness'].has_match)
        self.assertTrue(state['name-match'].has_match)
        self.assertTrue(state['name-match'].match_interface(itf_name="eth42"))
        self.assertFalse(state['name-match'].match_interface(itf_name="eth32"))
        self.assertTrue(state['driver-match'].match_interface(itf_driver="e1000"))
        self.assertFalse(state['name-match'].match_interface(itf_driver="ixgbe"))
        self.assertFalse(state['driver-match'].match_interface(itf_name="eth42"))
        self.assertTrue(state['mac-match'].match_interface(itf_mac="11:22:33:AA:BB:FF"))
        self.assertFalse(state['mac-match'].match_interface(itf_mac="11:22:33:AA:BB:CC"))

    def test_match_without_match_block(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')

        netdef = state['eth0']
        self.assertTrue(netdef.match_interface('eth0'))
        self.assertFalse(netdef.match_interface('eth000'))

    def test_vlan_props_without_vlan(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false''')

        self.assertIsNone(state['eth0'].vlan_id)
        self.assertIsNone(state['eth0'].vlan_link)

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

        self.assertFalse(state['eth0'].is_trivial_compound_itf)
        self.assertTrue(state['br0'].is_trivial_compound_itf)
        self.assertFalse(state['br1'].is_trivial_compound_itf)

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

        self.assertEqual(state['eth0'].bridge_link.id, "br0")

    def test_interface_pointer_to_bridge_is_none(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
      ''')

        self.assertIsNone(state['eth0'].bridge_link)

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

        self.assertEqual(state['eth0'].bond_link.id, "bond0")

    def test_interface_pointer_to_bond_is_none(self):
        state = state_from_yaml(self.confdir, '''network:
  ethernets:
    eth0:
      dhcp4: false
      ''')

        self.assertIsNone(state['eth0'].bond_link)

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

        self.assertEqual(state['patch0-1'].peer_link.id, "patch1-0")
        self.assertEqual(state['patch1-0'].peer_link.id, "patch0-1")


class TestFreeFunctions(TestBase):
    def test_create_yaml_patch_bad_syntax(self):
        with tempfile.TemporaryFile() as patchfile:
            with self.assertRaises(libnetplan.LibNetplanException) as context:
                libnetplan.create_yaml_patch(['network'], '{invalid_yaml]', patchfile)
            self.assertIn('Error parsing YAML', str(context.exception))
            patchfile.seek(0, io.SEEK_END)
            self.assertEqual(patchfile.tell(), 0)

    def test_dump_yaml_subtree_bad_file_perms(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w") as f, tempfile.TemporaryFile() as output:
            with self.assertRaises(libnetplan.LibNetplanException) as context:
                libnetplan.dump_yaml_subtree('network', f, output)
        self.assertIn('Invalid argument', str(context.exception))

    def test_dump_yaml_subtree_bad_yaml_outside(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('{garbage)')
            f.flush()
            with self.assertRaises(libnetplan.LibNetplanException) as context:
                libnetplan.dump_yaml_subtree('network', f, output)
        self.assertIn('Error parsing YAML', str(context.exception))

    def test_dump_yaml_subtree_bad_yaml_inside(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''network:
  ethernets:
    {garbage)''')
            f.flush()

            with self.assertRaises(libnetplan.LibNetplanException) as context:
                libnetplan.dump_yaml_subtree('network', f, output)
        self.assertIn('Error parsing YAML', str(context.exception))

    def test_dump_yaml_subtree_bad_type(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''[]''')
            f.flush()

            with self.assertRaises(libnetplan.LibNetplanException) as context:
                libnetplan.dump_yaml_subtree('network', f, output)
        self.assertIn('Unexpected YAML structure found', str(context.exception))

    def test_dump_yaml_subtree_bad_yaml_ignored(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''network:
  ethernets: null
ignored:
  - [}''')
            f.flush()
            with self.assertRaises(libnetplan.LibNetplanException) as context:
                libnetplan.dump_yaml_subtree('network', f, output)
        self.assertIn('Error parsing YAML', str(context.exception))

    def test_dump_yaml_subtree_discard_tail(self):
        input_file = os.path.join(self.workdir.name, 'input.yaml')
        with open(input_file, "w+") as f, tempfile.TemporaryFile() as output:
            f.write('''network:
  ethernets: {}
tail:
  - []''')
            f.flush()
            libnetplan.dump_yaml_subtree('network\tethernets', f, output)
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
            libnetplan.dump_yaml_subtree('network\tethernets\teth0', f, output)
            output.seek(0)
            self.assertEqual(yaml.safe_load(output), None)
