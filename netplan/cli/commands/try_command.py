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

'''netplan try command line'''

import os
import time
import signal
import sys

from netplan.configmanager import ConfigManager
import netplan.cli.utils as utils
from netplan.cli.commands.apply import NetplanApply
import netplan.terminal

# Keep a timeout long enough to allow the network to converge, 60 seconds may
# be slightly short given some complex configs, i.e. if STP must reconverge.
DEFAULT_INPUT_TIMEOUT = 120


class NetplanTry(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='try',
                         description='Try to apply a new netplan config to running '
                                     'system, with automatic rollback',
                         leaf=True)
        self.configuration_changed = False
        self.config_manager = ConfigManager()

    def run(self):  # pragma: nocover (requires user input)
        self.parser.add_argument('--config-file',
                                 help='Apply the config file in argument on top of current configuration.')
        self.parser.add_argument('--timeout',
                                 type=int, default=DEFAULT_INPUT_TIMEOUT,
                                 help="Maximum number of seconds to wait for the user's confirmation")

        self.func = self.command_try

        self.parse_args()
        self.run_command()

    def command_try(self):  # pragma: nocover (requires user input)
        try:
            fd = sys.stdin.fileno()
            t = netplan.terminal.Terminal(fd)
            t.enable_nonblocking_io()

            # we really don't want to be interrupted while doing backup/revert operations
            signal.signal(signal.SIGINT, self._signal_handler)

            self.backup()
            self.setup()

            NetplanApply.command_apply()

            t.get_confirmation_input(timeout=self.timeout)
        except netplan.terminal.InputRejected:
            print("\nReverting.")
            self.revert()
        except netplan.terminal.InputAccepted:
            print("\nConfiguration accepted.")
        except Exception as e:
            print("\nAn error occured: %s" % e)
            print("\nReverting.")
            self.revert()
        finally:
            t.reset()
            self.cleanup()

    def backup(self):  # pragma: nocover (requires user input)
        backup_config_dir = False
        if self.config_file:
            backup_config_dir = True
        self.config_manager.backup(backup_config_dir=backup_config_dir)

    def setup(self):  # pragma: nocover (requires user input)
        if self.config_file:
            dest_dir = os.path.join("/", "etc", "netplan")
            dest_name = os.path.basename(self.config_file).rstrip('.yaml')
            dest_suffix = time.time()
            dest_path = os.path.join(dest_dir, "{}.{}.yaml".format(dest_name, dest_suffix))
            self.config_manager.add({self.config_file: dest_path})
        self.configuration_changed = True

    def revert(self):  # pragma: nocover (requires user input)
        self.config_manager.revert()
        NetplanApply.command_apply(run_generate=False)

    def cleanup(self):  # pragma: nocover (requires user input)
        self.config_manager.cleanup()

    def _signal_handler(self, signal, frame):  # pragma: nocover (requires user input)
        if self.configuration_changed:
            raise netplan.terminal.InputRejected()
