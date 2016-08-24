#!/usr/bin/python3
# Blackbox tests of netplan generate that verify that the generated
# configuration files look as expected. These are run during "make check" and
# don't touch the system configuration at all.
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
import stat
import tempfile
import subprocess
import unittest

exe_generate = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'generate')

# make sure we fail on criticals
os.environ['G_DEBUG'] = 'fatal-criticals'


class TestBase(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.confdir = os.path.join(self.workdir.name, 'etc', 'netplan')
        self.nm_enable_all_conf = os.path.join(
            self.workdir.name, 'run', 'NetworkManager', 'conf.d', '10-globally-managed-devices.conf')

    def generate(self, yaml, expect_fail=False, extra_args=[], confs=None):
        '''Call generate with given YAML string as configuration

        Return stderr output.
        '''
        conf = os.path.join(self.confdir, 'a.yaml')
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        if yaml is not None:
            with open(conf, 'w') as f:
                f.write(yaml)
        if confs:
            for f, contents in confs.items():
                with open(os.path.join(self.confdir, f + '.yaml'), 'w') as f:
                    f.write(contents)

        argv = [exe_generate, '--root-dir', self.workdir.name] + extra_args
        if 'TEST_SHELL' in os.environ:
            print('Test is about to run:\n%s' % ' '.join(argv))
            subprocess.call(['bash', '-i'], cwd=self.workdir.name)

        p = subprocess.Popen(argv, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
        (out, err) = p.communicate()
        if expect_fail:
            self.assertGreater(p.returncode, 0)
        else:
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(out, '')
        return err

    def assert_networkd(self, file_contents_map):
        networkd_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'network')
        if not file_contents_map:
            self.assertFalse(os.path.exists(networkd_dir))
            return

        self.assertEqual(set(os.listdir(self.workdir.name)), {'etc', 'run'})
        self.assertEqual(set(os.listdir(networkd_dir)),
                         {'10-netplan-' + f for f in file_contents_map})
        for fname, contents in file_contents_map.items():
            with open(os.path.join(networkd_dir, '10-netplan-' + fname)) as f:
                self.assertEqual(f.read(), contents)

    def assert_nm(self, connections_map=None, conf=None):
        # check config
        conf_path = os.path.join(self.workdir.name, 'run', 'NetworkManager', 'conf.d', 'netplan.conf')
        if conf:
            with open(conf_path) as f:
                self.assertEqual(f.read(), conf)
        else:
            if os.path.exists(conf_path):
                with open(conf_path) as f:
                    self.fail('unexpected %s:\n%s' % (conf_path, f.read()))

        # check connections
        con_dir = os.path.join(self.workdir.name, 'run', 'NetworkManager', 'system-connections')
        if connections_map:
            self.assertEqual(set(os.listdir(con_dir)),
                             set(['netplan-' + n for n in connections_map]))
            for fname, contents in connections_map.items():
                with open(os.path.join(con_dir, 'netplan-' + fname)) as f:
                    self.assertEqual(f.read(), contents)
                    # NM connection files might contain secrets
                    self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        else:
            if os.path.exists(con_dir):
                self.assertEqual(os.listdir(con_dir), [])

    def assert_udev(self, contents):
        rule_path = os.path.join(self.workdir.name, 'run/udev/rules.d/90-netplan.rules')
        if contents is None:
            self.assertFalse(os.path.exists(rule_path))
            return
        with open(rule_path) as f:
            self.assertEqual(f.read(), contents)


class TestConfigArgs(TestBase):
    '''Config file argument handling'''

    def test_no_files(self):
        subprocess.check_call([exe_generate, '--root-dir', self.workdir.name])
        self.assertEqual(os.listdir(self.workdir.name), [])
        self.assert_udev(None)

    def test_no_configs(self):
        self.generate('network:\n  version: 2')
        # should not write any files
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])
        self.assert_udev(None)

    def test_empty_config(self):
        self.generate('')
        # should not write any files
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])
        self.assert_udev(None)

    def test_file_args(self):
        conf = os.path.join(self.workdir.name, 'config')
        with open(conf, 'w') as f:
            f.write('network: {}')
        # when specifying custom files, it should ignore the global config
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''', extra_args=[conf])
        self.assertEqual(set(os.listdir(self.workdir.name)), {'config', 'etc'})

    def test_file_args_notfound(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''', expect_fail=True, extra_args=['/non/existing/config'])
        self.assertEqual(err, 'Cannot open /non/existing/config: No such file or directory\n')
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])

    def test_help(self):
        conf = os.path.join(self.workdir.name, 'etc', 'netplan', 'a.yaml')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''')

        p = subprocess.Popen([exe_generate, '--root-dir', self.workdir.name, '--help'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        (out, err) = p.communicate()
        self.assertEqual(err, '')
        self.assertEqual(p.returncode, 0)
        self.assertIn('Usage:', out)
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])

    def test_unknown_cli_args(self):
        p = subprocess.Popen([exe_generate, '--foo'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        (out, err) = p.communicate()
        self.assertIn('nknown option --foo', err)
        self.assertNotEqual(p.returncode, 0)

    def test_output_mkdir_error(self):
        conf = os.path.join(self.workdir.name, 'config')
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''')
        err = self.generate('', extra_args=['--root-dir', '/proc/foo', conf], expect_fail=True)
        self.assertIn('cannot create directory /proc/foo/run/systemd/network', err)

    def test_systemd_generator(self):
        conf = os.path.join(self.confdir, 'a.yaml')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''')
        outdir = os.path.join(self.workdir.name, 'out')
        os.mkdir(outdir)

        generator = os.path.join(self.workdir.name, 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        subprocess.check_call([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir])
        self.assertEqual(set(os.listdir(outdir)),
                         {'netplan.stamp', 'multi-user.target.wants', 'network-online.target.wants'})
        n = os.path.join(self.workdir.name, 'run', 'systemd', 'network', '10-netplan-eth0.network')
        self.assertTrue(os.path.exists(n))
        os.unlink(n)

        # should auto-enable networkd and -wait-online
        self.assertTrue(os.path.islink(os.path.join(
            outdir, 'multi-user.target.wants', 'systemd-networkd.service')))
        self.assertTrue(os.path.islink(os.path.join(
            outdir, 'network-online.target.wants', 'systemd-networkd-wait-online.service')))

        # should be a no-op the second time while the stamp exists
        out = subprocess.check_output([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir],
                                      stderr=subprocess.STDOUT)
        self.assertFalse(os.path.exists(n))
        self.assertIn(b'netplan generate already ran', out)

        # after removing the stamp it generates again, and not trip over the
        # existing enablement symlink
        os.unlink(os.path.join(outdir, 'netplan.stamp'))
        subprocess.check_output([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir])
        self.assertTrue(os.path.exists(n))

    def test_systemd_generator_noconf(self):
        outdir = os.path.join(self.workdir.name, 'out')
        os.mkdir(outdir)

        generator = os.path.join(self.workdir.name, 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        subprocess.check_call([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir])
        # no enablement symlink here
        self.assertEqual(os.listdir(outdir), ['netplan.stamp'])


class TestNetworkd(TestBase):
    '''networkd output'''

    def test_eth_wol(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      wakeonlan: true
      dhcp4: n''')

        self.assert_networkd({'eth0.link': '[Match]\nOriginalName=eth0\n\n[Link]\nWakeOnLan=magic\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_udev(None)
        # should not allow NM to manage everything
        self.assertFalse(os.path.exists(self.nm_enable_all_conf))

    def test_eth_match_by_driver_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: ixgbe
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nDriver=ixgbe\n\n[Link]\nName=lom1\nWakeOnLan=off\n'})
        # NM cannot match by driver, so blacklisting needs to happen via udev
        self.assert_nm(None, None)
        self.assert_udev('ACTION=="add|change", SUBSYSTEM=="net", ENV{ID_NET_DRIVER}=="ixgbe", ENV{NM_UNMANAGED}="1"\n')

    def test_eth_match_by_mac_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nMACAddress=11:22:33:44:55:66\n\n[Link]\nName=lom1\nWakeOnLan=off\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=mac:11:22:33:44:55:66,''')
        self.assert_udev(None)

    def test_eth_implicit_name_match_dhcp4(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: y''')

        self.assert_networkd({'engreen.network': '[Match]\nName=engreen\n\n[Network]\nDHCP=ipv4\n'})

    def test_eth_match_dhcp4(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: ixgbe
      dhcp4: true''')

        self.assert_networkd({'def1.network': '[Match]\nDriver=ixgbe\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_udev('ACTION=="add|change", SUBSYSTEM=="net", ENV{ID_NET_DRIVER}=="ixgbe", ENV{NM_UNMANAGED}="1"\n')

    def test_eth_match_name(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      dhcp4: true''')

        self.assert_networkd({'def1.network': '[Match]\nName=green\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:green,''')
        self.assert_udev(None)

    def test_eth_match_name_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      set-name: blue
      dhcp4: true''')

        # the .network needs to match on the renamed name
        self.assert_networkd({'def1.link': '[Match]\nOriginalName=green\n\n[Link]\nName=blue\nWakeOnLan=off\n',
                              'def1.network': '[Match]\nName=blue\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:blue,''')

    def test_eth_match_all_names(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match: {name: "*"}
      dhcp4: true''')

        self.assert_networkd({'def1.network': '[Match]\nName=*\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:*,''')
        self.assert_udev(None)

    def test_eth_match_all(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match: {}
      dhcp4: true''')

        self.assert_networkd({'def1.network': '[Match]\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=type:ethernet,''')
        self.assert_udev(None)

    def test_match_multiple(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: en1s*
        macaddress: 00:11:22:33:44:55
      dhcp4: on''')
        self.assert_networkd({'def1.network': '[Match]\nMACAddress=00:11:22:33:44:55\nName=en1s*\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=mac:00:11:22:33:44:55,''')

    def test_eth_global_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: true''')

        self.assert_networkd({'eth0.network': '[Match]\nName=eth0\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_udev(None)
        # should not allow NM to manage everything
        self.assertFalse(os.path.exists(self.nm_enable_all_conf))

    def test_eth_type_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    renderer: networkd
    eth0:
      dhcp4: true''')

        self.assert_networkd({'eth0.network': '[Match]\nName=eth0\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        # should allow NM to manage everything else
        self.assertTrue(os.path.exists(self.nm_enable_all_conf))
        self.assert_udev(None)

    def test_eth_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    renderer: NetworkManager
    eth0:
      renderer: networkd
      dhcp4: true''')

        self.assert_networkd({'eth0.network': '[Match]\nName=eth0\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_udev(None)

    def test_eth_dhcp6(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {dhcp6: true}''')
        self.assert_networkd({'eth0.network': '[Match]\nName=eth0\n\n[Network]\nDHCP=ipv6\n'})

    def test_eth_dhcp4_and_6(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {dhcp4: true, dhcp6: true}''')
        self.assert_networkd({'eth0.network': '[Match]\nName=eth0\n\n[Network]\nDHCP=yes\n'})

    def test_eth_manual_addresses(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
Address=192.168.14.2/24
Address=2001:FFfe::1/64
'''})

    def test_eth_manual_addresses_dhcp(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: yes
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
DHCP=ipv4
Address=192.168.14.2/24
Address=2001:FFfe::1/64
'''})

    def test_wifi(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl1:
      renderer: networkd
      access-points:
        myap: {}''', expect_fail=True)
        self.assertIn('networkd does not support wifi', err)

    def test_bridge_empty(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '[Match]\nName=br0\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:br0,''')
        self.assert_udev(None)

    def test_bridge_type_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    renderer: networkd
    br0:
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '[Match]\nName=br0\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:br0,''')
        self.assert_udev(None)

    def test_bridge_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    renderer: NetworkManager
    br0:
      renderer: networkd
      addresses: [1.2.3.4/12]
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '[Match]\nName=br0\n\n[Network]\nDHCP=ipv4\nAddress=1.2.3.4/12\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:br0,''')
        self.assert_udev(None)

    def test_bridge_components(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bridges:
    br0:
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '[Match]\nName=br0\n\n[Network]\nDHCP=ipv4\n',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})


