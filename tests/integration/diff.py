#!/usr/bin/python3
# Netplan Diff integration tests.
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2023 Canonical, Ltd.
# Author: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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

import json
import sys
import subprocess
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def test_missing_netplan_ips(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:
    dummy0:
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})
        self.generate_and_settle(['dummy0'])

        subprocess.call(['ip', 'addr', 'add', '1.2.3.4/24', 'dev', 'dummy0'])
        subprocess.call(['ip', 'addr', 'add', '1.2.3.40/24', 'dev', 'dummy0'])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_ips = diff['interfaces']['dummy0']['netplan_state'].get('missing_addresses')
        self.assertIn('1.2.3.4/24', diff_ips)
        self.assertIn('1.2.3.40/24', diff_ips)

    def test_missing_system_ips(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:
    dummy0:
      addresses:
        - 1.2.3.4/24
        - 1.2.3.40/24
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})
        self.generate_and_settle(['dummy0'])

        subprocess.call(['ip', 'addr', 'del', '1.2.3.4/24', 'dev', 'dummy0'])
        subprocess.call(['ip', 'addr', 'del', '1.2.3.40/24', 'dev', 'dummy0'])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_ips = diff['interfaces']['dummy0']['system_state'].get('missing_addresses', [])
        self.assertIn('1.2.3.4/24', diff_ips)
        self.assertIn('1.2.3.40/24', diff_ips)

    def test_missing_sytem_ips_with_match(self):
        self.setup_eth(None)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  ethernets:
    mynic:
      match: {name: %(e2c)s}
      addresses:
        - 1.2.3.4/24
        - 1.2.3.40/24
      dhcp6: false
      dhcp4: false''' % {'r': self.backend, 'e2c': self.dev_e2_client})
        self.generate_and_settle([self.dev_e2_client])

        subprocess.call(['ip', 'addr', 'del', '1.2.3.4/24', 'dev', self.dev_e2_client])
        subprocess.call(['ip', 'addr', 'del', '1.2.3.40/24', 'dev', self.dev_e2_client])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_ips = diff['interfaces'][self.dev_e2_client]['system_state'].get('missing_addresses', [])
        netdef_id = diff['interfaces'][self.dev_e2_client]['id']
        self.assertIn('1.2.3.4/24', diff_ips)
        self.assertIn('1.2.3.40/24', diff_ips)
        self.assertEqual(netdef_id, 'mynic')

    def test_missing_interfaces(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy1'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  ethernets:
    eth123456:
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})

        # Add an extra interface not present in any YAML
        subprocess.check_call(['ip', 'link', 'add', 'type', 'dummy', 'dev', 'dummy1'])
        subprocess.check_call(['ip', 'link', 'add', 'type', 'dummy', 'dev', 'dummy1'])
        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        missing_system = diff.get('missing_interfaces_system', {})
        missing_netplan = diff.get('missing_interfaces_netplan', {})
        self.assertIn('dummy1', missing_netplan)
        self.assertIn('eth123456', missing_system)

    def test_missing_system_nameservers_addresses(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:
    dummy0:
      nameservers:
        addresses:
          - 1.1.1.1
          - 8.8.8.8
      addresses:
        - 1.2.3.4/24
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})
        self.generate_and_settle(['dummy0'])

        subprocess.call(['resolvectl', 'dns', 'dummy0', '8.8.8.8'])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_dns = diff['interfaces']['dummy0']['system_state'].get('missing_nameservers_addresses', [])
        self.assertIn('1.1.1.1', diff_dns)

    def test_missing_netplan_nameservers_addresses(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:
    dummy0:
      nameservers:
        addresses:
          - 1.1.1.1
      addresses:
        - 1.2.3.4/24
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})
        self.generate_and_settle(['dummy0'])

        subprocess.call(['resolvectl', 'dns', 'dummy0', '1.1.1.1', '8.8.8.8'])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_dns = diff['interfaces']['dummy0']['netplan_state'].get('missing_nameservers_addresses', [])
        self.assertIn('8.8.8.8', diff_dns)

    def test_missing_system_nameservers_search(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:
    dummy0:
      nameservers:
        addresses:
          - 1.1.1.1
          - 8.8.8.8
        search:
          - mynet.local
          - mydomain.local
      addresses:
        - 1.2.3.4/24
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})
        self.generate_and_settle(['dummy0'])

        subprocess.call(['resolvectl', 'domain', 'dummy0', 'mynet.local'])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_dns = diff['interfaces']['dummy0']['system_state'].get('missing_nameservers_search', [])
        self.assertIn('mydomain.local', diff_dns)

    def test_missing_netplan_nameservers_search(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:
    dummy0:
      nameservers:
        search:
          - mynet.local
        addresses:
          - 1.1.1.1
      addresses:
        - 1.2.3.4/24
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})
        self.generate_and_settle(['dummy0'])

        subprocess.call(['resolvectl', 'domain', 'dummy0', 'mynet.local', 'mydomain.local'])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_dns = diff['interfaces']['dummy0']['netplan_state'].get('missing_nameservers_search', [])
        self.assertIn('mydomain.local', diff_dns)

    def test_missing_netplan_route(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:
    dummy0:
      addresses:
        - 1.2.3.4/24
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})
        self.generate_and_settle(['dummy0'])

        subprocess.call(['ip', 'route', 'add', '3.2.1.0/24', 'via', '1.2.3.4'])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_routes = diff['interfaces']['dummy0']['netplan_state'].get('missing_routes', [])
        self.assertEqual(len(diff_routes), 1)
        route = diff_routes[0]
        self.assertEqual('3.2.1.0/24', route['to'])
        self.assertEqual('1.2.3.4', route['via'])
        self.assertEqual(2, route['family'])

    def test_missing_system_route(self):
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', 'dummy0'], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
  renderer: %(r)s
  version: 2
  dummy-devices:
    dummy0:
      routes:
        - to: 3.2.1.0/24
          via: 1.2.3.4
      addresses:
        - 1.2.3.4/24
      dhcp4: false
      dhcp6: false''' % {'r': self.backend})
        self.generate_and_settle(['dummy0'])

        subprocess.call(['ip', 'route', 'del', '3.2.1.0/24', 'via', '1.2.3.4'])

        diff = json.loads(subprocess.check_output(['netplan', 'status', '--diff', '-f', 'json']))
        diff_routes = diff['interfaces']['dummy0']['system_state'].get('missing_routes', [])
        self.assertEqual(len(diff_routes), 1)
        route = diff_routes[0]
        self.assertEqual('3.2.1.0/24', route['to'])
        self.assertEqual('1.2.3.4', route['via'])
        self.assertEqual(2, route['family'])


@unittest.skipIf("networkd" not in test_backends,
                 "skipping as networkd backend tests are disabled")
class TestNetworkd(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


@unittest.skipIf("NetworkManager" not in test_backends,
                 "skipping as NetworkManager backend tests are disabled")
class TestNetworkManager(IntegrationTestsBase, _CommonTests):
    backend = 'NetworkManager'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
