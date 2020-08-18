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
# Defaults for non-optional settings, as defined here:
# http://www.openvswitch.org//ovs-vswitchd.conf.db.5.pdf
DEFAULTS = {
    # Mandatory columns:
    'mcast_snooping_enable': 'false',
    'rstp_enable': 'false',
}
GLOBALS = {
    # Global commands:
    'set-fail-mode': 'del-fail-mode',
    'set-ssl': 'del-ssl',
}


def del_col(type, iface, column, value):  # pragma: nocover (covered in autopkgtest)
    """Cleanup values from a column (i.e. "column=value")"""
    default = DEFAULTS.get(column)
    if default is None:
        # removes the exact value only if it was set by netplan
        subprocess.check_call([OPENVSWITCH_OVS_VSCTL, 'remove', type, iface, column, value])
    elif default and default != value:
        # reset to default, if its not the default already
        subprocess.check_call([OPENVSWITCH_OVS_VSCTL, 'set', type, iface, '%s=%s' % (column, default)])


def del_dict(type, iface, column, key, value):  # pragma: nocover (covered in autopkgtest)
    """Cleanup values from a dictionary (i.e. "column:key=value")"""
    # removes the exact value only if it was set by netplan
    subprocess.check_call([OPENVSWITCH_OVS_VSCTL, 'remove', type, iface, column, key, value])


def del_global(type, iface, key, value):  # pragma: nocover (covered in autopkgtest)
    """Cleanup commands from the global namespace"""
    cmd = GLOBALS.get(key)
    # TODO: do noting if values are the same
    if cmd == 'del-ssl':
        subprocess.check_call([OPENVSWITCH_OVS_VSCTL, cmd])
    elif cmd == 'del-fail-mode':
        subprocess.check_call([OPENVSWITCH_OVS_VSCTL, cmd, iface])
    else:
        raise Exception('Reset command unkown for:', key)


def clear_setting(type, iface, setting, value):  # pragma: nocover (covered in autopkgtest)
    """Check if this setting is in a dict or a colum and delete accordingly"""
    split = setting.split('/', 2)
    col = split[1]
    if col == 'global' and len(split) > 2:
        del_global(type, iface, split[2], value)
    elif len(split) > 2:
        del_dict(type, iface, split[1], split[2], value)
    else:
        del_col(type, iface, split[1], value)
    # Cleanup the tag itself (i.e. "netplan/column[/key]")
    subprocess.check_call([OPENVSWITCH_OVS_VSCTL, 'remove', type, iface, 'external-ids', setting])


def is_ovs_interface(iface, interfaces):  # pragma: nocover (covered in autopkgtest)
    if interfaces[iface].get('openvswitch') is not None:
        return True
    else:
        contains_ovs_interfaces = False
        sub_interfaces = interfaces[iface].get('interfaces', [])
        for i in sub_interfaces:
            contains_ovs_interfaces |= is_ovs_interface(i, interfaces)
        return contains_ovs_interfaces


def apply_ovs_cleanup(config_manager, ovs_old, ovs_current):  # pragma: nocover (covered in autopkgtest)
    """
    Query OpenVSwitch state through 'ovs-vsctl' and filter for netplan=true
    tagged ports/bonds and bridges. Delete interfaces which are not defined
    in the current configuration.
    Also filter for individual settings tagged netplan/<column>[/<key]=value
    in external-ids and clear them if they have been set by netplan.
    """
    config_manager.parse()
    ovs_ifaces = set()
    for i in config_manager.interfaces.keys():
        if (is_ovs_interface(i, config_manager.interfaces)):
            ovs_ifaces.add(i)

    # Tear down old OVS interfaces, not defined in the current config.
    # Use 'del-br' on the Interface table, to delete any netplan created VLAN fake bridges.
    # Use 'del-bond-iface' on the Interface table, to delete netplan created patch port interfaces
    if os.path.isfile(OPENVSWITCH_OVS_VSCTL):
        # Step 1: Delete all interfaces, which are not part of the current OVS config
        for t in (('Port', 'del-port'), ('Bridge', 'del-br'), ('Interface', 'del-br')):
            out = subprocess.check_output([OPENVSWITCH_OVS_VSCTL, '--columns=name,external-ids',
                                           '-f', 'csv', '-d', 'bare', '--no-headings', 'list', t[0]],
                                          universal_newlines=True)
            for line in out.splitlines():
                if 'netplan=true' in line:
                    iface = line.split(',')[0]
                    # Skip cleanup if this OVS interface is part of the current netplan OVS config
                    if iface in ovs_ifaces:
                        continue
                    if t[0] == 'Interface' and subprocess.run([OPENVSWITCH_OVS_VSCTL, 'iface-to-br', iface]).returncode > 0:
                        subprocess.check_call([OPENVSWITCH_OVS_VSCTL, '--if-exists', 'del-bond-iface', iface])
                    else:
                        subprocess.check_call([OPENVSWITCH_OVS_VSCTL, '--if-exists', t[1], iface])

        # Step 2: Clean up the settings of the remaining interfaces
        for t in ('Port', 'Bridge', 'Interface', 'open_vswitch'):  # TODO: , 'Controller'):
            cols = 'external-ids' if t == 'open_vswitch' else 'name,external-ids'
            out = subprocess.check_output([OPENVSWITCH_OVS_VSCTL, '--columns=%s' % cols,
                                           '-f', 'csv', '-d', 'bare', '--no-headings', 'list', t],
                                          universal_newlines=True)
            for line in out.splitlines():
                if 'netplan/' in line:
                    iface = '.'
                    extids = line
                    if t != 'open_vswitch':
                        iface, extids = line.split(',', 1)

                    # TODO: Make sure our values do not contain (white-)spaces!
                    for entry in extids.strip('"').split(' '):
                        if entry.startswith('netplan/') and '=' in entry:
                            setting, val = entry.split('=', 1)
                            clear_setting(t, iface, setting, val)

    # Show the warning only if we are or have been working with OVS definitions
    elif ovs_old or ovs_current:
        logging.warning('ovs-vsctl is missing, cannot tear down old OpenVSwitch interfaces')
