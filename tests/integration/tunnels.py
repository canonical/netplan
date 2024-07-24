#!/usr/bin/python3
# Tunnel integration tests. NM and networkd are started on the generated
# configuration, using emulated ethernets (veth).
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2018-2021 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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

import sys
import subprocess
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_tunnel_sit(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'sit-tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    sit-tun0:
      mode: sit
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend})
        self.generate_and_settle(['sit-tun0'])
        self.assert_iface('sit-tun0', ['sit-tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])

    def test_tunnel_sit_without_local_address(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'sit-tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    sit-tun0:
      mode: sit
      remote: 99.99.99.99
''' % {'r': self.backend})
        self.generate_and_settle(['sit-tun0'])
        self.assert_iface('sit-tun0', ['sit-tun0@NONE', 'link.* 0.0.0.0 peer 99.99.99.99'])

    def test_tunnel_ipip(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: ipip
      local: 192.168.5.1
      remote: 99.99.99.99
      ttl: 64
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])

    def test_tunnel_ipip_without_local_address(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: ipip
      remote: 99.99.99.99
      ttl: 64
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 0.0.0.0 peer 99.99.99.99'])

    def test_tunnel_wireguard(self):
        try:
            subprocess.check_call(['modprobe', 'wireguard'])
        except Exception:
            raise unittest.SkipTest("wireguard module is unavailable, can't test")

        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'wg0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'wg1'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    wg0: #server
      mode: wireguard
      addresses: [10.10.10.20/24]
      gateway4: 10.10.10.21
      key: 4GgaQCy68nzNsUE5aJ9fuLzHhB65tAlwbmA72MWnOm8=
      mark: 42
      port: 51820
      peers:
        - keys:
            public: M9nt4YujIOmNrRmpIRTmYSfMdrpvE7u6WkG8FY8WjG4=
            shared: 7voRZ/ojfXgfPOlswo3Lpma1RJq7qijIEEUEMShQFV8=
          allowed-ips: [20.20.20.10/24]
    wg1: #client
      mode: wireguard
      addresses: [20.20.20.10/24]
      gateway4: 20.20.20.11
      key: KPt9BzQjejRerEv8RMaFlpsD675gNexELOQRXt/AcH0=
      peers:
        - endpoint: 10.10.10.20:51820
          allowed-ips: [0.0.0.0/0]
          keys:
            public: rlbInAj0qV69CysWPQY7KEBnKxpYCpaWqOs/dLevdWc=
            shared: 7voRZ/ojfXgfPOlswo3Lpma1RJq7qijIEEUEMShQFV8=
          keepalive: 21
''' % {'r': self.backend})
        self.generate_and_settle(['wg0', 'wg1'])
        # Wait for handshake/connection between client & server
        self.wait_output(['wg', 'show', 'wg0'], 'latest handshake')
        self.wait_output(['wg', 'show', 'wg1'], 'latest handshake')
        # Verify server
        out = subprocess.check_output(['wg', 'show', 'wg0', 'private-key'], text=True)
        self.assertIn("4GgaQCy68nzNsUE5aJ9fuLzHhB65tAlwbmA72MWnOm8=", out)
        out = subprocess.check_output(['wg', 'show', 'wg0', 'preshared-keys'], text=True)
        self.assertIn("7voRZ/ojfXgfPOlswo3Lpma1RJq7qijIEEUEMShQFV8=", out)
        out = subprocess.check_output(['wg', 'show', 'wg0'], text=True)
        self.assertIn("public key: rlbInAj0qV69CysWPQY7KEBnKxpYCpaWqOs/dLevdWc=", out)
        self.assertIn("listening port: 51820", out)
        self.assertIn("fwmark: 0x2a", out)
        self.assertIn("peer: M9nt4YujIOmNrRmpIRTmYSfMdrpvE7u6WkG8FY8WjG4=", out)
        self.assertIn("allowed ips: 20.20.20.0/24", out)
        self.assertRegex(out, r'latest handshake: (\d+ seconds? ago|Now)')
        self.assertRegex(out, r'transfer: \d+.*B received, \d+.*B sent')
        self.assert_iface('wg0', ['inet 10.10.10.20/24'])
        # Verify client
        out = subprocess.check_output(['wg', 'show', 'wg1', 'private-key'], text=True)
        self.assertIn("KPt9BzQjejRerEv8RMaFlpsD675gNexELOQRXt/AcH0=", out)
        out = subprocess.check_output(['wg', 'show', 'wg1', 'preshared-keys'], text=True)
        self.assertIn("7voRZ/ojfXgfPOlswo3Lpma1RJq7qijIEEUEMShQFV8=", out)
        out = subprocess.check_output(['wg', 'show', 'wg1'], text=True)
        self.assertIn("public key: M9nt4YujIOmNrRmpIRTmYSfMdrpvE7u6WkG8FY8WjG4=", out)
        self.assertIn("peer: rlbInAj0qV69CysWPQY7KEBnKxpYCpaWqOs/dLevdWc=", out)
        self.assertIn("endpoint: 10.10.10.20:51820", out)
        self.assertIn("allowed ips: 0.0.0.0/0", out)
        self.assertIn("persistent keepalive: every 21 seconds", out)
        self.assertRegex(out, r'latest handshake: (\d+ seconds? ago|Now)')
        self.assertRegex(out, r'transfer: \d+.*B received, \d+.*B sent')
        self.assert_iface('wg1', ['inet 20.20.20.10/24'])

    def test_tunnel_gre(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: gre
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])

    def test_tunnel_gre_without_local_address(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: gre
      remote: 99.99.99.99
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 0.0.0.0 peer 99.99.99.99'])

    def test_tunnel_gre6(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: ip6gre
      local: fe80::1
      remote: 2001:dead:beef::2
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* fe80::1 brd 2001:dead:beef::2'])

    def test_tunnel_gre_with_keys(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: gre
      keys:
        input: 1234
        output: 5678
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])
        out = subprocess.check_output(['ip', 'tunnel', 'show', 'tun0'], text=True)
        self.assertIn("ikey 1234 okey 5678", out)

    def test_tunnel_gre6_with_keys(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: ip6gre
      key: 1234
      local: fe80::1
      remote: 2001:dead:beef::2
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* fe80::1 brd 2001:dead:beef::2'])
        out = subprocess.check_output(['ip', '-6', 'tunnel', 'show', 'tun0'], text=True)
        self.assertIn("key 1234", out)

    def test_tunnel_vxlan(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'vx0'], stderr=subprocess.DEVNULL)
        self.setup_eth(None, False)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    vx0:
      mode: vxlan
      id: 1337
      link: %(ec)s
      local: 10.10.10.42
      remote: 224.0.0.5 # multicast group
      ttl: 64
      aging: 100
      port: 4567
      port-range: [4000, 4200]
      mac-learning: false
      short-circuit: true
      notifications: [l2-miss, l3-miss]
      checksums: [udp, zero-udp6-tx, zero-udp6-rx, remote-tx, remote-rx] # sd-networkd only
  ethernets:
    %(ec)s:
        addresses: [10.10.10.42/24]
''' % {'r': self.backend, 'ec': self.dev_e_client})
        self.generate_and_settle([self.dev_e_client, 'vx0'])
        self.assert_iface('vx0', ['vxlan ', ' id 1337 ', ' group 224.0.0.5 ',
                                  ' local 10.10.10.42 ', ' srcport 4000 4200 ',
                                  ' dev %s ' % self.dev_e_client,
                                  ' dstport 4567 ', ' rsc ', ' l2miss ',
                                  ' l3miss ', ' ttl 64 ', ' ageing 100 '])
        if self.backend == 'networkd':
            # checksums are not supported on the NetworkManager backend
            json = self.iface_json('vx0')
            data = json.get('linkinfo', {}).get('info_data', {})
            self.assertTrue(data.get('udp_csum'))
            self.assertTrue(data.get('udp_zero_csum6_tx'))
            self.assertTrue(data.get('udp_zero_csum6_rx'))
            self.assertTrue(data.get('remcsum_tx'))
            self.assertTrue(data.get('remcsum_rx'))


@unittest.skipIf("networkd" not in test_backends,
                 "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    def test_tunnel_vti(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: vti
      keys: 1234
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])

    def test_tunnel_vti6(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: vti6
      keys: 1234
      local: fe80::1
      remote: 2001:dead:beef::2
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        self.assert_iface('tun0', ['tun0@NONE', 'link.* fe80::1 brd 2001:dead:beef::2'])

    def test_tunnel_gretap_with_keys(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: gretap
      keys:
        input: 1.2.3.4
        output: 5.6.7.8
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        out = subprocess.check_output(['ip', '-details', 'link', 'show', 'tun0'], text=True)
        self.assertIn("gretap remote 99.99.99.99 local 192.168.5.1", out)
        self.assertIn("ikey 1.2.3.4 okey 5.6.7.8", out)

    def test_tunnel_gretap6_with_keys(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  tunnels:
    tun0:
      mode: ip6gretap
      keys: 1.2.3.4
      local: fe80::1
      remote: 2001:dead:beef::2
''' % {'r': self.backend})
        self.generate_and_settle(['tun0'])
        out = subprocess.check_output(['ip', '-details', 'link', 'show', 'tun0'], text=True)
        self.assertIn("gretap remote 2001:dead:beef::2 local fe80::1", out)
        self.assertIn("ikey 1.2.3.4 okey 1.2.3.4", out)


@unittest.skipIf("NetworkManager" not in test_backends,
                 "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
