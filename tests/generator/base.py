#
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
import random
import stat
import string
import tempfile
import subprocess
import unittest

exe_generate = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), 'generate')

# make sure we fail on criticals
os.environ['G_DEBUG'] = 'fatal-criticals'

# common patterns for expected output
ND_DHCP4 = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv4\nLinkLocalAddressing=ipv6\n\n[DHCP]\nRouteMetric=100\nUseMTU=true\n'
ND_DHCP4_NOMTU = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv4\nLinkLocalAddressing=ipv6\n\n[DHCP]\nRouteMetric=100\nUseMTU=false\n'
ND_WIFI_DHCP4 = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv4\nLinkLocalAddressing=ipv6\n\n[DHCP]\nRouteMetric=600\nUseMTU=true\n'
ND_DHCP6 = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv6\nLinkLocalAddressing=ipv6\n\n[DHCP]\nRouteMetric=100\nUseMTU=true\n'
ND_DHCP6_NOMTU = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv6\nLinkLocalAddressing=ipv6\n\n[DHCP]\nRouteMetric=100\nUseMTU=false\n'
ND_DHCPYES = '[Match]\nName=%s\n\n[Network]\nDHCP=yes\nLinkLocalAddressing=ipv6\n\n[DHCP]\nRouteMetric=100\nUseMTU=true\n'
ND_DHCPYES_NOMTU = '[Match]\nName=%s\n\n[Network]\nDHCP=yes\nLinkLocalAddressing=ipv6\n\n[DHCP]\nRouteMetric=100\nUseMTU=false\n'
UDEV_MAC_RULE = 'SUBSYSTEM=="net", ACTION=="add", DRIVERS=="%s", ATTR{address}=="%s", NAME="%s"\n'
UDEV_NO_MAC_RULE = 'SUBSYSTEM=="net", ACTION=="add", DRIVERS=="%s", NAME="%s"\n'


class TestBase(unittest.TestCase):

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.confdir = os.path.join(self.workdir.name, 'etc', 'netplan')
        self.nm_enable_all_conf = os.path.join(
            self.workdir.name, 'run', 'NetworkManager', 'conf.d', '10-globally-managed-devices.conf')
        self.maxDiff = None

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
        if 'TEST_SHELL' in os.environ:  # pragma nocover
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

    def eth_name(self):
        """Return a link name.

        Use when you need a link name for a test but don't want to
        encode a made up name in the test.
        """
        return 'eth' + ''.join(random.sample(string.ascii_letters + string.digits, k=4))

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

    def assert_networkd_udev(self, file_contents_map):
        udev_dir = os.path.join(self.workdir.name, 'run', 'udev', 'rules.d')
        if not file_contents_map:
            # it can either not exist, or can only contain 90-netplan.rules
            self.assertTrue((not os.path.exists(udev_dir)) or
                            (os.listdir(udev_dir) == ['90-netplan.rules']))
            return

        self.assertEqual(set(os.listdir(udev_dir)) - set(['90-netplan.rules']),
                         {'99-netplan-' + f for f in file_contents_map})
        for fname, contents in file_contents_map.items():
            with open(os.path.join(udev_dir, '99-netplan-' + fname)) as f:
                self.assertEqual(f.read(), contents)

    def get_network_config_for_link(self, link_name):
        """Return the content of the .network file for `link_name`."""
        networkd_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'network')
        with open(os.path.join(networkd_dir, '10-netplan-{}.network'.format(link_name))) as f:
            return f.read()

    def get_optional_addresses(self, eth_name):
        config = self.get_network_config_for_link(eth_name)
        r = set()
        prefix = "OptionalAddresses="
        for line in config.splitlines():
            if line.startswith(prefix):
                r.add(line[len(prefix):])
        return r

    def assert_nm(self, connections_map=None, conf=None):
        # check config
        conf_path = os.path.join(self.workdir.name, 'run', 'NetworkManager', 'conf.d', 'netplan.conf')
        if conf:
            with open(conf_path) as f:
                self.assertEqual(f.read(), conf)
        else:
            if os.path.exists(conf_path):
                with open(conf_path) as f:  # pragma: nocover
                    self.fail('unexpected %s:\n%s' % (conf_path, f.read()))

        # check connections
        con_dir = os.path.join(self.workdir.name, 'run', 'NetworkManager', 'system-connections')
        if connections_map:
            self.assertEqual(set(os.listdir(con_dir)),
                             set(['netplan-' + n.split('.nmconnection')[0] + '.nmconnection' for n in connections_map]))
            for fname, contents in connections_map.items():
                extension = ''
                if '.nmconnection' not in fname:
                    extension = '.nmconnection'
                with open(os.path.join(con_dir, 'netplan-' + fname + extension)) as f:
                    self.assertEqual(f.read(), contents)
                    # NM connection files might contain secrets
                    self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        else:
            if os.path.exists(con_dir):
                self.assertEqual(os.listdir(con_dir), [])

    def assert_nm_udev(self, contents):
        rule_path = os.path.join(self.workdir.name, 'run/udev/rules.d/90-netplan.rules')
        if contents is None:
            self.assertFalse(os.path.exists(rule_path))
            return
        with open(rule_path) as f:
            self.assertEqual(f.read(), contents)
