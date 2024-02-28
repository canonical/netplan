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

from collections import defaultdict
import ipaddress
import json
from typing import AbstractSet

from netplan.netdef import NetplanRoute
from netplan_cli.cli.state import SystemConfigState, NetplanConfigState, DEVICE_TYPES
from netplan_cli.cli.utils import is_valid_macaddress, route_table_lookup


class DiffJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, NetplanRoute):
            return obj.to_dict()

        # Shouldn't be reached as the only non-serializable type we have at the moment is NetplanRoute
        return json.JSONEncoder.default(self, obj)  # pragma: nocover (only NetplanRoute requires the encoder)


class NetplanDiffState():
    '''
    DiffState is mainly responsible for getting both system's and Netplan's configuration
    state, compare them and provide a data-structure containing the differences it found.
    '''

    def __init__(self, system_state: SystemConfigState, netplan_state: NetplanConfigState):
        self.system_state = system_state
        self.netplan_state = netplan_state

        self.route_lookup_table_names = {}

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
            else:
                interfaces = {}

        report = self._create_new_report()

        self._analyze_missing_interfaces(report, interface)

        for interface, config in interfaces.items():
            netdef_id = config.get('system_state', {}).get('id')
            index = config.get('system_state', {}).get('index')
            iface = self._create_new_iface(netdef_id, interface, index)

            self._analyze_ip_addresses(config, iface)
            self._analyze_nameservers(config, iface)
            self._analyze_search_domains(config, iface)
            self._analyze_mac_addresses(config, iface)
            self._analyze_routes(config, iface)
            self._analyze_parent_links(config, iface)

            report['interfaces'].update(iface)

        # Sort the list of interfaces according to their indices.
        report['interfaces'] = dict(sorted(report['interfaces'].items(), key=lambda iface: iface[1].get('index')))
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
        link_local = config.get('netplan_state', {}).get('link_local', [])
        system_ips = set()
        for addr, addr_data in config.get('system_state', {}).get('addresses', {}).items():
            ip = ipaddress.ip_interface(addr)
            flags = addr_data.get('flags', [])

            # Select only static IPs
            if 'dhcp' not in flags and 'link' not in flags:
                system_ips.add(addr)

            # Handle the link local address
            # If it's present but the respective setting is not enabled in the netdef
            # it's considered a difference.
            if 'link' in flags and ip.is_link_local:
                if isinstance(ip.ip, ipaddress.IPv4Address) and 'ipv4' not in link_local:
                    system_ips.add(addr)
                if isinstance(ip.ip, ipaddress.IPv6Address) and 'ipv6' not in link_local:
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
                'missing_addresses': list(sorted(present_only_in_system)),
            })

        if present_only_in_netplan:
            iface[name]['system_state'].update({
                'missing_addresses': list(sorted(present_only_in_netplan)),
            })

    def _get_comparable_interfaces(self, interfaces: dict) -> dict:
        ''' In order to compare interfaces, they must exist in the system AND in Netplan.
            Here we filter out interfaces that don't have a system_state, a netplan_state
            or a netdef ID.

            There is a special case where the interface will have a system_state and a netdef_id
            but will be missing in Netplan. That will happen when the user removes the interface
            only from Netplan but doesn't run netplan apply.
        '''
        filtered = {}

        for interface, config in interfaces.items():
            if config.get('system_state') is None or config.get('netplan_state') is None:
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

    def _analyze_nameservers(self, config: dict, iface: dict) -> None:
        name = list(iface.keys())[0]

        # TODO: improve analysis of configuration received from DHCP

        netplan_nameservers = set(config.get('netplan_state', {}).get('nameservers_addresses', []))
        system_nameservers = set(config.get('system_state', {}).get('nameservers_addresses', []))

        # Filter out dynamically assigned DNS data
        # Here we implement some heuristics to try to filter out dynamic DNS configuration
        #
        # If the nameserver address is the same as a RA route we assume it's dynamic
        system_routes = config.get('system_state', {}).get('routes', [])
        ra_routes = [r.via for r in system_routes if r.protocol == 'ra' and r.via]
        system_nameservers = {ns for ns in system_nameservers if ns not in ra_routes}

        # If the netplan configuration has DHCP enabled and an empty list of nameservers
        # we assume it's dynamic.
        # Note: Some useful information can be found in /var/run/systemd/netif/leases/
        # but the lease files have a comment saying they shouldn't be parsed.
        # There is a feature request to expose more DHCP information via the DBus API
        # https://github.com/systemd/systemd/issues/27699
        if not netplan_nameservers:
            if config.get('netplan_state', {}).get('dhcp4'):
                system_nameservers = {ns for ns in system_nameservers
                                      if not isinstance(ipaddress.ip_address(ns), ipaddress.IPv4Address)}
            if config.get('netplan_state', {}).get('dhcp6'):
                system_nameservers = {ns for ns in system_nameservers
                                      if not isinstance(ipaddress.ip_address(ns), ipaddress.IPv6Address)}

        present_only_in_netplan = netplan_nameservers.difference(system_nameservers)
        present_only_in_system = system_nameservers.difference(netplan_nameservers)

        if present_only_in_system:
            iface[name]['netplan_state'].update({
                'missing_nameservers_addresses': list(present_only_in_system),
            })

        if present_only_in_netplan:
            iface[name]['system_state'].update({
                'missing_nameservers_addresses': list(present_only_in_netplan),
            })

    def _analyze_search_domains(self, config: dict, iface: dict) -> None:
        name = list(iface.keys())[0]
        netplan_search_domains = set(config.get('netplan_state', {}).get('nameservers_search', []))
        system_search_domains = set(config.get('system_state', {}).get('nameservers_search', []))

        # If the netplan configuration has DHCP enabled and an empty list of search domains
        # we assume it's dynamic
        if not netplan_search_domains:
            if config.get('netplan_state', {}).get('dhcp4') or config.get('netplan_state', {}).get('dhcp6'):
                system_search_domains = set()

        present_only_in_netplan = netplan_search_domains.difference(system_search_domains)
        present_only_in_system = system_search_domains.difference(netplan_search_domains)

        if present_only_in_system:
            iface[name]['netplan_state'].update({
                'missing_nameservers_search': list(present_only_in_system),
            })

        if present_only_in_netplan:
            iface[name]['system_state'].update({
                'missing_nameservers_search': list(present_only_in_netplan),
            })

    def _analyze_mac_addresses(self, config: dict, iface: dict) -> None:
        name = list(iface.keys())[0]
        system_macaddress = config.get('system_state', {}).get('macaddress')
        netplan_macaddress = config.get('netplan_state', {}).get('macaddress')

        # if the macaddress in netplan is an special option (such as 'random')
        # don't try to diff it against the system MAC address
        if netplan_macaddress and not is_valid_macaddress(netplan_macaddress):
            return

        if system_macaddress and netplan_macaddress:
            if system_macaddress != netplan_macaddress:
                iface[name]['system_state'].update({
                    'missing_macaddress': netplan_macaddress
                })
                iface[name]['netplan_state'].update({
                    'missing_macaddress': system_macaddress
                })

    def _analyze_routes(self, config: dict, iface: dict) -> None:
        name = list(iface.keys())[0]
        netplan_routes = set(config.get('netplan_state', {}).get('routes', []))
        system_routes = set(config.get('system_state', {}).get('routes', []))
        netplan_routes = self._normalize_routes(netplan_routes)

        # Filter out some routes that are expected to be added automatically
        system_addresses = [ip for ip in config.get('system_state', {}).get('addresses', {})]
        system_routes = self._filter_system_routes(system_routes, system_addresses, config)

        present_only_in_netplan = netplan_routes.difference(system_routes)
        present_only_in_system = system_routes.difference(netplan_routes)

        if present_only_in_system:
            iface[name]['netplan_state'].update({
                'missing_routes': [route for route in sorted(present_only_in_system, key=lambda r: r.to)],
            })

        if present_only_in_netplan:
            iface[name]['system_state'].update({
                'missing_routes': [route for route in sorted(present_only_in_netplan, key=lambda r: r.to)],
            })

    def _analyze_missing_interfaces(self, report: dict, interface: str) -> None:
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

        netplan_only = sorted(netplan_only)
        system_only = sorted(system_only)

        if interface:
            netplan_only = filter(lambda i: i == interface, netplan_only)
            system_only = filter(lambda i: i == interface, system_only)

        system_state = self.system_state.get_data()

        for iface in netplan_only:
            iface_type = self.netplan_state.netdefs.get(iface).type
            report['missing_interfaces_system'][iface] = {
                'type': DEVICE_TYPES.get(iface_type, 'other')
            }

        for iface in system_only:
            report['missing_interfaces_netplan'][iface] = {
                'type': system_state.get(iface).get('type', 'other'),
                'index': system_state.get(iface).get('index'),
            }

    def _analyze_parent_links(self, config: dict, iface: dict) -> None:
        '''
        Analyze if interfaces such as bonds, bridges and VRFs are correctly attached to their
        members and vice versa.
        '''
        name = list(iface.keys())[0]
        bond = [config.get('system_state', {}).get('bond'), config.get('netplan_state', {}).get('bond')]
        bridge = [config.get('system_state', {}).get('bridge'), config.get('netplan_state', {}).get('bridge')]
        vrf = [config.get('system_state', {}).get('vrf'), config.get('netplan_state', {}).get('vrf')]
        interfaces = [config.get('system_state', {}).get('interfaces', []), config.get('netplan_state', {}).get('interfaces', [])]

        if bond != [None, None] and bond[0] != bond[1]:
            if bond[0]:
                iface[name]['netplan_state']['missing_bond_link'] = bond[0]
            if bond[1]:
                iface[name]['system_state']['missing_bond_link'] = bond[1]

        if bridge != [None, None] and bridge[0] != bridge[1]:
            if bridge[0]:
                iface[name]['netplan_state']['missing_bridge_link'] = bridge[0]
            if bridge[1]:
                iface[name]['system_state']['missing_bridge_link'] = bridge[1]

        if vrf != [None, None] and vrf[0] != vrf[1]:
            if vrf[0]:
                iface[name]['netplan_state']['missing_vrf_link'] = vrf[0]
            if vrf[1]:
                iface[name]['system_state']['missing_vrf_link'] = vrf[1]

        if interfaces != [[], []]:
            system = set(interfaces[0])
            netplan = set(interfaces[1])

            if system != netplan:
                if missing_system := netplan - system:
                    iface[name]['system_state']['missing_interfaces'] = list(missing_system)

                if missing_netplan := system - netplan:
                    iface[name]['netplan_state']['missing_interfaces'] = list(missing_netplan)

    def _normalize_routes(self, routes: set) -> set:
        ''' Apply some transformations to Netplan routes so their representation
        will match the system's.
        '''
        new_routes_set = set()
        for route in routes:
            # If the table is unspecified we set it to main
            if route.table == NetplanRoute._TABLE_UNSPEC_:
                route.table = self._default_route_tables_name_to_number('main')

            # If the addresses are IPv6, compress them so it will match the system representation
            route.to = self._compress_ipv6_address(route.to)
            route.from_addr = self._compress_ipv6_address(route.from_addr)
            route.via = self._compress_ipv6_address(route.via)

            # If the route.to prefix is either /32 and /128 we remove it to match
            # the system representation:
            if route.to != 'default':
                ip_prefix = route.to.split('/')
                if ip_prefix[1] == '32' or ip_prefix[1] == '128':
                    route.to = ip_prefix[0]

            new_routes_set.add(route)

        return new_routes_set

    def _filter_system_routes(self, system_routes: AbstractSet[NetplanRoute], system_addresses: list[str], config: dict) -> set:
        '''
        Some routes found in the system are installed automatically/dynamically without
        being configured in Netplan.
        Here we implement some heuristics to remove these routes from the list we want
        to compare. We do that because these type of routes will probably never be found in the
        Netplan configuration so there is no point in comparing them against Netplan.
        '''

        local_networks = [str(ipaddress.ip_interface(ip).network) for ip in system_addresses]
        # filter out the local link network as we give special treatment to it
        local_networks = list(filter(lambda n: n != 'fe80::/64', local_networks))
        addresses = [str(ipaddress.ip_interface(ip).ip) for ip in system_addresses]
        link_local = config.get('netplan_state', {}).get('link_local', [])
        routes = set()
        for route in system_routes:
            # Filter out link routes (but not link local as we handle them differently)
            if route.scope == 'link' and route.to != 'default' and not ipaddress.ip_interface(route.to).is_link_local:
                continue

            # Filter out routes installed by DHCP or RA
            if route.protocol == 'dhcp' or route.protocol == 'ra':
                continue

            # Filter out Link Local routes
            # We only filter them out if the respective 'link-local' setting is present in the netdef
            if route.to != 'default':
                route_to = ipaddress.ip_interface(route.to)
                if route_to.is_link_local:
                    if route.family == 10 and 'ipv6' in link_local:
                        continue
                    if route.family == 2 and 'ipv4' in link_local:
                        continue

            # Filter out host scoped routes
            if (route.scope == 'host' and route.type == 'local' and
                    (route.to in addresses or ipaddress.ip_interface(route.to).is_loopback)):
                continue

            # Filter out the default IPv6 multicast route
            if route.family == 10 and route.type == 'multicast' and route.to == 'ff00::/8':
                continue

            # Filter IPv6 local routes
            if route.family == 10 and (route.to in local_networks or route.to in addresses):
                continue

            routes.add(route)
        return routes

    def _get_netplan_interfaces(self) -> dict:
        system_interfaces = self.system_state.get_data()
        interfaces = {}
        for interface, config in self.netplan_state.netdefs.items():

            iface = {}
            iface[interface] = {'netplan_state': {'id': interface}}
            iface_ref = iface[interface]['netplan_state']

            iface_ref['type'] = DEVICE_TYPES.get(config.type, 'other')

            iface_ref['dhcp4'] = config.dhcp4
            iface_ref['dhcp6'] = config.dhcp6

            iface_ref['link_local'] = config.link_local

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

            if bridge := config.links.get('bridge'):
                iface_ref['bridge'] = bridge.id

            if bond := config.links.get('bond'):
                iface_ref['bond'] = bond.id

            if vrf := config.links.get('vrf'):
                iface_ref['vrf'] = vrf.id

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

        self._netplan_state_find_parents(interfaces)
        return interfaces

    def _netplan_state_find_parents(self, interfaces: dict) -> None:
        ''' Associates interfaces with their parents '''
        parents = defaultdict(set)
        for interface, config in interfaces.items():
            if link := config['netplan_state'].get('bridge'):
                parents[link].add(interface)
            if link := config['netplan_state'].get('bond'):
                parents[link].add(interface)
            if link := config['netplan_state'].get('vrf'):
                parents[link].add(interface)

        for interface, members in parents.items():
            interfaces[interface]['netplan_state']['interfaces'] = list(members)

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

            if uplink_interfaces := config.get('interfaces'):
                iface_ref['interfaces'] = uplink_interfaces

            if bond := config.get('bond'):
                iface_ref['bond'] = bond

            if bridge := config.get('bridge'):
                iface_ref['bridge'] = bridge

            if vrf := config.get('vrf'):
                iface_ref['vrf'] = vrf

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
        if name.isdigit():
            return int(name)

        if not self.route_lookup_table_names:
            self.route_lookup_table_names = route_table_lookup()

        return self.route_lookup_table_names.get(name, 0)
