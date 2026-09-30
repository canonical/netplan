#
# Tests for re-running the generator over existing networkd configuration
#
# Copyright (C) 2026 Deutsche Telekom AG
# Author: Pablo Murillo <pnogales@mirantis.com>
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

from .base import TestBase

BASE = '''network:
  version: 2
  ethernets:
    eth0:
      addresses: [10.10.0.1/24]
    eth1:
      addresses: [10.11.0.1/24]
      routes: [{to: 10.21.0.0/24, via: 10.11.0.254}]
'''


class TestRegenerate(TestBase):

    def _path(self, name, subdir=('run', 'systemd', 'network')):
        return os.path.join(self.workdir.name, *subdir, name)

    def _stat(self, name):
        st = os.stat(self._path(name))
        return (st.st_ino, st.st_mtime_ns)

    def _age(self, *names):
        # push mtimes into the past so any rewrite, even in place, is unambiguous
        for name in names:
            os.utime(self._path(name), ns=(1_000_000_000, 1_000_000_000))

    def test_only_changed_file_is_rewritten(self):
        self.generate(BASE)
        self._age('10-netplan-eth0.network', '10-netplan-eth1.network')
        eth0, eth1 = self._stat('10-netplan-eth0.network'), self._stat('10-netplan-eth1.network')
        self.generate(BASE.replace('10.21.0.0/24', '10.30.0.0/24'))  # same length: content, not size, must differ
        self.assertEqual(self._stat('10-netplan-eth0.network'), eth0)
        self.assertNotEqual(self._stat('10-netplan-eth1.network'), eth1)
        self.assert_networkd({'eth0.network': '''[Match]
Name=eth0

[Network]
LinkLocalAddressing=ipv6
Address=10.10.0.1/24
''',
                              'eth1.network': '''[Match]
Name=eth1

[Network]
LinkLocalAddressing=ipv6
Address=10.11.0.1/24

[Route]
Destination=10.30.0.0/24
Gateway=10.11.0.254
'''})

    def test_skipped_write_repairs_mode(self):
        self.generate(BASE)
        os.chmod(self._path('10-netplan-eth0.network'), 0o644)
        self._age('10-netplan-eth0.network')
        eth0 = self._stat('10-netplan-eth0.network')
        self.generate(BASE)
        self.assertEqual(self._stat('10-netplan-eth0.network'), eth0)
        self.assertEqual(os.stat(self._path('10-netplan-eth0.network')).st_mode & 0o777, 0o640)

    def test_stale_files_are_removed(self):
        self.generate(BASE)
        eth0 = self._stat('10-netplan-eth0.network')
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      addresses: [10.10.0.1/24]
''')
        self.assertEqual(self._stat('10-netplan-eth0.network'), eth0)
        self.assertFalse(os.path.exists(os.path.join(self.workdir.name, 'run', 'systemd', 'network',
                                                     '10-netplan-eth1.network')))
