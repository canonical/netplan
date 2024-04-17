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

        argv = [utils.get_generator_path()]
        if self.root_dir:
            argv += ['--root-dir', self.root_dir]
        if self.mapping:
            argv += ['--mapping', self.mapping]
        logging.debug('command generate: running %s', argv)
        res = subprocess.call(argv)
        # reload systemd, as we might have changed service units, such as
        # /run/systemd/system/systemd-networkd-wait-online.service.d/10-netplan.conf
        try:
            utils.systemctl_daemon_reload()
        except subprocess.CalledProcessError as e:
            logging.warning(e)
        # FIXME: os.execv(argv[0], argv) would be better but fails coverage
        sys.exit(res)
