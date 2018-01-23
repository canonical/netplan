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
import re
import sys
import stat
import tempfile
import textwrap
import subprocess
import unittest

exe_generate = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'generate')

# make sure we fail on criticals
os.environ['G_DEBUG'] = 'fatal-criticals'

# common patterns for expected output
ND_DHCP4 = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv4\n\n[DHCP]\nUseMTU=true\nRouteMetric=100\n'
ND_WIFI_DHCP4 = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv4\n\n[DHCP]\nUseMTU=true\nRouteMetric=600\n'
ND_DHCP6 = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv6\n\n[DHCP]\nUseMTU=true\nRouteMetric=100\n'
ND_DHCPYES = '[Match]\nName=%s\n\n[Network]\nDHCP=yes\n\n[DHCP]\nUseMTU=true\nRouteMetric=100\n'


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

        self.assertEqual(set(os.listdir(self.workdir.name)) - {'lib'}, {'etc', 'run'})
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

    def test_systemd_generator_badcall(self):
        outdir = os.path.join(self.workdir.name, 'out')
        os.mkdir(outdir)

        generator = os.path.join(self.workdir.name, 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        try:
            subprocess.check_output([generator, '--root-dir', self.workdir.name],
                                    stderr=subprocess.STDOUT)
            self.fail("direct systemd generator call is expected to fail, but succeeded.")
        except subprocess.CalledProcessError as e:
            self.assertEqual(e.returncode, 1)
            self.assertIn(b'can not be called directly', e.output)


class TestNetworkd(TestBase):
    '''networkd output'''

    def test_eth_optional(self):
        # TODO: cyphermox: this is to validate that "optional" does not cause
        #       any extra config to be generated; and will fail once it's actually
        #       implemented.
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp6: true
      optional: true''')
        self.assert_networkd({'eth0.network': ND_DHCP6 % 'eth0'})

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

    def test_eth_mtu(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth1:
      mtu: 1280
      dhcp4: n''')

        self.assert_networkd({'eth1.link': '[Match]\nOriginalName=eth1\n\n[Link]\nWakeOnLan=off\nMTUBytes=1280\n'})

    def test_mtu_all(self):
        self.generate(textwrap.dedent("""
            network:
              version: 2
              ethernets:
                eth1:
                  mtu: 1280
                  dhcp4: n
              bonds:
                bond0:
                  interfaces:
                  - eth1
                  mtu: 9000
              vlans:
                bond0.108:
                  link: bond0
                  id: 108"""))
        self.assert_networkd({
            'bond0.108.netdev': '[NetDev]\nName=bond0.108\nKind=vlan\n\n[VLAN]\nId=108\n',
            'bond0.netdev': '[NetDev]\nName=bond0\nMTUBytes=9000\nKind=bond\n',
            'bond0.network': '[Match]\nName=bond0\n\n[Network]\nVLAN=bond0.108\n',
            'eth1.link': '[Match]\nOriginalName=eth1\n\n[Link]\nWakeOnLan=off\nMTUBytes=1280\n',
            'eth1.network': '[Match]\nName=eth1\n\n[Network]\nBond=bond0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'
        })

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

        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen'})

    def test_eth_match_dhcp4(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: ixgbe
      dhcp4: true''')

        self.assert_networkd({'def1.network': '''[Match]
Driver=ixgbe

[Network]
DHCP=ipv4

[DHCP]
UseMTU=true
RouteMetric=100
'''})
        self.assert_udev('ACTION=="add|change", SUBSYSTEM=="net", ENV{ID_NET_DRIVER}=="ixgbe", ENV{NM_UNMANAGED}="1"\n')

    def test_eth_match_name(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      dhcp4: true''')

        self.assert_networkd({'def1.network': ND_DHCP4 % 'green'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:green,''')
        self.assert_udev(None)

    def test_eth_set_mac(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_networkd({'def1.network': ND_DHCP4 % 'green',
                              'def1.link': '[Match]\nOriginalName=green\n\n[Link]\nWakeOnLan=off\nMACAddress=00:01:02:03:04:05\n'
                              })

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
                              'def1.network': ND_DHCP4 % 'blue'})
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

        self.assert_networkd({'def1.network': ND_DHCP4 % '*'})
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

        self.assert_networkd({'def1.network': '[Match]\n\n[Network]\nDHCP=ipv4\n\n'
                                              '[DHCP]\nUseMTU=true\nRouteMetric=100\n'})
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
        self.assert_networkd({'def1.network': '''[Match]
MACAddress=00:11:22:33:44:55
Name=en1s*

[Network]
DHCP=ipv4

[DHCP]
UseMTU=true
RouteMetric=100
'''})
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

        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})
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

        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        # should allow NM to manage everything else
        self.assertTrue(os.path.exists(self.nm_enable_all_conf))
        self.assert_udev(None)

    def test_bridge_set_mac(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_networkd({'br0.network': ND_DHCP4 % 'br0',
                              'br0.netdev': '[NetDev]\nName=br0\nMACAddress=00:01:02:03:04:05\nKind=bridge\n'})

    def test_eth_def_renderer(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    renderer: NetworkManager
    eth0:
      renderer: networkd
      dhcp4: true''')

        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_udev(None)

    def test_eth_dhcp6(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {dhcp6: true}''')
        self.assert_networkd({'eth0.network': ND_DHCP6 % 'eth0'})

    def test_eth_dhcp6_no_accept_ra(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp6: true
      accept-ra: no''')
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
DHCP=ipv6
IPv6AcceptRA=no

[DHCP]
UseMTU=true
RouteMetric=100
'''})

    def test_eth_dhcp4_and_6(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0: {dhcp4: true, dhcp6: true}''')
        self.assert_networkd({'eth0.network': ND_DHCPYES % 'eth0'})

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

