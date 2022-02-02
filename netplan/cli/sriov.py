#!/usr/bin/python3
#
# Copyright (C) 2020-2022 Canonical, Ltd.
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
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

import logging
import os
import subprocess
import typing

from collections import defaultdict

import netplan.cli.utils as utils
import netplan.libnetplan as libnetplan
from netplan.configmanager import ConfigurationError

import netifaces


# PCIDevice class originates from mlnx_switchdev_mode/sriovify.py
# Copyright 2019 Canonical Ltd, Apache License, Version 2.0
# https://github.com/openstack-charmers/mlnx-switchdev-mode
class PCIDevice(object):
    """Helper class for interaction with a PCI device"""

    def __init__(self, pci_addr: str):
        """Initialise a new PCI device handler
        :param pci_addr: PCI address of device
        :type: str
        """
        self.pci_addr = pci_addr

    @property
    def sys(self) -> str:
        """sysfs path (can be overridden for testing)
        :return: full path to /sys filesystem
        :rtype: str
        """
        return "/sys"

    @property
    def path(self) -> str:
        """/sys path for PCI device
        :return: full path to PCI device in /sys filesystem
        :rtype: str
        """
        return os.path.join(self.sys, "bus/pci/devices", self.pci_addr)

    def subpath(self, subpath: str) -> str:
        """/sys subpath helper for PCI device
        :param subpath: subpath to construct path for
        :type: str
        :return: self.path + subpath
        :rtype: str
        """
        return os.path.join(self.path, subpath)

    @property
    def driver(self) -> str:
        """Kernel driver for PCI device
        :return: kernel driver in use for device
        :rtype: str
        """
        driver = ''
        if os.path.exists(self.subpath("driver")):
            driver = os.path.basename(os.readlink(self.subpath("driver")))
        return driver

    @property
    def bound(self) -> bool:
        """Determine if device is bound to a kernel driver
        :return: whether device is bound to a kernel driver
        :rtype: bool
        """
        return os.path.exists(self.subpath("driver"))

    @property
    def is_pf(self) -> bool:
        """Determine if device is a SR-IOV Physical Function
        :return: whether device is a PF
        :rtype: bool
        """
        return os.path.exists(self.subpath("sriov_numvfs"))

    @property
    def is_vf(self) -> bool:
        """Determine if device is a SR-IOV Virtual Function
        :return: whether device is a VF
        :rtype: bool
        """
        return os.path.exists(self.subpath("physfn"))

    @property
    def vf_addrs(self) -> list:
        """List Virtual Function addresses associated with a Physical Function
        :return: List of PCI addresses of Virtual Functions
        :rtype: list[str]
        """
        vf_addrs = []
        i = 0
        while True:
            try:
                vf_addrs.append(
                    os.path.basename(
                        os.readlink(self.subpath("virtfn{}".format(i)))
                    )
                )
            except FileNotFoundError:
                break
            i += 1
        return vf_addrs

    @property
    def vfs(self) -> list:
        """List Virtual Function associated with a Physical Function
        :return: List of PCI devices of Virtual Functions
        :rtype: list[PCIDevice]
        """
        return [PCIDevice(addr) for addr in self.vf_addrs]

    def devlink_set(self, obj_name: str, prop: str, value: str):
        """Set devlink options for the PCI device
        :param obj_name: devlink object to set options on
        :type: str
        :param prop: property to set
        :type: str
        :param value: value to set for property
        :type: str
        """
        subprocess.check_call(
            [
                "/sbin/devlink",
                "dev",
                obj_name,
                "set",
                "pci/{}".format(self.pci_addr),
                prop,
                value,
            ]
        )

    def __str__(self) -> str:
        """String represenation of object
        :return: PCI address of string
        :rtype: str
        """
        return self.pci_addr


def bind_vfs(vfs: typing.Iterable[PCIDevice], driver):
    """Bind unbound VFs to driver."""
    bound_vfs = []
    for vf in vfs:
        if not vf.bound:
            with open("/sys/bus/pci/drivers/{}/bind".format(driver), "wt") as f:
                f.write(vf.pci_addr)
                bound_vfs.append(vf)
    return bound_vfs