class TestNetworkManager(TestBase):
    def test_eth_wol(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      wakeonlan: true''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=1
'''})
        # should allow NM to manage everything else
        self.assertTrue(os.path.exists(self.nm_enable_all_conf))
        self.assert_networkd({})
        self.assert_udev(None)

    def test_eth_match_by_driver(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        driver: ixgbe''', expect_fail=True)
        self.assertIn('NetworkManager definitions do not support matching by driver', err)

    def test_eth_match_by_driver_rename(self):
        # in this case udev will rename the device so that NM can use the name
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        driver: ixgbe
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nDriver=ixgbe\n\n[Link]\nName=lom1\nWakeOnLan=off\n'})
        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=lom1

[ethernet]
wake-on-lan=0
'''})
        self.assert_udev(None)

    def test_eth_match_by_mac_rename(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nMACAddress=11:22:33:44:55:66\n\n[Link]\nName=lom1\nWakeOnLan=off\n'})
        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=lom1

[ethernet]
wake-on-lan=0
'''})
        self.assert_udev(None)

    def test_eth_implicit_name_match_dhcp4(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: true''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
'''})
        self.assert_networkd({})

    def test_eth_match_mac_dhcp4(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      dhcp4: true''')

        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mac-address=11:22:33:44:55:66

[ipv4]
method=auto
'''})
        self.assert_networkd({})

    def test_eth_match_name(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        name: green
      dhcp4: true''')

        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=green

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_eth_match_name_rename(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        name: green
      set-name: blue
      dhcp4: true''')

        # NM needs to match on the renamed name
        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=blue

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
'''})
        # ... while udev renames it
        self.assert_networkd({'def1.link': '[Match]\nOriginalName=green\n\n[Link]\nName=blue\nWakeOnLan=off\n'})
        self.assert_udev(None)

    def test_eth_match_name_glob(self):
        err = self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match: {name: "en*"}
      dhcp4: true''', expect_fail=True)
        self.assertIn('def1: NetworkManager definitions do not support name globbing', err)

        self.assert_nm({})
        self.assert_networkd({})

    def test_eth_match_all(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match: {}
      dhcp4: true''')

        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
