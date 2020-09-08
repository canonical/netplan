#!/usr/bin/python3
#
# Integration tests for complex networking scenarios
# (ie. mixes of various features, may test real live cases)
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
import os
import time
import subprocess
import unittest

from base import IntegrationTestReboot, test_backends


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestSpecialReboot(IntegrationTestReboot):
    backend = 'networkd'

    def test_generate_start_services_just_in_time(self):
        self.setup_eth(None)
        MARKER = 'cloud_init_generate'
        # PART 1: set up the requried files before rebooting
        if os.getenv('AUTOPKGTEST_REBOOT_MARK') != MARKER:
            # any netplan YAML config
            with open(self.config, 'w') as f:
                f.write('''network:
  ethernets:
    ethbn:
      match: {name: %(ec)s}
      dhcp4: true''' % {'ec': self.dev_e_client})
            # Prepare a dummy netplan service unit, which will be moved to /run/systemd/system/
            # during early boot, as if it would have been created by 'netplan generate'
            with open ('/netplan-dummy.service', 'w') as f:
                f.write('''[Unit]
Description=Check if this dummy is properly started by systemd

[Service]
Type=oneshot
# Keep it running, so we can verify it was properly started
RemainAfterExit=yes
ExecStart=echo "Doing nothing ..."
''')
            # A service simulating cloud-init, calling 'netplan generate' during early boot
            # at the 'initialization' phase of systemd (before basic.target is reached).
            with open ('/etc/systemd/system/cloud-init-dummy.service', 'w') as f:
                f.write('''[Unit]
Description=Simulating cloud-init's 'netplan generate' call during early boot
DefaultDependencies=no
Before=basic.target
After=sysinit.target

[Install]
WantedBy=multi-user.target

[Service]
Type=oneshot
# Keep it running, so we can verify it was properly started
RemainAfterExit=yes
# Simulate creating a new service unit (i.e. netplan-wpa-*.service / netplan-ovs-*.service)
ExecStart=/bin/mv /netplan-dummy.service /run/systemd/system/
ExecStart=/usr/sbin/netplan generate
''')
            subprocess.check_call(['systemctl', '--quiet', 'enable', 'cloud-init-dummy.service'])
            subprocess.check_call(['systemctl', '--quiet', 'disable', 'systemd-networkd.service'])
            subprocess.check_call(['/tmp/autopkgtest-reboot', MARKER])
        # PART 2: after reboot verify all (newly created) services have been started
        else:
            self.addCleanup(subprocess.call, ['rm', '/run/systemd/system/netplan-dummy.service'])
            self.addCleanup(subprocess.call, ['rm', '/etc/systemd/system/cloud-init-dummy.service'])
            self.addCleanup(subprocess.call, ['systemctl', '--quiet', 'disable', 'cloud-init-dummy.service'])
            
            time.sleep(5)  # Give some time for systemd to finish the boot transaction
            # Verify our cloud-init simulation worked
            out = subprocess.check_output(['systemctl', 'status', 'cloud-init-dummy.service'], universal_newlines=True)
            self.assertIn('Active: active (exited)', out)
            self.assertIn('mv /netplan-dummy.service /run/systemd/system/ (code=exited, status=0/SUCCESS)', out)
            self.assertIn('netplan generate (code=exited, status=0/SUCCESS)', out)
            # Verify the previously disabled networkd is running again
            out = subprocess.check_output(['systemctl', 'status', 'systemd-networkd.service'], universal_newlines=True)
            self.assertIn('Active: active (running)', out)
            # Verify the newly created services were started just-in-time
            out = subprocess.check_output(['systemctl', 'status', 'netplan-dummy.service'], universal_newlines=True)
            self.assertIn('Active: active (exited)', out)
            self.assertIn('echo Doing nothing ... (code=exited, status=0/SUCCESS)', out)


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
