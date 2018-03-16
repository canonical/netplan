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

'''netplan migrate command line'''

import logging
import os
import sys
import re
from glob import glob
import yaml
from collections import OrderedDict
import ipaddress

import netplan.cli.utils as utils


class NetplanMigrate(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='migrate',
                         description='Migration of /etc/network/interfaces to netplan',
                         leaf=True,
                         testing=True)

    def parse_dns_options(self, if_options, if_config):
        """Parse dns options (dns-nameservers and dns-search) from if_options
        (an interface options dict) into the interface configuration if_config
        Mutates the arguments in place.
        """
        if 'dns-nameservers' in if_options:
            if 'nameservers' not in if_config:
                if_config['nameservers'] = {}
            if 'addresses' not in if_config['nameservers']:
                if_config['nameservers']['addresses'] = []
            for ns in if_options['dns-nameservers'].split(' '):
                # allow multiple spaces in the dns-nameservers entry
                if not ns:
                    continue
                # validate?
                if_config['nameservers']['addresses'] += [ns]
            del if_options['dns-nameservers']
        if 'dns-search' in if_options:
            if 'nameservers' not in if_config:
                if_config['nameservers'] = {}
            if 'search' not in if_config['nameservers']:
                if_config['nameservers']['search'] = []
            for domain in if_options['dns-search'].split(' '):
                # allow multiple spaces in the dns-search entry
                if not domain:
                    continue
                if_config['nameservers']['search'] += [domain]
            del if_options['dns-search']

    def parse_mtu(self, iface, if_options, if_config):
        """Parse out the MTU. Operates the same way as parse_dns_options
        iface is the name of the interface, used only to print error messages
        """

        if 'mtu' in if_options:
            try:
                mtu = int(if_options['mtu'])
            except ValueError:
                logging.error('%s: cannot parse "%s" as an MTU', iface, if_options['mtu'])
                sys.exit(2)

            if 'mtu' in if_config and not if_config['mtu'] == mtu:
                logging.error('%s: tried to set MTU=%d, but already have MTU=%d', iface, mtu, if_config['mtu'])
                sys.exit(2)

            if_config['mtu'] = mtu
            del if_options['mtu']

    def parse_hwaddress(self, iface, if_options, if_config):
        """Parse out the manually configured MAC.
        Operates the same way as parse_dns_options
        iface is the name of the interface, used only to print error messages
        """

        if 'hwaddress' in if_options:
            if 'macaddress' in if_config and not if_config['macaddress'] == if_options['hwaddress']:
                logging.error('%s: tried to set MAC %s, but already have MAC %s', iface,
                              if_options['hwaddress'], if_config['macaddress'])
                sys.exit(2)

            if_config['macaddress'] = if_options['hwaddress']
            del if_options['hwaddress']

    def run(self):
        self.parser.add_argument('--root-dir',
                                 help='Search for and generate configuration files in this root directory instead of /')
        self.parser.add_argument('--dry-run', action='store_true',
                                 help='Print converted netplan configuration to stdout instead of writing/changing files')
        self.func = self.command_migrate

        self.parse_args()
        self.run_command()

    def command_migrate(self):
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
                    c = netplan_config.setdefault('network', {}).setdefault('ethernets', {}).setdefault(iface, {})

                    self.parse_dns_options(config['options'], c)
                    self.parse_hwaddress(iface, config['options'], c)

                    if config['options']:
                        logging.error('%s: option(s) %s are not supported for dhcp method',
                                      iface, ", ".join(config['options'].keys()))
                        sys.exit(2)
                    if family == 'inet':
                        c['dhcp4'] = True
                    else:
                        assert family == 'inet6'
                        c['dhcp6'] = True

                elif config['method'] == 'static':
                    c = netplan_config.setdefault('network', {}).setdefault('ethernets', {}).setdefault(iface, {})

                    if 'addresses' not in c:
                        c['addresses'] = []

                    self.parse_dns_options(config['options'], c)
                    self.parse_mtu(iface, config['options'], c)
                    self.parse_hwaddress(iface, config['options'], c)

                    # ipv4
                    if family == 'inet':
                        # Already handled: mtu, hwaddress
                        # Supported: address netmask gateway
                        # Not supported yet: metric(?)
                        # No YAML support: pointopoint scope broadcast
                        supported_opts = set(['address', 'netmask', 'gateway'])
                        unsupported_opts = set(['broadcast', 'metric', 'pointopoint', 'scope'])

                        opts = set(config['options'].keys())
                        bad_opts = opts - supported_opts
                        if bad_opts:
                            for unsupported in bad_opts.intersection(unsupported_opts):
                                logging.error('%s: unsupported %s option "%s"', iface, family, unsupported)
                                sys.exit(2)
                            for unknown in bad_opts - unsupported_opts:
                                logging.error('%s: unknown %s option "%s"', iface, family, unknown)
                                sys.exit(2)

                        # the address may contain a /prefix suffix, or
                        # the netmask property may be used. It's not clear
                        # what happens if both are supplied.
                        if 'address' not in config['options']:
                            logging.error('%s: no address supplied in static method', iface)
                            sys.exit(2)

                        if '/' in config['options']['address']:
                            addr_spec = config['options']['address'].split('/')[0]
                            net_spec = config['options']['address']
                        else:
                            if 'netmask' not in config['options']:
                                logging.error('%s: address does not specify prefix length, and netmask not specified',
                                              iface)
                                sys.exit(2)
                            addr_spec = config['options']['address']
                            net_spec = config['options']['address'] + '/' + config['options']['netmask']

                        try:
                            ipaddr = ipaddress.IPv4Address(addr_spec)
                        except ipaddress.AddressValueError as a:
                            logging.error('%s: error parsing "%s" as an IPv4 address: %s', iface, addr_spec, a)
                            sys.exit(2)

                        try:
                            ipnet = ipaddress.IPv4Network(net_spec, strict=False)
                        except ipaddress.NetmaskValueError as a:
                            logging.error('%s: error parsing "%s" as an IPv4 network: %s', iface, net_spec, a)
                            sys.exit(2)

                        c['addresses'] += [str(ipaddr) + '/' + str(ipnet.prefixlen)]

                        if 'gateway' in config['options']:
                            # validate?
                            c['gateway4'] = config['options']['gateway']

                    # ipv6
                    else:
                        assert family == 'inet6'

                        # Already handled: mtu, hwaddress
                        # supported: address netmask gateway
                        # partially supported: accept_ra (0/1 supported, 2 has no YAML rep)
                        # unsupported: metric(?)
                        # no YAML representation: media autoconf privext scope
                        #                         preferred-lifetime dad-attempts dad-interval
                        supported_opts = set(['address', 'netmask', 'gateway', 'accept_ra'])
                        unsupported_opts = set(['metric', 'media', 'autoconf', 'privext',
                                                'scope', 'preferred-lifetime', 'dad-attempts', 'dad-interval'])

                        opts = set(config['options'].keys())
                        bad_opts = opts - supported_opts
                        if bad_opts:
                            for unsupported in bad_opts.intersection(unsupported_opts):
                                logging.error('%s: unsupported %s option "%s"', iface, family, unsupported)
                                sys.exit(2)
                            for unknown in bad_opts - unsupported_opts:
                                logging.error('%s: unknown %s option "%s"', iface, family, unknown)
                                sys.exit(2)

                        # the address may contain a /prefix suffix, or
                        # the netmask property may be used. It's not clear
                        # what happens if both are supplied.
                        if 'address' not in config['options']:
                            logging.error('%s: no address supplied in static method', iface)
                            sys.exit(2)

                        if '/' in config['options']['address']:
                            addr_spec = config['options']['address'].split('/')[0]
                            net_spec = config['options']['address']
                        else:
                            if 'netmask' not in config['options']:
                                logging.error('%s: address does not specify prefix length, and netmask not specified',
                                              iface)
                                sys.exit(2)
                            addr_spec = config['options']['address']
                            net_spec = config['options']['address'] + '/' + config['options']['netmask']

                        try:
                            ipaddr = ipaddress.IPv6Address(addr_spec)
                        except ipaddress.AddressValueError as a:
                            logging.error('%s: error parsing "%s" as an IPv6 address: %s', iface, addr_spec, a)
                            sys.exit(2)

                        try:
                            ipnet = ipaddress.IPv6Network(net_spec, strict=False)
                        except ipaddress.NetmaskValueError as a:
                            logging.error('%s: error parsing "%s" as an IPv6 network: %s', iface, net_spec, a)
                            sys.exit(2)

                        c['addresses'] += [str(ipaddr) + '/' + str(ipnet.prefixlen)]

                        if 'gateway' in config['options']:
                            # validate?
                            c['gateway6'] = config['options']['gateway']

                        if 'accept_ra' in config['options']:
                            if config['options']['accept_ra'] == '0':
                                c['accept_ra'] = False
                            elif config['options']['accept_ra'] == '1':
                                c['accept_ra'] = True
                            elif config['options']['accept_ra'] == '2':
                                logging.error('%s: netplan does not support accept_ra=2', iface)
                                sys.exit(2)
                            else:
                                logging.error('%s: unexpected accept_ra value "%s"', iface,
                                              config['options']['accept_ra'])
                                sys.exit(2)

                else:  # pragma nocover
                    # this should be unreachable
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

        ifaces = OrderedDict()
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
                ifaces.setdefault(fields[1], OrderedDict())[in_family] = {'method': fields[3], 'options': {}}
            else:
                raise NotImplementedError('stanza type %s is not implemented' % fields[0])  # pragma nocover

        logging.debug('final parsed interfaces: %s; auto ifaces: %s', ifaces, auto)
        return (ifaces, auto)
