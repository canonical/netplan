#!/usr/bin/python3
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Łukas 'slyon' Märdian <lukas.maerdian@canonical.com>
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

import logging
import os
import subprocess

OPENVSWITCH_OVS_VSCTL = '/usr/bin/ovs-vsctl'


def apply_ovs_cleanup(config_manager, ovs_old, ovs_current):  # pragma: nocover (covered in autopkgtest)
    """
    Query OpenVSwitch state through 'ovs-vsctl' and filter for netplan=true
    tagged ports/bonds and bridges. Delete interfaces which are not defined
    in the current configuration.
    """
    config_manager.parse()

    # Tear down old OVS interfacess, not defined in the current config
    # Use 'del-br' on the Interface table, to delete any netplan created VLAN fake bridges
    if os.path.isfile(OPENVSWITCH_OVS_VSCTL):
        for t in (('Port', 'del-port'), ('Bridge', 'del-br'), ('Interface', 'del-br')):
            out = subprocess.check_output([OPENVSWITCH_OVS_VSCTL, '--columns=name,external-ids',
                                           '-f', 'csv', '-d', 'bare', '--no-headings', 'list', t[0]],
                                          universal_newlines=True)
            for line in out.splitlines():
                if 'netplan=true' in line:
                    iface = line.split(',')[0]
                    # Skip cleanup if this OVS interface is part of the current netplan OVS config
                    if config_manager.interfaces.get(iface, {}).get('openvswitch') is not None:
                        continue
                    subprocess.check_call([OPENVSWITCH_OVS_VSCTL, '--if-exists', t[1], iface])
    # Show the warning only if we are or have been working with OVS definitions
    elif ovs_old or ovs_current:
        logging.warning('ovs-vsctl is missing, cannot tear down old OpenVSwitch interfaces')
