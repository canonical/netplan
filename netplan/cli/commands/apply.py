#!/usr/bin/python3
#
# Copyright (C) 2018-2020 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
# Author: Lukas 'slyon' Märdian <lukas.maerdian@canonical.com>
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
import subprocess
import shutil

import netplan.cli.utils as utils
from netplan.configmanager import ConfigManager, ConfigurationError
from netplan.cli.sriov import apply_sriov_config
from netplan.cli.ovs import apply_ovs_cleanup

import netifaces


class NetplanApply(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='apply',
                         description='Apply current netplan config to running system',
                         leaf=True)
        self.sriov_only = False
        self.only_ovs_cleanup = False

    def run(self):  # pragma: nocover (covered in autopkgtest)
        self.parser.add_argument('--sriov-only', action='store_true',
                                 help='Only apply SR-IOV related configuration and exit')
        self.parser.add_argument('--only-ovs-cleanup', action='store_true',
                                 help='Only clean up old OpenVSwitch interfaces and exit')

        self.func = self.command_apply

        self.parse_args()
        self.run_command()

    def command_apply(self, run_generate=True, sync=False, exit_on_error=True):  # pragma: nocover (covered in autopkgtest)
        config_manager = ConfigManager()

        # For certain use-cases, we might want to only apply specific configuration.
        # If we only need SR-IOV configuration, do that and exit early.
        if self.sriov_only:
            NetplanApply.process_sriov_config(config_manager, exit_on_error)
            return
        # If we only need OpenVSwitch cleanup, do that and exit early.
        elif self.only_ovs_cleanup:
            NetplanApply.process_ovs_cleanup(config_manager, False, False, exit_on_error)
            return

        # if we are inside a snap, then call dbus to run netplan apply instead
        if "SNAP" in os.environ:
            # TODO: maybe check if we are inside a classic snap and don't do
            # this if we are in a classic snap?
            busctl = shutil.which("busctl")
            if busctl is None:
                raise RuntimeError("missing busctl utility")
            # XXX: DO NOT TOUCH or change this API call, it is used by snapd to communicate
            #      using core20 netplan binary/client/CLI on core18 base systems. Any change
            #      must be agreed upon with the snapd team, so we don't break support for
            #      base systems running older netplan versions.
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

        ovs_cleanup_service = '/run/systemd/system/netplan-ovs-cleanup.service'
        old_files_networkd = bool(glob.glob('/run/systemd/network/*netplan-*'))
        old_ovs_glob = glob.glob('/run/systemd/system/netplan-ovs-*')
        # Ignore netplan-ovs-cleanup.service, as it can always be there
        if ovs_cleanup_service in old_ovs_glob:
            old_ovs_glob.remove(ovs_cleanup_service)
        old_files_ovs = bool(old_ovs_glob)
        old_nm_glob = glob.glob('/run/NetworkManager/system-connections/netplan-*')
        nm_ifaces = utils.nm_interfaces(old_nm_glob, netifaces.interfaces())
        old_files_nm = bool(old_nm_glob)

        generator_call = []
        generate_out = None
        if 'NETPLAN_PROFILE' in os.environ:
            generator_call.extend(['valgrind', '--leak-check=full'])
            generate_out = subprocess.STDOUT

        generator_call.append(utils.get_generator_path())
        if run_generate and subprocess.call(generator_call, stderr=generate_out) != 0:
            if exit_on_error:
                sys.exit(os.EX_CONFIG)
            else:
                raise ConfigurationError("the configuration could not be generated")

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
        restart_ovs_glob = glob.glob('/run/systemd/system/netplan-ovs-*')
        # Ignore netplan-ovs-cleanup.service, as it can always be there
        if ovs_cleanup_service in restart_ovs_glob:
            restart_ovs_glob.remove(ovs_cleanup_service)
        restart_ovs = bool(restart_ovs_glob)
        if not restart_ovs and old_files_ovs:
            # OVS is managed via systemd units
            restart_networkd = True

        restart_nm_glob = glob.glob('/run/NetworkManager/system-connections/netplan-*')
        nm_ifaces.update(utils.nm_interfaces(restart_nm_glob, devices))
        restart_nm = bool(restart_nm_glob)
        if not restart_nm and old_files_nm:
            restart_nm = True

        # stop backends
        if restart_networkd:
            logging.debug('netplan generated networkd configuration changed, restarting networkd')
            # Running 'systemctl daemon-reload' will re-run the netplan systemd generator,
            # so let's make sure we only run it iff we're willing to run 'netplan generate'
            if run_generate:
                utils.systemctl_daemon_reload()
            # Clean up any old netplan related OVS ports/bonds/bridges, if applicable
            NetplanApply.process_ovs_cleanup(config_manager, old_files_ovs, restart_ovs, exit_on_error)
            wpa_services = ['netplan-wpa-*.service']
            # Historically (up to v0.98) we had netplan-wpa@*.service files, in case of an
            # upgraded system, we need to make sure to stop those.
            if utils.systemctl_is_active('netplan-wpa@*.service'):
                wpa_services.insert(0, 'netplan-wpa@*.service')
            utils.systemctl_networkd('stop', sync=sync, extra_services=wpa_services)
        else:
            logging.debug('no netplan generated networkd configuration exists')

        if restart_nm:
            logging.debug('netplan generated NM configuration changed, restarting NM')
            if utils.nm_running():
                # restarting NM does not cause new config to be applied, need to shut down devices first
                for device in devices:
                    if device not in nm_ifaces:
                        continue  # do not touch this interface
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

        # if the interface is up, we can still apply some .link file changes
        # but we cannot apply the interface rename via udev, as it won't touch
        # the interface name, if it was already renamed once (e.g. during boot),
        # because of the NamePolicy=keep default:
        # https://www.freedesktop.org/software/systemd/man/systemd.net-naming-scheme.html
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

        # apply some more changes manually
        for iface, settings in changes.items():
            # rename non-critical network interfaces
            if settings.get('name'):
                # bring down the interface, using its current (matched) interface name
                subprocess.check_call(['ip', 'link', 'set', 'dev', iface, 'down'],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
                # rename the interface to the name given via 'set-name'
                subprocess.check_call(['ip', 'link', 'set',
                                       'dev', iface,
                                       'name', settings.get('name')],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)

        subprocess.check_call(['udevadm', 'settle'])

        # apply any SR-IOV related changes, if applicable
        NetplanApply.process_sriov_config(config_manager, exit_on_error)

        # (re)start backends
        if restart_networkd:
            netplan_wpa = [os.path.basename(f) for f in glob.glob('/run/systemd/system/*.wants/netplan-wpa-*.service')]
            netplan_ovs = [os.path.basename(f) for f in glob.glob('/run/systemd/system/*.wants/netplan-ovs-*.service')]
            # Run 'systemctl start' command synchronously, to avoid race conditions
            # with 'oneshot' systemd service units, e.g. netplan-ovs-*.service.
            utils.systemctl_networkd('start', sync=True, extra_services=netplan_wpa + netplan_ovs)
        if restart_nm:
            # Flush all IP addresses of NM managed interfaces, to avoid NM creating
            # new, non netplan-* connection profiles, using the existing IPs.
            for iface in utils.nm_interfaces(restart_nm_glob, devices):
                utils.ip_addr_flush(iface)
            utils.systemctl_network_manager('start', sync=sync)

    @staticmethod
    def is_composite_member(composites, phy):  # pragma: nocover (covered in autopkgtest)
        """
        Is this physical interface a member of a 'composite' virtual
        interface? (bond, bridge)
        """
        for composite in composites:
            for _, settings in composite.items():
                members = settings.get('interfaces', [])
                for iface in members:
                    if iface == phy:
                        return True

        return False

    @staticmethod
    def process_link_changes(interfaces, config_manager):  # pragma: nocover (covered in autopkgtest)
        """
        Go through the pending changes and pick what needs special handling.
        Only applies to non-critical interfaces which can be safely updated.
        """

        changes = {}
        phys = dict(config_manager.physical_interfaces)
        composite_interfaces = [config_manager.bridges, config_manager.bonds]

        # Find physical interfaces which need a rename
        # But do not rename virtual interfaces
        for phy, settings in phys.items():
            if not settings or not isinstance(settings, dict):
                continue  # Skip special values, like "renderer: ..."
            newname = settings.get('set-name')
            if not newname:
                continue  # Skip if no new name needs to be set
            match = settings.get('match')
            if not match:
                continue  # Skip if no match for current name is given
            if NetplanApply.is_composite_member(composite_interfaces, phy):
                logging.debug('Skipping composite member {}'.format(phy))
                # do not rename members of virtual devices. MAC addresses
                # may be the same for all interface members.
                continue
            # Find current name of the interface, according to match conditions and globs (name, mac, driver)
            current_iface_name = utils.find_matching_iface(interfaces, match)
            if not current_iface_name:
                logging.warning('Cannot find unique matching interface for {}: {}'.format(phy, match))
                continue
            if current_iface_name == newname:
                # Skip interface if it already has the correct name
                logging.debug('Skipping correctly named interface: {}'.format(newname))
                continue
            if settings.get('critical', False):
                # Skip interfaces defined as critical, as we should not take them down in order to rename
                logging.warning('Cannot rename {} ({} -> {}) at runtime (needs reboot), due to being critical'
                                .format(phy, current_iface_name, newname))
                continue

            # record the interface rename change
            changes[current_iface_name] = {'name': newname}

        logging.debug('Link changes: {}'.format(changes))
        return changes

    @staticmethod
    def process_sriov_config(config_manager, exit_on_error=True):  # pragma: nocover (covered in autopkgtest)
        try:
            apply_sriov_config(config_manager)
        except (ConfigurationError, RuntimeError) as e:
            logging.error(str(e))
            if exit_on_error:
                sys.exit(1)

    @staticmethod
    def process_ovs_cleanup(config_manager, ovs_old, ovs_current, exit_on_error=True):  # pragma: nocover (autopkgtest)
        try:
            apply_ovs_cleanup(config_manager, ovs_old, ovs_current)
        except (OSError, RuntimeError) as e:
            logging.error(str(e))
            if exit_on_error:
                sys.exit(1)
