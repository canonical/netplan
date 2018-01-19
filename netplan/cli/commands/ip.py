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

'''netplan ip command line'''

import argparse
import logging
import os
import sys
import subprocess

from netplan.cli.core import Netplan

path_generate = os.environ.get('NETPLAN_GENERATE_PATH', '/lib/netplan/generate')

lease_path = {
    'networkd': {
        'pattern': 'run/systemd/netif/leases/{lease_id}',
        'method': 'ifindex',
    },
    'NetworkManager': {
        'pattern': 'var/lib/NetworkManager/dhclient-{lease_id}-{interface}.lease',
        'method': 'nm_connection',
    },
}

class NetplanIp(Netplan):

    def __init__(self):
        self._args = None

    def update(self, args):
        self._args = args

    def run(self):
        parser = argparse.ArgumentParser(prog='netplan ip', description='netplan ip commands')
        subparsers = parser.add_subparsers(title='Available commands (see "netplan ip <command> --help")',
                                           metavar='', dest='subcommand')

        # subcommand: leases
        p_ip_leases = subparsers.add_parser('leases',
                                            help='Display IP leases.')
        p_ip_leases.add_argument('interface',
                                 help='Interface for which to display IP lease settings.')
        p_ip_leases.add_argument('--root-dir',
                                 help='Search for configuration files in this root directory instead of /')
        p_ip_leases.set_defaults(func=self.command_ip_leases)

        args = parser.parse_args(self._args, namespace=self)

        if not self.subcommand:
            self.print_usage(parser)

        args.func()

    def command_ip_leases(self):
        def find_lease_file(mapping):
            def lease_method_ifindex():
                ifindex_f = os.path.join('/sys/class/net', self.interface, 'ifindex')
                try:
                    with open(ifindex_f) as f:
                        return f.readlines()[0].strip()
                except IOError as e:
                    logging.debug('Cannot replug %s: cannot read link %s/ifindex: %s', device, devdir, str(e))
                    raise
                return ifindex

            def lease_method_nm_connection():
                nmcli_dev_out = subprocess.Popen(['nmcli', 'dev', 'show', self.interface], env={'LC_ALL': 'C'}, stdout=subprocess.PIPE)
                for line in nmcli_dev_out.stdout:
                    line = line.decode('utf-8')
                    if 'GENERAL.CONNECTION' in line:
                        conn_id = line.split(':')[1].rstrip().strip()
                        nmcli_con_out = subprocess.Popen(['nmcli', 'con', 'show', 'id', conn_id], env={'LC_ALL': 'C'}, stdout=subprocess.PIPE)
                        for line in nmcli_con_out.stdout:
                            line = line.decode('utf-8')
                            if 'connection.uuid' in line:
                                return line.split(':')[1].rstrip().strip()
                raise IOError('device not found')

            lease_pattern = lease_path[mapping['backend']]['pattern']
            lease_method = lease_path[mapping['backend']]['method']

            lease_id = eval("lease_method_" + lease_method)()
            with open(os.path.join('/',
                                   os.path.abspath(self.root_dir),
                                   lease_pattern.format(interface=self.interface,
                                                        lease_id=lease_id))) as f:
                for line in f.readlines():
                    print(line.rstrip())

        argv = [path_generate]
        if self.root_dir:
            argv += ['--root-dir', self.root_dir]
        argv += ['--mapping', self.interface]

        # Extract out of the generator our mapping in a dict.
        logging.debug('command ip leases: running %s', argv)
        out = subprocess.check_output(argv, universal_newlines=True)
        mapping = {}
        mapping_s = out.split(',')
        for keyvalue in mapping_s:
            key, value = keyvalue.strip().split('=')
            mapping[key] = value

        find_lease_file(mapping)
