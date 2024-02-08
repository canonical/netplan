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
import os
import sys
from time import sleep

from .. import utils
from ..sriov import PCIDevice, bind_vfs, _get_pci_slot_name
import netplan


FALLBACK_WAIT_TIME_SEC = 3
INTERVAL_SEC = 0.2
MAX_WAITING_TIME_SEC = 5


class MLX5VFLAGStateNotFound(Exception):
    pass


class MLX5VFLAGStateCannotBeRead(Exception):
    pass


class MLX5VFLAGStateDisabled(Exception):
    pass


class NetplanSriovRebind(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='rebind',
                         description='Rebind SR-IOV virtual functions of given physical functions to their driver',
                         leaf=True)

    def run(self):
        self.parser.add_argument('--root-dir', default='/',
                                 help='Search for configuration files in this root directory instead of /')
        self.parser.add_argument('netdevs', type=str, nargs='*', default=[],
                                 help='Space separated list of PF interface names')
        self.func = self.command_rebind

        self.logger = logging.getLogger('sriov_rebind')
        self.logger.propagate = False
        log_handler = logging.StreamHandler(stream=sys.stdout)

        self.parse_args()

        # netplan rebind --debug setup
        if self.debug:
            self.logger.setLevel(logging.DEBUG)
            log_handler.setLevel(logging.DEBUG)
            log_handler.setFormatter(logging.Formatter('%(levelname)s:%(message)s'))
        else:
            self.logger.setLevel(logging.INFO)
            log_handler.setLevel(logging.INFO)
            log_handler.setFormatter(logging.Formatter('%(message)s'))

        self.logger.addHandler(log_handler)

        self.run_command()

    def command_rebind(self):
        """Bind virtual functions of SR-IOV devices to their corresponding driver after eswitch mode was changed"""
        for iface in self.netdevs:
            pci_addr = _get_pci_slot_name(iface)
            pcidev = PCIDevice(pci_addr)
            if not pcidev.is_pf:
                self.logger.debug('{} does not seem to be a SR-IOV physical function'.format(iface))
                continue

            # There are some hardware-specific configuration that must happen *before* the bind
            # of VFs to their drivers. Some settings take time to be effective and, when possible,
            # we need to wait until the driver reports it's ready.
            self._perform_hardware_specific_quirks(iface, pcidev)

            bound_vfs = bind_vfs(pcidev.vfs, pcidev.driver)
            self.logger.debug('{}: bound {} VFs'.format(pcidev, len(bound_vfs)))

    def _perform_hardware_specific_quirks(self, iface: str, pf: PCIDevice):
        """
        Perform any hardware-specific quirks for the given SR-IOV device to make
        sure it's ready before the bind.
        """

        if pf.driver in ['mlx5_core']:
            # Mellanox specific quirks

            parser = netplan.Parser()
            parser.load_yaml_hierarchy(self.root_dir)
            np_state = netplan.State()
            np_state.import_parser_results(parser)

            for netdef in np_state.ethernets.values():
                if (netdef._has_match and netdef.set_name == iface) or netdef.id == iface:
                    if bond_link := netdef.links.get('bond'):
                        # VF LAG support. See LP: #1988018
                        # If the PF is a member of a bond, the user might be trying to enable the
                        # VF LAG feature.
                        # Mellanox VF LAG requires that the LAG state reports as 'active'
                        # *before* VFs can be bound to the driver. Performing the bind operation
                        # before the device is ready will cause the VF LAG feature to never be enabled.

                        # Another condition for the VF LAG activation is that the LAG mode
                        # must be one of 'active-backup', 'balanced-xor' or '802.3ad'.
                        bond_mode = bond_link._bond_mode
                        if not self._is_bond_mode_supported(bond_mode):
                            self.logger.debug(f'{iface} - LAG mode {bond_mode} is not supported by VF LAG')
                            continue

                        self.logger.debug(f'{iface} - waiting for the LAG state to be \'active\'')
                        try:
                            self._wait_for_mlx5_pf_lag_state_active(pf)
                        except MLX5VFLAGStateCannotBeRead:
                            self.logger.debug(f'{iface} - VF LAG state cannot be read')
                        except MLX5VFLAGStateNotFound:
                            self.logger.debug(f'{iface} - VF LAG state debugfs file not found')
                        except MLX5VFLAGStateDisabled:
                            self.logger.debug(f'{iface} - VF LAG state is still \'disabled\' after waiting')
                        else:
                            self.logger.debug(f'{iface} - VF LAG state is \'active\'')

    def _wait_for_mlx5_pf_lag_state_active(self, pf: PCIDevice):
        """
        The mlx5 driver added support for debugfs in https://github.com/torvalds/linux/commit/7f46a0b7327a
        It's available since kernel 5.19 https://cdn.kernel.org/pub/linux/kernel/v5.x/ChangeLog-5.19
        """
        retries = int(MAX_WAITING_TIME_SEC / INTERVAL_SEC)
        pci_addr = pf.pci_addr
        path = f'/sys/kernel/debug/mlx5/{pci_addr}/lag/state'

        if not os.path.exists(path):
            # If the debugfs file doesn't exist, it might be because this version of the mlx5 driver
            # still doesn't support it or because the debugfs is not mounted.
            # In this case, we probably should still wait for a few seconds to give time for the
            # driver to change state.
            # Based on tests with a ConnectX-5 NIC, 1 second is enough time, so let's wait a bit more
            # just in case. This delay will only be introduced if the PF is part of a bond.
            sleep(FALLBACK_WAIT_TIME_SEC)
            raise MLX5VFLAGStateNotFound

        while retries > 0:
            try:
                if self._get_mlx5_vf_lag_state(pci_addr) != 'active':
                    self.logger.debug(f'{pci_addr} VF LAG state is not active yet, retrying...')
                    # Based on tests with a ConnectX-5 NIC, a single 1-second cycle was enough time to
                    # allow the interfaces to change state.
                    sleep(INTERVAL_SEC)
                else:
                    return

            except Exception:
                raise MLX5VFLAGStateCannotBeRead

            retries = retries - 1

        raise MLX5VFLAGStateDisabled

    def _is_bond_mode_supported(self, mode: str) -> bool:
        '''
        Return True or False if the bond mode is one of the supported modes
        for the VG LAG activation.
        '''
        return mode in ['active-backup', 'balanced-xor', '802.3ad']

    def _get_mlx5_vf_lag_state(self, pci_addr: str) -> str:
        path = f'/sys/kernel/debug/mlx5/{pci_addr}/lag/state'

        with open(path, 'r') as f:
            return f.read().strip()
