#!/usr/bin/python3
# Blackbox tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2016 Canonical, Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
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
import subprocess
import unittest
import tempfile
import shutil

import yaml

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe_cli = [os.path.join(rootdir, 'src', 'netplan.script')]
if shutil.which('python3-coverage'):
    exe_cli = ['python3-coverage', 'run', '--append', '--'] + exe_cli

# Make sure we can import our development netplan.
os.environ.update({'PYTHONPATH': '.'})


class TestArgs(unittest.TestCase):
    '''Generic argument parsing tests'''

    def test_global_help(self):
        out = subprocess.check_output(exe_cli + ['--help'])
        self.assertIn(b'Available commands', out)
        self.assertIn(b'generate', out)
        self.assertIn(b'--debug', out)

    def test_command_help(self):
        out = subprocess.check_output(exe_cli + ['generate', '--help'])
        self.assertIn(b'--root-dir', out)

    def test_no_command(self):
        os.environ['NETPLAN_GENERATE_PATH'] = os.path.join(rootdir, 'generate')
        p = subprocess.Popen(exe_cli, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        self.assertEqual(out, b'')
        self.assertIn(b'need to specify a command', err)
        self.assertNotEqual(p.returncode, 0)


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()

    def test_no_config(self):
        out = subprocess.check_output(exe_cli + ['generate', '--root-dir', self.workdir.name])
        self.assertEqual(out, b'')
        self.assertEqual(os.listdir(self.workdir.name), [])

    def test_with_config(self):
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        with open(os.path.join(c, 'a.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    enlol: {dhcp4: yes}''')
        out = subprocess.check_output(exe_cli + ['generate', '--root-dir', self.workdir.name])
        self.assertEqual(out, b'')
        self.assertEqual(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd', 'network')),
                         ['10-netplan-enlol.network'])

    def test_mapping_with_config(self):
        os.environ['NETPLAN_GENERATE_PATH'] = os.path.join(rootdir, 'generate')
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        with open(os.path.join(c, 'a.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    enlol: {dhcp4: yes}''')
        out = subprocess.check_output(exe_cli +
                                      ['generate', '--root-dir', self.workdir.name, '--mapping', 'enlol'])
        self.assertNotEqual(b'', out)
        self.assertIn('enlol', out.decode('utf-8'))


class TestIfupdownMigrate(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.ifaces_path = os.path.join(self.workdir.name, 'etc/network/interfaces')
        self.converted_path = os.path.join(self.workdir.name, 'etc/netplan/10-ifupdown.yaml')

    def test_system(self):
        rc = subprocess.call(exe_cli + ['ifupdown-migrate', '--dry-run'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # may succeed or fail, but should not crash
        self.assertIn(rc, [0, 2])

    def do_test(self, iface_file, expect_success=True, dry_run=True, dropins=None):
        if iface_file is not None:
            os.makedirs(os.path.dirname(self.ifaces_path))
            with open(self.ifaces_path, 'w') as f:
                f.write(iface_file)
        if dropins:
            for fname, contents in dropins.items():
                path = os.path.join(os.path.dirname(self.ifaces_path), fname)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as f:
                    f.write(contents)

        argv = exe_cli + ['--debug', 'ifupdown-migrate', '--root-dir', self.workdir.name]
        if dry_run:
            argv.append('--dry-run')
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        if expect_success:
            self.assertEqual(p.returncode, 0, err.decode())
        else:
            self.assertIn(p.returncode, [2, 3], err.decode())
        return (out, err)

    #
    # configs which can be converted
    #

    def test_no_config(self):
        (out, err) = self.do_test(None)
        self.assertEqual(out, b'')
        self.assertEqual(os.listdir(self.workdir.name), [])

    def test_only_empty_include(self):
        out = self.do_test('''# default interfaces file
source-directory /etc/network/interfaces.d''')[0]
        self.assertFalse(os.path.exists(self.converted_path))
        self.assertEqual(out, b'')

    def test_loopback_only(self):
        (out, err) = self.do_test('auto lo\n#ignore me\niface lo inet loopback')
        self.assertEqual(out, b'')
        self.assertIn(b'nothing to migrate\n', err)

    def test_dhcp4(self):
        out = self.do_test('auto en1\niface en1 inet dhcp')[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True}}}}, out.decode())

    def test_dhcp6(self):
        out = self.do_test('auto en1\niface en1 inet6 dhcp')[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp6': True}}}}, out.decode())

    def test_dhcp4_and_6(self):
        out = self.do_test('auto lo\niface lo inet loopback\n\n'
                           'auto en1\niface en1 inet dhcp\niface en1 inet6 dhcp')[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True, 'dhcp6': True}}}}, out.decode())

    def test_includedir_rel(self):
        out = self.do_test('iface lo inet loopback\nauto lo\nsource-directory interfaces.d',
                           dropins={'interfaces.d/std': 'auto en1\niface en1 inet dhcp',
                                    'interfaces.d/std.bak': 'some_bogus dontreadme'})[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True}}}}, out.decode())

    def test_includedir_abs(self):
        out = self.do_test('iface lo inet loopback\nauto lo\nsource-directory /etc/network/defs/my',
                           dropins={'defs/my/std': 'auto en1\niface en1 inet dhcp',
                                    'defs/my/std.bak': 'some_bogus dontreadme'})[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True}}}}, out.decode())

    def test_include_rel(self):
        out = self.do_test('iface lo inet loopback\nauto lo\nsource interfaces.d/*.cfg',
                           dropins={'interfaces.d/std.cfg': 'auto en1\niface en1 inet dhcp',
                                    'interfaces.d/std.cfgold': 'some_bogus dontreadme'})[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True}}}}, out.decode())

    def test_include_abs(self):
        out = self.do_test('iface lo inet loopback\nauto lo\nsource /etc/network/*.cfg',
                           dropins={'std.cfg': 'auto en1\niface en1 inet dhcp',
                                    'std.cfgold': 'some_bogus dontreadme'})[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True}}}}, out.decode())

    def test_allow(self):
        out = self.do_test('allow-hotplug en1\niface en1 inet dhcp\n'
                           'allow-auto en2\niface en2 inet dhcp')[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True},
                          'en2': {'dhcp4': True}}}}, out.decode())

    def test_no_scripts(self):
        out = self.do_test('auto en1\niface en1 inet dhcp\nno-scripts en1')[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True}}}}, out.decode())

    def test_write_file_noconfig(self):
        (out, err) = self.do_test('auto lo\niface lo inet loopback', dry_run=False)
        self.assertFalse(os.path.exists(self.converted_path))
        # should disable original ifupdown config
        self.assertFalse(os.path.exists(self.ifaces_path))
        self.assertTrue(os.path.exists(self.ifaces_path + '.netplan-converted'))

    def test_write_file_haveconfig(self):
        (out, err) = self.do_test('auto en1\niface en1 inet dhcp', dry_run=False)
        with open(self.converted_path) as f:
            config = yaml.load(f)
        self.assertEqual(config, {'network': {
            'version': 2,
            'ethernets': {'en1': {'dhcp4': True}}}})

        # should disable original ifupdown config
        self.assertFalse(os.path.exists(self.ifaces_path))
        self.assertTrue(os.path.exists(self.ifaces_path + '.netplan-converted'))

    def test_write_file_prev_run(self):
        os.makedirs(os.path.dirname(self.converted_path))
        with open(self.converted_path, 'w') as f:
            f.write('canary')
        (out, err) = self.do_test('auto en1\niface en1 inet dhcp', dry_run=False, expect_success=False)
        with open(self.converted_path) as f:
            self.assertEqual(f.read(), 'canary')

        # should not disable original ifupdown config
        self.assertTrue(os.path.exists(self.ifaces_path))

    #
    # configs which are not supported
    #

    def test_noauto(self):
        (out, err) = self.do_test('iface en1 inet dhcp', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'non-automatic interfaces are not supported', err)

    def test_dhcp_options(self):
        (out, err) = self.do_test('auto en1\niface en1 inet dhcp\nup myhook', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'options are not supported for dhcp method', err)

    def test_static(self):
        (out, err) = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'method static is not supported', err)

    def test_mapping(self):
        (out, err) = self.do_test('mapping en*\n  script /some/path/mapscheme\nmap HOME en1-home\n\n'
                                  'auto map1\niface map1 inet dhcp', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'mapping stanza is not supported', err)

    def test_unknown_allow(self):
        (out, err) = self.do_test('allow-foo en1\niface en1 inet dhcp', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'Unknown stanza type allow-foo', err)

    def test_unknown_stanza(self):
        (out, err) = self.do_test('foo en1\niface en1 inet dhcp', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'Unknown stanza type foo', err)

    def test_unknown_family(self):
        (out, err) = self.do_test('auto en1\niface en1 inet7 dhcp', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'Unknown address family inet7', err)

    def test_unknown_method(self):
        (out, err) = self.do_test('auto en1\niface en1 inet mangle', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'Unsupported method mangle', err)

    def test_too_few_fields(self):
        (out, err) = self.do_test('auto en1\niface en1 inet', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'Expected 3 fields for stanza type iface but got 2', err)

    def test_too_many_fields(self):
        (out, err) = self.do_test('auto en1\niface en1 inet dhcp foo', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'Expected 3 fields for stanza type iface but got 4', err)

    def test_write_file_notsupported(self):
        (out, err) = self.do_test('iface en1 inet dhcp', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'non-automatic interfaces are not supported', err)
        # should keep original ifupdown config
        self.assertTrue(os.path.exists(self.ifaces_path))


