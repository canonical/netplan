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
import subprocess

import netplan.cli.utils as utils
from netplan.configmanager import ConfigurationError


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
        if run_generate and subprocess.call([utils.get_generator_path()]) != 0:
            if exit_on_error:
                sys.exit(os.EX_CONFIG)
            else:
                raise ConfigurationError("the configuration could not be generated")

        devices = os.listdir('/sys/class/net')

        restart_networkd = bool(glob.glob('/run/systemd/network/*netplan-*'))
        restart_nm = bool(glob.glob('/run/NetworkManager/system-connections/netplan-*'))

        # stop backends
        if restart_networkd:
            logging.debug('netplan generated networkd configuration exists, restarting networkd')
            utils.systemctl_networkd('stop', sync=sync, extra_services=['netplan-wpa@*.service'])
        else:
            logging.debug('no netplan generated networkd configuration exists')

        if restart_nm:
            logging.debug('netplan generated NM configuration exists, restarting NM')
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

        # force-hotplug all "down" network interfaces to apply renames
        any_replug = False
        for device in devices:
            if not os.path.islink('/sys/class/net/' + device):
                continue
            if NetplanApply.replug(device):
                any_replug = True
            else:
                # if the interface is up, we can still apply .link file changes
                logging.debug('netplan triggering .link rules for %s', device)
                with open(os.devnull, 'w') as fd:
                    subprocess.check_call(['udevadm', 'test-builtin',
                                           'net_setup_link',
                                           '/sys/class/net/' + device],
                                          stdout=fd, stderr=fd)
        if any_replug:
            subprocess.check_call(['udevadm', 'settle'])

        # (re)start backends
        if restart_networkd:
            netplan_wpa = [os.path.basename(f) for f in glob.glob('/run/systemd/system/*.wants/netplan-wpa@*.service')]
            utils.systemctl_networkd('start', sync=sync, extra_services=netplan_wpa)
        if restart_nm:
            utils.systemctl_network_manager('start', sync=sync)

    @staticmethod
    def replug(device):  # pragma: nocover (covered in autopkgtest)
        '''Unbind and rebind device if it is down'''

        devdir = os.path.join('/sys/class/net', device)

        try:
            with open(os.path.join(devdir, 'operstate')) as f:
                state = f.read().strip()
                if state != 'down':
                    logging.debug('device %s operstate is %s, not replugging', device, state)
                    return False
        except IOError as e:
            logging.error('Cannot determine operstate of %s: %s', device, str(e))
            return False

        # /sys/class/net/ens3/device -> ../../../virtio0
        # /sys/class/net/ens3/device/driver -> ../../../../bus/virtio/drivers/virtio_net
        try:
            devname = os.path.basename(os.readlink(os.path.join(devdir, 'device')))
        except IOError as e:
            logging.debug('Cannot replug %s: cannot read link %s/device: %s', device, devdir, str(e))
            return False

        try:
            # we must resolve symlinks here as the device dir will be gone after unbind
            subsystem = os.path.realpath(os.path.join(devdir, 'device', 'subsystem'))
            subsystem_name = os.path.basename(subsystem)
            driver = os.path.realpath(os.path.join(devdir, 'device', 'driver'))
            driver_name = os.path.basename(driver)
            if driver_name == 'mac80211_hwsim':
                logging.debug('replug %s: mac80211_hwsim does not support rebinding, ignoring', device)
                return False
            # workaround for https://bugs.launchpad.net/ubuntu/+source/linux/+bug/1630285
            if driver_name == 'mwifiex_pcie':
                logging.debug('replug %s: mwifiex_pcie crashes on rebinding, ignoring', device)
                return False
            # workaround for https://bugs.launchpad.net/ubuntu/+source/linux/+bug/1729573
            if subsystem_name == 'xen' and driver_name == 'vif':
                logging.debug('replug %s: xen:vif fails on rebinding, ignoring', device)
                return False
            # workaround for problem with ath9k_htc module: this driver is async and does not support
            # sequential unbind / rebind, one soon after the other
            if driver_name == 'ath9k_htc':
                logging.debug('replug %s: ath9k_htc does not support rebinding, ignoring', device)
                return False
            # workaround for ath6kl_sdio, interface does not work after unbinding
            if 'ath6kl_sdio' in driver_name:
                logging.debug('replug %s: ath6kl_sdio driver does not support rebinding, ignoring', device)
                return False
            # workaround for brcmfmac, interface will be gone after unbind
            if 'brcmfmac' in driver_name:
                logging.debug('replug %s: brcmfmac drivers do not support rebinding, ignoring', device)
                return False
            # workaround for qeth: driver does not recognize unbind command
            # https://bugs.launchpad.net/ubuntu/+source/netplan.io/+bug/1756322
            if driver_name == 'qeth':
                logging.debug('replug %s: qeth driver do not support rebinding, ignoring (LP: #1756322)', device)
                return False
            logging.debug('replug %s: unbinding %s from %s', device, devname, driver)
            with open(os.path.join(driver, 'unbind'), 'w') as f:
                f.write(devname)
            logging.debug('replug %s: rebinding %s to %s', device, devname, driver)
            with open(os.path.join(driver, 'bind'), 'w') as f:
                f.write(devname)
        except IOError as e:
            logging.error('Cannot replug %s: %s', device, str(e))
            return False

        return True
