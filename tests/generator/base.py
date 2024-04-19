#
# Functional tests of netplan generate that verify that the generated
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
from io import StringIO

import netplan

exe_generate = os.environ.get('NETPLAN_GENERATE_PATH',
                              os.path.join(os.path.dirname(os.path.dirname(
                                           os.path.dirname(os.path.abspath(__file__)))), 'generate'))

# make sure we point to libnetplan properly.
os.environ.update({'LD_LIBRARY_PATH': '.:{}'.format(os.environ.get('LD_LIBRARY_PATH'))})

# make sure we fail on criticals
os.environ['G_DEBUG'] = 'fatal-criticals'

lib = ctypes.CDLL('libnetplan.so.1')

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
Type=oneshot\nTimeoutStartSec=10s\nExecStart=/usr/bin/ovs-vsctl --may-exist add-br %(iface)s\n' + OVS_BR_DEFAULT
OVS_CLEANUP = _OVS_BASE + 'ConditionFileIsExecutable=/usr/bin/ovs-vsctl\nBefore=network.target\nWants=network.target\n\n\
[Service]\nType=oneshot\nTimeoutStartSec=10s\nStartLimitBurst=0\nExecStart=/usr/sbin/netplan apply --only-ovs-cleanup\n'
UDEV_MAC_RULE = 'SUBSYSTEM=="net", ACTION=="add", DRIVERS=="%s", ATTR{address}=="%s", NAME="%s"\n'
UDEV_NO_MAC_RULE = 'SUBSYSTEM=="net", ACTION=="add", DRIVERS=="%s", NAME="%s"\n'
UDEV_SRIOV_RULE = 'ACTION=="add", SUBSYSTEM=="net", ATTRS{sriov_totalvfs}=="?*", RUN+="/usr/sbin/netplan apply --sriov-only"\n'
ND_WITHIPGW = '[Match]\nName=%s\n\n[Network]\nLinkLocalAddressing=ipv6\nAddress=%s\nAddress=%s\nGateway=%s\n\
ConfigureWithoutCarrier=yes\n'
NM_WG = '[connection]\nid=netplan-wg0\ntype=wireguard\ninterface-name=wg0\n\n[wireguard]\nprivate-key=%s\nlisten-port=%s\n%s\
\n\n[ipv4]\nmethod=manual\naddress1=15.15.15.15/24\ngateway=20.20.20.21\n\n[ipv6]\nmethod=manual\naddress1=\
2001:de:ad:be:ef:ca:fe:1/128\nip6-privacy=0\n'
ND_WG = '[NetDev]\nName=wg0\nKind=wireguard\n\n[WireGuard]\nPrivateKey%s\nListenPort=%s\n%s\n'
ND_VLAN = '[NetDev]\nName=%s\nKind=vlan\n\n[VLAN]\nId=%d\n'
ND_VXLAN = '[NetDev]\nName=%s\nKind=vxlan\n\n[VXLAN]\nVNI=%d\n'
ND_VRF = '[NetDev]\nName=%s\nKind=vrf\n\n[VRF]\nTable=%d\n'
ND_DUMMY = '[NetDev]\nName=%s\nKind=dummy\n'        # wokeignore:rule=dummy
ND_VETH = '[NetDev]\nName=%s\nKind=veth\n\n[Peer]\nName=%s\n'
SD_WPA = '''[Unit]
Description=WPA supplicant for netplan %(iface)s
DefaultDependencies=no
Requires=sys-subsystem-net-devices-%(iface)s.device
After=sys-subsystem-net-devices-%(iface)s.device
Before=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=/sbin/wpa_supplicant -c /run/netplan/wpa-%(iface)s.conf -i%(iface)s -D%(drivers)s
'''
NM_MANAGED = 'SUBSYSTEM=="net", ACTION=="add|change|move", ENV{ID_NET_NAME}=="%s", ENV{NM_UNMANAGED}="0"\n'
NM_UNMANAGED = 'SUBSYSTEM=="net", ACTION=="add|change|move", ENV{ID_NET_NAME}=="%s", ENV{NM_UNMANAGED}="1"\n'
NM_MANAGED_MAC = 'SUBSYSTEM=="net", ACTION=="add|change|move", ATTR{address}=="%s", ENV{NM_UNMANAGED}="0"\n'
NM_UNMANAGED_MAC = 'SUBSYSTEM=="net", ACTION=="add|change|move", ATTR{address}=="%s", ENV{NM_UNMANAGED}="1"\n'
NM_MANAGED_DRIVER = 'SUBSYSTEM=="net", ACTION=="add|change|move", ENV{ID_NET_DRIVER}=="%s", ENV{NM_UNMANAGED}="0"\n'
NM_UNMANAGED_DRIVER = 'SUBSYSTEM=="net", ACTION=="add|change|move", ENV{ID_NET_DRIVER}=="%s", ENV{NM_UNMANAGED}="1"\n'

