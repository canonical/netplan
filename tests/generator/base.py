#
# Blackbox tests of netplan generate that verify that the generated
# configuration files look as expected. These are run during "make check" and
# don't touch the system configuration at all.
#
# Copyright (C) 2016-2021 Canonical, Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
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
import random
import glob
import stat
import string
import tempfile
import subprocess
import unittest
import ctypes
import ctypes.util
import yaml
import difflib
import re
import logging

exe_generate = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), 'generate')

# make sure we point to libnetplan properly.
os.environ.update({'LD_LIBRARY_PATH': '.:{}'.format(os.environ.get('LD_LIBRARY_PATH'))})

# make sure we fail on criticals
os.environ['G_DEBUG'] = 'fatal-criticals'

lib = ctypes.CDLL(ctypes.util.find_library('netplan'))

# common patterns for expected output
ND_EMPTY = '[Match]\nName=%s\n\n[Network]\nLinkLocalAddressing=%s\nConfigureWithoutCarrier=yes\n'
ND_WITHIP = '[Match]\nName=%s\n\n[Network]\nLinkLocalAddressing=ipv6\nAddress=%s\nConfigureWithoutCarrier=yes\n'
ND_WIFI_DHCP4 = '[Match]\nName=%s\n\n[Network]\nDHCP=ipv4\nLinkLocalAddressing=ipv6\n\n[DHCP]\nRouteMetric=600\nUseMTU=true\n'
ND_DHCP = '[Match]\nName=%s\n\n[Network]\nDHCP=%s\nLinkLocalAddressing=ipv6%s\n\n[DHCP]\nRouteMetric=100\nUseMTU=%s\n'
ND_DHCP4 = ND_DHCP % ('%s', 'ipv4', '', 'true')
ND_DHCP4_NOMTU = ND_DHCP % ('%s', 'ipv4', '', 'false')
ND_DHCP6 = ND_DHCP % ('%s', 'ipv6', '', 'true')
ND_DHCP6_NOMTU = ND_DHCP % ('%s', 'ipv6', '', 'false')
ND_DHCP6_WOCARRIER = ND_DHCP % ('%s', 'ipv6', '\nConfigureWithoutCarrier=yes', 'true')
ND_DHCPYES = ND_DHCP % ('%s', 'yes', '', 'true')
ND_DHCPYES_NOMTU = ND_DHCP % ('%s', 'yes', '', 'false')
_OVS_BASE = '[Unit]\nDescription=OpenVSwitch configuration for %(iface)s\nDefaultDependencies=no\n\
Wants=ovsdb-server.service\nAfter=ovsdb-server.service\n'
OVS_PHYSICAL = _OVS_BASE + 'Requires=sys-subsystem-net-devices-%(iface)s.device\nAfter=sys-subsystem-net-devices-%(iface)s\
.device\nAfter=netplan-ovs-cleanup.service\nBefore=network.target\nWants=network.target\n%(extra)s'
OVS_VIRTUAL = _OVS_BASE + 'After=netplan-ovs-cleanup.service\nBefore=network.target\nWants=network.target\n%(extra)s'
OVS_BR_DEFAULT = 'ExecStart=/usr/bin/ovs-vsctl set Bridge %(iface)s external-ids:netplan=true\nExecStart=/usr/bin/ovs-vsctl \
set-fail-mode %(iface)s standalone\nExecStart=/usr/bin/ovs-vsctl set Bridge %(iface)s external-ids:netplan/global/set-fail-mode=\
standalone\nExecStart=/usr/bin/ovs-vsctl set Bridge %(iface)s mcast_snooping_enable=false\nExecStart=/usr/bin/ovs-vsctl set \
Bridge %(iface)s external-ids:netplan/mcast_snooping_enable=false\nExecStart=/usr/bin/ovs-vsctl set Bridge %(iface)s \
rstp_enable=false\nExecStart=/usr/bin/ovs-vsctl set Bridge %(iface)s external-ids:netplan/rstp_enable=false\n'
OVS_BR_EMPTY = _OVS_BASE + 'After=netplan-ovs-cleanup.service\nBefore=network.target\nWants=network.target\n\n[Service]\n\
Type=oneshot\nExecStart=/usr/bin/ovs-vsctl --may-exist add-br %(iface)s\n' + OVS_BR_DEFAULT
OVS_CLEANUP = _OVS_BASE + 'ConditionFileIsExecutable=/usr/bin/ovs-vsctl\nBefore=network.target\nWants=network.target\n\n\
[Service]\nType=oneshot\nExecStart=/usr/sbin/netplan apply --only-ovs-cleanup\n'
UDEV_MAC_RULE = 'SUBSYSTEM=="net", ACTION=="add", DRIVERS=="%s", ATTR{address}=="%s", NAME="%s"\n'
UDEV_NO_MAC_RULE = 'SUBSYSTEM=="net", ACTION=="add", DRIVERS=="%s", NAME="%s"\n'
UDEV_SRIOV_RULE = 'ACTION=="add", SUBSYSTEM=="net", ATTRS{sriov_totalvfs}=="?*", RUN+="/usr/sbin/netplan apply --sriov-only"\n'
ND_WITHIPGW = '[Match]\nName=%s\n\n[Network]\nLinkLocalAddressing=ipv6\nAddress=%s\nAddress=%s\nGateway=%s\n\
ConfigureWithoutCarrier=yes\n'
NM_WG = '[connection]\nid=netplan-wg0\ntype=wireguard\ninterface-name=wg0\n\n[wireguard]\nprivate-key=%s\nlisten-port=%s\n%s\
\n\n[ipv4]\nmethod=manual\naddress1=15.15.15.15/24\ngateway=20.20.20.21\n\n[ipv6]\nmethod=manual\naddress1=\
2001:de:ad:be:ef:ca:fe:1/128\n'
ND_WG = '[NetDev]\nName=wg0\nKind=wireguard\n\n[WireGuard]\nPrivateKey%s\nListenPort=%s\n%s\n'
ND_VLAN = '[NetDev]\nName=%s\nKind=vlan\n\n[VLAN]\nId=%d\n'


