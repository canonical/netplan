#
# systemd-generator behavior for netplan
#
# Copyright (C) 2025 Canonical, Ltd.
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

import pathlib

from .base import TestBase


class TestSystemdGenerator(TestBase):
    '''Netplan systemd generator testing'''

    def test_sandbox(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
    engreen:
      embedded-switch-mode: switchdev
      delay-virtual-functions-rebind: true
    enblue:
      match: {driver: fake_driver}
      set-name: enblue
      embedded-switch-mode: legacy
      delay-virtual-functions-rebind: true
      virtual-function-count: 4
    sriov_vf0:
      link: engreen
  wifis:
    wl0:
      regulatory-domain: GB
      access-points:
        home:
          password: "s0s3kr1t"
''')

        self.assertEqual(
            sorted(p.name for p in (pathlib.Path(self.workdir.name) / 'run' / 'systemd').iterdir()),
            ['generator', 'generator.early', 'generator.late', 'network'])
        # default generator output directory
        self.assertEqual(
            sorted(p.name for p in (pathlib.Path(self.workdir.name) / 'run' / 'systemd' / 'generator' /
                                    'multi-user.target.wants').iterdir()),
            ['systemd-networkd.service'])
        # late generator output directory
        self.assertEqual(
            sorted(p.name for p in (pathlib.Path(self.workdir.name) / 'run' / 'systemd' /
                                    'generator.late').iterdir()),
            ['multi-user.target.wants',
             'netplan-ovs-cleanup.service',
             'netplan-regdom.service',
             'netplan-sriov-apply.service',
             'netplan-sriov-rebind.service',
             'netplan-wpa-wl0.service',
             'network.target.wants',
             'systemd-networkd-wait-online.service.d',
             'systemd-networkd.service.wants'])
        # systemd-networkd-wait-online.service.d
        self.assertEqual(
            sorted(p.name for p in (pathlib.Path(self.workdir.name) / 'run' / 'systemd' /
                                    'generator.late' / 'systemd-networkd-wait-online.service.d').iterdir()),
            ['10-netplan.conf'])
        # systemd-networkd.service.wants
        self.assertEqual(
            sorted(p.name for p in (pathlib.Path(self.workdir.name) / 'run' / 'systemd' /
                                    'generator.late' / 'systemd-networkd.service.wants').iterdir()),
            ['netplan-ovs-cleanup.service', 'netplan-wpa-wl0.service'])
        # network.target.wants
        self.assertEqual(
            sorted(p.name for p in (pathlib.Path(self.workdir.name) / 'run' / 'systemd' /
                                    'generator.late' / 'network.target.wants').iterdir()),
            ['netplan-regdom.service'])
        # multi-user.target.wants
        self.assertEqual(
            sorted(p.name for p in (pathlib.Path(self.workdir.name) / 'run' / 'systemd' /
                                    'generator.late' / 'multi-user.target.wants').iterdir()),
            ['netplan-sriov-apply.service', 'netplan-sriov-rebind.service'])
