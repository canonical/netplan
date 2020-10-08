#!/usr/bin/python3
# Tunnel integration tests. NM and networkd are started on the generated
# configuration, using emulated ethernets (veth).
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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
import time
import unittest

from base import IntegrationTestsBase, test_backends

class _CommonTests():

    def test_tunnel_sit(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'sit-tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  tunnels:
    sit-tun0:
      mode: sit
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface('sit-tun0', ['sit-tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])

    def test_tunnel_ipip(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  tunnels:
    tun0:
      mode: ipip
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])

    def test_tunnel_wireguard(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'wg0'], stderr=subprocess.DEVNULL)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'wg1'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
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
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        time.sleep(2)  # Give some time for handshake/connection between client & server
        # Verify server
        out = subprocess.check_output(['wg', 'show', 'wg0', 'private-key'], universal_newlines=True)
        self.assertIn("4GgaQCy68nzNsUE5aJ9fuLzHhB65tAlwbmA72MWnOm8=", out)
        out = subprocess.check_output(['wg', 'show', 'wg0', 'preshared-keys'], universal_newlines=True)
        self.assertIn("7voRZ/ojfXgfPOlswo3Lpma1RJq7qijIEEUEMShQFV8=", out)
        out = subprocess.check_output(['wg', 'show', 'wg0'], universal_newlines=True)
        self.assertIn("public key: rlbInAj0qV69CysWPQY7KEBnKxpYCpaWqOs/dLevdWc=", out)
        self.assertIn("listening port: 51820", out)
        self.assertIn("fwmark: 0x2a", out)
        self.assertIn("peer: M9nt4YujIOmNrRmpIRTmYSfMdrpvE7u6WkG8FY8WjG4=", out)
        self.assertIn("allowed ips: 20.20.20.0/24", out)
        self.assertRegex(out, r'latest handshake: \d+ seconds? ago')
        self.assertRegex(out, r'transfer: \d+ B received, \d+ B sent')
        self.assert_iface('wg0', ['inet 10.10.10.20/24'])
        # Verify client
        out = subprocess.check_output(['wg', 'show', 'wg1', 'private-key'], universal_newlines=True)
        self.assertIn("KPt9BzQjejRerEv8RMaFlpsD675gNexELOQRXt/AcH0=", out)
        out = subprocess.check_output(['wg', 'show', 'wg1', 'preshared-keys'], universal_newlines=True)
        self.assertIn("7voRZ/ojfXgfPOlswo3Lpma1RJq7qijIEEUEMShQFV8=", out)
        out = subprocess.check_output(['wg', 'show', 'wg1'], universal_newlines=True)
        self.assertIn("public key: M9nt4YujIOmNrRmpIRTmYSfMdrpvE7u6WkG8FY8WjG4=", out)
        self.assertIn("peer: rlbInAj0qV69CysWPQY7KEBnKxpYCpaWqOs/dLevdWc=", out)
        self.assertIn("endpoint: 10.10.10.20:51820", out)
        self.assertIn("allowed ips: 0.0.0.0/0", out)
        self.assertIn("persistent keepalive: every 21 seconds", out)
        self.assertRegex(out, r'latest handshake: (\d+ seconds? ago|Now)')
        self.assertRegex(out, r'transfer: \d+ B received, \d+ B sent')
        self.assert_iface('wg1', ['inet 20.20.20.10/24'])


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'

    def test_tunnel_gre(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  tunnels:
    tun0:
      mode: gre
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])

    def test_tunnel_gre6(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  tunnels:
    tun0:
      mode: ip6gre
      local: fe80::1
      remote: 2001:dead:beef::2
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface('tun0', ['tun0@NONE', 'link.* fe80::1 brd 2001:dead:beef::2'])

    def test_tunnel_vti(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  tunnels:
    tun0:
      mode: vti
      keys: 1234
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])

    def test_tunnel_vti6(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  tunnels:
    tun0:
      mode: vti6
      keys: 1234
      local: fe80::1
      remote: 2001:dead:beef::2
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface('tun0', ['tun0@NONE', 'link.* fe80::1 brd 2001:dead:beef::2'])


@unittest.skipIf("NetworkManager" not in test_backends,
                     "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'

    def test_tunnel_gre(self):
        self.setup_eth(None)
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'tun0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    ethbn:
      match: {name: %(ec)s}
    ethb2:
      match: {name: %(e2c)s}
  tunnels:
    tun0:
      mode: gre
      keys: 1234
      local: 192.168.5.1
      remote: 99.99.99.99
''' % {'r': self.backend, 'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        self.assert_iface('tun0', ['tun0@NONE', 'link.* 192.168.5.1 peer 99.99.99.99'])


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
