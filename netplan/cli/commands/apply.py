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
import fnmatch

import netplan.cli.utils as utils


class NetplanApply(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='apply',
                         description='Apply current netplan config to running system',
                         leaf=True)

    def run(self):  # pragma: nocover (covered in autopkgtest)
        self.func = self.command_apply

        self.parse_args()

        # apply doesn't currently support an alternative root-dir
        config = utils.gather_replug_yaml('/')

        self.disable_all_replug = config['disable_all_replug']
        self.blacklist = config['blacklist']

        self.run_command()

    def command_apply(self):  # pragma: nocover (covered in autopkgtest)
        if subprocess.call([utils.get_generator_path()]) != 0:
            sys.exit(1)

        devices = os.listdir('/sys/class/net')

        restart_networkd = bool(glob.glob('/run/systemd/network/*netplan-*'))
        restart_nm = bool(glob.glob('/run/NetworkManager/system-connections/netplan-*'))

        # stop backends
        if restart_networkd:
            logging.debug('netplan generated networkd configuration exists, restarting networkd')
            subprocess.check_call(['systemctl', 'stop', '--no-block', 'systemd-networkd.service', 'netplan-wpa@*.service'])
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

                utils.systemctl_network_manager('stop')
        else:
            logging.debug('no netplan generated NM configuration exists')

        # force-hotplug all "down" network interfaces to apply renames
        any_replug = False
        for device in devices:
            if not os.path.islink('/sys/class/net/' + device):
                continue
            if self.replug(device):
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
            subprocess.check_call(['systemctl', 'start', '--no-block', 'systemd-networkd.service'] +
                                  [os.path.basename(f) for f in glob.glob('/run/systemd/system/*.wants/netplan-wpa@*.service')])
        if restart_nm:
            utils.systemctl_network_manager('start')

    def replug(self, device):  # pragma: nocover (covered in autopkgtest)
        '''Unbind and rebind device if it is down'''

        if self.disable_all_replug:
            logging.debug('disable_all_replug is set, not replugging')
            return True

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

            for entry in self.blacklist:
                # if a device matches all the criteria in a blacklist entry,
                # then do not replug it
                # note that an empty blacklist entry will match everything!

                if 'driver' in entry:
                    if not fnmatch.fnmatchcase(driver_name, entry['driver']):
                        continue

                if 'subsystem' in entry:
                    if not fnmatch.fnmatchcase(subsystem_name, entry['subsystem']):
                        continue

                logging.debug('replug %s: %s:%s is blacklisted from rebinding: %s',
                              device,
                              (entry['subsystem'] if 'subsystem' in entry else '*'),
                              (entry['driver'] if 'driver' in entry else '*'),
                              (entry['reason'] if 'reason' in entry else 'unsupported'))
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