'''})
        self.assert_networkd({})

    def test_match_multiple(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match:
        name: engreen
        macaddress: 00:11:22:33:44:55
      dhcp4: yes''')
        self.assert_nm({'def1': '''[connection]
id=netplan-def1
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mac-address=00:11:22:33:44:55

[ipv4]
method=auto
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_eth_global_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      dhcp4: true''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_eth_type_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    renderer: NetworkManager
    eth0:
      dhcp4: true''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_eth_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  ethernets:
    renderer: networkd
    eth0:
      renderer: NetworkManager''')

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_global_renderer_only(self):
        self.generate(None, confs={'01-default-nm.yaml': 'network: {version: 2, renderer: NetworkManager}'})
        # should allow NM to manage everything else
        self.assertTrue(os.path.exists(self.nm_enable_all_conf))
        # but not configure anything else
        self.assert_nm(None, None)
        self.assert_networkd({})
        self.assert_udev(None)

    def test_eth_dhcp6(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0: {dhcp6: true}''')
        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv6]
method=auto
'''})

    def test_eth_dhcp4_and_6(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0: {dhcp4: true, dhcp6: true}''')
        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[ipv6]
method=auto
'''})

    def test_eth_manual_addresses(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses:
        - 192.168.14.2/24
        - 172.16.0.4/16
        - 2001:FFfe::1/64''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
address2=172.16.0.4/16

[ipv6]
method=manual
address1=2001:FFfe::1/64
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_eth_manual_addresses_dhcp(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: yes
      addresses:
        - 192.168.14.2/24
        - 2001:FFfe::1/64''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
address1=192.168.14.2/24

[ipv6]
method=manual
address1=2001:FFfe::1/64
'''})

    def test_wifi_default(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s3kr1t"
        workplace:
          password: "c0mpany"
      dhcp4: yes''')

        self.assert_nm({'wl0-Joe%27s%20Home': '''[connection]
id=netplan-wl0-Joe's Home
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[wifi]
ssid=Joe's Home
mode=infrastructure

[wifi-security]
key-mgmt=wpa-psk
psk=s3kr1t
''',
                        'wl0-workplace': '''[connection]
id=netplan-wl0-workplace
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=auto

[wifi]
ssid=workplace
mode=infrastructure

[wifi-security]
key-mgmt=wpa-psk
psk=c0mpany
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_wifi_match_mac(self):
        self.generate('''network:
  version: 2
  wifis:
    all:
      match:
        macaddress: 11:22:33:44:55:66
      access-points:
        workplace: {}''')

        self.assert_nm({'all-workplace': '''[connection]
id=netplan-all-workplace
type=wifi

[ethernet]
wake-on-lan=0

[802-11-wireless]
mac-address=11:22:33:44:55:66

[wifi]
ssid=workplace
mode=infrastructure
'''})

    def test_wifi_match_all(self):
        self.generate('''network:
  version: 2
  wifis:
    all:
      match: {}
      access-points:
        workplace: {mode: infrastructure}''')

        self.assert_nm({'all-workplace': '''[connection]
id=netplan-all-workplace
type=wifi

[ethernet]
wake-on-lan=0

[wifi]
ssid=workplace
mode=infrastructure
'''})

    def test_wifi_ap(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          mode: ap
          password: s3cret''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[ipv4]
method=shared

[wifi]
ssid=homenet
mode=ap

[wifi-security]
key-mgmt=wpa-psk
psk=s3cret
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_wifi_adhoc(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        homenet:
          mode: adhoc''')

        self.assert_nm({'wl0-homenet': '''[connection]
id=netplan-wl0-homenet
type=wifi
interface-name=wl0

[ethernet]
wake-on-lan=0

[wifi]
ssid=homenet
mode=adhoc
'''})

    def test_bridge_empty(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    br0:
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bridge_type_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  bridges:
    renderer: NetworkManager
    br0:
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bridge_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: networkd
  bridges:
    renderer: networkd
    br0:
      renderer: NetworkManager
      addresses: [1.2.3.4/12]
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto
address1=1.2.3.4/12
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bridge_components(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bridges:
    br0:
      interfaces: [eno1, switchport]
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bridge
master=br0

[ethernet]
wake-on-lan=0
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bridge
master=br0

[ethernet]
wake-on-lan=0
''',
                        'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto
'''})
        self.assert_networkd({})
        self.assert_udev(None)


class TestConfigErrors(TestBase):
    def test_malformed_yaml(self):
        err = self.generate('network:\n  version: 2\n foo: *', expect_fail=True)
        self.assertIn('Invalid YAML', err)
        self.assertIn('/a.yaml line 2 column 1: did not find expected key', err)

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
        self.assertIn('/a.yaml line 1 column 2: expected mapping', err)

    def test_invalid_bool(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    id0:
      wakeonlan: wut
''', expect_fail=True)
        self.assertIn('invalid boolean value wut', err)

    def test_invalid_version(self):
        err = self.generate('network:\n  version: 1', expect_fail=True)
        self.assertIn('/a.yaml line 1 column 11: Only version 2 is supported', err)

    def test_duplicate_id(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    id0:
      wakeonlan: true
    id0:
      wakeonlan: true
''', expect_fail=True)
        self.assertIn("Duplicate net definition ID 'id0'", err)

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
        self.assertIn("redef.yaml line 3 column 4: Updated definition 'id0' changes device type", err)

    def test_set_name_without_match(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      set-name: lom1
''', expect_fail=True)
        self.assertIn('/a.yaml line 4 column 6: def1: set-name: requires match: properties', err)

    def test_virtual_set_name(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      set_name: br1''', expect_fail=True)
        self.assertIn('/a.yaml line 4 column 6: unknown key set_name\n', err)

    def test_virtual_match(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      match:
        driver: foo''', expect_fail=True)
        self.assertIn('/a.yaml line 4 column 6: unknown key match\n', err)

    def test_virtual_wol(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      wakeonlan: true''', expect_fail=True)
        self.assertIn('/a.yaml line 4 column 6: unknown key wakeonlan\n', err)

    def test_bridge_unknown_iface(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: ['foo']''', expect_fail=True)
        self.assertIn('/a.yaml line 4 column 18: bridge br0: interface foo is not defined\n', err)

    def test_bridge_multiple_assignments(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
  bridges:
    br0:
      interfaces: [eno1]
    br1:
      interfaces: [eno1]''', expect_fail=True)
        self.assertIn('bridge br1: interface eno1 is already assigned to bridge br0\n', err)

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
        self.assertIn('/etc/netplan/a.yaml line 6 column 10: unknown key something', err)

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


class TestMerging(TestBase):
    '''multiple *.yaml merging'''

    def test_global_backend(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      dhcp4: y''',
                      confs={'backend': 'network:\n  renderer: networkd'})

        self.assert_networkd({'engreen.network': '[Match]\nName=engreen\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:engreen,''')
        self.assert_udev(None)

    def test_add_def(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: true''',
                      confs={'blue': '''network:
  version: 2
  ethernets:
    enblue:
      dhcp4: true'''})

        self.assert_networkd({'enblue.network': '[Match]\nName=enblue\n\n[Network]\nDHCP=ipv4\n',
                              'engreen.network': '[Match]\nName=engreen\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:enblue,interface-name:engreen,''')
        self.assert_udev(None)

    def test_change_def(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      wakeonlan: true
      dhcp4: false''',
                      confs={'green-dhcp': '''network:
  version: 2
  ethernets:
    engreen:
      dhcp4: true'''})

        self.assert_networkd({'engreen.link': '[Match]\nOriginalName=engreen\n\n[Link]\nWakeOnLan=magic\n',
                              'engreen.network': '[Match]\nName=engreen\n\n[Network]\nDHCP=ipv4\n'})

    def test_cleanup_old_config(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen: {dhcp4: true}
    enyellow: {renderer: NetworkManager}''',
                      confs={'blue': '''network:
  version: 2
  ethernets:
    enblue:
      dhcp4: true'''})

        os.unlink(os.path.join(self.confdir, 'blue.yaml'))
        self.generate('''network:
  version: 2
  ethernets:
    engreen: {dhcp4: true}''')

        self.assert_networkd({'engreen.network': '[Match]\nName=engreen\n\n[Network]\nDHCP=ipv4\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:engreen,''')
        self.assert_udev(None)

    def test_ref(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute''',
                      confs={'bridges': '''network:
  version: 2
  bridges:
    br0:
      interfaces: [eno1, switchports]
      dhcp4: true'''})

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '[Match]\nName=br0\n\n[Network]\nDHCP=ipv4\n',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_def_in_run(self):
        rundir = os.path.join(self.workdir.name, 'run', 'netplan')
        os.makedirs(rundir)
        # override b.yaml definition for enred
        with open(os.path.join(rundir, 'b.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {enred: {dhcp4: true}}''')

        # append new definition for enblue
        with open(os.path.join(rundir, 'c.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {enblue: {dhcp4: true}}''')

        self.generate('''network:
  version: 2
  ethernets:
    engreen: {dhcp4: true}''', confs={'b': '''network:
  version: 2
  ethernets: {enred: {wakeonlan: true}}'''})

        # b.yaml in /run/ should completely shadow b.yaml in /etc, thus no enred.link
        self.assert_networkd({'engreen.network': '[Match]\nName=engreen\n\n[Network]\nDHCP=ipv4\n',
                              'enred.network': '[Match]\nName=enred\n\n[Network]\nDHCP=ipv4\n',
                              'enblue.network': '[Match]\nName=enblue\n\n[Network]\nDHCP=ipv4\n'})


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
