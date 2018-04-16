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
import logging
import os
import shutil
import sys
import tempfile
import yaml


class ConfigManager(object):

    def __init__(self, prefix="/", extra_files={}):
        self.prefix = prefix
        self.tempdir = tempfile.mkdtemp(prefix='netplan_')
        self.temp_etc = os.path.join(self.tempdir, "etc")
        self.temp_run = os.path.join(self.tempdir, "run")
        self.extra_files = extra_files
        self.config = {}

    @property
    def network(self):
        return self.config['network']

    @property
    def interfaces(self):
        interfaces = {}
        interfaces.update(self.ethernets)
        interfaces.update(self.wifis)
        interfaces.update(self.bridges)
        interfaces.update(self.bonds)
        interfaces.update(self.vlans)
        return interfaces

    @property
    def ethernets(self):
        return self.network['ethernets']

    @property
    def wifis(self):
        return self.network['wifis']

    @property
    def bridges(self):
        return self.network['bridges']

    @property
    def bonds(self):
        return self.network['bonds']

    @property
    def vlans(self):
        return self.network['vlans']

    def parse(self, extra_config=[]):
        """
        Parse all our config files to return an object that describes the system's
        entire configuration, so that it can later be interrogated.

        Returns a dict that contains the entire, collated and merged YAML.
        """
        # TODO: Clean this up, there's no solid reason why we should parse YAML
        #       in two different spots; here and in parse.c. We'd do better by
        #       parsing things once, in C form, and having some small glue
        #       Cpython code to call on the right methods and return an object
        #       that is meaningful for the Python code; but minimal parsing in
        #       pure Python will do for now.  ~cyphermox

        # /run/netplan shadows /etc/netplan/, which shadows /lib/netplan
        names_to_paths = {}
        for yaml_dir in ['lib', 'etc', 'run']:
            for yaml_file in glob.glob(os.path.join(self.prefix, yaml_dir, 'netplan', '*.yaml')):
                names_to_paths[os.path.basename(yaml_file)] = yaml_file

        files = [names_to_paths[name] for name in sorted(names_to_paths.keys())]

        if extra_config:
            files.extend(extra_config)

        self.config['network'] = {
            'ethernets': {},
            'wifis': {},
            'bridges': {},
            'bonds': {},
            'vlans': {}
        }
        for yaml_file in files:
            try:
                with open(yaml_file) as f:
                    yaml_data = yaml.load(f, Loader=yaml.CSafeLoader)
                    network = yaml_data.get('network')
                    if network:
                        if 'ethernets' in network:
                            self._merge_config(self.ethernets, network.get('ethernets'))
                        if 'wifis' in network:
                            self._merge_config(self.wifis, network.get('wifis'))
                        if 'bridges' in network:
                            self._merge_config(self.bridges, network.get('bridges'))
                        if 'bonds' in network:
                            self._merge_config(self.bonds, network.get('bonds'))
                        if 'vlans' in network:
                            self._merge_config(self.vlans, network.get('vlans'))
            except (IOError, yaml.YAMLError):  # pragma: nocover (filesystem failures/invalid YAML)
                logging.error('Error while loading {}, aborting.'.format(yaml_file))
                sys.exit(1)

    def add(self, config_dict):
        for config_file in config_dict:
            self._copy_file(config_file, config_dict[config_file])
        self.extra_files.update(config_dict)

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

    def _merge_config(self, orig, new):
        changed_ifaces = list(new.keys())
        for ifname in changed_ifaces:
            iface = new.pop(ifname)
            if ifname in orig:
                orig[ifname].update(iface)
            else:
                orig[ifname] = iface
