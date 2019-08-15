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

    def test_with_empty_config(self):
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        open(os.path.join(c, 'a.yaml'), 'w').close()
        with open(os.path.join(c, 'b.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    enlol: {dhcp4: yes}''')
        out = subprocess.check_output(exe_cli + ['generate', '--root-dir', self.workdir.name], stderr=subprocess.STDOUT)
        self.assertEqual(out, b'')
        self.assertEqual(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd', 'network')),
                         ['10-netplan-enlol.network'])

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

    def test_mapping_for_unknown_iface(self):
        os.environ['NETPLAN_GENERATE_PATH'] = os.path.join(rootdir, 'generate')
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        with open(os.path.join(c, 'a.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    enlol: {dhcp4: yes}''')
        p = subprocess.Popen(exe_cli +
                             ['generate', '--root-dir', self.workdir.name, '--mapping', 'nonexistent'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn(b'nonexistent', out)

    def test_mapping_for_interface(self):
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

    def test_mapping_for_renamed_iface(self):
        os.environ['NETPLAN_GENERATE_PATH'] = os.path.join(rootdir, 'generate')
        c = os.path.join(self.workdir.name, 'etc', 'netplan')
        os.makedirs(c)
        with open(os.path.join(c, 'a.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    myif:
      match:
        name: enlol
      set-name: renamediface
      dhcp4: yes
''')
        out = subprocess.check_output(exe_cli +
                                      ['generate', '--root-dir', self.workdir.name, '--mapping', 'renamediface'])
        self.assertNotEqual(b'', out)
        self.assertIn('renamediface', out.decode('utf-8'))


class TestIfupdownMigrate(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.ifaces_path = os.path.join(self.workdir.name, 'etc/network/interfaces')
        self.converted_path = os.path.join(self.workdir.name, 'etc/netplan/10-ifupdown.yaml')

    def test_system(self):
        os.environ.update({"ENABLE_TEST_COMMANDS": "1"})
        rc = subprocess.call(exe_cli + ['migrate', '--dry-run'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # may succeed or fail, but should not crash
        self.assertIn(rc, [0, 2])

    def do_test(self, iface_file, expect_success=True, dry_run=True, dropins=None):
        os.environ.update({"ENABLE_TEST_COMMANDS": "1"})
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

        argv = exe_cli + ['--debug', 'migrate', '--root-dir', self.workdir.name]
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
    # static
    #

    def test_static_ipv4_prefix(self):
        out = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/8', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["1.2.3.4/8"]}}}}, out.decode())

    def test_static_ipv4_netmask(self):
        out = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4\nnetmask 255.0.0.0', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["1.2.3.4/8"]}}}}, out.decode())

    def test_static_ipv4_no_address(self):
        out, err = self.do_test('auto en1\niface en1 inet static\nnetmask 1.2.3.4', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'no address supplied', err)

    def test_static_ipv4_no_network(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'does not specify prefix length, and netmask not specified', err)

    def test_static_ipv4_invalid_addr(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.400/8', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'error parsing "1.2.3.400" as an IPv4 address', err)

    def test_static_ipv4_invalid_netmask(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4\nnetmask 123.123.123.0', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'error parsing "1.2.3.4/123.123.123.0" as an IPv4 network', err)

    def test_static_ipv4_invalid_prefixlen(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/42', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'error parsing "1.2.3.4/42" as an IPv4 network', err)

    def test_static_ipv4_unsupported_option(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/24\nmetric 1280', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'unsupported inet option "metric"', err)

    def test_static_ipv4_unknown_option(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/24\nxyzzy 1280', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'unknown inet option "xyzzy"', err)

    def test_static_ipv6_prefix(self):
        out = self.do_test('auto en1\niface en1 inet6 static\naddress fc00:0123:4567:89ab:cdef::1234/64', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["fc00:123:4567:89ab:cdef::1234/64"]}}}}, out.decode())

    def test_static_ipv6_netmask(self):
        out = self.do_test('auto en1\niface en1 inet6 static\n'
                           'address fc00:0123:4567:89ab:cdef::1234\nnetmask 64', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["fc00:123:4567:89ab:cdef::1234/64"]}}}}, out.decode())

    def test_static_ipv6_no_address(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\nnetmask 64', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'no address supplied', err)

    def test_static_ipv6_no_network(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\n'
                                'address fc00:0123:4567:89ab:cdef::1234', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'does not specify prefix length, and netmask not specified', err)

    def test_static_ipv6_invalid_addr(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\n'
                                'address fc00:0123:4567:89ab:cdef::12345/64', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'error parsing "fc00:0123:4567:89ab:cdef::12345" as an IPv6 address', err)

    def test_static_ipv6_invalid_netmask(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\n'
                                'address fc00:0123:4567:89ab:cdef::1234\nnetmask 129', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'error parsing "fc00:0123:4567:89ab:cdef::1234/129" as an IPv6 network', err)

    def test_static_ipv6_invalid_prefixlen(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\n'
                                'address fc00:0123:4567:89ab:cdef::1234/129', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'error parsing "fc00:0123:4567:89ab:cdef::1234/129" as an IPv6 network', err)

    def test_static_ipv6_unsupported_option(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\n'
                                'address fc00:0123:4567:89ab:cdef::1234/64\nmetric 1280', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'unsupported inet6 option "metric"', err)

    def test_static_ipv6_unknown_option(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\n'
                                'address fc00:0123:4567:89ab:cdef::1234/64\nxyzzy 1280', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'unknown inet6 option "xyzzy"', err)

    def test_static_ipv6_accept_ra_0(self):
        out = self.do_test('auto en1\niface en1 inet6 static\n'
                           'address fc00:0123:4567:89ab:cdef::1234/64\naccept_ra 0', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["fc00:123:4567:89ab:cdef::1234/64"],
                                  'accept_ra': False}}}}, out.decode())

    def test_static_ipv6_accept_ra_1(self):
        out = self.do_test('auto en1\niface en1 inet6 static\n'
                           'address fc00:0123:4567:89ab:cdef::1234/64\naccept_ra 1', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["fc00:123:4567:89ab:cdef::1234/64"],
                                  'accept_ra': True}}}}, out.decode())

    def test_static_ipv6_accept_ra_2(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\n'
                                'address fc00:0123:4567:89ab:cdef::1234/64\naccept_ra 2', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'netplan does not support accept_ra=2', err)

    def test_static_ipv6_accept_ra_unexpected(self):
        out, err = self.do_test('auto en1\niface en1 inet6 static\n'
                                'address fc00:0123:4567:89ab:cdef::1234/64\naccept_ra fish', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'unexpected accept_ra value "fish"', err)

    def test_static_gateway(self):
        out = self.do_test("""auto en1
iface en1 inet static
  address 1.2.3.4
  netmask 255.0.0.0
  gateway 1.1.1.1
iface en1 inet6 static
  address fc00:0123:4567:89ab:cdef::1234/64
  gateway fc00:0123:4567:89ab::1""", dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1':
                          {'addresses': ["1.2.3.4/8", "fc00:123:4567:89ab:cdef::1234/64"],
                           'gateway4': "1.1.1.1",
                           'gateway6': "fc00:0123:4567:89ab::1"}}}}, out.decode())

    def test_static_dns(self):
        out = self.do_test("""auto en1
iface en1 inet static
  address 1.2.3.4
  netmask 255.0.0.0
  dns-nameservers 1.2.1.1  1.2.2.1
  dns-search weird.network
iface en1 inet6 static
  address fc00:0123:4567:89ab:cdef::1234/64
  dns-nameservers fc00:0123:4567:89ab:1::1  fc00:0123:4567:89ab:2::1""", dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1':
                          {'addresses': ["1.2.3.4/8", "fc00:123:4567:89ab:cdef::1234/64"],
                           'nameservers': {
                               'search': ['weird.network'],
                               'addresses': ['1.2.1.1', '1.2.2.1',
                                             'fc00:0123:4567:89ab:1::1', 'fc00:0123:4567:89ab:2::1']
                           }}}}}, out.decode())

    def test_static_dns2(self):
        out = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/8\ndns-search foo  foo.bar', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["1.2.3.4/8"],
                                  'nameservers': {
                                      'search': ['foo', 'foo.bar']
                                  }}}}}, out.decode())

    def test_static_mtu(self):
        out = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/8\nmtu 1280', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["1.2.3.4/8"],
                                  'mtu': 1280}}}}, out.decode())

    def test_static_invalid_mtu(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/8\nmtu fish', expect_success=False)
        self.assertEqual(b'', out)
        self.assertIn(b'cannot parse "fish" as an MTU', err)

    def test_static_two_different_mtus(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/8\nmtu 1280\n'
                                'iface en1 inet6 static\naddress 2001::1/64\nmtu 9000', expect_success=False)
        self.assertEqual(b'', out)
        self.assertIn(b'tried to set MTU=9000, but already have MTU=1280', err)

    def test_static_hwaddress(self):
        out = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/8\nhwaddress 52:54:00:6b:3c:59', dry_run=True)[0]
        self.assertEqual(yaml.load(out), {'network': {
            'version': 2,
            'ethernets': {'en1': {'addresses': ["1.2.3.4/8"],
                                  'macaddress': '52:54:00:6b:3c:59'}}}}, out.decode())

    def test_static_two_different_macs(self):
        out, err = self.do_test('auto en1\niface en1 inet static\naddress 1.2.3.4/8\nhwaddress 52:54:00:6b:3c:59\n'
                                'iface en1 inet6 static\naddress 2001::1/64\nhwaddress 52:54:00:6b:3c:58', expect_success=False)
        self.assertEqual(b'', out)
        self.assertIn(b'tried to set MAC 52:54:00:6b:3c:58, but already have MAC 52:54:00:6b:3c:59', err)

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
        self.assertIn(b'option(s) up are not supported for dhcp method', err)

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

    def test_write_file_unsupported(self):
        (out, err) = self.do_test('iface en1 inet dhcp', expect_success=False)
        self.assertEqual(out, b'')
        self.assertIn(b'non-automatic interfaces are not supported', err)
        # should keep original ifupdown config
        self.assertTrue(os.path.exists(self.ifaces_path))


class TestInfo(unittest.TestCase):
    '''Test netplan info'''

    def test_info_defaults(self):
        """
        Check that 'netplan info' outputs at all, should include website URL
        """
        out = subprocess.check_output(exe_cli + ['info'])
        self.assertIn(b'features:', out)

    def test_info_yaml(self):
        """
        Verify that 'netplan info --yaml' output looks a bit like YAML
        """
        out = subprocess.check_output(exe_cli + ['info', '--yaml'])
        self.assertIn(b'features:', out)

    def test_info_json(self):
        """
        Verify that 'netplan info --json' output looks a bit like JSON
        """
        out = subprocess.check_output(exe_cli + ['info', '--json'])
        self.assertIn(b'"features": [', out)


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
            # match against loopback so as to successfully get a predictable
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
            # match against loopback so as to successfully get a predictable
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
            # match against loopback so as to successfully get a predictable
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
