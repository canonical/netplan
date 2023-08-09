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

import logging
import netplan
import os
import shutil
import sys
import tempfile

from typing import Optional


class ConfigManager(object):
    def __init__(self, prefix="/", extra_files={}):
        self.prefix = prefix
        self.tempdir = tempfile.mkdtemp(prefix='netplan_')
        self.temp_etc = os.path.join(self.tempdir, "etc")
        self.temp_run = os.path.join(self.tempdir, "run")
        self.extra_files = extra_files
        self.new_interfaces = set()
        self.np_state: Optional[netplan.State] = None

    def __getattr__(self, attr):
        assert self.np_state is not None, "Must call parse() before accessing the config."
        return getattr(self.np_state, attr)

    @property
    def physical_interfaces(self):
        assert self.np_state is not None, "Must call parse() before accessing the config."
        interfaces = {}
        interfaces.update(self.np_state.ethernets)
        interfaces.update(self.np_state.modems)
        interfaces.update(self.np_state.wifis)
        return interfaces

    @property
    def virtual_interfaces(self):
        assert self.np_state is not None, "Must call parse() before accessing the config."
        interfaces = {}
        # what about ovs_ports?
        interfaces.update(self.np_state.bridges)
        interfaces.update(self.np_state.bonds)
        interfaces.update(self.np_state.dummy_devices)
        interfaces.update(self.np_state.tunnels)
        interfaces.update(self.np_state.virtual_ethernets)
        interfaces.update(self.np_state.vlans)
        interfaces.update(self.np_state.vrfs)
        return interfaces

    def parse(self, extra_config=None):
        """
        Parse all our config files to return an object that describes the system's
        entire configuration, so that it can later be interrogated.

        Returns a libnetplan State wrapper
        """

        # /run/netplan shadows /etc/netplan/, which shadows /lib/netplan
        parser = netplan.Parser()
        try:
            parser.load_yaml_hierarchy(rootdir=self.prefix)

            if extra_config:
                for f in extra_config:
                    parser.load_yaml(f)

            self.np_state = netplan.State()
            self.np_state.import_parser_results(parser)
        except netplan.NetplanException as e:
            raise ConfigurationError(str(e))

        # Convoluted way to dump the parsed config to the logs...
        with tempfile.TemporaryFile() as tmp:
            self.np_state._dump_yaml(output_file=tmp)
            logging.debug("Merged config:\n{}".format(tmp.read()))

        return self.np_state

    def add(self, config_dict):
        for config_file in config_dict:
            self._copy_file(config_file, config_dict[config_file])
        self.extra_files.update(config_dict)

        # Invalidate the current parsed state
        self.np_state = None

    def backup(self, backup_config_dir=True):
        if backup_config_dir:
            self._copy_tree(os.path.join(self.prefix, "etc/netplan"),
                            os.path.join(self.temp_etc, "netplan"))
        self._copy_tree(os.path.join(self.prefix, "run/NetworkManager/system-connections"),
                        os.path.join(self.temp_run, "NetworkManager", "system-connections"),
                        missing_ok=True)
        self._copy_tree(os.path.join(self.prefix, "run/systemd/network"),
                        os.path.join(self.temp_run, "systemd", "network"),
                        missing_ok=True)

    def revert(self):
        try:
            for extra_file in dict(self.extra_files):
                os.unlink(self.extra_files[extra_file])
                del self.extra_files[extra_file]
            temp_nm_path = "{}/NetworkManager/system-connections".format(self.temp_run)
            temp_networkd_path = "{}/systemd/network".format(self.temp_run)
            if os.path.exists(temp_nm_path):
                shutil.rmtree(os.path.join(self.prefix, "run/NetworkManager/system-connections"))
                self._copy_tree(temp_nm_path,
                                os.path.join(self.prefix, "run/NetworkManager/system-connections"))
            if os.path.exists(temp_networkd_path):
                shutil.rmtree(os.path.join(self.prefix, "run/systemd/network"))
                self._copy_tree(temp_networkd_path,
                                os.path.join(self.prefix, "run/systemd/network"))
        except Exception as e:  # pragma: nocover (only relevant to filesystem failures)
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

    def __del__(self):
        try:
            self.cleanup()
        except FileNotFoundError:
            # If cleanup() was called before, there is nothing to delete
            pass

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


class ConfigurationError(Exception):
    """
    Configuration could not be parsed or has otherwise failed to apply
    """
    pass
