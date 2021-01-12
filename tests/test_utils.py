#!/usr/bin/python3
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
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

import os
import unittest
import tempfile
import glob

from unittest.mock import patch

import netplan.cli.utils as utils


DEVICES = ['eth0', 'eth1', 'ens3', 'ens4', 'br0']


# Consider switching to something more standard, like MockProc
class MockCmd:
    """MockCmd will mock a given command name and capture all calls to it"""

    def __init__(self, name):
        self._tmp = tempfile.TemporaryDirectory()
        self.name = name
        self.path = os.path.join(self._tmp.name, name)
        self.call_log = os.path.join(self._tmp.name, "call.log")
        with open(self.path, "w") as fp:
            fp.write("""#!/bin/bash
printf "%%s" "$(basename "$0")" >> %(log)s
printf '\\0' >> %(log)s

for arg in "$@"; do
     printf "%%s" "$arg" >> %(log)s
     printf '\\0'  >> %(log)s
done

printf '\\0' >> %(log)s
""" % {'log': self.call_log})
        os.chmod(self.path, 0o755)

    def calls(self):
        """
        calls() returns the calls to the given mock command in the form of
        [ ["cmd", "call1-arg1"], ["cmd", "call2-arg1"], ... ]
        """
        with open(self.call_log) as fp:
            b = fp.read()
        calls = []
        for raw_call in b.rstrip("\0\0").split("\0\0"):
            call = raw_call.rstrip("\0")
            calls.append(call.split("\0"))
        return calls

    def set_output(self, output):
        with open(self.path, "a") as fp:
            fp.write("cat << EOF\n%s\nEOF" % output)

    def set_timeout(self, timeout_dsec=10):
        with open(self.path, "a") as fp:
            fp.write("""
if [[ "$*" == *try* ]]
then
    ACTIVE=1
    trap 'ACTIVE=0' SIGUSR1
    trap 'ACTIVE=0' SIGINT
    while (( $ACTIVE > 0 )) && (( $ACTIVE <= {} ))
    do
        ACTIVE=$(($ACTIVE+1))
        sleep 0.1
    done
fi
""".format(timeout_dsec))


class TestUtils(unittest.TestCase):

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.workdir.name, 'etc/netplan'))
        os.makedirs(os.path.join(self.workdir.name,
                    'run/NetworkManager/system-connections'))

    def _create_nm_keyfile(self, filename, ifname):
        with open(os.path.join(self.workdir.name,
                  'run/NetworkManager/system-connections/', filename), 'w') as f:
            f.write('[connection]\n')
            f.write('key=value\n')
            f.write('interface-name=%s\n' % ifname)
            f.write('key2=value2\n')

    def test_nm_interfaces(self):
        self._create_nm_keyfile('netplan-test.nmconnection', 'eth0')
        self._create_nm_keyfile('netplan-test2.nmconnection', 'eth1')
        ifaces = utils.nm_interfaces(glob.glob(os.path.join(self.workdir.name,
                                     'run/NetworkManager/system-connections/*.nmconnection')),
                                     DEVICES)
        self.assertTrue('eth0' in ifaces)
        self.assertTrue('eth1' in ifaces)
        self.assertTrue(len(ifaces) == 2)

    def test_nm_interfaces_globbing(self):
        self._create_nm_keyfile('netplan-test.nmconnection', 'eth?')
        ifaces = utils.nm_interfaces(glob.glob(os.path.join(self.workdir.name,
                                     'run/NetworkManager/system-connections/*.nmconnection')),
                                     DEVICES)
        self.assertTrue('eth0' in ifaces)
        self.assertTrue('eth1' in ifaces)
        self.assertTrue(len(ifaces) == 2)

    def test_nm_interfaces_globbing2(self):
        self._create_nm_keyfile('netplan-test.nmconnection', 'e*')
        ifaces = utils.nm_interfaces(glob.glob(os.path.join(self.workdir.name,
                                     'run/NetworkManager/system-connections/*.nmconnection')),
                                     DEVICES)
        self.assertTrue('eth0' in ifaces)
        self.assertTrue('eth1' in ifaces)
        self.assertTrue('ens3' in ifaces)
        self.assertTrue('ens4' in ifaces)
        self.assertTrue(len(ifaces) == 4)

    def test_find_matching_iface_too_many(self):
        # too many matches
        iface = utils.find_matching_iface(DEVICES, {'name': 'e*'})
        self.assertEqual(iface, None)

    @patch('netplan.cli.utils.get_interface_macaddress')
    def test_find_matching_iface(self, gim):
        # we mock-out get_interface_macaddress to return useful values for the test
        gim.side_effect = lambda x: '00:01:02:03:04:05' if x == 'eth1' else '00:00:00:00:00:00'

        match = {'name': 'e*', 'macaddress': '00:01:02:03:04:05'}
        iface = utils.find_matching_iface(DEVICES, match)
        self.assertEqual(iface, 'eth1')

    @patch('netplan.cli.utils.get_interface_driver_name')
    def test_find_matching_iface_name_and_driver(self, gidn):
        # we mock-out get_interface_driver_name to return useful values for the test
        gidn.side_effect = lambda x: 'foo' if x == 'ens4' else 'bar'

        match = {'name': 'ens?', 'driver': 'f*'}
        iface = utils.find_matching_iface(DEVICES, match)
        self.assertEqual(iface, 'ens4')
