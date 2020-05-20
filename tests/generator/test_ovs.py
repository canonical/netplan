#
# Common tests for netplan OpenVSwitch support
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@ubuntu.com>
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

from .base import TestBase, ND_DHCP4, ND_DHCP6


class TestOpenVSwitch(TestBase):
    '''OVS output'''

    def test_interface_external_ids_other_config(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      openvswitch:
        external-ids:
          iface-id: myhostname
        other-config:
          disable-in-band: true
      dhcp6: true
    eth1:
      dhcp4: true
      openvswitch:
        other-config:
          disable-in-band: false
''')
        self.assert_ovs({'eth0.service': '''[Unit]
Description=OpenVSwitch configuration for eth0
DefaultDependencies=no
Requires=sys-subsystem-net-devices-eth0.device
After=sys-subsystem-net-devices-eth0.device
Before=network.target
Wants=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Interface eth0 other-config:disable-in-band=true
''',
                         'eth1.service': '''[Unit]
Description=OpenVSwitch configuration for eth1
DefaultDependencies=no
Requires=sys-subsystem-net-devices-eth1.device
After=sys-subsystem-net-devices-eth1.device
Before=network.target
Wants=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Interface eth1 other-config:disable-in-band=false
'''})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth0.network': ND_DHCP6 % 'eth0',
                              'eth1.network': ND_DHCP4 % 'eth1'})

    def test_bridge_external_ids_other_config(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      openvswitch:
        external-ids:
          iface-id: myhostname
        other-config:
          disable-in-band: true
      dhcp4: yes
''')
        self.assert_ovs({'br0.service': '''[Unit]
Description=OpenVSwitch configuration for br0
DefaultDependencies=no
Before=network.target
Wants=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set Bridge br0 other-config:disable-in-band=true
'''})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'br0.netdev': '[NetDev]\nName=br0\nKind=bridge\n',
                              'br0.network': '''[Match]
Name=br0

[Network]
DHCP=ipv4
LinkLocalAddressing=ipv6
ConfigureWithoutCarrier=yes

[DHCP]
RouteMetric=100
UseMTU=true
'''})

    def test_global_external_ids_other_config(self):
        self.generate('''network:
  version: 2
  openvswitch:
    external-ids:
      iface-id: myhostname
    other-config:
      disable-in-band: true
  ethernets:
    eth0:
      dhcp4: yes
''')
        self.assert_ovs({'global.service': '''[Unit]
Description=OpenVSwitch configuration for global
DefaultDependencies=no
Before=network.target
Wants=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . external-ids:iface-id=myhostname
ExecStart=/usr/bin/ovs-vsctl set open_vswitch . other-config:disable-in-band=true
'''})
        # Confirm that the networkd config is still sane
        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})

    def test_duplicate_map_entry(self):
        err = self.generate('''network:
  version: 2
  openvswitch:
    external-ids:
      iface-id: myhostname
      iface-id: foobar
  ethernets:
    eth0:
      dhcp4: yes
''', expect_fail=True)
        self.assertIn("duplicate map entry 'iface-id'", err)

    def test_no_ovs_config(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: yes
''')
        self.assert_ovs(None)
        self.assert_networkd({'eth0.network': ND_DHCP4 % 'eth0'})
