#!/usr/bin/python3
#
# Copyright (C) 2016 Canonical, Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
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

'''netplan command line'''

import argparse
import logging
import os
import sys
import re
import subprocess
from glob import glob
import yaml

path_generate = os.environ.get('NETPLAN_GENERATE_PATH', '/lib/netplan/generate')


class Netplan(argparse.Namespace):

    def __init__(self):
        self._args = None

    #
    # helper functions
    #
    def parse_args(self):
        self.parser = argparse.ArgumentParser(description='netplan commands')
        self.parser.add_argument('--debug', action='store_true',
                                 help='Enable debug messages')
        subparsers = self.parser.add_subparsers(title='Available commands (see "netplan <command> --help")',
                                                metavar='', dest='command')

        # command: generate
        p_generate = subparsers.add_parser('generate',
                                           description='Generate backend specific configuration files from /etc/netplan/*.yaml',
                                           help='Generate backend specific configuration files from /etc/netplan/*.yaml')
        p_generate.add_argument('--root-dir',
                                help='Search for and generate configuration files in this root directory instead of /')
        p_generate.set_defaults(func=self.command_generate)

        # command: apply
        p_apply = subparsers.add_parser('apply',
                                        description='Apply current netplan config to running system',
                                        help='Apply current netplan config to running system (use with care!)')
        p_apply.set_defaults(func=self.command_apply)

        # command: ifupdown-migrate
        p_ifupdown = subparsers.add_parser('ifupdown-migrate',
                                           description='Migration of /etc/network/interfaces to netplan',
                                           help='Try to convert /etc/network/interfaces to netplan '
                                                'If successful, disable /etc/network/interfaces')
        p_ifupdown.add_argument('--root-dir',
                                help='Search for and generate configuration files in this root directory instead of /')
        p_ifupdown.add_argument('--dry-run', action='store_true',
                                help='Print converted netplan configuration to stdout instead of writing/changing files')
        p_ifupdown.set_defaults(func=self.command_ifupdown_migrate)

        ns, self._args = self.parser.parse_known_args(namespace=self)

        if not self.command:
            print('You need to specify a command', file=sys.stderr)
            self.print_usage(self.parser)

        return

    def print_usage(self, parser):
        parser.print_help(file=sys.stderr)
        sys.exit(os.EX_USAGE)

    def run_command(self):
        self.func()

    def nm_running(self):  # pragma: nocover (covered in autopkgtest)
        '''Check if NetworkManager is running'''

        try:
            subprocess.check_call(['nmcli', 'general'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def replug(self, device):  # pragma: nocover (covered in autopkgtest)
        '''Unbind and rebind device if it is down'''

        devdir = os.path.join('/sys/class/net', device)

        try:
            with open(os.path.join(devdir, 'operstate')) as f:
                state = f.read().strip()
                if state != 'down':
                    logging.debug('device %s operstate is %s, not replugging', device, state)
                    return False
        except IOError as e:
            logging.error('Cannot determine operstate of %s: %s', device, str(e))
            return False

        # /sys/class/net/ens3/device -> ../../../virtio0
        # /sys/class/net/ens3/device/driver -> ../../../../bus/virtio/drivers/virtio_net
        try:
            devname = os.path.basename(os.readlink(os.path.join(devdir, 'device')))
        except IOError as e:
            logging.debug('Cannot replug %s: cannot read link %s/device: %s', device, devdir, str(e))
            return False

        try:
            # we must resolve symlinks here as the device dir will be gone after unbind
            subsystem = os.path.realpath(os.path.join(devdir, 'device', 'subsystem'))
            subsystem_name = os.path.basename(subsystem)
            driver = os.path.realpath(os.path.join(devdir, 'device', 'driver'))
            driver_name = os.path.basename(driver)
            if driver_name == 'mac80211_hwsim':
                logging.debug('replug %s: mac80211_hwsim does not support rebinding, ignoring', device)
                return False
            # workaround for https://bugs.launchpad.net/ubuntu/+source/linux/+bug/1630285
            if driver_name == 'mwifiex_pcie':
                logging.debug('replug %s: mwifiex_pcie crashes on rebinding, ignoring', device)
                return False
            # workaround for https://bugs.launchpad.net/ubuntu/+source/linux/+bug/1729573
            if subsystem_name == 'xen' and driver_name == 'vif':
                logging.debug('replug %s: xen:vif fails on rebinding, ignoring', device)
                return False
            # workaround for problem with ath9k_htc module: this driver is async and does not support
            # sequential unbind / rebind, one soon after the other
            if driver_name == 'ath9k_htc':
                logging.debug('replug %s: ath9k_htc does not support rebinding, ignoring', device)
                return False
            # workaround for brcmfmac, interface will be gone after unbind
            if 'brcmfmac' in driver_name:
                logging.debug('replug %s: brcmfmac drivers do not support rebinding, ignoring', device)
                return False
            logging.debug('replug %s: unbinding %s from %s', device, devname, driver)
            with open(os.path.join(driver, 'unbind'), 'w') as f:
                f.write(devname)
            logging.debug('replug %s: rebinding %s to %s', device, devname, driver)
            with open(os.path.join(driver, 'bind'), 'w') as f:
                f.write(devname)
        except IOError as e:
            logging.error('Cannot replug %s: %s', device, str(e))
            return False

        return True

    def _ifupdown_lines_from_file(self, rootdir, path):
        '''Return normalized lines from ifupdown config

        This resolves "source" and "source-directory" includes.
        '''
        def expand_source_arg(rootdir, curdir, line):
            arg = line.split()[1]
            if arg.startswith('/'):
                return rootdir + arg
            else:
                return curdir + '/' + arg

        lines = []
        rootdir_len = len(rootdir) + 1
        try:
            with open(rootdir + '/' + path) as f:
                logging.debug('reading %s', f.name)
                for line in f:
                    # normalize, strip empty lines and comments
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    if line.startswith('source-directory '):
                        valid_re = re.compile('^[a-zA-Z0-9_-]+$')
                        d = expand_source_arg(rootdir, os.path.dirname(f.name), line)
                        for f in os.listdir(d):
                            if valid_re.match(f):
                                lines += self._ifupdown_lines_from_file(rootdir, os.path.join(d[rootdir_len:], f))
                    elif line.startswith('source '):
                        for f in glob(expand_source_arg(rootdir, os.path.dirname(f.name), line)):
                            lines += self._ifupdown_lines_from_file(rootdir, f[rootdir_len:])
                    else:
                        lines.append(line)
        except FileNotFoundError:
            logging.debug('%s/%s does not exist, ignoring', rootdir, path)
        return lines

    def parse_ifupdown(self, rootdir='/'):
        '''Parse ifupdown configuration.

        Return (iface_name →  family → {method, options}, auto_ifaces: set) tuple
        on successful parsing, or a ValueError when encountering an invalid file or
        ifupdown features which are not supported (such as "mapping").

        options is itself a dictionary option_name → value.
        '''
        # expected number of fields for every possible keyword, excluding the keyword itself
        fieldlen = {'auto': 1, 'allow-auto': 1, 'allow-hotplug': 1, 'mapping': 1, 'no-scripts': 1, 'iface': 3}

        # read and normalize all lines from config, with resolving includes
        lines = self._ifupdown_lines_from_file(rootdir, '/etc/network/interfaces')

        ifaces = {}
        auto = set()
        in_options = None  # interface name if parsing options lines after iface stanza
        in_family = None

        # we now have resolved all includes and normalized lines
        for line in lines:
            fields = line.split()

            try:
                # does the line start with a known stanza field?
                exp_len = fieldlen[fields[0]]
                logging.debug('line fields %s (expected length: %i)', fields, exp_len)
                in_options = None  # stop option line parsing of iface stanza
                in_family = None
            except KeyError:
                # no known stanza field, are we in an iface stanza and parsing options?
                if in_options:
                    logging.debug('in_options %s, parsing as option: %s', in_options, line)
                    ifaces[in_options][in_family]['options'][fields[0]] = line.split(maxsplit=1)[1]
                    continue
                else:
                    raise ValueError('Unknown stanza type %s' % fields[0])

            # do we have the expected #parameters?
            if len(fields) != exp_len + 1:
                raise ValueError('Expected %i fields for stanza type %s but got %i' %
                                 (exp_len, fields[0], len(fields) - 1))

            # we have a valid stanza line now, handle them
            if fields[0] in ('auto', 'allow-auto', 'allow-hotplug'):
                auto.add(fields[1])
            elif fields[0] == 'mapping':
                raise ValueError('mapping stanza is not supported')
            elif fields[0] == 'no-scripts':
                pass  # ignore these
            elif fields[0] == 'iface':
                if fields[2] not in ('inet', 'inet6'):
                    raise ValueError('Unknown address family %s' % fields[2])
                if fields[3] not in ('loopback', 'static', 'dhcp'):
                    raise ValueError('Unsupported method %s' % fields[3])
                in_options = fields[1]
                in_family = fields[2]
                ifaces.setdefault(fields[1], {})[in_family] = {'method': fields[3], 'options': {}}
            else:
                raise NotImplementedError('stanza type %s is not implemented' % fields[0])  # pragma nocover

        logging.debug('final parsed interfaces: %s; auto ifaces: %s', ifaces, auto)
        return (ifaces, auto)

    #
    # implementation of the top-level commands
    #
    def command_generate(self):
        argv = [path_generate]
        if self.root_dir:
            argv += ['--root-dir', self.root_dir]
        logging.debug('command generate: running %s', argv)
        # FIXME: os.execv(argv[0], argv) would be better but fails coverage
        sys.exit(subprocess.call(argv))

    def command_apply(self):  # pragma: nocover (covered in autopkgtest)
        if subprocess.call([path_generate]) != 0:
            sys.exit(1)

        devices = os.listdir('/sys/class/net')

        restart_networkd = bool(glob('/run/systemd/network/*netplan-*'))
        restart_nm = bool(glob('/run/NetworkManager/system-connections/netplan-*'))

        # stop backends
        if restart_networkd:
            logging.debug('netplan generated networkd configuration exists, restarting networkd')
            subprocess.check_call(['systemctl', 'stop', '--no-block', 'systemd-networkd.service', 'netplan-wpa@*.service'])
        else:
            logging.debug('no netplan generated networkd configuration exists')

        if restart_nm:
            logging.debug('netplan generated NM configuration exists, restarting NM')
            if self.nm_running():
                # restarting NM does not cause new config to be applied, need to shut down devices first
                for device in devices:
                    # ignore failures here -- some/many devices might not be managed by NM
                    subprocess.call(['nmcli', 'device', 'disconnect', device], stderr=subprocess.DEVNULL)
                subprocess.check_call(['systemctl', 'stop', '--no-block', 'NetworkManager.service'])
        else:
            logging.debug('no netplan generated NM configuration exists')

        # force-hotplug all "down" network interfaces to apply renames
        any_replug = False
        for device in devices:
            if not os.path.islink('/sys/class/net/' + device):
                continue
            if self.replug(device):
                any_replug = True
            else:
                # if the interface is up, we can still apply .link file changes
                logging.debug('netplan triggering .link rules for %s', device)
                with open(os.devnull, 'w') as fd:
                    subprocess.check_call(['udevadm', 'test-builtin',
                                           'net_setup_link',
                                           '/sys/class/net/' + device],
                                          stdout=fd, stderr=fd)
        if any_replug:
            subprocess.check_call(['udevadm', 'settle'])

        # (re)start backends
        if restart_networkd:
            subprocess.check_call(['systemctl', 'start', '--no-block', 'systemd-networkd.service'] +
                                  [os.path.basename(f) for f in glob('/run/systemd/system/*.wants/netplan-wpa@*.service')])
        if restart_nm:
            subprocess.call(['systemctl', 'start', '--no-block', 'NetworkManager.service'])

    def command_ifupdown_migrate(self):
        netplan_config = {}
        try:
            ifaces, auto_ifaces = self.parse_ifupdown(self.root_dir or '')
        except ValueError as e:
            logging.error(str(e))
            sys.exit(2)
        for iface, family_config in ifaces.items():
            for family, config in family_config.items():
                logging.debug('Converting %s family %s %s', iface, family, config)
                if iface not in auto_ifaces:
                    logging.error('%s: non-automatic interfaces are not supported', iface)
                    sys.exit(2)
                if config['method'] == 'loopback':
                    # both systemd and modern ifupdown set up lo automatically
                    logging.debug('Ignoring loopback interface %s', iface)
                elif config['method'] == 'dhcp':
                    if config['options']:
                        logging.error('%s: options are not supported for dhcp method', iface)
                        sys.exit(2)
                    c = netplan_config.setdefault('network', {}).setdefault('ethernets', {}).setdefault(iface, {})
                    if family == 'inet':
                        c['dhcp4'] = True
                    else:
                        assert family == 'inet6'
                        c['dhcp6'] = True
                else:
                    logging.error('%s: method %s is not supported', iface, config['method'])
                    sys.exit(2)

        if_config = os.path.join(self.root_dir or '/', 'etc/network/interfaces')

        if netplan_config:
            netplan_config['network']['version'] = 2
            netplan_yaml = yaml.dump(netplan_config)
            if self.dry_run:
                print(netplan_yaml)
            else:
                dest = os.path.join(self.root_dir or '/', 'etc/netplan/10-ifupdown.yaml')
                try:
                    os.makedirs(os.path.dirname(dest))
                except FileExistsError:
                    pass
                try:
                    with open(dest, 'x') as f:
                        f.write(netplan_yaml)
                except FileExistsError:
                    logging.error('%s already exists; remove it if you want to run the migration again', dest)
                    sys.exit(3)
                logging.info('migration complete, wrote %s', dest)
        else:
            logging.info('ifupdown does not configure any interfaces, nothing to migrate')

        if not self.dry_run:
            logging.info('renaming %s to %s.netplan-converted', if_config, if_config)
            os.rename(if_config, if_config + '.netplan-converted')

    #
    # main
    #
    def main(self):
        self.parse_args()

        if self.debug:
            logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(message)s')
            os.environ['G_MESSAGES_DEBUG'] = 'all'
        else:
            logging.basicConfig(level=logging.INFO, format='%(message)s')

        self.run_command()

