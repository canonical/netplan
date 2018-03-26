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

import fcntl
import os
import termios
import time
import select
import signal
import sys

from netplan.configmanager import ConfigManager
import netplan.cli.utils as utils
from netplan.cli.commands.apply import NetplanApply

# Keep a timeout long enough to allow the network to converge, 60 seconds may
# be slightly short given some complex configs, i.e. if STP must reconverge.
INPUT_TIMEOUT = 120


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

        self.func = self.command_try

        self.parse_args()
        self.run_command()

    def command_try(self):  # pragma: nocover (requires user input)
        try:
            fd = sys.stdin.fileno()
            old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            old_term = termios.tcgetattr(fd)

            raw_term = termios.tcgetattr(fd)
            raw_term[3] = raw_term[3] & ~termios.ICANON
            raw_term[3] = raw_term[3] & ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSANOW, raw_term)

            fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)

            # we really don't want to be interrupted while doing backup/revert operations
            signal.signal(signal.SIGINT, self._signal_handler)

            self.backup()
            self.setup()

            NetplanApply.command_apply()

            print("Do you want to keep these settings?\n\n")
            print("Press ENTER before timeout to accept the new configuration\n\n")
            timeout_now = INPUT_TIMEOUT
            while (timeout_now > 0):
                print("Network changes will revert in {:>2} seconds".format(timeout_now), end='\r')
                i, o, err = select.select([sys.stdin], [], [], 1)
                try:
                    sys.stdin.read()
                    raise ConfigurationAccepted()
                except ConfigurationAccepted:
                    raise
                except ConfigurationRejected:
                    raise
                except TypeError:
                    pass
                timeout_now -= 1
            raise ConfigurationRejected()
        except ConfigurationRejected:
            print("\nReverting.")
            self.revert()
        except ConfigurationAccepted:
            print("\nConfiguration accepted.")
        except Exception as e:
            print("\nAn error occured: %s" % e)
            print("\nReverting.")
            self.revert()
        finally:
            self.cleanup()
            termios.tcsetattr(fd, termios.TCSAFLUSH, old_term)
            fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)

    def backup(self):  # pragma: nocover (requires user input)
        self.config_manager.backup(with_config_file=self.config_file)

    def setup(self):  # pragma: nocover (requires user input)
        if self.config_file:
            dest_dir = os.path.join("/", "etc", "netplan")
            dest_name = os.path.basename(self.config_file).rstrip('.yaml')
            dest_suffix = time.time()
            dest_path = os.path.join(dest_dir, "{}.{}.yaml".format(dest_name, dest_suffix))
            self.config_manager.add({self.config_file: dest_path})
        self.configuration_changed = True

    def revert(self):  # pragma: nocover (requires user input)
        self.config_manager.revert(with_config_file=self.config_file)
        NetplanApply.command_apply(run_generate=False)

    def cleanup(self):  # pragma: nocover (requires user input)
        self.config_manager.cleanup()

    def _signal_handler(self, signal, frame):  # pragma: nocover (requires user input)
        if self.configuration_changed:
            raise ConfigurationRejected()


class ConfigurationAccepted(Exception):
    pass


class ConfigurationRejected(Exception):
    pass
