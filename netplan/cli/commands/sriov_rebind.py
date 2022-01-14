#!/usr/bin/python3
#
# Copyright (C) 2022 Canonical, Ltd.
# Author: Lukas Märdian <slyon@ubuntu.com>
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

'''netplan SR-IOV rebind command line'''

import logging

import netplan.cli.utils as utils
from netplan.cli.sriov import PCIDevice, bind_vfs, _get_pci_slot_name


class NetplanSriovRebind(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='rebind',
                         description='Rebind SR-IOV virtual functions of given physical functions to their driver',
                         leaf=True)

    def run(self):
        self.parser.add_argument('netdevs', type=str, nargs='*', default=[],
                                 help='Space separated list of PF interface names')
        self.func = self.command_rebind

        self.parse_args()
        self.run_command()

    def command_rebind(self):
        """Bind virtual functions of SR-IOV devices to their corresponding driver after eswitch mode was changed"""
        for iface in self.netdevs:
            pci_addr = _get_pci_slot_name(iface)
            pcidev = PCIDevice(pci_addr)
            if not pcidev.is_pf:
                logging.warning('{} does not seem to be a SR-IOV physical function'.format(iface))
                continue
            bound_vfs = bind_vfs(pcidev.vfs, pcidev.driver)
            logging.info('{}: bound {} VFs'.format(pcidev, len(bound_vfs)))