WOKE_REPLACE_REGEX = ' +# wokeignore:rule=[a-z]+'


class NetplanV2Normalizer():

    def __init__(self):
        self.YAML_FALSE = ['n', 'no', 'off', 'false']
        self.YAML_TRUE = ['y', 'yes', 'on', 'true']
        self.DEFAULT_STANZAS = [
            'dhcp4-overrides: {}',  # 2nd level default (containing defaults itself)
            'dhcp6-overrides: {}',  # 2nd level default (containing defaults itself)
            'hidden: false',  # access-point
            'on-link: false',  # route
            'stp: true',  # paramters
            'type: unicast',  # route
            'version: 2',  # global
        ]
        self.DEFAULT_NETDEF = {
            'dhcp4': self.YAML_FALSE,
            'dhcp6': self.YAML_FALSE,
            'dhcp-identifier': ['duid'],
            'hidden': self.YAML_FALSE,
        }
        self.DEFAULT_DHCP = {
            'send-hostname': self.YAML_TRUE,
            'use-dns': self.YAML_TRUE,
            'use-hostname': self.YAML_TRUE,
            'use-mtu': self.YAML_TRUE,
            'use-ntp': self.YAML_TRUE,
            'use-routes': self.YAML_TRUE,
        }

    def _clear_mapping_defaults(self, keys, defaults, data):
        potential_defaults = list(set(keys) & set(defaults.keys()))
        for k in potential_defaults:
            if any(map(str(data[k]).lower().__eq__, defaults[k])):
                del data[k]

    def normalize_yaml_line(self, line):
        '''Process formatted YAML line by line (one setting/key per line)

        Deleting default values and re-writing to default wording
        '''
        kv = line.replace('"', '').replace('\'', '').split(':', 1)
        if len(kv) != 2 or kv[1].isspace() or kv[1] == '':
            return line  # no normalization needed; no value given

        # normalize key
        key = kv[0]
        if 'gratuitious-arp' in key:  # historically supported typo
            kv[0] = key.replace('gratuitious-arp', 'gratuitous-arp')

        # normalize value
        val = kv[1].strip()
        if val in self.YAML_FALSE:
            kv[1] = 'false'
        elif val in self.YAML_TRUE:
            kv[1] = 'true'
        elif val == '5G':
            kv[1] = '5GHz'
        elif val == '2.4G':
            kv[1] = '2.4GHz'
        else:  # no normalization needed or known
            kv[1] = val

        return ': '.join(kv)

    def normalize_yaml_tree(self, data, full_key=''):
        '''Walk the YAML dict/tree @data and sort its sequences in place

        Keeping track of the @full_key (path), e.g.: "network:ethernets:eth0:dhcp4"
        And normalizing certain netplan special cases
        '''
        if isinstance(data, list):
            scalars_only = not any(list(map(lambda elem: (isinstance(elem, dict) or isinstance(elem, list)), data)))
            # sort sequence alphabetically
            if scalars_only:
                data.sort()
                # remove duplicates (if needed)
                unique = set(data)
                if len(data) > len(unique):
                    rm_idx = set()
                    last_idx = 0
                    for elem in unique:
                        if data.count(elem) > 1:
                            idx = data.index(elem, last_idx)
                            rm_idx.add(idx)
                            last_idx = idx
                    for idx in rm_idx:
                        del data[idx]
        elif isinstance(data, dict):
            keys = data.keys()
            # expand special short forms
            if 'password' in keys and ':auth' not in full_key:
                data['auth'] = {'key-management': 'psk', 'password': data['password']}
                del data['password']
            if 'auth' in keys and data['auth'] == {}:
                data['auth'] = {'key-management': 'none'}
            # remove default stanza ("link-local: [ ipv6 ]"")
            if 'link-local' in keys and data['link-local'] == ['ipv6']:
                del data['link-local']
            # remove default stanza ("wakeonwlan: [ default ]")
            if 'wakeonwlan' in keys and data['wakeonwlan'] == ['default']:
                del data['wakeonwlan']
            # remove explicit openvswitch stanzas, they might not always be
            # defined in the original YAML (due to being implicit)
            if ('openvswitch' in keys and data['openvswitch'] == {} and
                    any(map(full_key.__contains__, [':bonds:', ':bridges:', ':vlans:']))):
                del data['openvswitch']
            # remove default empty bond-parameters, those are not rendered by the YAML generator
            if 'parameters' in keys and data['parameters'] == {} and ':bonds:' in full_key:
                del data['parameters']
            # remove default mode=infrastructore from wifi APs, keeping the SSID
            if 'mode' in keys and ':wifis:' in full_key and 'infrastructure' in data['mode']:
                del data['mode']
            # ignore renderer: on other than global levels for now, as that
            # information is currently not stored in the netdef data structure
            if ('renderer' in keys and len(full_key.split(':')) > 1 and
                    data['renderer'] in ['networkd', 'NetworkManager']):
                del data['renderer']
            # remove default values from the dhcp4/6-overrides mappings
            if full_key.endswith(':dhcp4-overrides') or full_key.endswith(':dhcp6-overrides'):
                self._clear_mapping_defaults(keys, self.DEFAULT_DHCP, data)
            # remove default values from netdef/interface mappings
            if len(full_key.split(':')) == 3:  # netdef level
                self._clear_mapping_defaults(keys, self.DEFAULT_NETDEF, data)

            # continue to walk the dict
            for key in data.keys():
                full_key_next = ':'.join([str(full_key), str(key)]) if full_key != '' else key
                self.normalize_yaml_tree(data[key], full_key_next)

    def normalize_yaml(self, yaml_dict):
        # 1st pass: normalize the YAML tree in place, sorting and removing some values
        self.normalize_yaml_tree(yaml_dict)
        # 2nd pass: sort the mapping keys and output a formatted yaml (one key per line)
        formatted_yaml = yaml.dump(yaml_dict, sort_keys=True)
        # 3rd pass: normalize the wording of certain keys/values per line
        #           and remove any line, containg only default values
        output = []
        for line in formatted_yaml.splitlines():
            line = self.normalize_yaml_line(line)
            if line.strip() in self.DEFAULT_STANZAS:
                continue
            output.append(line)
        return output


