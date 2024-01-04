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

import logging
import netplan
import os
import time
import shutil
import signal
import sys
import tempfile

from ...configmanager import ConfigManager
from .. import utils
from .apply import NetplanApply
from ... import terminal

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
        self.new_interfaces = None
        self.config_file = None
        self._config_manager = None
        self.t_settings = None
        self.t = None
        self._rootdir = os.environ.get('DBUS_TEST_NETPLAN_ROOT', '/')
        self._netplan_try_stamp = os.path.join(self._rootdir, 'run', 'netplan', 'netplan-try.ready')

    @property
    def config_manager(self):  # pragma: nocover (called by later commands)
        if not self._config_manager:
            self._config_manager = ConfigManager(prefix=self._rootdir)
        return self._config_manager

    def clear_ready_stamp(self):
        if os.path.isfile(self._netplan_try_stamp):
            os.remove(self._netplan_try_stamp)
            return True
        return False

    def touch_ready_stamp(self):
        os.makedirs(self._rootdir + '/run/netplan', mode=0o700, exist_ok=True)
        open(self._netplan_try_stamp, 'w').close()

    def run(self):  # pragma: nocover (requires user input)
        self.parser.add_argument('--config-file',
                                 help='Apply the config file in argument in addition to current configuration.')
        self.parser.add_argument('--timeout',
                                 type=int, default=DEFAULT_INPUT_TIMEOUT,
                                 help="Maximum number of seconds to wait for the user's confirmation")
        self.parser.add_argument('--state',
                                 help='Directory containing previous YAML configuration')

        self.func = self.command_try

        self.parse_args()
        self.run_command()

    def command_try(self):  # pragma: nocover (requires user input)
        if not self.is_revertable():
            sys.exit(os.EX_CONFIG)

        try:
            fd = sys.stdin.fileno()
            self.t = terminal.Terminal(fd)
            self.t.save(self.t_settings)

            # we really don't want to be interrupted while doing backup/revert operations
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGUSR1, self._signal_handler)

            self.backup()
            self.setup()

            NetplanApply().command_apply(run_generate=True, sync=True, exit_on_error=False, state_dir=self.state)

            # Touch stamp file, it is the signal (for netplan-dbus) that we're
            # ready to accept any Accept/Reject input (like SIGUSR1 or SIGTERM)
            self.touch_ready_stamp()
            self.t.get_confirmation_input(timeout=self.timeout)
        except terminal.InputRejected:
            print("\nReverting.")
            self.revert()
        except terminal.InputAccepted:
            print("\nConfiguration accepted.")
        except Exception as e:
            print("\nAn error occurred: %s" % e)
            print("\nReverting.")
            self.revert()
        finally:
            if self.t:
                self.t.reset(self.t_settings)
            self.cleanup()
            self.clear_ready_stamp()

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
        # backup the state we just tried to apply
        tempdir = tempfile.mkdtemp()
        confdir = os.path.join(tempdir, 'etc', 'netplan')
        os.makedirs(confdir)
        shutil.copytree('/etc/netplan', confdir, dirs_exist_ok=True)
        # restore previous state
        self.config_manager.revert()
        NetplanApply().command_apply(run_generate=False, sync=True, exit_on_error=False, state_dir=tempdir)
        # clear the backup
        shutil.rmtree(tempdir)

    def cleanup(self):  # pragma: nocover (requires user input)
        self.config_manager.cleanup()

    def is_revertable(self):
        '''
        Check if the configuration is revertable, if it doesn't contain bits
        that we know are likely to render the system unstable if we apply it,
        or if we revert.

        Returns True if the parsed config is "revertable", meaning that we
        can actually rely on backends to re-apply /all/ of the relevant
        configuration to interfaces when their config changes.

        Returns False if the parsed config contains options that are known
        to not cleanly revert via the backend.
        '''

        extra_config = []
        if self.config_file:
            extra_config.append(self.config_file)
        np_state = None
        try:
            np_state = self.config_manager.parse(extra_config=extra_config)
        except utils.config_errors as e:
            logging.error(e)
            sys.exit(os.EX_CONFIG)

        revert_unsupported = []

        # Bridges and bonds are special. They typically include (or could include)
        # more than one device in them, and they can be set with special parameters
        # to tweak their behavior, which are really hard to "revert", especially
        # as systemd-networkd doesn't necessarily touch them when config changes.
        multi_iface: dict[str, netplan.NetDefinition] = {}
        multi_iface.update(np_state.bridges)
        multi_iface.update(np_state.bonds)
        for itf in multi_iface.values():
            if not itf._is_trivial_compound_itf:
                reason = "reverting custom parameters for bridges and bonds is not supported"
                revert_unsupported.append((itf.id, reason))

        if revert_unsupported:
            for ifname, reason in revert_unsupported:
                print("{}: {}".format(ifname, reason))
            print("\nPlease carefully review the configuration and use 'netplan apply' directly.")
            return False
        return True

    def _signal_handler(self, sig, frame):  # pragma: nocover (requires user input)
        if sig == signal.SIGUSR1:
            raise terminal.InputAccepted()
        else:
            if self.configuration_changed:
                raise terminal.InputRejected()
