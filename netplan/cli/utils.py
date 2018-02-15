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

import sys
import os
import argparse
import subprocess

NM_SERVICE_NAME = 'NetworkManager.service'
NM_SNAP_SERVICE_NAME = 'snap.network-manager.networkmanager.service'


def is_nm_snap_enabled():  # pragma: nocover (covered in autopkgtest)
    return subprocess.call(['systemctl', '--quiet', 'is-enabled', NM_SNAP_SERVICE_NAME], stderr=subprocess.DEVNULL) == 0


def nmcli(args):  # pragma: nocover (covered in autopkgtest)
    binary_name = 'nmcli'

    if is_nm_snap_enabled():
        binary_name = 'network-manager.nmcli'

    subprocess.check_call([binary_name] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def nm_running():  # pragma: nocover (covered in autopkgtest)
    '''Check if NetworkManager is running'''

    try:
        nmcli(['general'])
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def systemctl_network_manager(action):  # pragma: nocover (covered in autopkgtest)
    service_name = NM_SERVICE_NAME

    # If the network-manager snap is installed use its service
    # name rather than the one of the deb packaged NetworkManager
    if is_nm_snap_enabled():
        service_name = NM_SNAP_SERVICE_NAME

    subprocess.check_call(['systemctl', action, '--no-block', service_name])


class NetplanCommand(argparse.Namespace):

    def __init__(self, command_id, description, leaf):
        self.command_id = command_id
        self.leaf_command = leaf
        self.debug = False
        self._args = None
        self.commandclass = None
        self.func = None
        self.subcommand = None

        self.parser = argparse.ArgumentParser(prog="%s %s" % (sys.argv[0], command_id),
                                              description=description,
                                              add_help=True)
        self.parser.add_argument('--debug', action='store_true',
                                 help='Enable debug messages')
        if not leaf:
            self.subparsers = self.parser.add_subparsers(title='Available commands',
                                                         metavar='', dest='subcommand')
            p_help = self.subparsers.add_parser('help',
                                                description='Show this help message',
                                                help='Show this help message')
            p_help.set_defaults(func=self.print_usage)

    def update(self, args):
        self._args = args

    def parse_args(self):
        ns, self._args = self.parser.parse_known_args(args=self._args, namespace=self)

        if not self.subcommand and not self.leaf_command:
            print('You need to specify a command', file=sys.stderr)
            self.print_usage()

    def run_command(self):
        if self.commandclass:
            self.commandclass.update(self._args)

        self.func()

    def print_usage(self):
        self.parser.print_help(file=sys.stderr)
        sys.exit(os.EX_USAGE)
