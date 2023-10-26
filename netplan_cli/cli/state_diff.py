#!/usr/bin/python3
#
# Copyright (C) 2023 Canonical, Ltd.
# Authors: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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

import ipaddress

from netplan.netdef import NetplanRoute
from netplan_cli.cli.state import SystemConfigState, NetplanConfigState, DEVICE_TYPES


class NetplanDiffState():
    '''
    DiffState is mainly responsible for getting both system's and Netplan's configuration
    state, compare them and provide a data-structure containing the differences it found.
    '''

    def __init__(self, system_state: SystemConfigState, netplan_state: NetplanConfigState):
        self.system_state = system_state
        self.netplan_state = netplan_state

    def get_full_state(self) -> dict:
        '''
        Return the states of both the system and Netplan in a common representation
        that makes it easier to compare them.
        '''

        full_state = {
            'interfaces': {}
        }

        system_interfaces = self._get_system_interfaces()
        netplan_interfaces = self._get_netplan_interfaces()

        # Merge all the interfaces in the same data structure
        all_interfaces = set(list(system_interfaces.keys()) + list(netplan_interfaces.keys()))
        for interface in all_interfaces:
            full_state['interfaces'][interface] = {}

        for interface, config in system_interfaces.items():
            full_state['interfaces'][interface].update(config)

        for interface, config in netplan_interfaces.items():
            full_state['interfaces'][interface].update(config)

        return full_state

    def get_diff(self, interface: str = '') -> dict:
        '''
        Compare the configuration of interfaces currently found in the system against Netplan configuration.
        A number of heuristics are used to eliminate configuration that is automatically set in the system,
        such as certain routes and IP addresses. That is necessary because this configuration will not be found
        in Netplan. For example, if Netplan is enabling DHCP on an interface and not defining any extra IP addresses,
        we don't count the IPs automatically assigned to the interface as a difference. We do though count the eventual
        absence of addresses that should be assigned by DHCP as a difference.
        '''

        full_state = self.get_full_state()
        interfaces = self._get_comparable_interfaces(full_state.get('interfaces', {}))

        if interface:
            if config := interfaces.get(interface):
                interfaces = {interface: config}

        report = self._create_new_report()

        self._analyze_missing_interfaces(report)

        for interface, config in interfaces.items():
            netdef_id = config.get('system_state', {}).get('id')
            index = config.get('system_state', {}).get('index')
            iface = self._create_new_iface(netdef_id, interface, index)

            self._analyze_ip_addresses(config, iface)

            report['interfaces'].update(iface)

        return report

    def _create_new_report(self) -> dict:
        return {
            'interfaces': {},
            'missing_interfaces_system': {},
            'missing_interfaces_netplan': {},
        }

    def _create_new_iface(self, netdef_id: str, interface: str, index: int) -> dict:
        return {
            interface: {
                'index': index,
                'name': interface,
                'id': netdef_id,
                'system_state': {},
                'netplan_state': {},
            }
        }

    def _analyze_ip_addresses(self, config: dict, iface: dict) -> None:
        name = list(iface.keys())[0]
        netplan_ips = {ip for ip in config.get('netplan_state', {}).get('addresses', [])}
        netplan_ips = self._normalize_ip_addresses(netplan_ips)

        missing_dhcp4_address = config.get('netplan_state', {}).get('dhcp4', False)
        missing_dhcp6_address = config.get('netplan_state', {}).get('dhcp6', False)
        system_ips = set()
        for addr, addr_data in config.get('system_state', {}).get('addresses', {}).items():
            ip = ipaddress.ip_interface(addr)
            flags = addr_data.get('flags', [])

            # Select only static IPs
            if 'dhcp' not in flags and 'link' not in flags:
                system_ips.add(addr)

            # TODO: improve the detection of addresses assigned dynamically
            # in the class Interface.
            if 'dhcp' in flags:
                if isinstance(ip.ip, ipaddress.IPv4Address):
                    missing_dhcp4_address = False
                if isinstance(ip.ip, ipaddress.IPv6Address):
                    missing_dhcp6_address = False

        present_only_in_netplan = netplan_ips.difference(system_ips)
        present_only_in_system = system_ips.difference(netplan_ips)

        if missing_dhcp4_address:
            iface[name]['system_state']['missing_dhcp4_address'] = True

        if missing_dhcp6_address:
            iface[name]['system_state']['missing_dhcp6_address'] = True

        if present_only_in_system:
            iface[name]['netplan_state'].update({
                'missing_addresses': list(present_only_in_system),
            })

        if present_only_in_netplan:
            iface[name]['system_state'].update({
                'missing_addresses': list(present_only_in_netplan),
            })

    def _get_comparable_interfaces(self, interfaces: dict) -> dict:
        ''' In order to compare interfaces, they must exist in the system AND in Netplan.
            Here we filter out interfaces that don't have a system_state and a netdef ID.
        '''
        filtered = {}

        for interface, config in interfaces.items():
            if config.get('system_state') is None:
                continue

            if not config.get('system_state', {}).get('id'):
                continue

            filtered[interface] = config

        return filtered

    def _normalize_ip_addresses(self, addresses: set) -> set:
        ''' Apply some transformations to IP addresses so their representation
        will match the system's.
        '''
        new_ips_set = set()
        for ip in addresses:
            ip = self._compress_ipv6_address(ip)
            new_ips_set.add(ip)

        return new_ips_set

    def _compress_ipv6_address(self, address: str) -> str:
        '''
        Compress IPv6 addresses to match the system representation
        Example: 1:2:0:0::123/64 -> 1:2::123/64
                 1:2:0:0::123 -> 1:2::123
        If "address" is not an IPv6Address, return the original value
        '''
        try:
            addr = ipaddress.ip_interface(address)
            if '/' in address:
                return addr.with_prefixlen
            return str(addr.ip)
        except ValueError:
            return address

    def _analyze_missing_interfaces(self, report: dict) -> None:
        netplan_interfaces = {iface for iface in self.netplan_state.netdefs}
        system_interfaces_netdef_ids = {iface.netdef_id for iface in self.system_state.interface_list if iface.netdef_id}

        netplan_only = netplan_interfaces.difference(system_interfaces_netdef_ids)
        # Filtering out disconnected wifi netdefs
        # If a wifi netdef is present in the netplan_only list it's because it's disconnected
        netplan_only = list(filter(lambda i: self.netplan_state.netdefs.get(i).type != 'wifis', netplan_only))

        system_only = []
        for iface in self.system_state.interface_list:
            if iface.netdef_id not in netplan_interfaces:
                system_only.append(iface.name)

        report['missing_interfaces_system'] = sorted(netplan_only)
        report['missing_interfaces_netplan'] = sorted(system_only)

    def _get_netplan_interfaces(self) -> dict:
        system_interfaces = self.system_state.get_data()
        interfaces = {}
        for interface, config in self.netplan_state.netdefs.items():

            iface = {}
            iface[interface] = {'netplan_state': {'id': interface}}
            iface_ref = iface[interface]['netplan_state']

            iface_ref['type'] = DEVICE_TYPES.get(config.type, 'unknown')

            iface_ref['dhcp4'] = config.dhcp4
            iface_ref['dhcp6'] = config.dhcp6

            addresses = [addr for addr in config.addresses]
            if addresses:
                iface_ref['addresses'] = {}
                for addr in addresses:
                    flags = {}
                    if addr.label:
                        flags['label'] = addr.label
                    if addr.lifetime:
                        flags['lifetime'] = addr.lifetime
                    iface_ref['addresses'][str(addr)] = {'flags': flags}

            if nameservers := list(config.nameserver_addresses):
                iface_ref['nameservers_addresses'] = nameservers

            if search := list(config.nameserver_search):
                iface_ref['nameservers_search'] = search

            if routes := list(config.routes):
                iface_ref['routes'] = routes

            if mac := config.macaddress:
                iface_ref['macaddress'] = mac

            if interface not in system_interfaces:
                # If the netdef ID doesn't correspond to any interface name in the system,
                # it might be associated with multiple system interfaces, such as when the 'match' key is used,
                # or the interface name is set in the passthrough section, such as when we create a connection via
                # Network Manager and the netdef ID is the UUID of the connetion.
                # In these cases, we need to look for all the system's interfaces
                # pointing to this netdef and add one netdef entry per device.
                found_some = False
                for key, value in system_interfaces.items():
                    if netdef_id := value.get('id'):
                        if netdef_id == interface:
                            found_some = True
                            interfaces[key] = iface[interface]

                # If we don't find any system interface associated with the netdef
                # that's because it's not matching any device. In this case, we add the
                # netdef ID to the list anyway.
                if not found_some:
                    interfaces.update(iface)
            else:
                interfaces.update(iface)

        return interfaces

    def _get_system_interfaces(self) -> dict:
        interfaces = {}

        for interface, config in self.system_state.get_data().items():
            if interface == 'netplan-global-state':
                continue

            device_type = config.get('type')
            interfaces[interface] = {'system_state': {'type': device_type}}

            if netdef_id := config.get('id'):
                interfaces[interface]['system_state']['id'] = netdef_id

            iface_ref = interfaces[interface]['system_state']

            if index := config.get('index'):
                iface_ref['index'] = index

            addresses = {}
            for addr in config.get('addresses', []):
                ip = list(addr.keys())[0]
                prefix = addr.get(ip).get('prefix')
                full_addr = f'{ip}/{prefix}'

                addresses[full_addr] = {'flags': addr.get(ip).get('flags', [])}
            if addresses:
                iface_ref['addresses'] = addresses

            if nameservers := config.get('dns_addresses'):
                iface_ref['nameservers_addresses'] = nameservers

            if search := config.get('dns_search'):
                iface_ref['nameservers_search'] = search

            if routes := config.get('routes'):
                iface_ref['routes'] = [self._system_route_to_netplan(route) for route in routes]

            if mac := config.get('macaddress'):
                iface_ref['macaddress'] = mac

        return interfaces

    def _system_route_to_netplan(self, system_route: dict) -> NetplanRoute:
        route = {}

        if family := system_route.get('family'):
            route['family'] = family
        if to := system_route.get('to'):
            route['to'] = to
        if via := system_route.get('via'):
            route['via'] = via
        if from_addr := system_route.get('from'):
            route['from_addr'] = from_addr
        if metric := system_route.get('metric'):
            route['metric'] = metric
        if scope := system_route.get('scope'):
            route['scope'] = scope
        if route_type := system_route.get('type'):
            route['type'] = route_type
        if protocol := system_route.get('protocol'):
            route['protocol'] = protocol
        if table := system_route.get('table'):
            route['table'] = self._default_route_tables_name_to_number(table)

        return NetplanRoute(**route)

    def _default_route_tables_name_to_number(self, name: str) -> int:
        value = 0
        # Mapped in /etc/iproute2/rt_tables
        if name == 'default':
            value = 253
        elif name == 'main':
            value = 254
        elif name == 'local':
            value = 255
        else:
            try:
                value = int(name)
            except ValueError:
                value = 0

        return value
