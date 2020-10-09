#!/usr/bin/python3
#
# Integration tests for bonds
#
# These need to be run in a VM and do change the system
# configuration.
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

import sys
import subprocess
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    def _collect_ovs_settings(self, bridge0):
        d = {}
        d['show'] = subprocess.check_output(['ovs-vsctl', 'show'])
        d['ssl'] = subprocess.check_output(['ovs-vsctl', 'get-ssl'])
        # Get external-ids
        for tbl in ('Open_vSwitch', 'Controller', 'Bridge', 'Port', 'Interface'):
            cols = 'name,external-ids'
            if tbl == 'Open_vSwitch':
                cols = 'external-ids'
            elif tbl == 'Controller':
                cols = '_uuid,external-ids'
            d['external-ids-%s' % tbl] = subprocess.check_output(['ovs-vsctl', '--columns=%s' % cols, '-f', 'csv', '-d',
                                                                  'bare', '--no-headings', 'list', tbl])
        # Get other-config
        for tbl in ('Open_vSwitch', 'Bridge', 'Port', 'Interface'):
            cols = 'name,other-config'
            if tbl == 'Open_vSwitch':
                cols = 'other-config'
            d['other-config-%s' % tbl] = subprocess.check_output(['ovs-vsctl', '--columns=%s' % cols, '-f', 'csv', '-d',
                                                                  'bare', '--no-headings',  'list', tbl])
        # Get bond settings
        for col in ('bond_mode', 'lacp'):
            d['%s-Bond' % col] = subprocess.check_output(['ovs-vsctl', '--columns=name,%s' % col, '-f', 'csv', '-d', 'bare',
                                                           '--no-headings', 'list', 'Port'])
        # Get bridge settings
        d['set-fail-mode-Bridge'] = subprocess.check_output(['ovs-vsctl', 'get-fail-mode', bridge0])
        for col in ('mcast_snooping_enable', 'rstp_enable', 'protocols'):
            d['%s-Bridge' % col] = subprocess.check_output(['ovs-vsctl', '--columns=name,%s' % col, '-f', 'csv', '-d', 'bare',
                                                             '--no-headings', 'list', 'Bridge'])
        # Get controller settings
        d['set-controller-Bridge'] = subprocess.check_output(['ovs-vsctl', 'get-controller', bridge0])
        for col in ('connection_mode',):
            d['%s-Controller' % col] = subprocess.check_output(['ovs-vsctl', '--columns=_uuid,%s' % col, '-f', 'csv', '-d',
                                                                'bare', '--no-headings', 'list', 'Controller'])
        return d

    def test_cleanup_interfaces(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovs0'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovs1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'patch0-1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'patch1-0'])
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    # Add a normal interface, to avoid networkd-wait-online.service timeout.
    # If we have just OVS interfaces/ports networkd/networkctl will not be
    # aware that our network is ready.
    %(ec)s: {addresses: [10.10.10.20/24]}
  openvswitch:
    ports:
      - [patch0-1, patch1-0]
  bridges:
    ovs0: {interfaces: [patch0-1]}
    ovs1: {interfaces: [patch1-0]}''' % {'ec': self.dev_e_client})
        self.generate_and_settle()
        # Basic verification that the bridges/ports/interfaces are there in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge ovs0', out)
        self.assertIn(b'        Port patch0-1', out)
        self.assertIn(b'            Interface patch0-1', out)
        self.assertIn(b'    Bridge ovs1', out)
        self.assertIn(b'        Port patch1-0', out)
        self.assertIn(b'            Interface patch1-0', out)
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    %(ec)s: {addresses: ['1.2.3.4/24']}''' % {'ec': self.dev_e_client})
        self.generate_and_settle()
        # Verify that the netplan=true tagged bridges/ports have been cleaned up
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertNotIn(b'Bridge ovs0', out)
        self.assertNotIn(b'Port patch0-1', out)
        self.assertNotIn(b'Interface patch0-1', out)
        self.assertNotIn(b'Bridge ovs1', out)
        self.assertNotIn(b'Port patch1-0', out)
        self.assertNotIn(b'Interface patch1-0', out)
        self.assert_iface_up(self.dev_e_client, ['inet 1.2.3.4/24'])

    def test_cleanup_patch_ports(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovs0'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovs1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'patch0-1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'patchy'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'bond0'])
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    %(ec)s: {addresses: [10.10.10.20/24]}
  openvswitch:
    ports: [[patch0-1, patch1-0]]
  bonds:
    bond0: {interfaces: [patch1-0, %(ec)s]}
  bridges:
    ovs0: {interfaces: [patch0-1, bond0]}''' % {'ec': self.dev_e_client})
        self.generate_and_settle()
        # Basic verification that the bridges/ports/interfaces are there in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge ovs0', out)
        self.assertIn(b'        Port patch0-1\n            Interface patch0-1\n                type: patch', out)
        self.assertIn(b'        Port bond0', out)
        self.assertIn(b'            Interface patch1-0\n                type: patch', out)
        self.assertIn(b'            Interface eth42', out)
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    %(ec)s: {addresses: [10.10.10.20/24]}
  openvswitch:
    ports: [[patchx, patchy]]
  bonds:
    bond0: {interfaces: [patchx, %(ec)s]}
  bridges:
    ovs1: {interfaces: [patchy, bond0]}''' % {'ec': self.dev_e_client})
        self.generate_and_settle()
        # Verify that the netplan=true tagged patch ports have been cleaned up
        # even though the containing bond0 port still exists (with new patch ports)
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge ovs1', out)
        self.assertIn(b'        Port patchy\n            Interface patchy\n                type: patch', out)
        self.assertIn(b'        Port bond0', out)
        self.assertIn(b'            Interface patchx\n                type: patch', out)
        self.assertIn(b'            Interface eth42', out)
        self.assertNotIn(b'Bridge ovs0', out)
        self.assertNotIn(b'Port patch0-1', out)
        self.assertNotIn(b'Interface patch0-1', out)
        self.assertNotIn(b'Port patch1-0', out)
        self.assertNotIn(b'Interface patch1-0', out)

    def test_bridge_vlan(self):
        self.setup_eth(None, True)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br-%s' % self.dev_e_client])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br-data'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br-%s.100' % self.dev_e_client])
        with open(self.config, 'w') as f:
            f.write('''network:
    version: 2
    ethernets:
        %(ec)s:
            mtu: 9000
    bridges:
        br-%(ec)s:
            dhcp4: true
            mtu: 9000
            interfaces: [%(ec)s]
            openvswitch: {}
        br-data:
            openvswitch: {}
            addresses: [192.168.20.1/16]
    vlans:
        #implicitly handled by OVS because of its link
        br-%(ec)s.100:
            id: 100
            link: br-%(ec)s''' % {'ec': self.dev_e_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are set up in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge br-%b' % self.dev_e_client.encode(), out)
        self.assertIn(b'''        Port %(ec)b
            Interface %(ec)b''' % {b'ec': self.dev_e_client.encode()}, out)
        self.assertIn(b'''        Port br-%(ec)b.100
            tag: 100
            Interface br-%(ec)b.100
                type: internal''' % {b'ec': self.dev_e_client.encode()}, out)
        self.assertIn(b'    Bridge br-data', out)
        self.assert_iface('br-%s' % self.dev_e_client,
                          ['inet 192.168.5.[0-9]+/16', 'mtu 9000'])  # from DHCP
        self.assert_iface('br-data', ['inet 192.168.20.1/16'])
        self.assert_iface(self.dev_e_client, ['mtu 9000', 'master ovs-system'])
        self.assertIn(b'100', subprocess.check_output(['ovs-vsctl', 'br-to-vlan',
                      'br-%s.100' % self.dev_e_client]))
        self.assertIn(b'br-%b' % self.dev_e_client.encode(), subprocess.check_output(
                      ['ovs-vsctl', 'br-to-parent', 'br-%s.100' % self.dev_e_client]))
        self.assertIn(b'br-%b' % self.dev_e_client.encode(), out)

    def test_bridge_base(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovsbr'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', 'del-ssl'])
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    %(ec)s: {}
    %(e2c)s: {}
  openvswitch:
    ssl:
      ca-cert: /some/ca-cert.pem
      certificate: /another/certificate.pem
      private-key: /private/key.pem
  bridges:
    ovsbr:
      addresses: [192.170.1.1/24]
      interfaces: [%(ec)s, %(e2c)s]
      openvswitch:
        fail-mode: secure
        controller:
          addresses: [tcp:127.0.0.1, "pssl:1337:[::1]", unix:/some/socket]
''' % {'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge ovsbr', out)
        self.assertIn(b'        Controller "tcp:127.0.0.1"', out)
        self.assertIn(b'        Controller "pssl:1337:[::1]"', out)
        self.assertIn(b'        Controller "unix:/some/socket"', out)
        self.assertIn(b'        fail_mode: secure', out)
        self.assertIn(b'        Port %(ec)b\n            Interface %(ec)b' % {b'ec': self.dev_e_client.encode()}, out)
        self.assertIn(b'        Port %(e2c)b\n            Interface %(e2c)b' % {b'e2c': self.dev_e2_client.encode()}, out)
        # Verify the bridge was tagged 'netplan:true' correctly
        out = subprocess.check_output(['ovs-vsctl', '--columns=name,external-ids', '-f', 'csv', '-d', 'bare',
                                       'list', 'Bridge', 'ovsbr'])
        self.assertIn(b'netplan=true', out)
        self.assert_iface('ovsbr', ['inet 192.170.1.1/24'])

    def test_bond_base(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovsbr'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'mybond'])
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    %(ec)s: {}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [%(ec)s, %(e2c)s]
      parameters:
        mode: balance-slb
      openvswitch:
        lacp: off
  bridges:
    ovsbr:
      addresses: [192.170.1.1/24]
      interfaces: [mybond]''' % {'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge ovsbr', out)
        self.assertIn(b'        Port mybond', out)
        self.assertIn(b'            Interface %b' % self.dev_e_client.encode(), out)
        self.assertIn(b'            Interface %b' % self.dev_e2_client.encode(), out)
        # Verify the bond was tagged 'netplan:true' correctly
        out = subprocess.check_output(['ovs-vsctl', '--columns=name,external-ids', '-f', 'csv', '-d', 'bare', 'list', 'Port'])
        self.assertIn(b'mybond,netplan=true', out)
        # Verify bond params
        out = subprocess.check_output(['ovs-appctl', 'bond/show', 'mybond'])
        self.assertIn(b'---- mybond ----', out)
        self.assertIn(b'bond_mode: balance-slb', out)
        self.assertIn(b'lacp_status: off', out)
        self.assertIn(b'slave %b: enabled' % self.dev_e_client.encode(), out)
        self.assertIn(b'slave %b: enabled' % self.dev_e2_client.encode(), out)
        self.assert_iface('ovsbr', ['inet 192.170.1.1/24'])

    def test_bridge_patch_ports(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br0'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'patch0-1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'patch1-0'])
        with open(self.config, 'w') as f:
            f.write('''network:
  openvswitch:
    ports:
      - [patch0-1, patch1-0]
  bridges:
    br0:
      addresses: [192.168.1.1/24]
      interfaces: [patch0-1]
    br1:
      addresses: [192.168.2.1/24]
      interfaces: [patch1-0]''')
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are set up in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge br0', out)
        self.assertIn(b'''        Port patch0-1
            Interface patch0-1
                type: patch
                options: {peer=patch1-0}''', out)
        self.assertIn(b'    Bridge br1', out)
        self.assertIn(b'''        Port patch1-0
            Interface patch1-0
                type: patch
                options: {peer=patch0-1}''', out)
        self.assert_iface('br0', ['inet 192.168.1.1/24'])
        self.assert_iface('br1', ['inet 192.168.2.1/24'])

    def test_bridge_non_ovs_bond(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovs-br'])
        self.addCleanup(subprocess.call, ['ip', 'link', 'del', 'non-ovs-bond'])
        with open(self.config, 'w') as f:
            f.write('''network:
    version: 2
    ethernets:
        %(ec)s: {}
        %(e2c)s: {}
    bonds:
        non-ovs-bond:
            interfaces: [%(ec)s, %(e2c)s]
    bridges:
        ovs-br:
            interfaces: [non-ovs-bond]
            openvswitch: {}''' % {'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are set up in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'], universal_newlines=True)
        self.assertIn('    Bridge ovs-br', out)
        self.assertIn('''        Port non-ovs-bond
            Interface non-ovs-bond''', out)
        self.assertIn('''        Port ovs-br
            Interface ovs-br
                type: internal''', out)
        self.assert_iface('non-ovs-bond', ['master ovs-system'])
        self.assert_iface(self.dev_e_client, ['master non-ovs-bond'])
        self.assert_iface(self.dev_e2_client, ['master non-ovs-bond'])

    def test_vlan_maas(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovs0'])
        self.addCleanup(subprocess.call, ['ip', 'link', 'delete', '%s.21' % self.dev_e_client], stderr=subprocess.DEVNULL)
        with open(self.config, 'w') as f:
            f.write('''network:
    version: 2
    bridges:
        ovs0:
            addresses: [10.5.48.11/20]
            interfaces: [%(ec)s.21]
            macaddress: 00:1f:16:15:78:6f
            mtu: 1500
            nameservers:
                addresses: [10.5.32.99]
                search: [maas]
            openvswitch: {}
            parameters:
                forward-delay: 15
                stp: false
    ethernets:
        %(ec)s:
            addresses: [10.5.32.26/20]
            gateway4: 10.5.32.1
            mtu: 1500
            nameservers:
                addresses: [10.5.32.99]
                search: [maas]
    vlans:
        %(ec)s.21:
            id: 21
            link: %(ec)s
            mtu: 1500''' % {'ec': self.dev_e_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are set up in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'], universal_newlines=True)
        self.assertIn('    Bridge ovs0', out)
        self.assertIn('''        Port %(ec)s.21
            Interface %(ec)s.21''' % {'ec': self.dev_e_client}, out)
        self.assertIn('''        Port ovs0
            Interface ovs0
                type: internal''', out)
        self.assert_iface('ovs0', ['inet 10.5.48.11/20'])
        self.assert_iface_up(self.dev_e_client, ['inet 10.5.32.26/20'])
        self.assert_iface_up('%s.21' % self.dev_e_client, ['%(ec)s.21@%(ec)s' % {'ec': self.dev_e_client}])

    def test_missing_ovs_tools(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['mv', '/usr/bin/ovs-vsctl.bak', '/usr/bin/ovs-vsctl'])
        subprocess.check_call(['mv', '/usr/bin/ovs-vsctl', '/usr/bin/ovs-vsctl.bak'])
        with open(self.config, 'w') as f:
            f.write('''network:
    version: 2
    bridges:
      ovs0:
        interfaces: [%(ec)s]
        openvswitch: {}
    ethernets:
      %(ec)s: {}''' % {'ec': self.dev_e_client})
        p = subprocess.Popen(['netplan', 'apply'], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
        (out, err) = p.communicate()
        self.assertIn('ovs0: The \'ovs-vsctl\' tool is required to setup OpenVSwitch interfaces.', err)
        self.assertNotEqual(p.returncode, 0)

    def test_settings_tag_cleanup(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovs0'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovs1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'bond0'])
        with open(self.config, 'w') as f:
            f.write('''network:
  version: 2
  openvswitch:
    protocols: [OpenFlow13, OpenFlow14, OpenFlow15]
    ports:
      - [patch0-1, patch1-0]
    ssl:
      ca-cert: /some/ca-cert.pem
      certificate: /another/cert.pem
      private-key: /private/key.pem
    external-ids:
      somekey: somevalue
    other-config:
      key: value
  ethernets:
    %(ec)s:
      addresses: [10.5.32.26/20]
      openvswitch:
        external-ids:
          iface-id: mylocaliface
        other-config:
          disable-in-band: false
    %(e2c)s: {}
  bonds:
    bond0:
      interfaces: [patch1-0, %(e2c)s]
      openvswitch:
        lacp: passive
      parameters:
        mode: balance-tcp
  bridges:
    ovs0:
      addresses: [10.5.48.11/20]
      interfaces: [patch0-1, %(ec)s, bond0]
      openvswitch:
        protocols: [OpenFlow10, OpenFlow11, OpenFlow12]
        controller:
          addresses: [unix:/var/run/openvswitch/ovs0.mgmt]
          connection-mode: out-of-band
        fail-mode: secure
        mcast-snooping: true
        external-ids:
          iface-id: myhostname
        other-config:
          disable-in-band: true
    ovs1:
      openvswitch:
        # Add ovs1 as rstp cannot be used if bridge contains a bond interface
        rstp: true

''' % {'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        before = self._collect_ovs_settings('ovs0')
        subprocess.check_call(['netplan', 'apply', '--only-ovs-cleanup'])
        after = self._collect_ovs_settings('ovs0')

        # Verify interfaces
        for data in (before['show'], after['show']):
            self.assertIn(b'Bridge ovs0', data)
            self.assertIn(b'Port ovs0', data)
            self.assertIn(b'Interface ovs0', data)
            self.assertIn(b'Port patch0-1', data)
            self.assertIn(b'Interface patch0-1', data)
            self.assertIn(b'Port eth42', data)
            self.assertIn(b'Interface eth42', data)
            self.assertIn(b'Bridge ovs1', data)
            self.assertIn(b'Port ovs1', data)
            self.assertIn(b'Interface ovs1', data)
            self.assertIn(b'Port bond0', data)
            self.assertIn(b'Interface eth42', data)
            self.assertIn(b'Interface patch1-0', data)
        # Verify all settings tags have been removed
        for tbl in ('Open_vSwitch', 'Controller', 'Bridge', 'Port', 'Interface'):
            self.assertNotIn(b'netplan/', after['external-ids-%s' % tbl])
        # Verify SSL
        for s in (b'Private key: /private/key.pem', b'Certificate: /another/cert.pem', b'CA Certificate: /some/ca-cert.pem'):
            self.assertIn(s, before['ssl'])
            self.assertNotIn(s, after['ssl'])
        # Verify Bond
        self.assertIn(b'bond0,balance-tcp\n', before['bond_mode-Bond'])
        self.assertIn(b'bond0,\n', after['bond_mode-Bond'])
        self.assertIn(b'bond0,passive\n', before['lacp-Bond'])
        self.assertIn(b'bond0,\n', after['lacp-Bond'])
        # Verify Bridge
        self.assertIn(b'secure', before['set-fail-mode-Bridge'])
        self.assertNotIn(b'secure', after['set-fail-mode-Bridge'])
        self.assertIn(b'ovs0,true\n', before['mcast_snooping_enable-Bridge'])
        self.assertIn(b'ovs0,false\n', after['mcast_snooping_enable-Bridge'])
        self.assertIn(b'ovs1,true\n', before['rstp_enable-Bridge'])
        self.assertIn(b'ovs1,false\n', after['rstp_enable-Bridge'])
        self.assertIn(b'ovs0,OpenFlow10 OpenFlow11 OpenFlow12\n', before['protocols-Bridge'])
        self.assertIn(b'ovs0,\n', after['protocols-Bridge'])
        # Verify global protocols
        self.assertIn(b'ovs1,OpenFlow13 OpenFlow14 OpenFlow15\n', before['protocols-Bridge'])
        self.assertIn(b'ovs1,\n', after['protocols-Bridge'])
        # Verify Controller
        self.assertIn(b'Controller "unix:/var/run/openvswitch/ovs0.mgmt"', before['show'])
        self.assertNotIn(b'Controller', after['show'])
        self.assertIn(b'unix:/var/run/openvswitch/ovs0.mgmt', before['set-controller-Bridge'])
        self.assertIn(b',out-of-band', before['connection_mode-Controller'])
        self.assertEqual(b'', after['set-controller-Bridge'])
        self.assertEqual(b'', after['connection_mode-Controller'])
        # Verify other-config
        self.assertIn(b'key=value', before['other-config-Open_vSwitch'])
        self.assertNotIn(b'key=value', after['other-config-Open_vSwitch'])
        self.assertIn(b'ovs0,disable-in-band=true\n', before['other-config-Bridge'])
        self.assertIn(b'ovs0,\n', after['other-config-Bridge'])
        self.assertIn(b'eth42,disable-in-band=false\n', before['other-config-Interface'])
        self.assertIn(b'eth42,\n', after['other-config-Interface'])
        # Verify external-ids
        self.assertIn(b'somekey=somevalue', before['external-ids-Open_vSwitch'])
        self.assertNotIn(b'somekey=somevalue', after['external-ids-Open_vSwitch'])
        self.assertIn(b'iface-id=myhostname', before['external-ids-Bridge'])
        self.assertNotIn(b'iface-id=myhostname', after['external-ids-Bridge'])
        self.assertIn(b'iface-id=mylocaliface', before['external-ids-Interface'])
        self.assertNotIn(b'iface-id=mylocaliface', after['external-ids-Interface'])
        for tbl in ('Bridge', 'Port'):
            # The netplan=true tag shall be kept unitl the interface is deleted
            self.assertIn(b'netplan=true', before['external-ids-%s' % tbl])
            self.assertIn(b'netplan=true', after['external-ids-%s' % tbl])

    @unittest.skip("For debugging only")
    def test_zzz_ovs_debugging(self):  # Runs as the last test, to collect all logs
        """Display OVS logs of the previous tests"""
        out = subprocess.check_output(['cat', '/var/log/openvswitch/ovs-vswitchd.log'], universal_newlines=True)
        print(out)
        out = subprocess.check_output(['ovsdb-tool', 'show-log'], universal_newlines=True)
        print(out)


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestOVS(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