def unbind_vfs(vfs: typing.Iterable[PCIDevice], driver) -> typing.Iterable[PCIDevice]:
    """Unbind bound VFs from driver."""
    unbound_vfs = []
    for vf in vfs:
        if vf.bound:
            with open("/sys/bus/pci/drivers/{}/unbind".format(driver), "wt") as f:
                f.write(vf.pci_addr)
                unbound_vfs.append(vf)
    return unbound_vfs


def _get_target_interface(interfaces, config_manager, pf_link, pfs):
    if pf_link not in pfs:
        # handle the match: syntax, get the actual device name
        pf_dev = config_manager.ethernets[pf_link]
        pf_match = pf_dev.get('match')
        if pf_match:
            # now here it's a bit tricky
            set_name = pf_dev.get('set-name')
            if set_name and set_name in interfaces:
                # if we had a match: stanza and set-name: this means we should
                # assume that, if found, the interface has already been
                # renamed - use the new name
                pfs[pf_link] = set_name
            else:
                # no set-name (or interfaces not yet renamed) so we need to do
                # the matching ourselves
                by_name = pf_match.get('name')
                by_mac = pf_match.get('macaddress')
                by_driver = pf_match.get('driver')

                for interface in interfaces:
                    if ((by_name and not utils.is_interface_matching_name(interface, by_name)) or
                            (by_mac and not utils.is_interface_matching_macaddress(interface, by_mac)) or
                            (by_driver and not utils.is_interface_matching_driver_name(interface, by_driver))):
                        continue
                    # we have a matching PF
                    # store the matching interface in the dictionary of
                    # active PFs, but error out if we matched more than one
                    if pf_link in pfs:
                        raise ConfigurationError('matched more than one interface for a PF device: %s' % pf_link)
                    pfs[pf_link] = interface
        else:
            # no match field, assume entry name is the interface name
            if pf_link in interfaces:
                pfs[pf_link] = pf_link

    return pfs.get(pf_link, None)


def _get_pci_slot_name(netdev):
    """
    Read PCI slot name for given interface name
    """
    uevent_path = os.path.join('/sys/class/net', netdev, 'device/uevent')
    try:
        with open(uevent_path) as f:
            pci_slot_name = None
            for line in f.readlines():
                line = line.strip()
                if line.startswith('PCI_SLOT_NAME='):
                    pci_slot_name = line.split('=', 2)[1]
                    return pci_slot_name
    except IOError as e:
        raise RuntimeError('failed parsing PCI slot name for %s: %s' % (netdev, str(e)))


def get_vf_count_and_functions(interfaces, config_manager,
                               vf_counts, vfs, pfs):
    """
    Go through the list of netplan ethernet devices and identify which are
    PFs and VFs, matching the former with actual networking interfaces.
    Count how many VFs each PF will need.
    """
    explicit_counts = {}
    for ethernet, settings in config_manager.ethernets.items():
        if not settings:
            continue
        if ethernet == 'renderer':
            continue

        # we now also support explicitly stating how many VFs should be
        # allocated for a PF
        explicit_num = settings.get('virtual-function-count')
        if explicit_num:
            pf = _get_target_interface(interfaces, config_manager, ethernet, pfs)
            if pf:
                explicit_counts[pf] = explicit_num
            continue

        pf_link = settings.get('link')
        if pf_link and pf_link in config_manager.ethernets:
            _get_target_interface(interfaces, config_manager, pf_link, pfs)

            if pf_link in pfs:
                vf_counts[pfs[pf_link]] += 1
            else:
                logging.warning('could not match physical interface for the defined PF: %s' % pf_link)
                # continue looking for other VFs
                continue

            # we can't yet perform matching on VFs as those are only
            # created later - but store, for convenience, all the valid
            # VFs that we encounter so far
            vfs[ethernet] = None

    # sanity check: since we can explicitly state the VF count, make sure
    # that this number isn't smaller than the actual number of VFs declared
    # the explicit number also overrides the number of actual VFs
    for pf, count in explicit_counts.items():
        if pf in vf_counts and vf_counts[pf] > count:
            raise ConfigurationError(
                'more VFs allocated than the explicit size declared: %s > %s' % (vf_counts[pf], count))
        vf_counts[pf] = count


