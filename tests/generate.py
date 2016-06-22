#!/usr/bin/python3
# Blackbox tests of ubuntu-network-generate that verify that the generated
# configuration files look as expected. These are run during "make check" and
# don't touch the system configuration at all.

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

    def generate(self, yaml, expect_fail=False, extra_args=[]):
        '''Call generate with given YAML string as configuration

        Return stderr output.
        '''
        conf = os.path.join(self.workdir.name, 'etc', 'network', 'config')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as f:
            f.write(yaml)

        p = subprocess.Popen([exe_generate, '--root-dir', self.workdir.name] + extra_args,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        (out, err) = p.communicate()
        if expect_fail:
            self.assertNotEqual(p.returncode, 0)
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
                         set(file_contents_map))
        for fname, contents in file_contents_map.items():
            with open(os.path.join(networkd_dir, fname)) as f:
                self.assertEqual(f.read(), contents)

    def assert_nm(self, connections_map=None, conf=None):
        # check config
        conf_path = os.path.join(self.workdir.name, 'run', 'NetworkManager', 'conf.d', 'ubuntu-network.conf')
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
                             set(['ubuntu-network-' + n for n in connections_map]))
            for fname, contents in connections_map.items():
                with open(os.path.join(con_dir, 'ubuntu-network-' + fname)) as f:
                    self.assertEqual(f.read(), contents)
                    # NM connection files might contain secrets
                    self.assertEqual(stat.S_IMODE(os.fstat(f.fileno()).st_mode), 0o600)
        else:
            self.assertFalse(os.path.exists(con_dir))

    def assert_udev(self, contents):
        rule_path = os.path.join(self.workdir.name, 'run/udev/rules.d/90-ubuntu-network.rules')
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
        self.assertEqual(os.listdir(self.workdir.name), ['etc', 'config'])

    def test_file_args_notfound(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''', expect_fail=True, extra_args=['/non/existing/config'])
        self.assertEqual(err, 'Cannot open /non/existing/config: No such file or directory\n')
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])

    def test_help(self):
        conf = os.path.join(self.workdir.name, 'etc', 'network', 'config')
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


class TestNetworkd(TestBase):
    '''networkd output'''

    def test_eth_wol(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      wakeonlan: true''')

        self.assert_networkd({'eth0.link': '[Match]\nOriginalName=eth0\n\n[Link]\nWakeOnLan=magic\n'})
        self.assert_nm(None, '''[keyfile]
# devices managed by networkd
unmanaged-devices+=interface-name:eth0,''')
        self.assert_udev(None)

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
      dhcp4: true''')

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
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '[Match]\nName=br0\n\n[Network]\nDHCP=ipv4\n'})
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
                              'eno1.network': '[Match]\nName=eno1\n\n[Network]\nBridge=br0\n',
                              'switchports.network': '[Match]\nDriver=yayroute\n\n[Network]\nBridge=br0\n'})


class TestNetworkManager(TestBase):
    def test_eth_wol(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      wakeonlan: true''')

        self.assert_nm({'eth0': '''[connection]
id=ubuntu-network-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=1
'''})
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
id=ubuntu-network-def1
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
id=ubuntu-network-def1
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
id=ubuntu-network-engreen
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
id=ubuntu-network-def1
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
id=ubuntu-network-def1
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
id=ubuntu-network-def1
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

    # glob matching not supported with NM
    @unittest.expectedFailure
    def test_eth_match_all_names(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    def1:
      match: {name: "*"}
      dhcp4: true''')

        self.assert_nm({'def1': '''[connection]
id=ubuntu-network-def1
type=ethernet

[ethernet]
wake-on-lan=0

[ipv4]
method=auto
'''})
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
id=ubuntu-network-def1
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
id=ubuntu-network-def1
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
id=ubuntu-network-eth0
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
id=ubuntu-network-eth0
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
id=ubuntu-network-eth0
type=ethernet
interface-name=eth0

[ethernet]
wake-on-lan=0
'''})
        self.assert_networkd({})
        self.assert_udev(None)

    def test_bridge_empty(self):
        self.generate('''network:
  version: 2
  renderer: NetworkManager
  bridges:
    br0:
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=ubuntu-network-br0
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
id=ubuntu-network-br0
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
      dhcp4: true''')

        self.assert_nm({'br0': '''[connection]
id=ubuntu-network-br0
type=bridge
interface-name=br0

[ipv4]
method=auto
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
id=ubuntu-network-eno1
type=ethernet
interface-name=eno1
slave-type=bridge
master=br0

[ethernet]
wake-on-lan=0
''',
                        'switchport': '''[connection]
id=ubuntu-network-switchport
type=ethernet
interface-name=enp2s1
slave-type=bridge
master=br0

[ethernet]
wake-on-lan=0
''',
                        'br0': '''[connection]
id=ubuntu-network-br0
type=bridge
interface-name=br0

[ipv4]
method=auto
'''})
        self.assert_networkd({})
        self.assert_udev(None)


class TestConfigErrors(TestBase):
    def test_malformed_yaml(self):
        err = self.generate('network:\n  version', expect_fail=True)
        self.assertIn('/config line 1 column 2: expected mapping', err)

    def test_invalid_version(self):
        err = self.generate('network:\n  version: 1', expect_fail=True)
        self.assertIn('/config line 1 column 11: Only version 2 is supported', err)

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

    def test_set_name_without_match(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      set-name: lom1
''', expect_fail=True)
        self.assertIn('/config line 4 column 6: def1: set-name: requires match: properties', err)

    def test_virtual_set_name(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      set_name: br1''', expect_fail=True)
        self.assertIn('/config line 4 column 6: unknown key set_name\n', err)

    def test_virtual_match(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      match:
        driver: foo''', expect_fail=True)
        self.assertIn('/config line 4 column 6: unknown key match\n', err)

    def test_virtual_wol(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      wakeonlan: true''', expect_fail=True)
        self.assertIn('/config line 4 column 6: unknown key wakeonlan\n', err)

    def test_bridge_unknown_iface(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: ['foo']''', expect_fail=True)
        self.assertIn('/config line 4 column 18: bridge br0: interface foo is not defined\n', err)

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

    def test_unknown_renderer(self):
        err = self.generate('''network:
  version: 2
  renderer: bogus
''', expect_fail=True)
        self.assertIn("unknown renderer 'bogus'", err)


unittest.main(testRunner=unittest.TextTestRunner(
    stream=sys.stdout, verbosity=2))