class TestIp(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()

    def test_valid_subcommand(self):
        p = subprocess.Popen(exe_cli + ['ip'], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        self.assertEqual(out, b'')
        self.assertIn(b'Available command', err)
        self.assertNotEqual(p.returncode, 0)

    def test_ip_leases_networkd(self):
        os.environ['NETPLAN_GENERATE_PATH'] = os.path.join(rootdir, 'generate')
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        with open(os.path.join(c, 'a.yaml'), 'w') as f:
            # match against loopback so as to succesfully get a predictable
            # ifindex
            f.write('''network:
  version: 2
  renderer: networkd
  ethernets:
    enlol:
      match:
        name: lo
      dhcp4: yes
''')
        fake_netif_lease_dir = os.path.join(self.workdir.name,
                                            'run', 'systemd', 'netif', 'leases')
        os.makedirs(fake_netif_lease_dir)
        with open(os.path.join(fake_netif_lease_dir, '1'), 'w') as f:
            f.write('''THIS IS A FAKE NETIF LEASE FOR LO''')
        out = subprocess.check_output(exe_cli +
                                      ['ip', 'leases',
                                       '--root-dir', self.workdir.name, 'lo'])
        self.assertNotEqual(out, b'')
        self.assertIn('FAKE NETIF', out.decode('utf-8'))

    def test_ip_leases_nm(self):
        unittest.skip("Cannot be tested offline due to calls required to nmcli."
                      "This is tested in integration tests.")

    def test_ip_leases_no_networkd_lease(self):
        os.environ['NETPLAN_GENERATE_PATH'] = os.path.join(rootdir, 'generate')
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        with open(os.path.join(c, 'a.yaml'), 'w') as f:
            # match against loopback so as to succesfully get a predictable
            # ifindex
            f.write('''network:
  version: 2
  ethernets:
    enlol:
      match:
        name: lo
      dhcp4: yes
''')
        p = subprocess.Popen(exe_cli +
                             ['ip', 'leases', '--root-dir', self.workdir.name, 'enlol'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        self.assertEqual(out, b'')
        self.assertIn(b'No lease found', err)
        self.assertNotEqual(p.returncode, 0)

    def test_ip_leases_no_nm_lease(self):
        os.environ['NETPLAN_GENERATE_PATH'] = os.path.join(rootdir, 'generate')
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        with open(os.path.join(c, 'a.yaml'), 'w') as f:
            # match against loopback so as to succesfully get a predictable
            # ifindex
            f.write('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    enlol:
      match:
        name: lo
      dhcp4: yes
''')
        p = subprocess.Popen(exe_cli +
                             ['ip', 'leases', '--root-dir', self.workdir.name, 'enlol'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        self.assertEqual(out, b'')
        self.assertIn(b'No lease found', err)
        self.assertNotEqual(p.returncode, 0)


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