def set_numvfs_for_pf(pf, vf_count):
    """
    Allocate the required number of VFs for the selected PF.
    """
    if vf_count > 256:
        raise ConfigurationError(
            'cannot allocate more VFs for PF %s than the SR-IOV maximum: %s > 256' % (pf, vf_count))

    devdir = os.path.join('/sys/class/net', pf, 'device')
    numvfs_path = os.path.join(devdir, 'sriov_numvfs')
    totalvfs_path = os.path.join(devdir, 'sriov_totalvfs')
    try:
        with open(totalvfs_path) as f:
            vf_max = int(f.read().strip())
    except IOError as e:
        raise RuntimeError('failed parsing sriov_totalvfs for %s: %s' % (pf, str(e)))
    except ValueError:
        raise RuntimeError('invalid sriov_totalvfs value for %s' % pf)

    if vf_count > vf_max:
        raise ConfigurationError(
            'cannot allocate more VFs for PF %s than supported: %s > %s (sriov_totalvfs)' % (pf, vf_count, vf_max))

    try:
        with open(numvfs_path, 'w') as f:
            f.write(str(vf_count))
    except IOError as e:
        bail = True
        if e.errno == 16:  # device or resource busy
            logging.warning('device or resource busy while setting sriov_numvfs for %s, trying workaround' % pf)
            try:
                # doing this in two open/close sequences so that
                # it's as close to writing via shell as possible
                with open(numvfs_path, 'w') as f:
                    f.write('0')
                with open(numvfs_path, 'w') as f:
                    f.write(str(vf_count))
            except IOError as e_inner:
                e = e_inner
            else:
                bail = False
        if bail:
            raise RuntimeError('failed setting sriov_numvfs to %s for %s: %s' % (vf_count, pf, str(e)))

    return True


def perform_hardware_specific_quirks(pf):
    """
    Perform any hardware-specific quirks for the given SR-IOV device to make
    sure all the VF-count changes are applied.
    """
    devdir = os.path.join('/sys/class/net', pf, 'device')
    try:
        with open(os.path.join(devdir, 'vendor')) as f:
            device_id = f.read().strip()[2:]
        with open(os.path.join(devdir, 'device')) as f:
            vendor_id = f.read().strip()[2:]
    except IOError as e:
        raise RuntimeError('could not determine vendor and device ID of %s: %s' % (pf, str(e)))

    combined_id = ':'.join([vendor_id, device_id])
    quirk_devices = ()  # TODO: add entries to the list
    if combined_id in quirk_devices:
        # some devices need special handling, so this is the place

        # Currently this part is empty, but has been added as a preemptive
        # measure, as apparently a lot of SR-IOV cards have issues with
        # dynamically allocating VFs. Some cards seem to require a full
        # kernel module reload cycle after changing the sriov_numvfs value
        # for the changes to come into effect.
        # Any identified card/vendor can then be special-cased here, if
        # needed.
        pass


