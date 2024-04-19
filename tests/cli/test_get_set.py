#!/usr/bin/python3
# Functional tests of netplan CLI. These are run during "make check" and don't
# touch the system configuration at all.
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
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
import unittest
import tempfile
import shutil
import glob

import yaml

from netplan_cli.cli.commands.set import FALLBACK_FILENAME
from netplan_cli.cli.ovs import OPENVSWITCH_OVS_VSCTL

from netplan import NetplanException
from tests.test_utils import call_cli


class TestSet(unittest.TestCase):
    '''Test netplan set'''
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory(prefix='netplan_')
        self.file = '70-netplan-set.yaml'
        self.path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'etc', 'netplan'))

    def tearDown(self):
        shutil.rmtree(self.workdir.name)

    def _set(self, args):
        args.insert(0, 'set')
        out = call_cli(args + ['--root-dir', self.workdir.name])
        self.assertEqual(out, '', msg='netplan set returned unexpected output')

    def test_set_scalar(self):
        self._set(['ethernets.eth0.dhcp4=true'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIs(True, yaml.safe_load(f)['network']['ethernets']['eth0']['dhcp4'])

    def test_set_scalar2(self):
        self._set(['ethernets.eth0.dhcp4="yes"'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            # XXX: the previous version using PyYAML would keep the "yes" variant but the round-trip
            # through libnetplan doesn't keep formatting choices (yes is a keyword same as true)
            self.assertIs(True, yaml.safe_load(f)['network']['ethernets']['eth0']['dhcp4'])

    def test_set_global(self):
        self._set([r'network={renderer: NetworkManager}'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertEqual('NetworkManager', yaml.safe_load(f)['network']['renderer'])

    def test_set_sequence(self):
        self._set(['ethernets.eth0.addresses=[1.2.3.4/24, \'5.6.7.8/24\']'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertListEqual(
                    ['1.2.3.4/24', '5.6.7.8/24'],
                    yaml.safe_load(f)['network']['ethernets']['eth0']['addresses'])

    def test_set_sequence2(self):
        self._set(['ethernets.eth0.addresses=["1.2.3.4/24", 5.6.7.8/24]'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertListEqual(
                    ['1.2.3.4/24', '5.6.7.8/24'],
                    yaml.safe_load(f)['network']['ethernets']['eth0']['addresses'])

    def test_set_mapping(self):
        self._set(['ethernets.eth0={addresses: [1.2.3.4/24], dhcp4: true}'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
            self.assertSequenceEqual(
                    ['1.2.3.4/24'],
                    out['network']['ethernets']['eth0']['addresses'])
            self.assertIs(True, out['network']['ethernets']['eth0']['dhcp4'])

    def test_set_origin_hint(self):
        self._set(['ethernets.eth0.dhcp4=true', '--origin-hint=99_snapd'])
        p = os.path.join(self.workdir.name, 'etc', 'netplan', '99_snapd.yaml')
        self.assertTrue(os.path.isfile(p))
        with open(p, 'r') as f:
            self.assertIs(True, yaml.safe_load(f)['network']['ethernets']['eth0']['dhcp4'])

    def test_set_origin_hint_update(self):
        hint = os.path.join(self.workdir.name, 'etc', 'netplan', 'hint.yaml')
        with open(hint, 'w') as f:
            f.write('''network:
  version: 2
  renderer: networkd
  ethernets: {eth0: {dhcp6: true}}''')
        self._set(['ethernets.eth0={dhcp4: true, dhcp6: NULL}', '--origin-hint=hint'])
        self.assertTrue(os.path.isfile(hint))
        with open(hint, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertEqual(2, yml['network']['version'])
            self.assertEqual('networkd', yml['network']['renderer'])
            self.assertTrue(yml['network']['ethernets']['eth0']['dhcp4'])
            self.assertNotIn('dhcp6', yml['network']['ethernets']['eth0'])

    def test_set_origin_hint_override(self):
        defaults = os.path.join(self.workdir.name, 'etc', 'netplan', '0-snapd-defaults.yaml')
        with open(defaults, 'w') as f:
            f.write('''network:
  renderer: networkd
  bridges: {br54: {dhcp4: true, dhcp6: true}}
  ethernets: {eth0: {dhcp4: true}}''')
        self._set(['network.version=2', '--origin-hint=90-snapd-config'])
        self._set(['renderer=NetworkManager', '--origin-hint=90-snapd-config'])
        self._set(['bridges.br55.dhcp4=false', '--origin-hint=90-snapd-config'])
        self._set(['bridges.br54.dhcp4=false', '--origin-hint=90-snapd-config'])
        self._set(['bridges.br54.interfaces=[eth0]', '--origin-hint=90-snapd-config'])
        self.assertTrue(os.path.isfile(defaults))
        with open(defaults, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertEqual("networkd", yml['network']['renderer'])
        p = os.path.join(self.workdir.name, 'etc', 'netplan', '90-snapd-config.yaml')
        self.assertTrue(os.path.isfile(p))
        with open(p, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertIs(False, yml['network']['bridges']['br54']['dhcp4'])
            self.assertNotIn('dhcp6', yml['network']['bridges']['br54'])
            self.assertEqual(['eth0'], yml['network']['bridges']['br54']['interfaces'])
            self.assertIs(False, yml['network']['bridges']['br55']['dhcp4'])
            self.assertIs(2, yml['network']['version'])
            self.assertEqual("NetworkManager", yml['network']['renderer'])

    def test_set_origin_hint_override_no_leak_renderer(self):
        defaults = os.path.join(self.workdir.name, 'etc', 'netplan', '0-snapd-defaults.yaml')
        with open(defaults, 'w') as f:
            f.write('''network:
  renderer: networkd
  bridges: {br54: {dhcp4: true}}''')
        os.chmod(defaults, mode=0o600)
        self._set(['bridges.br54.dhcp4=false', '--origin-hint=90-snapd-config'])
        self.assertTrue(os.path.isfile(defaults))
        with open(defaults, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertEqual("networkd", yml['network']['renderer'])
        p = os.path.join(self.workdir.name, 'etc', 'netplan', '90-snapd-config.yaml')
        self.assertTrue(os.path.isfile(p))
        with open(p, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertIs(False, yml['network']['bridges']['br54']['dhcp4'])
            self.assertNotIn('renderer', yml['network'])

    def test_set_origin_hint_override_invalid_netdef_setting(self):
        defaults = os.path.join(self.workdir.name, 'etc', 'netplan', '0-snapd-defaults.yaml')
        with open(defaults, 'w') as f:
            f.write('''network:
  vrfs:
    vrf0:
      table: 1005
      routes:
      - to: default
        via: 10.10.10.4
        table: 1005
''')
        with self.assertRaises(NetplanException) as e:
            self._set(['vrfs.vrf0.table=1004', '--origin-hint=90-snapd-config'])
        self.assertIn('vrf0: VRF routes table mismatch (1004 != 1005)', str(e.exception))
        # hint/output file should not exist
        p = os.path.join(self.workdir.name, 'etc', 'netplan', '90-snapd-config.yaml')
        self.assertFalse(os.path.isfile(p))
        # original (defaults) file should stay untouched
        self.assertTrue(os.path.isfile(defaults))
        with open(defaults, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertEqual(1005, yml['network']['vrfs']['vrf0']['table'])

    def test_set_origin_hint_extend(self):
        p = os.path.join(self.workdir.name, 'etc', 'netplan', '90-snapd-config.yaml')
        with open(p, 'w') as f:
            f.write('''network: {bridges: {br54: {dhcp4: true}}}''')
        self._set(['bridges.br54.dhcp4=false', '--origin-hint=90-snapd-config'])
        self._set(['bridges.br55.dhcp4=true', '--origin-hint=90-snapd-config'])
        self.assertTrue(os.path.isfile(p))
        with open(p, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertIs(False, yml['network']['bridges']['br54']['dhcp4'])
            self.assertIs(True, yml['network']['bridges']['br55']['dhcp4'])
            self.assertNotIn('renderer', yml['network'])

    def test_set_empty_origin_hint(self):
        with self.assertRaises(Exception) as context:
            self._set(['ethernets.eth0.dhcp4=true', '--origin-hint='])
        self.assertTrue('Invalid/empty origin-hint' in str(context.exception))

    def test_set_empty_hint_file(self):
        empty_file = os.path.join(self.workdir.name, 'etc', 'netplan', '00-empty.yaml')
        open(empty_file, 'w').close()  # touch 00-empty.yaml
        self._set(['ethernets.eth0.dhcp4=true', '--origin-hint=00-empty'])
        self.assertTrue(os.path.isfile(empty_file))
        with open(empty_file, 'r') as f:
            self.assertTrue(yaml.safe_load(f)['network']['ethernets']['eth0']['dhcp4'])

    def test_set_empty_hint_file_whitespace(self):
        empty_file = os.path.join(self.workdir.name, 'etc', 'netplan', '00-empty.yaml')
        with open(empty_file, 'w') as f:
            f.write('\n')  # echo "" > 00-empty.yaml
        self._set(['ethernets.eth0=null', '--origin-hint=00-empty'])
        self.assertFalse(os.path.isfile(empty_file))

    def test_set_network_null_hint(self):
        not_a_file = os.path.join(self.workdir.name, 'etc', 'netplan', '00-no-exist.yaml')
        self._set(['network=null', '--origin-hint=00-no-exist'])
        self.assertFalse(os.path.isfile(not_a_file))

    def test_unset_non_existing_hint(self):
        not_a_file = os.path.join(self.workdir.name, 'etc', 'netplan', '00-no-exist.yaml')
        self._set(['network.ethernets=null', '--origin-hint=00-no-exist'])
        self.assertFalse(os.path.isfile(not_a_file))

    def test_set_network_null_hint_rm(self):
        some_hint = os.path.join(self.workdir.name, 'etc', 'netplan', '00-some-hint.yaml')
        with open(some_hint, 'w') as f:
            f.write('network: {ethernets: {eth0: {dhcp4: true}}}')
        with open(self.path, 'w') as f:
            f.write('network: {version: 2}')
        self._set(['network=null', '--origin-hint=00-some-hint'])
        self.assertFalse(os.path.isfile(some_hint))  # the hint file is deleted
        self.assertTrue(os.path.isfile(self.path))   # any other YAML still exists

    def test_set_network_null_global(self):
        some_hint = os.path.join(self.workdir.name, 'etc', 'netplan', '00-some-hint.yaml')
        with open(some_hint, 'w') as f:
            f.write('network: {ethernets: {eth0: {dhcp4: true}}}')
        with open(self.path, 'w') as f:
            f.write('network: {version: 2}')
        self._set(['network=null'])
        any_yaml = glob.glob(os.path.join(self.workdir.name, 'etc', 'netplan', '*.yaml'))
        self.assertEqual(any_yaml, [])
        self.assertFalse(os.path.isfile(self.path))
        self.assertFalse(os.path.isfile(some_hint))

    def test_set_no_netdefs_just_globals(self):  # LP: #2027584
        keepme1 = os.path.join(self.workdir.name, 'etc', 'netplan',
                               '00-no-netdefs-just-renderer.yaml')
        with open(keepme1, 'w') as f:
            f.write('''network: {renderer: NetworkManager}''')
        keepme2 = os.path.join(self.workdir.name, 'etc', 'netplan',
                               '00-no-netdefs-just-version.yaml')
        with open(keepme2, 'w') as f:
            f.write('''network: {version: 2}''')
        deleteme = os.path.join(self.workdir.name, 'etc', 'netplan',
                                '90-some-netdefs.yaml')
        with open(deleteme, 'w') as f:
            f.write('''network: {ethernets: {eth99: {dhcp4: true}}}''')

        self._set(['ethernets.eth99=NULL'])
        self.assertFalse(os.path.isfile(deleteme))
        self.assertTrue(os.path.isfile(keepme1))
        with open(keepme1, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertEqual('NetworkManager', yml['network']['renderer'])
        # XXX: It's probably fine to delete a file that just contains "version: 2"
        #      Or is it? And what about other globals, such as OVS ports?
        self.assertFalse(os.path.isfile(keepme2))

    def test_set_clear_netdefs_keep_globals(self):  # LP: #2027584
        keep = os.path.join(self.workdir.name, 'etc', 'netplan', '00-keep.yaml')
        with open(keep, 'w') as f:
            f.write('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    br54:
      addresses: [1.2.3.4/24]
''')
        self._set(['network.bridges.br54=NULL'])
        self.assertTrue(os.path.isfile(keep))
        with open(keep, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertEqual(2, yml['network']['version'])
            self.assertEqual('NetworkManager', yml['network']['renderer'])
            self.assertNotIn('bridges', yml['network'])
        default = os.path.join(self.workdir.name, 'etc', 'netplan', FALLBACK_FILENAME)
        self.assertFalse(os.path.isfile(default))

    def test_set_clear_netdefs_keep_globals_default_renderer(self):
        keep = os.path.join(self.workdir.name, 'etc', 'netplan', '00-keep.yaml')
        with open(keep, 'w') as f:
            f.write('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    br54:
      addresses: [1.2.3.4/24]
''')
        default = os.path.join(self.workdir.name, 'etc', 'netplan', FALLBACK_FILENAME)
        with open(default, 'w') as f:
            f.write('''network:
  renderer: networkd
''')
        self._set(['network.bridges.br54=NULL'])
        self.assertTrue(os.path.isfile(keep))
        with open(keep, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertEqual(2, yml['network']['version'])
            self.assertEqual('NetworkManager', yml['network']['renderer'])
            self.assertNotIn('bridges', yml['network'])
        self.assertTrue(os.path.isfile(default))
        with open(default, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertEqual(2, yml['network']['version'])
            self.assertEqual('networkd', yml['network']['renderer'])

    def test_set_invalid(self):
        with self.assertRaises(Exception) as context:
            self._set(['xxx.yyy=abc'])
        self.assertIn('unknown key \'xxx\'', str(context.exception))
        self.assertFalse(os.path.isfile(self.path))

    def test_set_invalid_validation(self):
        with self.assertRaises(Exception) as context:
            self._set(['ethernets.eth0.set-name=myif0'])
        self.assertIn('eth0: \'set-name:\' requires \'match:\' properties', str(context.exception))
        self.assertFalse(os.path.isfile(self.path))

    def test_set_invalid_validation2(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  tunnels:
    tun0:
      mode: sit
      local: 1.2.3.4
      remote: 5.6.7.8''')
        with self.assertRaises(NetplanException) as context:
            self._set(['tunnels.tun0.keys.input=12345'])
        self.assertIn('tun0: \'input-key\' is not required for this tunnel type', str(context.exception))

    def test_set_append(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        self._set(['ethernets.eth0.dhcp4=true'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
            self.assertIn('ens3', out['network']['ethernets'])
            self.assertIn('eth0', out['network']['ethernets'])
            self.assertIs(True, out['network']['ethernets']['ens3']['dhcp4'])
            self.assertIs(True, out['network']['ethernets']['eth0']['dhcp4'])
            self.assertEqual(2, out['network']['version'])

    def test_set_overwrite_eq(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  ethernets:
    ens3: {dhcp4: "yes"}''')
        self._set(['ethernets.ens3.dhcp4=yes'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            self.assertIs(
                    True,
                    yaml.safe_load(f)['network']['ethernets']['ens3']['dhcp4'])

    def test_set_overwrite(self):
        p = os.path.join(self.workdir.name, 'etc', 'netplan', 'test.yaml')
        with open(p, 'w') as f:
            f.write('''network:
  renderer: networkd
  ethernets:
    ens3: {dhcp4: "no"}''')
        self._set(['ethernets.ens3.dhcp4=true'])
        self.assertTrue(os.path.isfile(p))
        with open(p, 'r') as f:
            yml = yaml.safe_load(f)
            self.assertIs(True, yml['network']['ethernets']['ens3']['dhcp4'])
            self.assertEqual('networkd', yml['network']['renderer'])

    def test_set_delete(self):
        with open(self.path, 'w') as f:
            f.write('''network:\n  version: 2\n  renderer: NetworkManager
  ethernets:
    ens3: {dhcp4: yes, dhcp6: yes}
    eth0: {addresses: [1.2.3.4/24]}
    eth1: {addresses: [2.3.4.5/24]}
    ''')
        self._set(['ethernets.eth0.addresses=NULL'])
        self._set(['ethernets.ens3.dhcp6=null'])
        self._set(['ethernets.eth1=NULL'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
            self.assertIn('ethernets', out['network'])
            self.assertEqual(2, out['network']['version'])
            self.assertIs(True, out['network']['ethernets']['ens3']['dhcp4'])
            self.assertNotIn('dhcp6', out['network']['ethernets']['ens3'])
            self.assertNotIn('eth0', out['network']['ethernets'])
            self.assertNotIn('eth1', out['network']['ethernets'])

    def test_set_delete_subtree(self):
        with open(self.path, 'w') as f:
            f.write('''network:\n  version: 2\n  renderer: NetworkManager
  ethernets:
    eth0: {addresses: [1.2.3.4/24]}''')
        self._set(['network.ethernets=null'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
        self.assertIn('network', out)
        self.assertEqual(2, out['network']['version'])
        self.assertEqual('NetworkManager', out['network']['renderer'])
        self.assertNotIn('ethernets', out['network'])

    def test_set_global_ovs(self):
        with open(self.path, 'w') as f:
            f.write('''network:\n  version: 2
  ethernets:
    eth0: {addresses: [1.2.3.4/24]}''')
        self._set(['network.openvswitch={"ports": [[port1, port2]], "other-config": null}'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
        self.assertIn('network', out)
        self.assertEqual(2, out['network']['version'])
        self.assertEqual('1.2.3.4/24', out['network']['ethernets']['eth0']['addresses'][0])
        self.assertNotIn('other-config', out['network']['openvswitch'])
        self.assertSequenceEqual(['port1', 'port2'], out['network']['openvswitch']['ports'][0])

    def test_set_delete_access_point(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  wifis:
    wl0:
      access-points:
        "Joe's Home":
          password: "s0s3kr1t"
          bssid: 00:11:22:33:44:55
          band: 2.4GHz
          channel: 11
        workplace:
          password: "c0mpany1"
          bssid: de:ad:be:ef:ca:fe
          band: 5GHz
          channel: 100
        peer2peer:
          mode: adhoc''')
        self._set(['network.wifis.wl0.access-points.Joe\'s Home=null'])
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
        self.assertNotIn('Joe\'s Home', out['network']['wifis']['wl0']['access-points'])

    def test_set_delete_nm_passthrough(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  wifis:
    wlan0:
      renderer: NetworkManager
      dhcp4: true
      macaddress: "00:11:22:33:44:55"
      access-points:
        "SOME-SSID":
          bssid: "de:ad:be:ef:ca:fe"
          networkmanager:
            name: "myid with spaces"
            passthrough:
              connection.permissions: ""
              ipv4.dns-search: ""''')
        ap_key = 'network.wifis.wlan0.access-points.SOME-SSID'
        self._set([ap_key+'.networkmanager.passthrough.connection\\.permissions=null'])
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
        ap = out['network']['wifis']['wlan0']['access-points']['SOME-SSID']
        self.assertNotIn('connection.permissions', ap['networkmanager']['passthrough'])
        self.assertEqual('', ap['networkmanager']['passthrough']['ipv4.dns-search'])

    def test_set_delete_bridge_subparams(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eno1: {}
    eno2: {}
    switchports:
      match:
        driver: yayroute
  bridges:
    br0:
      interfaces: [eno1, eno2, switchports]
      parameters:
        path-cost:
          eno1: 70
          eno2: 80
        port-priority:
          eno1: 14
          eno2: 15''')

        self._set(['network.bridges.br0.parameters={path-cost: {eno1: null}, port-priority: {eno2: null}}'])

        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
        self.assertNotIn('eno1', out['network']['bridges']['br0']['parameters']['path-cost'])
        self.assertEqual(80, out['network']['bridges']['br0']['parameters']['path-cost']['eno2'])

        self.assertNotIn('eno2', out['network']['bridges']['br0']['parameters']['port-priority'])
        self.assertEqual(14, out['network']['bridges']['br0']['parameters']['port-priority']['eno1'])

    @unittest.skipIf(not os.path.exists(OPENVSWITCH_OVS_VSCTL),
                     'OpenVSwitch not installed')
    def test_set_delete_ovs_other_config(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      openvswitch:
        other-config:
          bogus-option: bogus
          disable-in-band: true
      dhcp6: true
  bridges:
    ovs0:
      interfaces: [eth0]
      openvswitch: {}
''')
        self._set(['ethernets.eth0.openvswitch.other-config.bogus-option=null'])

        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
        self.assertNotIn('bogus-option', out['network']['ethernets']['eth0']['openvswitch']['other-config'])
        self.assertTrue(out['network']['ethernets']['eth0']['openvswitch']['other-config']['disable-in-band'])

    def test_set_delete_file(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  ethernets:
    ens3: {dhcp4: yes}''')
        self._set(['network.ethernets.ens3.dhcp4=NULL'])
        # The file should be deleted if this was the last/only key left
        self.assertFalse(os.path.isfile(self.path))

    def test_set_delete_file_with_version(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        self._set(['network.ethernets.ens3=NULL'])
        # The file should be deleted if only "network: {version: 2}" is left
        self.assertFalse(os.path.isfile(self.path))

    def test_set_invalid_delete(self):
        with open(self.path, 'w') as f:
            f.write('''network:\n  version: 2\n  renderer: NetworkManager
  ethernets:
    eth0: {addresses: [1.2.3.4]}''')
        with self.assertRaises(Exception) as context:
            self._set(['ethernets.eth0.addresses'])
        self.assertEqual('Invalid value specified', str(context.exception))

    def test_set_escaped_dot(self):
        self._set([r'ethernets.eth0\.123.dhcp4=false'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
            self.assertIs(False, out['network']['ethernets']['eth0.123']['dhcp4'])

    def test_set_invalid_input(self):
        with self.assertRaises(Exception) as context:
            self._set([r'ethernets.eth0={dhcp4:false}'])
        self.assertIn(
                "unknown key 'dhcp4:false'",
                str(context.exception))

    def test_set_override_existing_file(self):
        override = os.path.join(self.workdir.name, 'etc', 'netplan', 'some-file.yaml')
        with open(override, 'w') as f:
            f.write(r'network: {ethernets: {eth0: {dhcp4: true}, eth1: {dhcp6: false}}}')
        self._set([r'ethernets.eth0.dhcp4=false'])
        self.assertFalse(os.path.isfile(self.path))
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            out = yaml.safe_load(f)
            self.assertIs(False, out['network']['ethernets']['eth0']['dhcp4'])
            self.assertIs(False, out['network']['ethernets']['eth1']['dhcp6'])

    def test_set_override_existing_file_escaped_dot(self):
        override = os.path.join(self.workdir.name, 'etc', 'netplan', 'some-file.yaml')
        with open(override, 'w') as f:
            f.write(r'network: {ethernets: {eth0.123: {dhcp4: true}}}')
        self._set([r'ethernets.eth0\.123.dhcp4=false'])
        self.assertFalse(os.path.isfile(self.path))
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            out = yaml.safe_load(f)
            self.assertIs(False, out['network']['ethernets']['eth0.123']['dhcp4'])

    def test_set_override_multiple_existing_files(self):
        file1 = os.path.join(self.workdir.name, 'etc', 'netplan', 'eth0.yaml')
        with open(file1, 'w') as f:
            f.write(r'network: {ethernets: {eth0.1: {dhcp4: true}, eth0.2: {dhcp4: true}}}')
        file2 = os.path.join(self.workdir.name, 'etc', 'netplan', 'eth1.yaml')
        with open(file2, 'w') as f:
            f.write(r'network: {ethernets: {eth1: {dhcp4: true}}}')
        self._set([(r'network={"renderer": "NetworkManager", "version":2,'
                    r'"ethernets":{'
                    r'"eth1":{"dhcp4":false},'
                    r'"eth0.1":{"dhcp4":false},'
                    r'"eth0.2":{"dhcp4":false}},'
                    r'"bridges":{'
                    r'"br99":{"dhcp4":false}}}')])
        self.assertTrue(os.path.isfile(file1))
        with open(file1, 'r') as f:
            self.assertIs(False, yaml.safe_load(f)['network']['ethernets']['eth0.1']['dhcp4'])
        self.assertTrue(os.path.isfile(file2))
        with open(file2, 'r') as f:
            self.assertIs(False, yaml.safe_load(f)['network']['ethernets']['eth1']['dhcp4'])
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, 'r') as f:
            out = yaml.safe_load(f)
            self.assertIs(False, out['network']['bridges']['br99']['dhcp4'])
            self.assertEqual(2, out['network']['version'])
            self.assertEqual('NetworkManager', out['network']['renderer'])


class TestGet(unittest.TestCase):
    '''Test netplan get'''
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.file = '00-config.yaml'
        self.path = os.path.join(self.workdir.name, 'etc', 'netplan', self.file)
        os.makedirs(os.path.join(self.workdir.name, 'etc', 'netplan'))

    def _get(self, args):
        args.insert(0, 'get')
        return call_cli(args + ['--root-dir', self.workdir.name])

    def test_get_scalar(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        out = self._get(['ethernets.ens3.dhcp4'])
        self.assertIn('true', out)

    def test_get_mapping(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3:
      dhcp4: yes
      addresses: [1.2.3.4/24, 5.6.7.8/24]''')
        out = yaml.safe_load(self._get(['ethernets']))
        self.assertDictEqual({'ens3': {'addresses': ['1.2.3.4/24', '5.6.7.8/24'], 'dhcp4': True}}, out)

    def test_get_modems(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  modems:
    wwan0:
      apn: internet
      pin: 1234
      dhcp4: yes
      addresses: [1.2.3.4/24, 5.6.7.8/24]''')
        out = yaml.safe_load(self._get(['modems.wwan0']))
        self.assertDictEqual({
                'addresses': ['1.2.3.4/24', '5.6.7.8/24'],
                'apn': 'internet',
                'dhcp4': True,
                'pin': '1234'
            }, out)

    def test_get_sequence(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {addresses: [1.2.3.4/24, 5.6.7.8/24]}''')
        out = yaml.safe_load(self._get(['network.ethernets.ens3.addresses']))
        self.assertSequenceEqual(['1.2.3.4/24', '5.6.7.8/24'], out)

    def test_get_null(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    ens3: {dhcp4: yes}''')
        out = self._get(['ethernets.eth0.dhcp4'])
        self.assertEqual('null\n', out)

    def test_get_escaped_dot(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0.123: {dhcp4: yes}''')
        out = self._get([r'ethernets.eth0\.123.dhcp4'])
        self.assertEqual('true\n', out)

    def test_get_all(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0: {dhcp4: yes}''')
        out = yaml.safe_load(self._get([]))
        self.assertDictEqual({'network': {
                'ethernets': {'eth0': {'dhcp4': True}},
                'version': 2,
                }
            }, out)

    def test_get_network(self):
        with open(self.path, 'w') as f:
            f.write('network:\n  version: 2\n  renderer: NetworkManager')
        os.chmod(self.path, mode=0o600)
        out = yaml.safe_load(self._get(['network']))
        self.assertDictEqual({'renderer': 'NetworkManager', 'version': 2}, out)

    def test_get_bad_network(self):
        with open(self.path, 'w') as f:
            f.write('network:\n  version: 2\n  renderer: NetworkManager')
        out = yaml.safe_load(self._get(['networkINVALID']))
        self.assertIsNone(out)

    def test_get_yaml_document_end_failure(self):
        with open(self.path, 'w') as f:
            f.write('''network:
  ethernets:
    eth0:
      match:
        name: "test"
      mtu: 9000
      set-name: "yo"
      dhcp4: true
      virtual-function-count: 2
''')
        # this shall not throw any (YAML DOCUMENT-END) exception
        out = yaml.safe_load(self._get(['ethernets.eth0']))
        self.assertListEqual(['match', 'dhcp4', 'set-name', 'mtu', 'virtual-function-count'], list(out))
