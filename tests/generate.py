#!/usr/bin/python3

import os
import sys
import tempfile
import subprocess
import unittest

exe_generate = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'ubuntu-network-generate')


class T(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.networkd_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'network')

    def generate(self, yaml, expect_fail=False):
        '''Call generate with given YAML string as configuration

        Return stderr output.
        '''
        conf = os.path.join(self.workdir.name, 'config')
        with open(conf, 'w') as f:
            f.write(yaml)

        p = subprocess.Popen([exe_generate, conf, self.workdir.name],
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
        self.assertEqual(set(os.listdir(self.workdir.name)), {'config', 'run'})
        self.assertEqual(set(os.listdir(self.networkd_dir)),
                         set(file_contents_map))
        for fname, contents in file_contents_map.items():
            with open(os.path.join(self.networkd_dir, fname)) as f:
                self.assertEqual(f.read(), contents)

    #
    # Trivial cases
    #

    @unittest.skip('need to define and implement default config location')
    def test_no_files(self):
        subprocess.check_call([exe_generate, '--root', self.workdir.name])
        self.assertEqual(os.listdir(self.workdir.name), [])

    def test_no_configs(self):
        self.generate('network:\n  version: 2')
        # should not write any files
        self.assertEqual(os.listdir(self.workdir.name), ['config'])

    #
    # networkd output
    #

    def test_eth_wol(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      wakeonlan: true''')

        self.assert_networkd({'eth0.link': '[Match]\nOriginalName=eth0\n\n[Link]\nWakeOnLan=magic\n'})

    def test_eth_match_by_driver_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        driver: ixgbe
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nDriver=ixgbe\n\n[Link]\nName=lom1\nWakeOnLan=off\n'})

    def test_eth_match_by_mac_rename(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        macaddress: 11:22:33:44:55:66
      set-name: lom1''')

        self.assert_networkd({'def1.link': '[Match]\nMACAddress=11:22:33:44:55:66\n\n[Link]\nName=lom1\nWakeOnLan=off\n'})

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

    def test_eth_match_name(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match:
        name: green
      dhcp4: true''')

        self.assert_networkd({'def1.network': '[Match]\nName=green\n\n[Network]\nDHCP=ipv4\n'})

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

    def test_eth_match_all_names(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match: {name: "*"}
      dhcp4: true''')

        self.assert_networkd({'def1.network': '[Match]\nName=*\n\n[Network]\nDHCP=ipv4\n'})

    def test_eth_match_all(self):
        self.generate('''network:
  version: 2
  ethernets:
    def1:
      match: {}
      dhcp4: true''')

        self.assert_networkd({'def1.network': '[Match]\n\n[Network]\nDHCP=ipv4\n'})

    def test_bridge_empty(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      dhcp4: true''')

        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '[Match]\nName=br0\n\n[Network]\nDHCP=ipv4\n'})

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

    #
    # Errors
    #

    def test_malformed_yaml(self):
        err = self.generate('network:\n  version', True)
        self.assertIn('/config line 1 column 2: expected mapping', err)

    def test_invalid_version(self):
        err = self.generate('network:\n  version: 1', True)
        self.assertIn('/config line 1 column 11: Only version 2 is supported', err)

    def test_duplicate_id(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    id0:
      wakeonlan: true
    id0:
      wakeonlan: true
''', True)
        self.assertIn("Duplicate net definition ID 'id0'", err)

    def test_set_name_without_match(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    def1:
      set-name: lom1
''', True)
        self.assertIn('/config line 4 column 6: def1: set-name: requires match: properties', err)

    def test_virtual_set_name(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      set_name: br1''', True)
        self.assertIn('/config line 4 column 6: unknown key set_name\n', err)

    def test_virtual_match(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      match:
        driver: foo''', True)
        self.assertIn('/config line 4 column 6: unknown key match\n', err)

    def test_bridge_unknown_iface(self):
        err = self.generate('''network:
  version: 2
  bridges:
    br0:
      interfaces: ['foo']''', True)
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
      interfaces: [eno1]''', True)
        self.assertIn('bridge br1: interface eno1 is already assigned to bridge br0\n', err)


unittest.main(testRunner=unittest.TextTestRunner(
    stream=sys.stdout, verbosity=2))