def apply_vlan_filter_for_vf(pf, vf, vlan_name, vlan_id, prefix='/'):
    """
    Apply the hardware VLAN filtering for the selected VF.
    """

    # this is more complicated, because to do this, we actually need to have
    # the vf index - just knowing the vf interface name is not enough
    vf_index = None
    # the prefix argument is here only for unit testing purposes
    vf_devdir = os.path.join(prefix, 'sys/class/net', vf, 'device')
    vf_dev_id = os.path.basename(os.readlink(vf_devdir))
    pf_devdir = os.path.join(prefix, 'sys/class/net', pf, 'device')
    for f in os.listdir(pf_devdir):
        if 'virtfn' in f:
            dev_path = os.path.join(pf_devdir, f)
            dev_id = os.path.basename(os.readlink(dev_path))
            if dev_id == vf_dev_id:
                vf_index = f[6:]
                break

    if not vf_index:
        raise RuntimeError(
            'could not determine the VF index for %s while configuring vlan %s' % (vf, vlan_name))

    # now, create the VLAN filter
    # TODO: would be best if we did this directl via python, without calling
    #  the iproute tooling
    try:
        subprocess.check_call(['ip', 'link', 'set',
                               'dev', pf,
                               'vf', vf_index,
                               'vlan', str(vlan_id)],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise RuntimeError(
            'failed setting SR-IOV VLAN filter for vlan %s (ip link set command failed)' % vlan_name)


def apply_sriov_config(config_manager, rootdir='/'):
    """
    Go through all interfaces, identify which ones are SR-IOV VFs, create
    them and perform all other necessary setup.
    """
    parser = libnetplan.Parser()
    parser.load_yaml_hierarchy(rootdir)

    np_state = libnetplan.State()
    np_state.import_parser_results(parser)

    config_manager.parse()
    interfaces = netifaces.interfaces()

    # for sr-iov devices, we identify VFs by them having a link: field
    # pointing to an PF. So let's browse through all ethernet devices,
    # find all that are VFs and count how many of those are linked to
    # particular PFs, as we need to then set the numvfs for each.
    vf_counts = defaultdict(int)
    # we also store all matches between VF/PF netplan entry names and
    # interface that they're currently matching to
    vfs = {}
    pfs = {}

    get_vf_count_and_functions(
        interfaces, config_manager, vf_counts, vfs, pfs)

    # setup the required number of VFs per PF
    # at the same time store which PFs got changed in case the NICs
    # require some special quirks for the VF number to change
    vf_count_changed = []
    if vf_counts:
        for pf, vf_count in vf_counts.items():
            if not set_numvfs_for_pf(pf, vf_count):
                continue

            vf_count_changed.append(pf)

    if vf_count_changed:
        # some cards need special treatment when we want to change the
        # number of enabled VFs
        for pf in vf_count_changed:
            perform_hardware_specific_quirks(pf)

        # also, since the VF number changed, the interfaces list also
        # changed, so we need to refresh it
        interfaces = netifaces.interfaces()

    # now in theory we should have all the new VFs set up and existing;
    # this is needed because we will have to now match the defined VF
    # entries to existing interfaces, otherwise we won't be able to set
    # filtered VLANs for those.
    # XXX: does matching those even make sense?
    for vf in vfs:
        settings = config_manager.ethernets.get(vf)
        match = settings.get('match')
        if match:
            # right now we only match by name, as I don't think matching per
            # driver and/or macaddress makes sense
            by_name = match.get('name')
            # by_mac = match.get('macaddress')
            # by_driver = match.get('driver')
            # TODO: print warning if other matches are provided

            for interface in interfaces:
                if by_name and not utils.is_interface_matching_name(interface, by_name):
                    continue
                if vf in vfs and vfs[vf]:
                    raise ConfigurationError('matched more than one interface for a VF device: %s' % vf)
                vfs[vf] = interface
        else:
            if vf in interfaces:
                vfs[vf] = vf

    # Walk the SR-IOV PFs and check if we need to change the eswitch mode
    for netdef_id, iface in pfs.items():
        netdef = np_state[netdef_id]
        eswitch_mode = netdef.embedded_switch_mode
        if eswitch_mode in ['switchdev', 'legacy']:
            pci_addr = _get_pci_slot_name(iface)
            pcidev = PCIDevice(pci_addr)
            if pcidev.is_pf:
                logging.debug("Found VFs of {}: {}".format(pcidev, pcidev.vf_addrs))
                if pcidev.vfs:
                    rebind_delayed = netdef.delay_virtual_functions_rebind
                    try:
                        unbind_vfs(pcidev.vfs, pcidev.driver)
                        pcidev.devlink_set('eswitch', 'mode', eswitch_mode)
                    finally:
                        if not rebind_delayed:
                            bind_vfs(pcidev.vfs, pcidev.driver)

    filtered_vlans_set = set()
    for vlan, settings in config_manager.vlans.items():
        # there is a special sriov vlan renderer that one can use to mark
        # a selected vlan to be done in hardware (VLAN filtering)
        if settings.get('renderer') == 'sriov':
            # this only works for SR-IOV VF interfaces
            link = settings.get('link')
            vlan_id = settings.get('id')
            vf = vfs.get(link)
            if not vf:
                # it is possible this is not an error, for instance when
                # the configuration has been defined 'for the future'
                # XXX: but maybe we should error out here as well?
                logging.warning(
                    'SR-IOV vlan defined for %s but link %s is either not a VF or has no matches' % (vlan, link))
                continue

            # get the parent pf interface
            # first we fetch the related vf netplan entry
            vf_parent_entry = config_manager.ethernets.get(link).get('link')
            # and finally, get the matched pf interface
            pf = pfs.get(vf_parent_entry)

            if vf in filtered_vlans_set:
                raise ConfigurationError(
                    'interface %s for netplan device %s (%s) already has an SR-IOV vlan defined' % (vf, link, vlan))

            # TODO: make sure that we don't apply the filter twice
            apply_vlan_filter_for_vf(pf, vf, vlan, vlan_id)
            filtered_vlans_set.add(vf)
