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
        self.new_interfaces = set()

    @property
    def network(self):
        return self.config['network']

    @property
    def interfaces(self):
        interfaces = {}
        interfaces.update(self.ovs_ports)
        interfaces.update(self.ethernets)
        interfaces.update(self.modems)
        interfaces.update(self.wifis)
        interfaces.update(self.bridges)
        interfaces.update(self.bonds)
        interfaces.update(self.tunnels)
        interfaces.update(self.vlans)
        return interfaces

    @property
    def physical_interfaces(self):
        interfaces = {}
        interfaces.update(self.ethernets)
        interfaces.update(self.modems)
        interfaces.update(self.wifis)
        return interfaces

    @property
    def ovs_ports(self):
        return self.network['ovs_ports']

    @property
    def openvswitch(self):
        return self.network['openvswitch']

    @property
    def ethernets(self):
        return self.network['ethernets']

    @property
    def modems(self):
        return self.network['modems']

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
    def tunnels(self):
        return self.network['tunnels']

    @property
    def vlans(self):
        return self.network['vlans']

    @property
    def nm_devices(self):
        return self.network['nm-devices']

    @property
    def version(self):
        return self.network['version']

    @property
    def renderer(self):
        return self.network['renderer']

    @property
    def tree(self):
        return self.strip_tree(self.config)

    @staticmethod
    def strip_tree(data):
        '''clear empty branches'''
        new_data = {}
        for k, v in data.items():
            if isinstance(v, dict):
                v = ConfigManager.strip_tree(v)
            if v not in (u'', None, {}):
                new_data[k] = v
        return new_data

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

        self.config['network'] = {
            'ovs_ports': {},
            'openvswitch': {},
            'ethernets': {},
            'modems': {},
            'wifis': {},
            'bridges': {},
            'bonds': {},
            'tunnels': {},
            'vlans': {},
            'nm-devices': {},
            'version': None,
            'renderer': None
        }
        for yaml_file in files:
            self._merge_yaml_config(yaml_file)

        for yaml_file in extra_config:
            self.new_interfaces |= self._merge_yaml_config(yaml_file)

        logging.debug("Merged config:\n{}".format(yaml.dump(self.tree, default_flow_style=False)))

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

    def _merge_ovs_ports_config(self, orig, new):
        new_interfaces = set()
        ports = dict()
        if 'ports' in new:
            for p1, p2 in new.get('ports'):
                # Spoof an interface config for patch ports, which are usually
                # just strings. Add 'peer' and mark it via 'openvswitch' key.
                ports[p1] = {'peer': p2, 'openvswitch': {}}
                ports[p2] = {'peer': p1, 'openvswitch': {}}
        changed_ifaces = list(ports.keys())

        for ifname in changed_ifaces:
            iface = ports.pop(ifname)
            if ifname in orig:
                logging.debug("{} exists in {}".format(ifname, orig))
                orig[ifname].update(iface)
            else:
                logging.debug("{} not found in {}".format(ifname, orig))
                orig[ifname] = iface
                new_interfaces.add(ifname)

        return new_interfaces

    def _merge_interface_config(self, orig, new):
        new_interfaces = set()
        changed_ifaces = list(new.keys())

        for ifname in changed_ifaces:
            iface = new.pop(ifname)
            if ifname in orig:
                logging.debug("{} exists in {}".format(ifname, orig))
                orig[ifname].update(iface)
            else:
                logging.debug("{} not found in {}".format(ifname, orig))
                orig[ifname] = iface
                new_interfaces.add(ifname)

        return new_interfaces

    def _merge_yaml_config(self, yaml_file):
        new_interfaces = set()

        try:
            with open(yaml_file) as f:
                yaml_data = yaml.load(f, Loader=yaml.CSafeLoader)
                network = None
                if yaml_data is not None:
                    network = yaml_data.get('network')
                if network:
                    if 'openvswitch' in network:
                        new = self._merge_ovs_ports_config(self.ovs_ports, network.get('openvswitch'))
                        new_interfaces |= new
                        self.network['openvswitch'] = network.get('openvswitch')
                    if 'ethernets' in network:
                        new = self._merge_interface_config(self.ethernets, network.get('ethernets'))
                        new_interfaces |= new
                    if 'modems' in network:
                        new = self._merge_interface_config(self.modems, network.get('modems'))
                        new_interfaces |= new
                    if 'wifis' in network:
                        new = self._merge_interface_config(self.wifis, network.get('wifis'))
                        new_interfaces |= new
                    if 'bridges' in network:
                        new = self._merge_interface_config(self.bridges, network.get('bridges'))
                        new_interfaces |= new
                    if 'bonds' in network:
                        new = self._merge_interface_config(self.bonds, network.get('bonds'))
                        new_interfaces |= new
                    if 'tunnels' in network:
                        new = self._merge_interface_config(self.tunnels, network.get('tunnels'))
                        new_interfaces |= new
                    if 'vlans' in network:
                        new = self._merge_interface_config(self.vlans, network.get('vlans'))
                        new_interfaces |= new
                    if 'nm-devices' in network:
                        new = self._merge_interface_config(self.nm_devices, network.get('nm-devices'))
                        new_interfaces |= new
                    if 'version' in network:
                        self.network['version'] = network.get('version')
                    if 'renderer' in network:
                        self.network['renderer'] = network.get('renderer')
            return new_interfaces
        except (IOError, yaml.YAMLError):  # pragma: nocover (filesystem failures/invalid YAML)
            logging.error('Error while loading {}, aborting.'.format(yaml_file))
            sys.exit(1)


class ConfigurationError(Exception):
    """
    Configuration could not be parsed or has otherwise failed to apply
    """
    pass
