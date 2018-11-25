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

import logging
import os
import sys
import subprocess
from subprocess import CalledProcessError

import netplan.cli.utils as utils

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


class NetplanIp(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='ip',
                         description='Retrieve IP information from the system',
                         leaf=False)

    def run(self):
        self.command_leases = NetplanIpLeases()

        # subcommand: leases
        p_ip_leases = self.subparsers.add_parser('leases',
                                                 help='Display IP leases',
                                                 add_help=False)
        p_ip_leases.set_defaults(func=self.command_leases.run, commandclass=self.command_leases)

        self.parse_args()
        self.run_command()


class NetplanIpLeases(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='ip leases',
                         description='Display IP leases',
                         leaf=True)

    def run(self):
        self.parser.add_argument('interface',
                                 help='Interface for which to display IP lease settings.')
        self.parser.add_argument('--root-dir',
                                 help='Search for configuration files in this root directory instead of /')

        self.func = self.command_ip_leases

        self.parse_args()
        self.run_command()

    def command_ip_leases(self):

        if self.interface == 'help':  # pragma: nocover (covered in autopkgtest)
            self.print_usage()

        def find_lease_file(mapping):
            def lease_method_ifindex():
                ifindex_f = os.path.join('/sys/class/net', self.interface, 'ifindex')
                try:
                    with open(ifindex_f) as f:
                        return f.readlines()[0].strip()
                except Exception as e:
                    logging.debug('Cannot read file %s: %s', ifindex_f, str(e))
                    raise

            def lease_method_nm_connection():  # pragma: nocover (covered in autopkgtest)
                # FIXME: handle older versions of NM where 'nmcli dev show' doesn't exist
                try:
                    nmcli_dev_out = subprocess.Popen(['nmcli', 'dev', 'show', self.interface],
                                                     env={'LC_ALL': 'C'},
                                                     stdout=subprocess.PIPE)
                    for line in nmcli_dev_out.stdout:
                        line = line.decode('utf-8')
                        if 'GENERAL.CONNECTION' in line:
                            conn_id = line.split(':')[1].rstrip().strip()
                            nmcli_con_out = subprocess.Popen(['nmcli', 'con', 'show', 'id', conn_id],
                                                             env={'LC_ALL': 'C'},
                                                             stdout=subprocess.PIPE)
                            for line in nmcli_con_out.stdout:
                                line = line.decode('utf-8')
                                if 'connection.uuid' in line:
                                    return line.split(':')[1].rstrip().strip()
                except Exception as e:
                    raise Exception('Could not find a NetworkManager connection for the interface: %s' % str(e))
                raise Exception('Could not find a NetworkManager connection for the interface')

            lease_pattern = lease_path[mapping['backend']]['pattern']
            lease_method = lease_path[mapping['backend']]['method']

            try:
                lease_id = eval("lease_method_" + lease_method)()

                # We found something to build the path to the lease file with,
                # at this point we may have something to look at; but if not,
                # we'll rely on open() throwing an error.
                # This might happen if networkd doesn't use DHCP for the interface,
                # for instance.
                with open(os.path.join('/',
                                       os.path.abspath(self.root_dir) if self.root_dir else "",
                                       lease_pattern.format(interface=self.interface,
                                                            lease_id=lease_id))) as f:
                    for line in f.readlines():
                        print(line.rstrip())
            except Exception as e:
                print("No lease found for interface '%s': %s" % (self.interface, str(e)),
                      file=sys.stderr)
                sys.exit(1)

        argv = [utils.get_generator_path()]
        if self.root_dir:
            argv += ['--root-dir', self.root_dir]
        argv += ['--mapping', self.interface]

        # Extract out of the generator our mapping in a dict.
        logging.debug('command ip leases: running %s', argv)
        try:
            out = subprocess.check_output(argv, universal_newlines=True)
        except CalledProcessError:  # pragma: nocover (better be covered in autopkgtest)
            sys.exit(1)
        mapping = {}
        mapping_s = out.split(',')
        for keyvalue in mapping_s:
            key, value = keyvalue.strip().split('=')
            mapping[key] = value

        find_lease_file(mapping)
