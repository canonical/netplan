#!/usr/bin/python3
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

'''netplan generate command line'''

import logging
import os
import sys
import subprocess
import shutil

from .. import utils


class NetplanGenerate(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='generate',
                         description='Generate backend specific configuration files'
                                     ' from /etc/netplan/*.yaml',
                         leaf=True)

    def run(self):
        self.parser.add_argument('--root-dir',
                                 help='Search for and generate configuration files in this root directory instead of /')
        self.parser.add_argument('--mapping',
                                 help='Display the netplan device ID/backend/interface name mapping and exit.')

        self.func = self.command_generate
        self._rootdir = '/'

        self.parse_args()
        self.run_command()

    def command_generate(self):
        # if we are inside a snap, then call dbus to run netplan apply instead
        if "SNAP" in os.environ:
            # TODO: maybe check if we are inside a classic snap and don't do
            # this if we are in a classic snap?
            busctl = shutil.which("busctl")
            if busctl is None:
                raise RuntimeError("missing busctl utility")  # pragma: nocover
            # XXX: DO NOT TOUCH or change this API call, it is used by snapd to communicate
            #      using core20 netplan binary/client/CLI on core18 base systems. Any change
            #      must be agreed upon with the snapd team, so we don't break support for
            #      base systems running older netplan versions.
            #      https://github.com/snapcore/snapd/pull/10212
            res = subprocess.call([busctl, "call", "--quiet", "--system",
                                   "io.netplan.Netplan",  # the service
                                   "/io/netplan/Netplan",  # the object
                                   "io.netplan.Netplan",  # the interface
                                   "Generate",  # the method
                                   ])

            if res != 0:
                if res == 130:
                    raise PermissionError(
                        "PermissionError: failed to communicate with dbus service")
                else:
                    raise RuntimeError(
                        "RuntimeError: failed to communicate with dbus service: error %s" % res)
            else:
                return

        argv = [utils.get_configure_path()]
        if self.root_dir:
            argv += ['--root-dir', self.root_dir]
            self._rootdir = self.root_dir
        if self.mapping:
            argv += ['--mapping', self.mapping]

        self._netplan_try_stamp = os.path.join(self._rootdir, self.try_ready_stamp)
        if self.mapping:  # XXX: get rid of the legacy "--mapping" option
            argv[0] = utils.get_generator_path()
            res = subprocess.call(argv)
        elif os.path.isfile(self._netplan_try_stamp):
            # Avoid calling the Netplan generator if 'netplan try' is restoring
            # a previous configuration. See https://github.com/canonical/netplan/pull/548
            # This is especially relevant when NetworkManager is calling 'netplan generate'
            # before loading connection profiles, as this would trigger a 'systemctl daemon-reload'
            # and remove the /run/systemd/generator[.late]/ directories while the sd-generator
            # itself would be blocked from re-generating the files due to the
            # /run/netplan/netplan-try.ready stamp.
            logging.debug('Skipping daemon-reload... \'netplan try\' is restoring configuration, '
                          'remove %s to force re-run.', self._netplan_try_stamp)
            res = 1
        else:
            logging.debug('executing Netplan systemd-generator via daemon-reload')
            if self.root_dir:  # for testing purposes
                sd_generator = os.path.join(self.root_dir, 'usr', 'lib', 'systemd', 'system-generators', 'netplan')
                generator_dir = os.path.join(self.root_dir, 'run', 'systemd', 'generator')
                generator_early_dir = os.path.join(self.root_dir, 'run', 'systemd', 'generator.early')
                generator_late_dir = os.path.join(self.root_dir, 'run', 'systemd', 'generator.late')
                # Ensure necessary directories exist
                for d in (os.path.dirname(sd_generator), generator_dir, generator_early_dir, generator_late_dir):
                    try:
                        os.makedirs(d, exist_ok=True)
                    except OSError as e:  # pragma: nocover (testing only)
                        logging.debug(f'Could not create directory {d}: {e}')
                # Ensure sd_generator exists and points to the real generator
                real_generator = utils.get_generator_path()
                try:  # pragma: nocover (testing only)
                    if not os.path.exists(sd_generator):
                        os.symlink(real_generator, sd_generator)
                except OSError as e:  # pragma: nocover (testing only)
                    logging.debug(f'Could not create symlink {sd_generator} -> {real_generator}: {e}')
                subprocess.check_call([sd_generator, '--root-dir', self.root_dir,
                                       generator_dir, generator_early_dir, generator_late_dir])
            else:  # pragma: nocover (covered by autopkgtests)
                # automatically reloads systemd, as we might have changed
                # service units, such as
                # /run/systemd/generator.late/systemd-networkd-wait-online.service.d/10-netplan.conf
                utils.systemctl_daemon_reload()

            logging.debug('command configure: running %s', argv)
            res = subprocess.call(argv)
            try:
                subprocess.check_call(['udevadm', 'control', '--reload'])
            except subprocess.CalledProcessError as e:
                logging.debug(f'Could not call "udevadm control --reload": {str(e)}')

        # FIXME: os.execv(argv[0], argv) would be better but fails coverage
        sys.exit(res)
