# Copyright (C) 2018-2020 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
# Author: Lukas 'slyon' Märdian <lukas.maerdian@canonical.com>
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
import argparse
import subprocess
import netifaces
import fnmatch
import re

NM_SERVICE_NAME = 'NetworkManager.service'
NM_SNAP_SERVICE_NAME = 'snap.network-manager.networkmanager.service'


def get_generator_path():
    return os.environ.get('NETPLAN_GENERATE_PATH', '/lib/netplan/generate')


def is_nm_snap_enabled():
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


def nm_interfaces(paths, devices):
    pat = re.compile('^interface-name=(.*)$')
    interfaces = set()
    for path in paths:
        with open(path, 'r') as f:
            for line in f:
                m = pat.match(line)
                if m:
                    # Expand/match globbing of interface names, to real devices
                    interfaces.update(set(fnmatch.filter(devices, m.group(1))))
                    break  # skip to next file
    return interfaces


def systemctl_network_manager(action, sync=False):
    # If the network-manager snap is installed use its service
    # name rather than the one of the deb packaged NetworkManager
    if is_nm_snap_enabled():
        return systemctl(action, [NM_SNAP_SERVICE_NAME], sync)
    return systemctl(action, [NM_SERVICE_NAME], sync)  # pragma: nocover (covered in autopkgtest)


def systemctl(action, services, sync=False):
    if len(services) >= 1:
        command = ['systemctl', action]

        if not sync:
            command.append('--no-block')

        command.extend(services)

        subprocess.check_call(command)


def networkd_interfaces():
    interfaces = set()
    out = subprocess.check_output(['networkctl', '--no-pager', '--no-legend'], universal_newlines=True)
    for line in out.splitlines():
        s = line.strip().split(' ')
        if s[0].isnumeric() and s[-1] not in ['unmanaged', 'linger']:
            interfaces.add(s[0])
    return interfaces


def networkctl_reload():
    subprocess.check_call(['networkctl', 'reload'])


def networkctl_reconfigure(interfaces):
    if len(interfaces) >= 1:
        subprocess.check_call(['networkctl', 'reconfigure'] + list(interfaces))


def systemctl_is_active(unit_pattern):
    '''Return True if at least one matching unit is running'''
    if subprocess.call(['systemctl', '--quiet', 'is-active', unit_pattern]) == 0:
        return True
    return False


def systemctl_daemon_reload():
    '''Reload systemd unit files from disk and re-calculate its dependencies'''
    subprocess.check_call(['systemctl', 'daemon-reload'])


def ip_addr_flush(iface):
    '''Flush all IP addresses of a given interface via iproute2'''
    subprocess.check_call(['ip', 'addr', 'flush', iface], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


def get_interface_macaddress(interface):
    # return an empty list (and string) if no LL data can be found
    link = netifaces.ifaddresses(interface).get(netifaces.AF_LINK, [{}])[0]
    return link.get('addr', '')


def is_interface_matching_name(interface, match_name):
    # globs are supported
    return fnmatch.fnmatchcase(interface, match_name)


def is_interface_matching_driver_name(interface, match_driver):
    driver_globs = match_driver
    if isinstance(driver_globs, str):
        driver_globs = [match_driver]
    driver_name = get_interface_driver_name(interface)
    # globs are supported
    return any(
        fnmatch.fnmatchcase(driver_name, pattern)
        for pattern in driver_globs
    )


def is_interface_matching_macaddress(interface, match_mac):
    macaddress = get_interface_macaddress(interface)
    # exact, case insensitive match. globs are not supported
    return match_mac.lower() == macaddress.lower()


def find_matching_iface(interfaces, match):
    assert isinstance(match, dict)

    # Filter for match.name glob, fallback to '*'
    name_glob = match.get('name') if match.get('name', False) else '*'
    matches = fnmatch.filter(interfaces, name_glob)

    # Filter for match.macaddress (exact match)
    if len(matches) > 1 and match.get('macaddress'):
        matches = list(filter(lambda iface: is_interface_matching_macaddress(iface, match.get('macaddress')), matches))

    # Filter for match.driver glob
    if len(matches) > 1 and match.get('driver'):
        matches = list(filter(lambda iface: is_interface_matching_driver_name(iface, match.get('driver')), matches))

    # Return current name of unique matched interface, if available
    if len(matches) != 1:
        logging.info(matches)
        return None
    return matches[0]


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
