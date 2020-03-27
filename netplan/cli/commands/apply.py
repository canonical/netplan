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

'''netplan apply command line'''

import logging
import os
import sys
import glob
import fnmatch
import subprocess
import shutil

from collections import defaultdict

import netplan.cli.utils as utils
from netplan.configmanager import ConfigManager, ConfigurationError

import netifaces


class NetplanApply(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='apply',
                         description='Apply current netplan config to running system',
                         leaf=True)

    def run(self):  # pragma: nocover (covered in autopkgtest)
        self.func = NetplanApply.command_apply

        self.parse_args()
        self.run_command()

    @staticmethod
    def command_apply(run_generate=True, sync=False, exit_on_error=True):  # pragma: nocover (covered in autopkgtest)
        # if we are inside a snap, then call dbus to run netplan apply instead
        if "SNAP" in os.environ:
            # TODO: maybe check if we are inside a classic snap and don't do
            # this if we are in a classic snap?
            busctl = shutil.which("busctl")
            if busctl is None:
                raise RuntimeError("missing busctl utility")
            res = subprocess.call([busctl, "call", "--quiet", "--system",
                                   "io.netplan.Netplan",  # the service
                                   "/io/netplan/Netplan",  # the object
                                   "io.netplan.Netplan",  # the interface
                                   "Apply",  # the method
                                   ])

            if res != 0:
                if exit_on_error:
                    sys.exit(res)
                elif res == 130:
                    raise PermissionError(
                        "failed to communicate with dbus service")
                elif res == 1:
                    raise RuntimeError(
                        "failed to communicate with dbus service")
            else:
                return

        old_files_networkd = bool(glob.glob('/run/systemd/network/*netplan-*'))
        old_files_nm = bool(glob.glob('/run/NetworkManager/system-connections/netplan-*'))

        if run_generate and subprocess.call([utils.get_generator_path()]) != 0:
            if exit_on_error:
                sys.exit(os.EX_CONFIG)
            else:
                raise ConfigurationError("the configuration could not be generated")

        config_manager = ConfigManager()
        devices = netifaces.interfaces()

        # Re-start service when
        # 1. We have configuration files for it
        # 2. Previously we had config files for it but not anymore
        # Ideally we should compare the content of the *netplan-* files before and
        # after generation to minimize the number of re-starts, but the conditions
        # above works too.
        restart_networkd = bool(glob.glob('/run/systemd/network/*netplan-*'))
        if not restart_networkd and old_files_networkd:
            restart_networkd = True
        restart_nm = bool(glob.glob('/run/NetworkManager/system-connections/netplan-*'))
        if not restart_nm and old_files_nm:
            restart_nm = True

        # stop backends
        if restart_networkd:
            logging.debug('netplan generated networkd configuration changed, restarting networkd')
            utils.systemctl_networkd('stop', sync=sync, extra_services=['netplan-wpa@*.service'])
        else:
            logging.debug('no netplan generated networkd configuration exists')

        if restart_nm:
            logging.debug('netplan generated NM configuration changed, restarting NM')
            if utils.nm_running():
                # restarting NM does not cause new config to be applied, need to shut down devices first
                for device in devices:
                    # ignore failures here -- some/many devices might not be managed by NM
                    try:
                        utils.nmcli(['device', 'disconnect', device])
                    except subprocess.CalledProcessError:
                        pass

                utils.systemctl_network_manager('stop', sync=sync)
        else:
            logging.debug('no netplan generated NM configuration exists')

        # Refresh devices now; restarting a backend might have made something appear.
        devices = netifaces.interfaces()

        # evaluate config for extra steps we need to take (like renaming)
        # for now, only applies to non-virtual (real) devices.
        config_manager.parse()
        changes = NetplanApply.process_link_changes(devices, config_manager)

        # apply any SR-IOV related changes, if applicable
        try:
            NetplanApply.apply_sriov_changes(devices, config_manager)
        except ConfigurationError as e:
            logging.error(str(e))
            if exit_on_error:
                sys.exit(1)

        # if the interface is up, we can still apply some .link file changes
        devices = netifaces.interfaces()
        for device in devices:
            logging.debug('netplan triggering .link rules for %s', device)
            try:
                subprocess.check_call(['udevadm', 'test-builtin',
                                       'net_setup_link',
                                       '/sys/class/net/' + device],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                logging.debug('Ignoring device without syspath: %s', device)

        # apply renames to "down" devices
        for iface, settings in changes.items():
            if settings.get('name'):
                subprocess.check_call(['ip', 'link', 'set',
                                       'dev', iface,
                                       'name', settings.get('name')],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)

        subprocess.check_call(['udevadm', 'settle'])

        # (re)start backends
        if restart_networkd:
            netplan_wpa = [os.path.basename(f) for f in glob.glob('/run/systemd/system/*.wants/netplan-wpa@*.service')]
            utils.systemctl_networkd('start', sync=sync, extra_services=netplan_wpa)
        if restart_nm:
            utils.systemctl_network_manager('start', sync=sync)

    @staticmethod
    def is_composite_member(composites, phy):  # pragma: nocover (covered in autopkgtest)
        """
        Is this physical interface a member of a 'composite' virtual
        interface? (bond, bridge)
        """
        for composite in composites:
            for id, settings in composite.items():
                members = settings.get('interfaces', [])
                for iface in members:
                    if iface == phy:
                        return True

        return False

    @staticmethod
    def get_interface_driver_name(interface, only_down=False):
        devdir = os.path.join('/sys/class/net', interface)
        if only_down:
            try:
                with open(os.path.join(devdir, 'operstate')) as f:
                    state = f.read().strip()
                    if state != 'down':
                        logging.debug('device %s operstate is %s, not changing', interface, state)
                        continue
            except IOError as e:
                logging.error('Cannot determine operstate of %s: %s', interface, str(e))
                return None

        try:
            driver = os.path.realpath(os.path.join(devdir, 'device', 'driver'))
            driver_name = os.path.basename(driver)
        except IOError as e:
            logging.debug('Cannot replug %s: cannot read link %s/device: %s', interface, devdir, str(e))
            return None

        return driver_name

    @staticmethod
    def get_interface_macaddress(interface):
        link = netifaces.ifaddresses(interface)[netifaces.AF_LINK][0]

        return link.get('addr')

    @staticmethod
    def is_interface_matching_name(interface, match_driver):
        return fnmatch.fnmatchcase(interface, match_driver)

    @staticmethod
    def is_interface_matching_driver_name(interface, match_driver):
        driver_name = get_interface_driver_name(interface)

        return match_driver == driver_name

    @staticmethod
    def is_interface_matching_macaddress(interface, match_mac):
        macaddress = get_interface_macaddress(interface)

        return match_mac == macaddress

    @staticmethod
    def process_link_changes(interfaces, config_manager):  # pragma: nocover (covered in autopkgtest)
        """
        Go through the pending changes and pick what needs special
        handling. Only applies to "down" interfaces which can be safely
        updated.
        """

        changes = {}
        phys = dict(config_manager.physical_interfaces)
        composite_interfaces = [config_manager.bridges, config_manager.bonds]

        # TODO (cyphermox): factor out some of this matching code (and make it
        # pretty) in its own module.
        matches = {'by-driver': {},
                   'by-mac': {},
                   }
        for phy, settings in phys.items():
            if not settings:
                continue
            if phy == 'renderer':
                continue
            newname = settings.get('set-name')
            if not newname:
                continue
            match = settings.get('match')
            if not match:
                continue
            driver = match.get('driver')
            mac = match.get('macaddress')
            if driver:
                matches['by-driver'][driver] = newname
            if mac:
                matches['by-mac'][mac] = newname

        # /sys/class/net/ens3/device -> ../../../virtio0
        # /sys/class/net/ens3/device/driver -> ../../../../bus/virtio/drivers/virtio_net
        for interface in interfaces:
            if interface not in phys:
                # do not rename  virtual devices
                logging.debug('Skipping non-physical interface: %s', interface)
                continue
            if NetplanApply.is_composite_member(composite_interfaces, interface):
                logging.debug('Skipping composite member %s', interface)
                # do not rename members of virtual devices. MAC addresses
                # may be the same for all interface members.
                continue

            driver_name = get_interface_driver_name(interface, only_down=True)
            macaddress = get_interface_macaddress(interface)
            if driver_name in matches['by-driver']:
                new_name = matches['by-driver'][driver_name]
                logging.debug(new_name)
                logging.debug(interface)
                if new_name != interface:
                    changes.update({interface: {'name': new_name}})
            if macaddress in matches['by-mac']:
                new_name = matches['by-mac'][macaddress]
                if new_name != interface:
                    changes.update({interface: {'name': new_name}})

        logging.debug(changes)
        return changes

    @staticmethod
    def apply_sriov_changes(interfaces, config_manager):
        """
        Go through all interfaces, identify which ones are SR-IOV VFs, create
        then and perform all other necessary setup.
        """

        # for sr-iov devices, we identify VFs by them having a link: field
        # pointing to an PF. So let's browse through all ethernet devices,
        # find all that are VFs and count how many of those are linked to
        # particular PFs, as we need to then set the numvfs for each.
        vf_counts = defaultdict(int)
        # we also store all matches between VF/PF netplan entry names and
        # interface that they're currently matching to
        active_vfs = {}
        active_pfs = defaultdict(list)

        for phy, settings in config_manager.ethernets.items():
            if not settings:
                continue
            if phy == 'renderer':
                continue

            pf_link = settings.get('link')
            if pf_link and pf_link in config_manager.ethernets:
                # handle the match: syntax, get the actual device name
                pf_match = config_manager.ethernets[pf_link].get('match')

                if pf_match:
                    by_name = pf_match.get('name')
                    by_mac = pf_match.get('macaddress')
                    by_driver = pf_match.get('driver')

                    for interface in interfaces:
                        #if interface not in config_manager.ethernets:
                        #    continue
                        if ((by_name and not is_interface_matching_name(interface, by_name)) or
                             (by_mac and not is_interface_matching_macaddress(interface, by_mac)) or
                             (by_driver and not is_interface_matching_driver_name(interface, by_driver))):
                            continue
                        # we have a matching PF
                        # let's remember that we can have more than one match
                        vf_counts[interface] += 1
                        # store the matching interface in the dictionary of
                        # active PFs
                        active_pfs[pf_link].append(interface)
                    else:
                        logging.warning('could not match physical interface for the defined PF: %s' % pf_link)
                        # continue looking for other VFs
                        continue
                else:
                    # no match field, assume entry name is interface name
                    vf_counts[pf_link] += 1
                    active_pfs[pf_link].append(pf_link)

                # we can't yet perform matching on VFs as those are only
                # created later - but store, for convenience, all the valid
                # VFs that we encounter so far
                active_vfs[phy] = []

        # setup the required number of VFs per PF
        # at the same time store which PFs got changed in case the NICs
        # require some special quirks for the VF number to change
        vf_count_changed = []
        if vf_counts:
            for pf, vf_count in vf_counts.items():
                devdir = os.path.join('/sys/class/net', pf, 'device')
                numvfs_path = os.path.join(devdir, 'sriov_numvfs')
                totalvfs_path = os.path.join(devdir, 'sriov_totalvfs')
                try:
                    with open(numvfs_path) as f:
                        vf_current = int(f.read().strip())
                    with open(totalvfs_path) as f:
                        vf_max = int(f.read().strip())
                except IOError as e:
                    raise RuntimeError('failed parsing sriov_numvfs/sriov_totalvfs for %s: %s' % (pf, str(e)))
                except ValueError:
                    raise RuntimeError('invalid sriov_numvfs/sriov_totalvfs value for %s' % pf)

                if vf_count > vf_max:
                    raise ConfigurationError(
                        'cannot allocate more VFs for PF %s than supported: %s > %s (sriov_totalvfs)' % (pf, vf_count, vf_max))

                if vf_count <= vf_current:
                    # XXX: this might be a wrong assumption, but I assume that
                    #  the operation of adding/removing VFs is very invasive,
                    #  so it makes no sense to decrease the number of VFs if
                    #  less are needed - leaving the unused ones unconfigured?
                    logging.debug('the %s PF already defines more VFs than required (%s > %s), skipping' % (pf, vf_current, vf_count))
                    continue

                try:
                    with open(numvfs_path, 'w') as f:
                        f.write(vf_count)
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
                                f.write(vf_count)
                        except IOError as e_inner:
                            e = e_inner
                        else:
                            bail = False
                    if bail:
                        raise RuntimeError('failed setting sriov_numvfs to %s for %s: %s' % (vf_count, pf, str(e)))

                vf_count_changed.append(pf)

        if vf_count_changed:
            # some cards need special treatment when we want to change the
            # number of enabled VFs
            for pf in vf_count_changed:
                devdir = os.path.join('/sys/class/net', pf, 'device')
                try:
                    with open(os.path.join(devdir, 'vendor')) as f:
                        device_id = f.read().strip()[2:]
                    with open(os.path.join(devdir, 'device')) as f:
                        vendor_id = f.read().strip()[2:]
                except IOError as e:
                    raise RuntimeError('could not determine vendor and device ID of %s: %s', pf, str(e))

                combined_id = ':'.join(vendor_id, device_id)
                quirk_devices = ()  # TODO: add entries to the list
                if combined_id in quirk_devices:
                    # some devices need special handling, so this is the place
                    # TODO
                    pass

            # also, since the VF number changed, the interfaces list also
            # changed, so we need to refresh it
            interfaces = netifaces.interfaces()

        # now in theory we should have all the new VFs set up and existing;
        # this is needed because we will have to now match the defined VF
        # entries to existing interfaces, otherwise we won't be able to set
        # filtered VLANs for those.
        for vf in active_vfs:
            settings = config_manager.ethernets.get(vf)
            match = settings.get('match')
            if match:
                by_name = pf_match.get('name')
                by_mac = pf_match.get('macaddress')
                by_driver = pf_match.get('driver')

                for interface in interfaces:
                    if ((by_name and not is_interface_matching_name(interface, by_name)) or
                         (by_mac and not is_interface_matching_macaddress(interface, by_mac)) or
                         (by_driver and not is_interface_matching_driver_name(interface, by_driver))):
                        continue

                    active_vfs[vf].append(interface)

        filtered_vlans_set = set()
        for vlan, settings in config_manager.vlans.items():
            # there is a special sriov vlan renderer that one can use to mark
            # a selected vlan to be done in hardware (VLAN filtering)
            if settings.get('renderer') == 'sriov':
                # this only works for SR-IOV VF interfaces
                link = settings.get('link')
                if link not in vfs:
                    raise ConfigurationError(
                        'SR-IOV vlan %s defined for %s, which is not a VF' % (vlan, link))

                vlan_id = settings.get('id')
                if not vlan_id:
                    raise ConfigurationError(
                        'no id property defined for SR-IOV vlan %s' % vlan)

                vfs = active_vfs.get(link)
                if not vfs:
                    # it is possible this is not an error, for instance when
                    # the configuration has been defined 'for the future'
                    # XXX: but maybe we should error out here as well?
                    logging.warning(
                        'SR-IOV vlan defined for %s but link %s has no matches' % (vlan, link))
                    continue

                # get the parent pf interface
                # first we fetch the related vf netplan entry
                vf_entry = config_manager.ethernets.get(link).get('link')
                # then use it to get the pf
                pf_entry = config_manager.ethernets.get(vf_entry)
                # and finally, get the matched pf interface
                # XXX: what if there are multiple vfs matched and pfs matched?
                pf = active_pfs.get(pf_entry)[0]  # TODO: this is probably wrong

                for vf in vfs:
                    if vf in filtered_vlans_set:
                        raise ConfigurationError(
                            'interface %s for netplan device %s (%s) already has an SR-IOV vlan defined' % (vf, vlan, link))

                    # we need to get the vf index
                    vf_index = None
                    vf_devdir = os.path.join('/sys/class/net', vf, 'device')
                    vf_dev_id = os.path.basename(os.readlink(vf_devdir))
                    pf_devdir = os.path.join('/sys/class/net', pf, 'device')
                    for f in os.listdir(pf_devdir):
                        if 'virtfn' in f:
                            dev_path = os.path.join(pf_devdir, f)
                            dev_id = os.path.basename(os.readlink(dev_path))
                            if dev_id == vf_dev_id:
                                vf_index = f[6:]
                                break

                    if not vf_index:
                        raise RuntimeError(
                            'could not determine the VF index for %s while configuring vlan %s' % (vf, vlan))

                    # now, create the VLAN filter
                    # ip link set dev PF vf ID vlan VID
                    try:
                        subprocess.check_call(['ip', 'link', 'set',
                                               'dev', pf,
                                               'vf', vf_index,
                                               'vlan', vlan_id],
                                              stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
                    except subprocess.CalledProcessError:
                        raise RuntimeError(
                            'failed setting SR-IOV VLAN filter for vlan %s (ip link set command failed)' % vlan)
