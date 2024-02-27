# Copyright (C) 2023 Canonical, Ltd.
# Author: Lukas Märdian <slyon@ubuntu.com>
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

from dataclasses import dataclass

from ._netplan_cffi import ffi, lib
from ._utils import _string_realloc_call_no_error, NetplanException


class NetDefinition():
    def __init__(self, np_state, ptr):
        self._ptr = ptr
        # We hold on to this to avoid the underlying pointer being invalidated by
        # the GC invoking netplan_state_free
        self._parent = np_state

    def __eq__(self, other: 'NetDefinition') -> bool:
        if not hasattr(other, '_ptr'):
            return False
        return self._ptr == other._ptr

    def _match_interface(self, iface_name: str = None, iface_driver: str = None, iface_mac: str = None) -> bool:
        return bool(lib.netplan_netdef_match_interface(
            self._ptr,
            iface_name.encode('utf-8') if iface_name else ffi.NULL,
            iface_mac.encode('utf-8') if iface_mac else ffi.NULL,
            iface_driver.encode('utf-8') if iface_driver else ffi.NULL))

    @property
    def addresses(self) -> '_NetdefAddressIterator':
        return _NetdefAddressIterator(self._ptr)

    @property
    def dhcp4(self) -> bool:
        return bool(lib.netplan_netdef_get_dhcp4(self._ptr))

    @property
    def dhcp6(self) -> bool:
        return bool(lib.netplan_netdef_get_dhcp6(self._ptr))

    @property
    def link_local(self) -> list:
        linklocal = []
        if bool(lib.netplan_netdef_get_link_local_ipv4(self._ptr)):
            linklocal.append('ipv4')
        if bool(lib.netplan_netdef_get_link_local_ipv6(self._ptr)):
            linklocal.append('ipv6')
        return linklocal

    @property
    def nameserver_addresses(self) -> '_NetdefNameserverIterator':
        return _NetdefNameserverIterator(self._ptr)

    @property
    def nameserver_search(self) -> '_NetdefSearchDomainIterator':
        return _NetdefSearchDomainIterator(self._ptr)

    @property
    def routes(self) -> '_NetdefRouteIterator':
        return _NetdefRouteIterator(self._ptr)

    @property
    def macaddress(self) -> str:
        return _string_realloc_call_no_error(lambda b: lib.netplan_netdef_get_macaddress(self._ptr, b, len(b)))

    @property
    def _has_match(self) -> bool:
        return bool(lib.netplan_netdef_has_match(self._ptr))

    @property
    def set_name(self) -> str:
        return _string_realloc_call_no_error(lambda b: lib.netplan_netdef_get_set_name(self._ptr, b, len(b)))

    @property
    def critical(self) -> bool:
        return bool(lib._netplan_netdef_get_critical(self._ptr))

    @property
    def links(self) -> dict:
        d = dict()
        if sriov_link := lib.netplan_netdef_get_sriov_link(self._ptr):
            d['sriov'] = NetDefinition(self._parent, sriov_link)

        if vlan_link := lib.netplan_netdef_get_vlan_link(self._ptr):
            d['vlan'] = NetDefinition(self._parent, vlan_link)

        if bridge_link := lib.netplan_netdef_get_bridge_link(self._ptr):
            d['bridge'] = NetDefinition(self._parent, bridge_link)

        if bond_link := lib.netplan_netdef_get_bond_link(self._ptr):
            d['bond'] = NetDefinition(self._parent, bond_link)

        if vrf_link := lib.netplan_netdef_get_vrf_link(self._ptr):
            d['vrf'] = NetDefinition(self._parent, vrf_link)

        # TODO: ovs vs veth? Should we use the same field?
        if peer_link := lib.netplan_netdef_get_peer_link(self._ptr):
            d['peer'] = NetDefinition(self._parent, peer_link)
        return d

    @property
    def _vlan_id(self) -> int:
        vlan_id = lib._netplan_netdef_get_vlan_id(self._ptr)
        if vlan_id == lib.UINT_MAX:
            return None
        return vlan_id

    @property
    def _has_sriov_vlan_filter(self) -> bool:
        return bool(lib._netplan_netdef_get_sriov_vlan_filter(self._ptr))

    @property
    def backend(self) -> str:
        return ffi.string(lib.netplan_backend_name(lib.netplan_netdef_get_backend(self._ptr))).decode('utf-8')

    @property
    def type(self) -> str:
        return ffi.string(lib.netplan_def_type_name(lib.netplan_netdef_get_type(self._ptr))).decode('utf-8')

    @property
    def id(self) -> str:
        return _string_realloc_call_no_error(lambda b: lib.netplan_netdef_get_id(self._ptr, b, len(b)))

    @property
    def filepath(self) -> str:
        return _string_realloc_call_no_error(lambda b: lib.netplan_netdef_get_filepath(self._ptr, b, len(b)))

    @property
    def _embedded_switch_mode(self) -> str:
        return _string_realloc_call_no_error(lambda b: lib._netplan_netdef_get_embedded_switch_mode(self._ptr, b, len(b)))

    @property
    def _delay_virtual_functions_rebind(self) -> bool:
        return bool(lib._netplan_netdef_get_delay_virtual_functions_rebind(self._ptr))

    @property
    def _vf_count(self) -> int:
        ref = ffi.new('NetplanError **')
        count = lib._netplan_state_get_vf_count_for_def(self._parent._ptr, self._ptr, ref)
        if count < 0:
            err = ref[0]
            msg = _string_realloc_call_no_error(lambda b: lib.netplan_error_message(err, b, len(b)))
            raise NetplanException(msg)
        return count

    @property
    def _bond_mode(self) -> str:
        return _string_realloc_call_no_error(lambda b: lib._netplan_netdef_get_bond_mode(self._ptr, b, len(b)))

    @property
    def _is_trivial_compound_itf(self) -> bool:
        '''
        Returns True if the interface is a compound interface (bond or bridge),
        and its configuration is trivial, without any variation from the defaults.
        '''
        return bool(lib._netplan_netdef_is_trivial_compound_itf(self._ptr))


