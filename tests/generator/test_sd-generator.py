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

import os
import subprocess

from .base import TestBase, exe_generate


class TestSystemdGenerator(TestBase):
    '''Netplan systemd generator testing'''

    def test_sandbox(self):
        conf = os.path.join(self.confdir, 'a.yaml')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
  wifis:
    wl0:
      regulatory-domain: GB
      access-points:
        home:
          password: "s0s3kr1t"
''')
        os.chmod(conf, 0o600)

        generator = os.path.join(self.workdir.name, 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        # Generators executed by the system manager are invoked in a sandbox
        # with a private writable /tmp/ directory and where most of the file
        # system is read-only except for the generator output directories.
        # https://www.freedesktop.org/software/systemd/man/latest/systemd.generator.html#Description
        generator_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'generator')
        generator_early_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'generator.early')
        generator_late_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'generator.late')
        # XXX: confirm those directories are created by the generator, if they do not exist
        os.makedirs(generator_dir, mode=0o755, exist_ok=True)
        os.makedirs(generator_early_dir, mode=0o755, exist_ok=True)
        os.makedirs(generator_late_dir, mode=0o755, exist_ok=True)

        # XXX: debug, clean up later
        out = subprocess.check_output(['tree', self.workdir.name], text=True)
        print("\n\n"+out, flush=True)

        # XXX: should we use PrivateTmp=disconnected, too?
        #      But this conflicts with self.workdir in public /tmp
        sandbox = ['systemd-run', '--user', '--pty', '--collect',
                   '--property=ReadOnlyPaths=/',
                   '--property=ReadWritePaths=' + generator_dir,
                   '--property=ReadWritePaths=' + generator_early_dir,
                   '--property=ReadWritePaths=' + generator_late_dir]
        try:
            subprocess.check_output(sandbox +
                                    [generator, '--root-dir', self.workdir.name,
                                     generator_dir, generator_early_dir, generator_late_dir],
                                    stderr=subprocess.PIPE, text=True)
        except subprocess.CalledProcessError as e:
            # XXX: debug, clean up later
            out = subprocess.check_output(['tree', self.workdir.name], text=True)
            print("\n\n"+out, flush=True)
            self.fail(f"{e.output.strip()}\n"
                      f"stderr: {e.stderr.strip()}\n"
                      f"return code: {e.returncode}")
        # XXX: debug, clean up later
        out = subprocess.check_output(['tree', self.workdir.name], text=True)
        print("\n\n"+out, flush=True)
        self.assertEqual(sorted(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd'))),
                         ['generator', 'generator.early', 'generator.late'])
        # default generator output directory
        self.assertEqual(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd', 'generator', 'multi-user.target.wants')),
                         ['systemd-networkd.service'])
        # late generator output directory
        self.assertEqual(sorted(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd', 'generator.late'))),
                         ['netplan-ovs-cleanup.service',
                          'netplan-regdom.service',
                          'netplan-wpa-wl0.service',
                          'network.target.wants',
                          'systemd-networkd-wait-online.service.d',
                          'systemd-networkd.service.wants'])
        # systemd-networkd-wait-online.service.d
        self.assertEqual(sorted(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd', 'generator.late', 'systemd-networkd-wait-online.service.d'))),
                         ['10-netplan.conf'])
        # systemd-networkd.service.wants
        self.assertEqual(sorted(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd', 'generator.late', 'systemd-networkd.service.wants'))),
                         ['netplan-ovs-cleanup.service', 'netplan-wpa-wl0.service'])
        # network.target.wants
        self.assertEqual(sorted(os.listdir(os.path.join(self.workdir.name, 'run', 'systemd', 'generator.late', 'network.target.wants'))),
                         ['netplan-regdom.service'])

        self.assert_nm_udev(None)  # TODO: drop this?