class TestBase(unittest.TestCase):

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.confdir = os.path.join(self.workdir.name, 'etc', 'netplan')
        self.nm_enable_all_conf = os.path.join(
            self.workdir.name, 'run', 'NetworkManager', 'conf.d', '10-globally-managed-devices.conf')
        self.maxDiff = None

    def validate_generated_yaml(self, yaml_input):
        '''Validate a list of YAML input files one by one.

        Go through the list @yaml_input one by one, parse the YAML and
        re-generate the YAML output. Afterwards, normalize and compare the
        original (and normalized) input with the generated (and normalized)
        output.
        '''

        for input in yaml_input:
            parser = netplan.Parser()
            parser.load_yaml(input)
            state = netplan.State()
            state.import_parser_results(parser)

            # TODO: Allow handling of full hierarchy overrides,
            #       dealing only with the current element of 'yaml_input'.
            #       E.g. allow vlan.id & vlan.link to be defined in a base file.
            #       See test_routing.py:
            #       test_add_routes_to_different_tables_from_multiple_files
            #       test_add_duplicate_routes_from_multiple_files

            # Read output of the YAML generator (if any)
            output_fd = StringIO()
            state._dump_yaml(output_fd)
            output_yaml = yaml.safe_load(output_fd.getvalue())

            # Read input YAML file, as defined by the self.generate('...') method
            input_yaml = None
            with open(input, 'r') as orig:
                input_yaml = yaml.safe_load(orig.read())
                # Consider 'network: {}' and 'network: {version: 2}' to be empty
                if input_yaml is None or input_yaml == {'network': {}} or input_yaml == {'network': {'version': 2}}:
                    input_yaml = yaml.safe_load('')

            # Normalize input and output YAML
            netplan_normalizer = NetplanV2Normalizer()
            input_lines = netplan_normalizer.normalize_yaml(input_yaml)
            output_lines = netplan_normalizer.normalize_yaml(output_yaml)

            # Check if (normalized) input and (normalized) output are equal
            yaml_files_differ = len(input_lines) != len(output_lines)
            if not yaml_files_differ:  # pragma: no cover (only execited in error case)
                for i in range(len(input_lines)):
                    if input_lines[i] != output_lines[i]:
                        yaml_files_differ = True
                        break
            if yaml_files_differ:  # pragma: no cover (only execited in error case)
                fromfile = 'original (%s)' % input
                for line in difflib.unified_diff(input_lines, output_lines, fromfile, tofile='generated', lineterm=''):
                    print(line, flush=True)
                self.fail('Re-generated YAML file does not match (adopt netplan.c YAML generator?)')

    def generate(self, yaml, expect_fail=False, extra_args=[], confs=None, skip_generated_yaml_validation=False):
        '''Call generate with given YAML string as configuration

        Return stderr output.
        '''
        yaml_input = []
        conf = os.path.join(self.confdir, 'a.yaml')
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        if yaml is not None:
            with open(conf, 'w') as f:
                f.write(yaml)
            os.chmod(conf, mode=0o600)
            yaml_input.append(conf)
        if confs:
            for f, contents in confs.items():
                path = os.path.join(self.confdir, f + '.yaml')
                with open(path, 'w') as f:
                    f.write(contents)
                os.chmod(path, mode=0o600)
                yaml_input.append(path)

        argv = [exe_generate, '--root-dir', self.workdir.name] + extra_args
        if 'TEST_SHELL' in os.environ:  # pragma nocover
            print('Test is about to run:\n%s' % ' '.join(argv))
            subprocess.call(['bash', '-i'], cwd=self.workdir.name)

        p = subprocess.Popen(argv, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        (out, err) = p.communicate()
        if expect_fail:
            self.assertGreater(p.returncode, 0)
        else:
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(out, '')
        if not expect_fail and not skip_generated_yaml_validation:
            yaml_input = list(set(yaml_input + extra_args))
            yaml_input.sort()
            self.validate_generated_yaml(yaml_input)
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
            contents = re.sub(WOKE_REPLACE_REGEX, '', contents)
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

    def assert_wpa_supplicant(self, iface, content):
        conf_path = os.path.join(self.workdir.name, 'run', 'netplan', "wpa-" + iface + ".conf")
        with open(conf_path) as f:
            self.assertEqual(f.read(), content)

    def assert_nm(self, connections_map=None, conf=None):
        # check config
        conf_path = os.path.join(self.workdir.name, 'run', 'NetworkManager', 'conf.d', 'netplan.conf')
        if conf:
            conf = re.sub(WOKE_REPLACE_REGEX, '', conf)
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
                contents = re.sub(WOKE_REPLACE_REGEX, '', contents)
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
            lines = []
            for line in f.readlines():
                # ignore any comment in udev rules.d file
                if not line.startswith('#'):
                    lines.append(line)
            self.assertEqual(''.join(lines), contents)

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

    def assert_sriov(self, file_contents_map):
        systemd_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'system')
        sriov_systemd_dir = glob.glob(os.path.join(systemd_dir, '*netplan-sriov-*.service'))
        self.assertEqual(set(os.path.basename(file) for file in sriov_systemd_dir),
                         {'netplan-sriov-' + f for f in file_contents_map})
        self.assertEqual(set(os.listdir(self.workdir.name)) - {'lib'}, {'etc', 'run'})

        for file in sriov_systemd_dir:
            basename = os.path.basename(file)
            with open(file, 'r') as f:
                contents = f.read()
                map_contents = file_contents_map.get(basename.replace('netplan-sriov-', ''))
                self.assertEqual(map_contents, contents)