class NetDefinitionIterator():
    def __init__(self, np_state, dev_type: str = None):
        # To keep things valid, keep a reference to the parent state
        self.np_state = np_state
        np_type = dev_type.encode('utf-8') if dev_type else ffi.NULL
        self.iterator = lib._netplan_state_new_netdef_pertype_iter(np_state._ptr, np_type)

    def __del__(self):
        lib._netplan_netdef_pertype_iter_free(self.iterator)

    def __iter__(self):
        return self

    def __next__(self):
        next_value = lib._netplan_netdef_pertype_iter_next(self.iterator)
        if not next_value:
            raise StopIteration
        return NetDefinition(self.np_state, next_value)


class NetplanAddress:
    def __init__(self, address: str, lifetime: str, label: str):
        self.address = address
        self.lifetime = lifetime
        self.label = label

    def __str__(self) -> str:
        return self.address


class _NetdefAddressIterator:
    def __init__(self, netdef: NetDefinition):
        self.netdef = netdef
        self.iterator = lib._netplan_netdef_new_address_iter(netdef)

    def __del__(self):
        lib._netplan_address_iter_free(self.iterator)

    def __iter__(self):
        return self

    def __next__(self):
        next_value = lib._netplan_address_iter_next(self.iterator)
        if not next_value:
            raise StopIteration
        content = next_value
        # XXX: Introduce getters for .address/.lifetime/.label, to avoid
        #      exposing the 'address_iter' struct in _netplan_cffi.so
        address = ffi.string(content.address).decode('utf-8') if content.address else None
        lifetime = ffi.string(content.lifetime).decode('utf-8') if content.lifetime else None
        label = ffi.string(content.label).decode('utf-8') if content.label else None
        return NetplanAddress(address, lifetime, label)


