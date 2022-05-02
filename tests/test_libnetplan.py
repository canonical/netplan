#!/usr/bin/python3
# Blackbox tests of certain libnetplan functions. These are run during
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


class TestFreeFunctions(TestBase):
    def setUp(self):
        super().setUp()
        os.makedirs(self.confdir)

    def tearDown(self):
        shutil.rmtree(self.workdir.name)
        super().tearDown()

    def test_netplan_get_filename_by_id(self):
        file_a = os.path.join(self.workdir.name, 'etc/netplan/a.yaml')
        file_b = os.path.join(self.workdir.name, 'etc/netplan/b.yaml')
        with open(file_a, 'w') as f:
            f.write('network:\n  ethernets:\n    id_a:\n      dhcp4: true')
        with open(file_b, 'w') as f:
            f.write('network:\n  ethernets:\n    id_b:\n      dhcp4: true\n    id_a:\n      dhcp4: true')
        # netdef:b can only be found in b.yaml
        basename = os.path.basename(libnetplan.netplan_get_filename_by_id('id_b', self.workdir.name))
        self.assertEqual(basename, 'b.yaml')
        # netdef:a is defined in a.yaml, overriden by b.yaml
        basename = os.path.basename(libnetplan.netplan_get_filename_by_id('id_a', self.workdir.name))
        self.assertEqual(basename, 'b.yaml')

    def test_netplan_get_filename_by_id_no_files(self):
        self.assertIsNone(libnetplan.netplan_get_filename_by_id('some-id', self.workdir.name))

    def test_netplan_get_filename_by_id_invalid(self):
        file = os.path.join(self.workdir.name, 'etc/netplan/a.yaml')
        with open(file, 'w') as f:
            f.write('''network:
  tunnels:
    id_a:
      mode: sit
      local: 0.0.0.0
      remote: 0.0.0.0
      key: 0.0.0.0''')
        self.assertIsNone(libnetplan.netplan_get_filename_by_id('some-id', self.workdir.name))

    def test_netplan_get_ids_for_devtype(self):
        path = os.path.join(self.workdir.name, 'etc/netplan/a.yaml')
        with open(path, 'w') as f:
            f.write('''network:
  ethernets:
    id_b:
      dhcp4: true
    id_a:
      dhcp4: true
  vlans:
    en-intra:
      id: 3
      link: id_b
      dhcp4: true''')
        self.assertSetEqual(
                set(libnetplan.netplan_get_ids_for_devtype("ethernets", self.workdir.name)),
                set(["id_a", "id_b"]))

    def test_netplan_get_ids_for_devtype_no_dev(self):
        path = os.path.join(self.workdir.name, 'etc/netplan/a.yaml')
        with open(path, 'w') as f:
            f.write('''network:
  ethernets:
    id_b:
      dhcp4: true''')
        self.assertSetEqual(
                set(libnetplan.netplan_get_ids_for_devtype("tunnels", self.workdir.name)),
                set([]))

    def test_NetdefIterator_with_clear_netplan(self):
        state = libnetplan.State()
        self.assertSequenceEqual(list(libnetplan._NetdefIterator(state, "ethernets")), [])

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
