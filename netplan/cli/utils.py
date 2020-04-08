#!/usr/bin/python3
#
# Copyright (C) 2018-2020 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
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
import logging
import fnmatch
import argparse
import subprocess
import netifaces

NM_SERVICE_NAME = 'NetworkManager.service'
NM_SNAP_SERVICE_NAME = 'snap.network-manager.networkmanager.service'


def get_generator_path():
    return os.environ.get('NETPLAN_GENERATE_PATH', '/lib/netplan/generate')


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


def systemctl_network_manager(action, sync=False):  # pragma: nocover (covered in autopkgtest)
    service_name = NM_SERVICE_NAME

    command = ['systemctl', action]
    if not sync:
        command.append('--no-block')

    # If the network-manager snap is installed use its service
    # name rather than the one of the deb packaged NetworkManager
    if is_nm_snap_enabled():
        service_name = NM_SNAP_SERVICE_NAME

    command.append(service_name)

    subprocess.check_call(command)


def systemctl_networkd(action, sync=False, extra_services=[]):  # pragma: nocover (covered in autopkgtest)
    command = ['systemctl', action]

    if not sync:
        command.append('--no-block')

    command.append('systemd-networkd.service')

    for service in extra_services:
        command.append(service)

    subprocess.check_call(command)


def get_interface_driver_name(interface, only_down=False):  # pragma: nocover (covered in autopkgtest)
    devdir = os.path.join('/sys/class/net', interface)
    if only_down:
        try:
            with open(os.path.join(devdir, 'operstate')) as f:
                state = f.read().strip()
                if state != 'down':
                    logging.debug('device %s operstate is %s, not changing', interface, state)
                    return None
        except IOError as e:
            logging.error('Cannot determine operstate of %s: %s', interface, str(e))
            return None

    try:
        driver = os.path.realpath(os.path.join(devdir, 'device', 'driver'))
        driver_name = os.path.basename(driver)
    except IOError as e:
        logging.debug('Cannot replug %s: cannot read link %s/device: %s', interface, devdir, str(e))
        return None

    return driver_name


def get_interface_macaddress(interface):  # pragma: nocover (covered in autopkgtest)
    link = netifaces.ifaddresses(interface)[netifaces.AF_LINK][0]

    return link.get('addr')


def is_interface_matching_name(interface, match_driver):
    return fnmatch.fnmatchcase(interface, match_driver)


def is_interface_matching_driver_name(interface, match_driver):
    driver_name = get_interface_driver_name(interface)

    return match_driver == driver_name


def is_interface_matching_macaddress(interface, match_mac):
    macaddress = get_interface_macaddress(interface)

    return match_mac == macaddress


class NetplanCommand(argparse.Namespace):

    def __init__(self, command_id, description, leaf=True, testing=False):
        self.command_id = command_id
        self.description = description
        self.leaf_command = leaf
        self.testing = testing
        self._args = None
        self.debug = False
        self.commandclass = None
        self.subcommands = {}
        self.subcommand = None
        self.func = None

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

        # TODO: (cyphermox) this is actually testable in tests/cli.py; add it.
        if self.leaf_command and 'help' in self._args:  # pragma: nocover (covered in autopkgtest)
            self.print_usage()

        self.func()

    def print_usage(self):
        self.parser.print_help(file=sys.stderr)
        sys.exit(os.EX_USAGE)

    def _add_subparser_from_class(self, name, commandclass):
        instance = commandclass()

        self.subcommands[name] = {}
        self.subcommands[name]['class'] = name
        self.subcommands[name]['instance'] = instance

        if instance.testing:
            if not os.environ.get('ENABLE_TEST_COMMANDS', None):
                return

        p = self.subparsers.add_parser(instance.command_id,
                                       description=instance.description,
                                       help=instance.description,
                                       add_help=False)
        p.set_defaults(func=instance.run, commandclass=instance)
        self.subcommands[name]['parser'] = p

    def _import_subcommands(self, submodules):
        import inspect
        for name, obj in inspect.getmembers(submodules):
            if inspect.isclass(obj) and issubclass(obj, NetplanCommand):
                self._add_subparser_from_class(name, obj)