class _NetdefNameserverIterator:
    def __init__(self, netdef: NetDefinition):
        self.netdef = netdef
        self.iterator = lib._netplan_netdef_new_nameserver_iter(netdef)

    def __del__(self):
        lib._netplan_nameserver_iter_free(self.iterator)

    def __iter__(self):
        return self

    def __next__(self):
        next_value = lib._netplan_nameserver_iter_next(self.iterator)
        if not next_value:
            raise StopIteration
        return ffi.string(next_value).decode('utf-8')


class _NetdefSearchDomainIterator:
    def __init__(self, netdef):
        self.netdef = netdef
        self.iterator = lib._netplan_netdef_new_search_domain_iter(netdef)

    def __del__(self):
        lib._netplan_search_domain_iter_free(self.iterator)

    def __iter__(self):
        return self

    def __next__(self):
        next_value = lib._netplan_search_domain_iter_next(self.iterator)
        if not next_value:
            raise StopIteration
        return ffi.string(next_value).decode('utf-8')


@dataclass
class NetplanRoute:
    _METRIC_UNSPEC_ = lib.UINT_MAX
    _TABLE_UNSPEC_ = 0

    to: str = None
    via: str = None
    from_addr: str = None
    type: str = 'unicast'
    scope: str = 'global'
    protocol: str = None
    table: int = _TABLE_UNSPEC_
    family: int = -1
    metric: int = _METRIC_UNSPEC_
    mtubytes: int = 0
    congestion_window: int = 0
    advertised_receive_window: int = 0
    onlink: bool = False

    def __str__(self):
        route = ""
        if self.to:
            route = route + self.to
        if self.via:
            route = route + f' via {self.via}'
        if self.type:
            route = route + f' type {self.type}'
        if self.scope:
            route = route + f' scope {self.scope}'
        if self.from_addr:
            route = route + f' src {self.from_addr}'
        if self.metric < self._METRIC_UNSPEC_:
            route = route + f' metric {self.metric}'
        if self.table > self._TABLE_UNSPEC_:
            route = route + f' table {self.table}'
        return route.strip()

    def to_dict(self):
        route = {}
        if self.family >= 0:
            route['family'] = self.family
        if self.to:
            route['to'] = self.to
        if self.via:
            route['via'] = self.via
        if self.from_addr:
            route['from'] = self.from_addr
        if self.metric < self._METRIC_UNSPEC_:
            route['metric'] = self.metric
        if self.table > self._TABLE_UNSPEC_:
            route['table'] = self.table

        route['type'] = self.type

        return route

    def __hash__(self):
        return hash(
            (self.to, self.via,
             self.from_addr, self.table,
             self.family, self.metric,
             self.type, self.scope))

    def __eq__(self, route):
        return (
            self.to == route.to and
            self.via == route.via and
            self.from_addr == route.from_addr and
            self.table == route.table and
            self.family == route.family and
            self.metric == route.metric and
            self.type == route.type and
            self.scope == route.scope
        )


class _NetdefRouteIterator:
    def __init__(self, netdef):
        self.netdef = netdef
        self.iterator = lib._netplan_netdef_new_route_iter(netdef)

    def __del__(self):
        lib._netplan_route_iter_free(self.iterator)

    def __iter__(self):
        return self

    def __next__(self):
        next_value = lib._netplan_route_iter_next(self.iterator)
        if not next_value:
            raise StopIteration

        # The field 'from' happens to be a reserved keyword in Python
        from_addr = getattr(next_value, 'from')

        route = {
            'to': ffi.string(next_value.to).decode('utf-8') if next_value.to else None,
            'via': ffi.string(next_value.via).decode('utf-8') if next_value.via else None,
            'from_addr': ffi.string(from_addr).decode('utf-8') if from_addr else None,
            'type': ffi.string(next_value.type).decode('utf-8') if next_value.type else None,
            'scope': ffi.string(next_value.scope).decode('utf-8') if next_value.scope else None,
            'protocol': None,
            'table': next_value.table,
            'family': next_value.family,
            'metric': next_value.metric,
            'mtubytes': next_value.mtubytes,
            'congestion_window': next_value.congestion_window,
            'advertised_receive_window': next_value.advertised_receive_window,
            'onlink': next_value.onlink
        }

        return NetplanRoute(**route)
