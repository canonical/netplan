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

'''netplan configuration manager'''

import glob
import os
import shutil
import tempfile


class ConfigManager(object):

    def __init__(self):
        self.tempdir = tempfile.mkdtemp(prefix='netplan_')
        self.temp_etc = os.path.join(self.tempdir, "etc")
        self.temp_run = os.path.join(self.tempdir, "run")
        self.extra_files = {}

    def add(self, config_dict):
        for config_file in config_dict:
            self._copy_file(config_file, config_dict[config_file])
        self.extra_files.update(config_dict)

    def backup(self, with_config_file=False):
        if with_config_file:
            self._copy_tree("/etc/netplan",
                            os.path.join(self.temp_etc, "netplan"))
        self._copy_tree("/run/NetworkManager/system-connections",
                        os.path.join(self.temp_run, "NetworkManager", "system-connections"),
                        missing_ok=True)
        self._copy_tree("/run/systemd/network",
                        os.path.join(self.temp_run, "systemd", "network"),
                        missing_ok=True)

    def revert(self, with_config_file=False):
        try:
            for extra_file in self.extra_files.values():
                os.unlink(extra_file)
            temp_nm_path = "{}/NetworkManager/system-connections".format(self.temp_run)
            temp_networkd_path = "{}/systemd/network".format(self.temp_run)
            if os.path.exists(temp_nm_path):
                shutil.rmtree("/run/NetworkManager/system-connections")
                self._copy_tree(temp_nm_path, "/run/NetworkManager/system-connections")
            if os.path.exists(temp_networkd_path):
                shutil.rmtree("/run/systemd/network")
                self._copy_tree(temp_networkd_path, "/run/systemd/network")
        except Exception as e:
            # If we reach here, we're in big trouble. We may have wiped out
            # file NM or networkd are using, and we most likely removed the
            # "new" config -- or at least our copy of it.
            # Given that we're in some halfway done revert; warn the user
            # aggressively and drop everything; leaving any remaining backups
            # around for the user to handle themselves.
            logging.error("Something really bad happened while reverting config: {}".format(e))
            logging.error("You should verify the netplan YAML in /etc/netplan and probably run 'netplan apply' again.")
            sys.exit(-1)

    def cleanup(self):
        shutil.rmtree(self.tempdir)

    def _copy_file(self, src, dst):
        shutil.copy(src, dst)

    def _copy_tree(self, src, dst, missing_ok=False):
        try:
            shutil.copytree(src, dst)
        except FileNotFoundError:
            if missing_ok:
                pass
            else:
                raise