[DHCP]
UseMTU=true
RouteMetric=100
'''})

    def test_route_v4_single(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          metric: 100
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
Address=192.168.14.2/24

[Route]
Destination=10.10.10.0/24
Gateway=192.168.14.20
Metric=100
'''})

    def test_route_v4_multiple(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 8.8.0.0/16
          via: 192.168.1.1
        - to: 10.10.10.8
          via: 192.168.1.2
          metric: 5000
        - to: 11.11.11.0/24
          via: 192.168.1.3
          metric: 9999
          ''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
Address=192.168.14.2/24

[Route]
Destination=8.8.0.0/16
Gateway=192.168.1.1

[Route]
Destination=10.10.10.8
Gateway=192.168.1.2
Metric=5000

[Route]
Destination=11.11.11.0/24
Gateway=192.168.1.3
Metric=9999
'''})

    def test_route_v6_single(self):
        self.generate('''network:
  version: 2
  ethernets:
    enblue:
      addresses: ["192.168.1.3/24"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1''')

        self.assert_networkd({'enblue.network': '''[Match]
Name=enblue

[Network]
Address=192.168.1.3/24

[Route]
Destination=2001:dead:beef::2/64
Gateway=2001:beef:beef::1
'''})

    def test_route_v6_multiple(self):
        self.generate('''network:
  version: 2
  ethernets:
    enblue:
      addresses: ["192.168.1.3/24"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1
        - to: 2001:f00f:f00f::fe/64
          via: 2001:beef:feed::1
          metric: 1024''')

        self.assert_networkd({'enblue.network': '''[Match]
Name=enblue

[Network]
Address=192.168.1.3/24

[Route]
Destination=2001:dead:beef::2/64
Gateway=2001:beef:beef::1

[Route]
Destination=2001:f00f:f00f::fe/64
Gateway=2001:beef:feed::1
Metric=1024
'''})

    def test_wifi(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s3kr1t"
        workplace:
          password: "c0mpany"
        peer2peer:
          mode: adhoc
      dhcp4: yes''')

        self.assert_networkd({'wl0.network': ND_WIFI_DHCP4 % 'wl0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:wl0,''')
        self.assert_udev(None)

        # generates wpa config and enables wpasupplicant unit
        with open(os.path.join(self.workdir.name, 'run/netplan/wpa-wl0.conf')) as f:
            self.assertEqual(f.read(), '''ctrl_interface=/run/wpa_supplicant

network={
  ssid="Joe's Home"
  psk="s3kr1t"
}
network={
  ssid="workplace"
  psk="c0mpany"
}
network={
  ssid="peer2peer"
  key_mgmt=NONE
  mode=1
}
''')
            self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        self.assertTrue(os.path.islink(os.path.join(
            self.workdir.name, 'run/systemd/system/multi-user.target.wants/netplan-wpa@wl0.service')))

    def test_wifi_route(self):
        self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          password: "c0mpany"
      dhcp4: yes
      routes:
        - to: 10.10.10.0/24
          via: 8.8.8.8''')

        self.assert_networkd({'wl0.network': '''[Match]
Name=wl0

[Network]
DHCP=ipv4

[Route]
Destination=10.10.10.0/24
Gateway=8.8.8.8

[DHCP]
UseMTU=true
RouteMetric=600
'''})

        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:wl0,''')
        self.assert_udev(None)

    def test_wifi_match(self):
        err = self.generate('''network:
  version: 2
  wifis:
    somewifi:
      match:
        driver: foo
      access-points:
        workplace:
          password: "c0mpany"
      dhcp4: yes''', expect_fail=True)
        self.assertIn('networkd backend does not support wifi with match:', err)

    def test_wifi_ap(self):
        err = self.generate('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          password: "c0mpany"
          mode: ap
      dhcp4: yes''', expect_fail=True)
        self.assertIn('networkd does not support wifi in access point mode', err)

    def test_bridge_empty(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': ND_DHCP4 % 'br0'})
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
                              'br0.network': ND_DHCP4 % 'br0'})
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
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
Address=1.2.3.4/12

[DHCP]
UseMTU=true
RouteMetric=100
'''})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:br0,''')
        self.assert_udev(None)

    def test_bridge_forward_declaration(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: [eno1, switchports]
      dhcp4: true
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': ND_DHCP4 % 'br0',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_eth_bridge_nm_blacklist(self):
        self.generate('''network:
  renderer: networkd
  ethernets:
    eth42:
      dhcp4: yes
    ethbr:
      match: {name: eth43}
  bridges:
    mybr:
      interfaces: [ethbr]
      dhcp4: yes''')
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth42,interface-name:eth43,interface-name:mybr,''')

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
                              'br0.network': ND_DHCP4 % 'br0',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_bridge_params(self):
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
      parameters:
        ageing-time: 50
        forward-delay: 12
        hello-time: 6
        max-age: 24
        stp: true
        path-cost:
          eno1: 70
        port-priority:
          eno1: 14
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n\n'
                                            '[Bridge]\nAgeingTimeSec=50\n'
                                            'ForwardDelaySec=12\n'
                                            'HelloTimeSec=6\n'
                                            'MaxAgeSec=24\n'
                                            'STP=true\n',
                              'br0.network': ND_DHCP4 % 'br0',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n\n'
                                              '[Bridge]\nCost=70\nPriority=14\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_bond_empty(self):
        self.generate('''network:
  version: 2
  bonds:
    bn0:
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n',
                              'bn0.network': ND_DHCP4 % 'bn0'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:bn0,''')
        self.assert_udev(None)

    def test_bond_components(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n',
                              'bn0.network': ND_DHCP4 % 'bn0',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBond=bn0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBond=bn0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_bond_empty_parameters(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      parameters: {}
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n',
                              'bn0.network': ND_DHCP4 % 'bn0',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBond=bn0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBond=bn0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_bond_with_parameters(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      parameters:
        mode: 802.1ad
        lacp-rate: 10
        mii-monitor-interval: 10
        min-links: 10
        up-delay: 10
        down-delay: 10
        all-slaves-active: true
        transmit-hash-policy: none
        ad-select: none
        arp-interval: 10
        arp-validate: all
        arp-all-targets: all
        fail-over-mac-policy: none
        gratuitious-arp: 10
        packets-per-slave: 10
        primary-reselect-policy: none
        resend-igmp: 10
        learn-packet-interval: 10
        arp-ip-targets:
          - 10.10.10.10
          - 20.20.20.20
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n\n'
                                            '[Bond]\n'
                                            'Mode=802.1ad\n'
                                            'LACPTransmitRate=10\n'
                                            'MIIMonitorSec=10\n'
                                            'MinLinks=10\n'
                                            'TransmitHashPolicy=none\n'
                                            'AdSelect=none\n'
                                            'AllSlavesActive=1\n'
                                            'ARPIntervalSec=10\n'
                                            'ARPIPTargets=10.10.10.10,20.20.20.20\n'
                                            'ARPValidate=all\n'
                                            'ARPAllTargets=all\n'
                                            'UpDelaySec=10\n'
                                            'DownDelaySec=10\n'
                                            'FailOverMACPolicy=none\n'
                                            'GratuitiousARP=10\n'
                                            'PacketsPerSlave=10\n'
                                            'PrimaryReselectPolicy=none\n'
                                            'ResendIGMP=10\n'
                                            'LearnPacketIntervalSec=10\n',
                              'bn0.network': ND_DHCP4 % 'bn0',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBond=bn0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBond=bn0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_bond_primary_slave(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1: {}
    switchports:
      match:
        driver: yayroute
  bonds:
    bn0:
      parameters:
        mode: active-backup
        primary: eno1
      interfaces: [eno1, switchports]
      dhcp4: true''')

        self.assert_networkd({'bn0.netdev': '[NetDev]\nName=bn0\nKind=bond\n\n'
                                            '[Bond]\n'
                                            'Mode=active-backup\n',
                              'bn0.network': ND_DHCP4 % 'bn0',
                              'eno1.network': '[Match]\nName=eno1\n\n'
                                              '[Network]\nBond=bn0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\nPrimarySlave=true\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n'
                                                     '[Network]\nBond=bn0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_gateway(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24", "2001:FFfe::1/64"]
      gateway4: 192.168.14.1
      gateway6: 2001:FFfe::2''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
Address=192.168.14.2/24
Address=2001:FFfe::1/64
Gateway=192.168.14.1
Gateway=2001:FFfe::2
'''})

    def test_nameserver(self):
        self.generate('''network:
  version: 2
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      nameservers:
        addresses: [1.2.3.4, "1234::FFFF"]
    enblue:
      addresses: ["192.168.1.3/24"]
      nameservers:
        search: [lab, kitchen]
        addresses: [8.8.8.8]''')

        self.assert_networkd({'engreen.network': '''[Match]
Name=engreen

[Network]
Address=192.168.14.2/24
DNS=1.2.3.4
DNS=1234::FFFF
''',
                              'enblue.network': '''[Match]
Name=enblue

[Network]
Address=192.168.1.3/24
DNS=8.8.8.8
Domains=lab kitchen
'''})

    def test_vlan(self):
        self.generate('''network:
  version: 2
  ethernets:
    en1: {}
  vlans:
    enblue:
      id: 1
      link: en1
      addresses: [1.2.3.4/24]
    enred:
      id: 3
      link: en1
      macaddress: aa:bb:cc:dd:ee:11
    engreen: {id: 2, link: en1, dhcp6: true}''')

        self.assert_networkd({'en1.network': '[Match]\nName=en1\n\n[Network]\nVLAN=engreen\nVLAN=enblue\nVLAN=enred\n',
                              'enblue.netdev': '[NetDev]\nName=enblue\nKind=vlan\n\n[VLAN]\nId=1\n',
                              'engreen.netdev': '[NetDev]\nName=engreen\nKind=vlan\n\n[VLAN]\nId=2\n',
                              'enred.netdev': '[NetDev]\nName=enred\nMACAddress=aa:bb:cc:dd:ee:11\nKind=vlan\n\n[VLAN]\nId=3\n',
                              'enblue.network': '[Match]\nName=enblue\n\n[Network]\nAddress=1.2.3.4/24\n',
                              'engreen.network': ND_DHCP6 % 'engreen'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:engreen,interface-name:en1,interface-name:enblue,interface-name:enred,''')
        self.assert_udev(None)


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

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})
        # should allow NM to manage everything else
        self.assertTrue(os.path.exists(self.nm_enable_all_conf))
        self.assert_networkd({'eth0.link': '[Match]\nOriginalName=eth0\n\n[Link]\nWakeOnLan=magic\n'})
        self.assert_udev(None)

    def test_eth_mtu(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth1:
      mtu: 1280
      dhcp4: n''')

        self.assert_networkd({'eth1.link': '[Match]\nOriginalName=eth1\n\n[Link]\nWakeOnLan=off\nMTUBytes=1280\n'})
        self.assert_nm({'eth1': '''[connection]
id=netplan-eth1
type=ethernet
interface-name=eth1

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mtu=1280

[ipv4]
method=link-local

[ipv6]
method=ignore
'''})

    def test_mtu_all(self):
        self.generate(textwrap.dedent("""
            network:
              version: 2
              renderer: NetworkManager
              ethernets:
                eth1:
                  mtu: 1280
                  dhcp4: n
              bonds:
                bond0:
                  interfaces:
                  - eth1
                  mtu: 9000
              vlans:
                bond0.108:
                  link: bond0
                  id: 108"""))
        self.assert_nm({
            'bond0.108': '''[connection]
id=netplan-bond0.108
type=vlan
interface-name=bond0.108

[vlan]
id=108
parent=bond0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
            'bond0': '''[connection]
id=netplan-bond0
type=bond
interface-name=bond0

[802-3-ethernet]
mtu=9000

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
            'eth1': '''[connection]
id=netplan-eth1
type=ethernet
interface-name=eth1
slave-type=bond
master=bond0

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mtu=1280

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
        })

    def test_eth_set_mac(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_networkd({'eth0.link': '''[Match]
OriginalName=eth0

[Link]
WakeOnLan=off
MACAddress=00:01:02:03:04:05
'''})

        self.assert_nm({'eth0': '''[connection]
id=netplan-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0

[802-3-ethernet]
cloned-mac-address=00:01:02:03:04:05

[ipv4]
method=auto

[ipv6]
method=ignore
'''})

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

[ipv4]
method=link-local

[ipv6]
method=ignore
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

[ipv4]
method=link-local

[ipv6]
method=ignore
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

[ipv6]
method=ignore
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

[ipv6]
method=ignore
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

[ipv6]
method=ignore
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

[ipv6]
method=ignore
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

[ipv6]
method=ignore
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

[ipv6]
method=ignore
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

[ipv6]
method=ignore
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

[ipv6]
method=ignore
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

[ipv4]
method=link-local

[ipv6]
method=ignore
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

[ipv4]
method=link-local

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

    def test_route_v4_single(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 10.10.10.0/24
          via: 192.168.14.20
          metric: 100
          ''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
route1=10.10.10.0/24,192.168.14.20,100

[ipv6]
method=ignore
'''})

    def test_route_v4_multiple(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      routes:
        - to: 8.8.0.0/16
          via: 192.168.1.1
          metric: 5000
        - to: 10.10.10.8
          via: 192.168.1.2
        - to: 11.11.11.0/24
          via: 192.168.1.3
          metric: 9999
          ''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
route1=8.8.0.0/16,192.168.1.1,5000
route2=10.10.10.8,192.168.1.2
route3=11.11.11.0/24,192.168.1.3,9999

[ipv6]
method=ignore
'''})

    def test_route_v6_single(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    enblue:
      addresses: ["2001:f00f:f00f::2/64"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1''')

        self.assert_nm({'enblue': '''[connection]
id=netplan-enblue
type=ethernet
interface-name=enblue

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=manual
address1=2001:f00f:f00f::2/64
route1=2001:dead:beef::2/64,2001:beef:beef::1
'''})

    def test_route_v6_multiple(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    enblue:
      addresses: ["2001:f00f:f00f::2/64"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1
        - to: 2001:dead:feed::2/64
          via: 2001:beef:beef::2
          metric: 1000''')

        self.assert_nm({'enblue': '''[connection]
id=netplan-enblue
type=ethernet
interface-name=enblue

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=manual
address1=2001:f00f:f00f::2/64
route1=2001:dead:beef::2/64,2001:beef:beef::1
route2=2001:dead:feed::2/64,2001:beef:beef::2,1000
'''})

    def test_routes_mixed(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24", "2001:f00f::2/128"]
      routes:
        - to: 2001:dead:beef::2/64
          via: 2001:beef:beef::1
          metric: 997
        - to: 8.8.0.0/16
          via: 192.168.1.1
          metric: 5000
        - to: 10.10.10.8
          via: 192.168.1.2
        - to: 11.11.11.0/24
          via: 192.168.1.3
          metric: 9999
        - to: 2001:f00f:f00f::fe/64
          via: 2001:beef:feed::1
          ''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
route1=8.8.0.0/16,192.168.1.1,5000
route2=10.10.10.8,192.168.1.2
route3=11.11.11.0/24,192.168.1.3,9999

[ipv6]
method=manual
address1=2001:f00f::2/128
route1=2001:dead:beef::2/64,2001:beef:beef::1,997
route2=2001:f00f:f00f::fe/64,2001:beef:feed::1
'''})

    def test_wifi_default(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
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

[ipv6]
method=ignore

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

[ipv6]
method=ignore

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
  renderer: NetworkManager
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

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=workplace
mode=infrastructure
'''})

    def test_wifi_match_all(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
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

[ipv4]
method=link-local

[ipv6]
method=ignore

[wifi]
ssid=workplace
mode=infrastructure
'''})

    def test_wifi_ap(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
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

[ipv6]
method=ignore

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
  renderer: NetworkManager
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

[ipv4]
method=link-local

[ipv6]
method=ignore

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

[ipv6]
method=ignore
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

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bridge_set_mac(self):
        self.generate('''network:
  version: 2
  bridges:
    renderer: NetworkManager
    br0:
      macaddress: 00:01:02:03:04:05
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[802-3-ethernet]
cloned-mac-address=00:01:02:03:04:05

[ipv4]
method=auto

[ipv6]
method=ignore
'''})

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

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bridge_forward_declaration(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    br0:
      interfaces: [eno1, switchport]
      dhcp4: true
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bridge
master=br0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bridge
master=br0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto

[ipv6]
method=ignore
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

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bridge
master=br0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bridge_params(self):
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
      parameters:
        ageing-time: 50
        priority: 1000
        forward-delay: 12
        hello-time: 6
        max-age: 24
        path-cost:
          eno1: 70
        port-priority:
          eno1: 61
        stp: true
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bridge
master=br0

[bridge-port]
path-cost=70
priority=61

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bridge
master=br0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'br0': '''[connection]
id=netplan-br0
type=bridge
interface-name=br0

[bridge]
ageing-time=50
priority=1000
forward-delay=12
hello-time=6
max-age=24
stp=true

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bond_empty(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bonds:
    bn0:
      dhcp4: true''')

        self.assert_nm({'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})

    def test_bond_components(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bonds:
    bn0:
      interfaces: [eno1, switchport]
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bond_empty_params(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bonds:
    bn0:
      interfaces: [eno1, switchport]
      parameters: {}
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bond_with_params(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bonds:
    bn0:
      interfaces: [eno1, switchport]
      parameters:
        mode: 802.1ad
        lacp-rate: 10
        mii-monitor-interval: 10
        min-links: 10
        up-delay: 10
        down-delay: 10
        all-slaves-active: true
        transmit-hash-policy: none
        ad-select: none
        arp-interval: 10
        arp-validate: all
        arp-all-targets: all
        arp-ip-targets:
          - 10.10.10.10
          - 20.20.20.20
        fail-over-mac-policy: none
        gratuitious-arp: 10
        packets-per-slave: 10
        primary-reselect-policy: none
        resend-igmp: 10
        learn-packet-interval: 10
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[bond]
mode=802.1ad
lacp_rate=10
miimon=10
min_links=10
xmit_hash_policy=none
ad_select=none
all_slaves_active=1
arp_interval=10
arp_ip_target=10.10.10.10,20.20.20.20
arp_validate=all
arp_all_targets=all
updelay=10
downdelay=10
fail_over_mac=none
num_grat_arp=10
packets_per_slave=10
primary_reselect=none
resend_igmp=10
lp_interval=10

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bond_primary_slave(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eno1: {}
    switchport:
      match:
        name: enp2s1
  bonds:
    bn0:
      interfaces: [eno1, switchport]
      parameters:
        mode: active-backup
        primary: eno1
      dhcp4: true''')

        self.assert_nm({'eno1': '''[connection]
id=netplan-eno1
type=ethernet
interface-name=eno1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'switchport': '''[connection]
id=netplan-switchport
type=ethernet
interface-name=enp2s1
slave-type=bond
master=bn0

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'bn0': '''[connection]
id=netplan-bn0
type=bond
interface-name=bn0

[bond]
mode=active-backup
primary=eno1

[ipv4]
method=auto

[ipv6]
method=ignore
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_gateway(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24", "2001:FFfe::1/64"]
      gateway4: 192.168.14.1
      gateway6: 2001:FFfe::2''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
gateway=192.168.14.1

[ipv6]
method=manual
address1=2001:FFfe::1/64
gateway=2001:FFfe::2
'''})

    def test_nameserver(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    engreen:
      addresses: ["192.168.14.2/24"]
      nameservers:
        addresses: [1.2.3.4, 2.3.4.5, "1234::FFFF"]
        search: [lab, kitchen]
    enblue:
      addresses: ["192.168.1.3/24"]
      nameservers:
        addresses: [8.8.8.8]''')

        self.assert_nm({'engreen': '''[connection]
id=netplan-engreen
type=ethernet
interface-name=engreen

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.14.2/24
dns=1.2.3.4;2.3.4.5;
dns-search=lab;kitchen;

[ipv6]
method=manual
dns=1234::FFFF;
dns-search=lab;kitchen;
''',
                        'enblue': '''[connection]
id=netplan-enblue
type=ethernet
interface-name=enblue

[ethernet]
wake-on-lan=0

[ipv4]
method=manual
address1=192.168.1.3/24
dns=8.8.8.8;

[ipv6]
method=ignore
'''})

    def test_vlan(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    en1: {}
  vlans:
    enblue:
      id: 1
      link: en1
      addresses: [1.2.3.4/24]
    engreen: {id: 2, link: en1, dhcp6: true}''')

        self.assert_networkd({})
        self.assert_nm({'en1': '''[connection]
id=netplan-en1
type=ethernet
interface-name=en1

[ethernet]
wake-on-lan=0

[ipv4]
method=link-local

[ipv6]
method=ignore
''',
                        'enblue': '''[connection]
id=netplan-enblue
type=vlan
interface-name=enblue

[vlan]
id=1
parent=en1

[ipv4]
method=manual
address1=1.2.3.4/24

[ipv6]
method=ignore
''',
                        'engreen': '''[connection]
id=netplan-engreen
type=vlan
interface-name=engreen

[vlan]
id=2
parent=en1

[ipv4]
method=link-local

[ipv6]
method=auto
'''})
        self.assert_udev(None)

    def test_vlan_parent_match(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    en-v:
      match: {macaddress: "11:22:33:44:55:66"}
  vlans:
    engreen: {id: 2, link: en-v, dhcp4: true}''')

        self.assert_networkd({})

        # get assigned UUID  from en-v connection
        with open(os.path.join(self.workdir.name, 'run/NetworkManager/system-connections/netplan-en-v')) as f:
            m = re.search('uuid=([0-9a-fA-F-]{36})\n', f.read())
            self.assertTrue(m)
            uuid = m.group(1)
            self.assertNotEquals(uuid, "00000000-0000-0000-0000-000000000000")

        self.assert_nm({'en-v': '''[connection]
id=netplan-en-v
type=ethernet
uuid=%s

[ethernet]
wake-on-lan=0

[802-3-ethernet]
mac-address=11:22:33:44:55:66

[ipv4]
method=link-local

[ipv6]
method=ignore
''' % uuid,
                        'engreen': '''[connection]
id=netplan-engreen
type=vlan
interface-name=engreen

[vlan]
id=2
parent=%s

[ipv4]
method=auto

[ipv6]
method=ignore
''' % uuid})
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
        self.assertIn('/a.yaml line 4 column 19: br0: interface foo is not defined\n', err)

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
        self.assertIn('br1: interface eno1 is already assigned to br0\n', err)

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
        self.assertIn('missing id property', err)

    def test_vlan_invalid_id(self):
        err = self.generate('''network:
  version: 2
  ethernets: {en1: {}}
  vlans:
    ena: {id: a, link: en1}''', expect_fail=True)
        self.assertIn('invalid unsigned int value a', err)

        err = self.generate('''network:
  version: 2
  ethernets: {en1: {}}
  vlans:
    ena: {id: 4095, link: en1}''', expect_fail=True)
        self.assertIn('invalid id 4095', err)

    def test_vlan_missing_link(self):
        err = self.generate('''network:
  version: 2
  vlans:
    ena: {id: 1}''', expect_fail=True)
        self.assertIn('ena: missing link property', err)

    def test_vlan_unknown_link(self):
        err = self.generate('''network:
  version: 2
  vlans:
    ena: {id: 1, link: en1}''', expect_fail=True)
        self.assertIn('ena: interface en1 is not defined\n', err)

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

    def test_bridge_invalid_dev_for_path_cost(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        path-cost:
          eth0: 50
      dhcp4: true''', expect_fail=True)

    def test_bridge_path_cost_already_defined(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        path-cost:
          eno1: 50
          eno1: 40
      dhcp4: true''', expect_fail=True)

    def test_bridge_invalid_path_cost(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        path-cost:
          eno1: aa
      dhcp4: true''', expect_fail=True)

    def test_bridge_invalid_dev_for_port_prio(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-priority:
          eth0: 50
      dhcp4: true''', expect_fail=True)

    def test_bridge_port_prio_already_defined(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-priority:
          eno1: 50
          eno1: 40
      dhcp4: true''', expect_fail=True)

    def test_bridge_invalid_port_prio(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bridges:
    br0:
      interfaces: [eno1]
      parameters:
        port-priority:
          eno1: 257
      dhcp4: true''', expect_fail=True)

    def test_bond_invalid_arp_target(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bonds:
    bond0:
      interfaces: [eno1]
      parameters:
        arp-ip-targets:
          - 2001:dead:beef::1
      dhcp4: true''', expect_fail=True)

    def test_bond_invalid_primary_slave(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
  bonds:
    bond0:
      interfaces: [eno1]
      parameters:
        primary: wigglewiggle
      dhcp4: true''', expect_fail=True)

    def test_bond_duplicate_primary_slave(self):
        self.generate('''network:
  version: 2
  ethernets:
    eno1:
      match:
        name: eth0
    eno2:
      match:
        name: eth1
  bonds:
    bond0:
      interfaces: [eno1, eno2]
      parameters:
        primary: eno1
        primary: eno2
      dhcp4: true''', expect_fail=True)


class TestForwardDeclaration(TestBase):

    def test_fwdecl_bridge_on_bond(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: ['bond0']
      dhcp4: true
  bonds:
    bond0:
      interfaces: ['eth0', 'eth1']
  ethernets:
    eth0:
      match:
        macaddress: 00:01:02:03:04:05
      set-name: eth0
    eth1:
      match:
        macaddress: 02:01:02:03:04:05
      set-name: eth1
''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': ND_DHCP4 % 'br0',
                              'bond0.netdev': '[NetDev]\nName=bond0\nKind=bond\n',
                              'bond0.network': '[Match]\nName=bond0\n\n'
                                               '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'eth0.link': '[Match]\nMACAddress=00:01:02:03:04:05\n\n'
                                           '[Link]\nName=eth0\nWakeOnLan=off\n',
                              'eth0.network': '[Match]\nMACAddress=00:01:02:03:04:05\nName=eth0\n\n'
                                              '[Network]\nBond=bond0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'eth1.link': '[Match]\nMACAddress=02:01:02:03:04:05\n\n'
                                           '[Link]\nName=eth1\nWakeOnLan=off\n',
                              'eth1.network': '[Match]\nMACAddress=02:01:02:03:04:05\nName=eth1\n\n'
                                              '[Network]\nBond=bond0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})

    def test_fwdecl_feature_blend(self):
        self.generate('''network:
  version: 2
  vlans:
    vlan1:
      link: 'br0'
      id: 1
      dhcp4: true
  bridges:
    br0:
      interfaces: ['bond0', 'eth2']
      parameters:
        path-cost:
          eth2: 1000
          bond0: 8888
  bonds:
    bond0:
      interfaces: ['eth0', 'br1']
  ethernets:
    eth0:
      match:
        macaddress: 00:01:02:03:04:05
      set-name: eth0
  bridges:
    br1:
      interfaces: ['eth1']
  ethernets:
    eth1:
      match:
        macaddress: 02:01:02:03:04:05
      set-name: eth1
    eth2:
      match:
        name: eth2
''')

        self.assert_networkd({'vlan1.netdev': '[NetDev]\nName=vlan1\nKind=vlan\n\n'
                                              '[VLAN]\nId=1\n',
                              'vlan1.network': ND_DHCP4 % 'vlan1',
                              'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n\n'
                                            '[Bridge]\nSTP=true\n',
                              'br0.network': '[Match]\nName=br0\n\n'
                                             '[Network]\nVLAN=vlan1\n',
                              'bond0.netdev': '[NetDev]\nName=bond0\nKind=bond\n',
                              'bond0.network': '[Match]\nName=bond0\n\n'
                                               '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n\n'
                                               '[Bridge]\nCost=8888\n',
                              'eth2.network': '[Match]\nName=eth2\n\n'
                                              '[Network]\nBridge=br0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n\n'
                                              '[Bridge]\nCost=1000\n',
                              'br1.netdev': '[NetDev]\nName=br1\nKind=bridge\n',
                              'br1.network': '[Match]\nName=br1\n\n'
                                             '[Network]\nBond=bond0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'eth0.link': '[Match]\nMACAddress=00:01:02:03:04:05\n\n'
                                           '[Link]\nName=eth0\nWakeOnLan=off\n',
                              'eth0.network': '[Match]\nMACAddress=00:01:02:03:04:05\nName=eth0\n\n'
                                              '[Network]\nBond=bond0\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n',
                              'eth1.link': '[Match]\nMACAddress=02:01:02:03:04:05\n\n'
                                           '[Link]\nName=eth1\nWakeOnLan=off\n',
                              'eth1.network': '[Match]\nMACAddress=02:01:02:03:04:05\nName=eth1\n\n'
                                              '[Network]\nBridge=br1\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n'})


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

        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen'})
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

        self.assert_networkd({'enblue.network': ND_DHCP4 % 'enblue',
                              'engreen.network': ND_DHCP4 % 'engreen'})
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
                              'engreen.network': ND_DHCP4 % 'engreen'})

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

        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen'})
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
                              'br0.network': ND_DHCP4 % 'br0',
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
        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen',
                              'enred.network': ND_DHCP4 % 'enred',
                              'enblue.network': ND_DHCP4 % 'enblue'})

    def test_def_in_lib(self):
        libdir = os.path.join(self.workdir.name, 'lib', 'netplan')
        rundir = os.path.join(self.workdir.name, 'run', 'netplan')
        os.makedirs(libdir)
        os.makedirs(rundir)
        # b.yaml is in /etc/netplan too which should have precedence
        with open(os.path.join(libdir, 'b.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {notme: {dhcp4: true}}''')

        # /run should trump /lib too
        with open(os.path.join(libdir, 'c.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {alsonot: {dhcp4: true}}''')
        with open(os.path.join(rundir, 'c.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {enyellow: {dhcp4: true}}''')

        # this should be considered
        with open(os.path.join(libdir, 'd.yaml'), 'w') as f:
            f.write('''network:
  version: 2
  ethernets: {enblue: {dhcp4: true}}''')

        self.generate('''network:
  version: 2
  ethernets:
    engreen: {dhcp4: true}''', confs={'b': '''network:
  version: 2
  ethernets: {enred: {wakeonlan: true}}'''})

        self.assert_networkd({'engreen.network': ND_DHCP4 % 'engreen',
                              'enred.link': '[Match]\nOriginalName=enred\n\n[Link]\nWakeOnLan=magic\n',
                              'enyellow.network': ND_DHCP4 % 'enyellow',
                              'enblue.network': ND_DHCP4 % 'enblue'})


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