TYPES = ['ethernets', 'wifis', 'modems', 'bridges', 'bonds', 'vlans', 'tunnels']


class TestBase(unittest.TestCase):

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.confdir = os.path.join(self.workdir.name, 'etc', 'netplan')
        self.nm_enable_all_conf = os.path.join(
            self.workdir.name, 'run', 'NetworkManager', 'conf.d', '10-globally-managed-devices.conf')
        self.maxDiff = None

    def normalize_yaml_value(self, line):
        kv = line.replace('"', '').replace('\'', '').split(':', 1)
        if len(kv) != 2 or kv[1].isspace() or kv[1] == '':
            return line  # no normalization needed; no value given

        # normalize key
        key = kv[0]
        if 'gratuitious-arp' in key:  # historically supported typo
            kv[0] = key.replace('gratuitious-arp', 'gratuitous-arp')

        # normalize value
        val = kv[1].strip()
        if val in ['n', 'no', 'off', 'false']:
            kv[1] = 'false'
        elif val in ['y', 'yes', 'on', 'true']:
            kv[1] = 'true'
        elif val in ['5G']:
            kv[1] = '5GHz'
        elif val in ['2.4G']:
            kv[1] = '2.4GHz'
        else:
            kv[1] = val  # no normalization needed or known

        return ': '.join(kv)

    def expand_yaml(self, line):
        line = self.normalize_yaml_value(line)
        if line == '  version: 2':
            return []
        elif line == '          mode: infrastructure':
            return []
        elif 'dhcp4: false' in line:
            return []
        elif 'dhcp6: false' in line:
            return []
        elif 'accept-ra: false' in line:
            return []
        elif 'hidden: false' in line:
            return []
        elif 'send-hostname: true' in line:
            return []
        elif 'use-dns: true' in line:
            return []
        elif 'use-hostname: true' in line:
            return []
        elif 'use-mtu: true' in line:
            return []
        elif 'use-ntp: true' in line:
            return []
        elif 'use-routes: true' in line:
            return []
        elif 'dhcp-identifier: duid' in line:
            return []
        elif 'ipv6-privacy: false' in line:
            return []
        elif 'optional: false' in line:
            return []
        elif 'critical: false' in line:
            return []
        elif 'type: unicast' in line:
            return []
        elif 'on-link: false' in line:
            return []
        # ignore renderer: on different levels for now
        # that information is not stored in the netdef data structure
        elif 'renderer: ' in line:
            return []
        elif 'parameters: {}' in line:
            return []
        elif line.endswith(': {}'):
            return [line[:-3]]
        # nothing to do
        else:
            return [line]

    def sort_sequences(self, data, full_key=None):
        '''Walk a YAML dict and sort its sequences, keeping track of the full_key (e.g. "network:ethernets:eth0:dhcp4")'''
        if isinstance(data, list):
            scalars_only = not any(list(map(lambda elem: (isinstance(elem, dict) or isinstance(elem, list)), data)))
            # sort sequence alphabetically
            if scalars_only:
                data = data.sort()
            # else: handle list of mappings (like wireguard peers)
        elif isinstance(data, dict):
            # expand short forms
            keys = data.keys()
            if 'password' in keys and ':auth' not in full_key:
                data['auth'] = {'key-management': 'psk', 'password': data['password']}
                del data['password']
            elif 'auth' in keys and data['auth'] == {}:
                data['auth'] = {'key-management': 'none'}
            elif 'link-local' in keys and data['link-local'] == ['ipv6']:
                del data['link-local']  # remove default setting

            # continue walk the dict
            for key in data.keys():
                full_key = ':'.join([str(full_key), str(key)]) if full_key is not None else key
                self.sort_sequences(data[key], full_key)

    def clear_empty_mappings(self, lines):
        new_lines = []
        last = len(lines)
        for i in range(last):
            current = lines[i]
            following = lines[i+1] if i+1 < last else ''
            if current.endswith(':'):
                m = re.match(r'(\W*)(\w+)', current)
                m2 = re.match(r'(\W*)(\w*)', following)
                indentation_curr = len(m.group(1))
                indentation_next = len(m2.group(1))
                if indentation_next <= indentation_curr:
                    logging.debug('removing empty mapping:  ' + current)
                    logging.debug('context (line+1)      : ' + following)
                    continue
            elif '- dhcp4' in current and '- dhcp4' in following:
                continue  # skip current line, it's a duplicate

            new_lines.append(current)
        return new_lines

    def validate_generated_yaml(self, conf, yaml_data, extra_args):  # XXX: remove yaml_data?
        filename = '_generated_test_output.yaml'
        generated = None
        y1 = None
        y2 = None

        if len(extra_args) > 0:
            conf = extra_args[0]  # TODO: handle multiple files

        lib.netplan_clear_netdefs()  # clear previous netdefs
        lib.netplan_parse_yaml(conf.encode(), None)
        lib._write_netplan_conf_full(filename.encode(), self.workdir.name.encode())

        with open(conf, 'r') as orig:
            y1 = yaml.safe_load(orig.read())
            # Consider 'network: {}' and 'network: {version: 2}' to be empty
            if y1 is None or y1 == {'network': {}} or y1 == {'network': {'version': 2}}:
                y1 = yaml.safe_load('')
            generated_path = os.path.join(self.confdir, filename)
            if os.path.isfile(generated_path):
                with open(generated_path, 'r') as generated:
                    out = generated.read()
                    # print('real Y2', out)
                    y2 = yaml.safe_load(out)
            else:
                y2 = yaml.safe_load('')

            # print('Y1', y1)
            self.sort_sequences(y1)
            # print('Y2', y2)
            self.sort_sequences(y2)
            A = yaml.dump(y1, sort_keys=True)
            B = yaml.dump(y2, sort_keys=True)
            Ax = []
            Bx = []
            for line in A.splitlines():
                for lnA in self.expand_yaml(line):
                    Ax.append(lnA)
            for line in B.splitlines():
                for lnB in self.expand_yaml(line):
                    Bx.append(lnB)

            Ax = self.clear_empty_mappings(Ax)
            Bx = self.clear_empty_mappings(Bx)
            # NORMALIZED YAMLs
            # print('\n'.join(Ax))
            # print('\n'.join(Bx))

            # FIXME: ordering of keys
            # Sort again (after substitutions)
            # Aa = yaml.dump(yaml.safe_load('\n'.join(Ax)))
            # Bb = yaml.dump(yaml.safe_load('\n'.join(Bx)))
            # Ax = Aa.splitlines()
            # Bx = Bb.splitlines()

            if len(Ax) != len(Bx):
                for line in difflib.unified_diff(Ax, Bx, fromfile='original', tofile='generated', lineterm=''):
                    print(line, flush=True)
                self.fail('Files have different length')

            for i in range(len(Ax)):
                if Ax[i] != Bx[i]:
                    for line in difflib.unified_diff(Ax, Bx, fromfile='original', tofile='generated', lineterm=''):
                        print(line, flush=True)
                    self.fail('Files do not match')

        # cleanup generated file and data structures
        lib.netplan_clear_netdefs()
        if os.path.isfile(os.path.join(self.confdir, filename)):
            os.remove(os.path.join(self.confdir, filename))

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
        if not expect_fail:
            self.validate_generated_yaml(conf, yaml, extra_args)
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

    def assert_additional_udev(self, file_contents_map):
        udev_dir = os.path.join(self.workdir.name, 'run', 'udev', 'rules.d')
        for fname, contents in file_contents_map.items():
            with open(os.path.join(udev_dir, fname)) as f:
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

    def assert_ovs(self, file_contents_map):
        systemd_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'system')
        if not file_contents_map:
            # in this case we assume no OVS configuration should be present
            self.assertFalse(glob.glob(os.path.join(systemd_dir, '*netplan-ovs-*.service')))
            return

        self.assertEqual(set(os.listdir(self.workdir.name)) - {'lib'}, {'etc', 'run'})
        ovs_systemd_dir = set(os.listdir(systemd_dir))
        ovs_systemd_dir.remove('systemd-networkd.service.wants')
        self.assertEqual(ovs_systemd_dir, {'netplan-ovs-' + f for f in file_contents_map})
        for fname, contents in file_contents_map.items():
            fname = 'netplan-ovs-' + fname
            with open(os.path.join(systemd_dir, fname)) as f:
                self.assertEqual(f.read(), contents)
            if fname.endswith('.service'):
                link_path = os.path.join(
                    systemd_dir, 'systemd-networkd.service.wants', fname)
                self.assertTrue(os.path.islink(link_path))
                link_target = os.readlink(link_path)
                self.assertEqual(link_target,
                                 os.path.join(
                                    '/', 'run', 'systemd', 'system', fname))
