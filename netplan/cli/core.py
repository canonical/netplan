#!/usr/bin/python3
#
# Copyright (C) 2018 Canonical, Ltd.
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

import logging
import os
import sys
import re
from glob import glob
import yaml

import netplan.cli.utils as utils


class Netplan(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='',
                         description='Network configuration in YAML',
                         leaf=False)

    #
    # helper functions
    #
    def parse_args(self):
        from netplan.cli.commands import NetplanApply
        from netplan.cli.commands import NetplanGenerate
        from netplan.cli.commands import NetplanIp

        # command: generate
        self.command_generate = NetplanGenerate()
        p_generate = self.subparsers.add_parser('generate',
                                                description='Generate backend specific configuration files'
                                                            ' from /etc/netplan/*.yaml',
                                                help='Generate backend specific configuration files from /etc/netplan/*.yaml',
                                                add_help=False)
        p_generate.set_defaults(func=self.command_generate.run, commandclass=self.command_generate)

        # command: apply
        self.command_apply = NetplanApply()
        p_apply = self.subparsers.add_parser('apply',
                                             description='Apply current netplan config to running system',
                                             help='Apply current netplan config to running system (use with care!)',
                                             add_help=False)
        p_apply.set_defaults(func=self.command_apply.run, commandclass=self.command_apply)

        # command: ifupdown-migrate
        p_ifupdown = self.subparsers.add_parser('ifupdown-migrate',
                                                description='Migration of /etc/network/interfaces to netplan',
                                                help='Try to convert /etc/network/interfaces to netplan '
                                                     'If successful, disable /etc/network/interfaces')
        p_ifupdown.add_argument('--root-dir',
                                help='Search for and generate configuration files in this root directory instead of /')
        p_ifupdown.add_argument('--dry-run', action='store_true',
                                help='Print converted netplan configuration to stdout instead of writing/changing files')
        p_ifupdown.set_defaults(func=self.command_ifupdown_migrate)

        # command: ip
        self.command_ip = NetplanIp()
        p_ip = self.subparsers.add_parser('ip',
                                          description='Describe current IP configuration',
                                          help='Describe current IP configuration',
                                          add_help=False)
        p_ip.set_defaults(func=self.command_ip.run, commandclass=self.command_ip)

        super().parse_args()

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
