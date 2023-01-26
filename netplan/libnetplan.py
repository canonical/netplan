# Copyright (C) 2018-2020 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
# Author: Lukas 'slyon' Märdian <lukas.maerdian@canonical.com>
# Author: Simon Chopin <simon.chopin@canonical.com>
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

import re
import tempfile
import logging
import ctypes
import ctypes.util
from ctypes import c_char_p, c_void_p, c_int, c_uint, c_size_t, c_ssize_t
from typing import List, Union, IO


class LibNetplanException(Exception):
    pass


SCHEMA_ERROR_MESSAGE_REGEX = (
    r'(?P<file_path>.*):(?P<error_line>\d+):(?<error_col>\d+): (?P<message>.*)'
)

class LibNetplanSchemaValidationException(LibNetplanException):

    def __init__(self, message):
        schema_error = re.match(SCHEMA_ERROR_MSG_REGEX, message).groupdict()
        schema_error.groupdict()
        self.file_path = schema_error["file_path"]
        self.error_line = schema_error["error_line"]
        self.error_col = schema_error["error_col"]
        super().__init__(schema_error["message"])


class _GError(ctypes.Structure):
    _fields_ = [("domain", ctypes.c_uint32), ("code", c_int), ("message", c_char_p)]


class _netplan_state(ctypes.Structure):
    pass


class _netplan_parser(ctypes.Structure):
    pass


class _netplan_net_definition(ctypes.Structure):
    pass


lib = ctypes.CDLL(ctypes.util.find_library('netplan'))

_GErrorPP = ctypes.POINTER(ctypes.POINTER(_GError))
_NetplanParserP = ctypes.POINTER(_netplan_parser)
_NetplanStateP = ctypes.POINTER(_netplan_state)
_NetplanNetDefinitionP = ctypes.POINTER(_netplan_net_definition)

lib.netplan_get_id_from_nm_filename.restype = ctypes.c_char_p


def _string_realloc_call_no_error(function):
    size = 16
    while size < 1073741824:  # 1MB
        buffer = ctypes.create_string_buffer(size)
        code = function(buffer)
        if code == -2:
            size = size * 2
            continue

        if code < 0:  # pragma: nocover
            raise LibNetplanException("Unknown error: %d" % code)
        elif code == 0:
            return None  # pragma: nocover as it's hard to trigger for now
        else:
            return buffer.value.decode('utf-8')
    raise LibNetplanException('Aborting due to string buffer size > 1M')  # pragma: nocover


# Specialized exceptions based on err.contents.code or err.contents.message
GERROR_MESSAGE_FORMAT_EXCEPTION_MAP = {
    r'.*:\d+:\d+: Error in network definition':
        LibNetplanSchemaValidationException
}

def _checked_lib_call(fn, *args):
    err = ctypes.POINTER(_GError)()
    ret = bool(fn(*args, ctypes.byref(err)))
    if not ret:
        exception_cls = LibNetplanException
        for error_format, error_type in GERROR_MESSAGE_FORMAT_EXCEPTION_MAP:
            if re.match(error_format, err.contents.message.decode('utf-8')):
                exception_cls = error_type
        # Specialize error type if possible
        raise exception_cls(err.contents.message.decode('utf-8'))


class Parser:
    _abi_loaded = False

    @classmethod
    def _load_abi(cls):
        if cls._abi_loaded:
            return

        lib.netplan_parser_new.restype = _NetplanParserP
        lib.netplan_parser_clear.argtypes = [ctypes.POINTER(_NetplanParserP)]

        lib.netplan_parser_load_yaml.argtypes = [_NetplanParserP, c_char_p, _GErrorPP]
        lib.netplan_parser_load_yaml.restype = c_int

        lib.netplan_parser_load_yaml_from_fd.argtypes = [_NetplanParserP, c_int, _GErrorPP]
        lib.netplan_parser_load_yaml_from_fd.restype = c_int

        lib.netplan_parser_load_nullable_fields.argtypes = [_NetplanParserP, c_int, _GErrorPP]
        lib.netplan_parser_load_nullable_fields.restype = c_int

        lib.netplan_parser_load_nullable_overrides.argtypes =\
            [_NetplanParserP, c_int, c_char_p, _GErrorPP]
        lib.netplan_parser_load_nullable_overrides.restype = c_int

        cls._abi_loaded = True

    def __init__(self):
        self._load_abi()
        self._ptr = lib.netplan_parser_new()

    def __del__(self):
        lib.netplan_parser_clear(ctypes.byref(self._ptr))

    def load_yaml(self, input_file: Union[str, IO]):
        if isinstance(input_file, str):
            _checked_lib_call(lib.netplan_parser_load_yaml, self._ptr, input_file.encode('utf-8'))
        else:
            _checked_lib_call(lib.netplan_parser_load_yaml_from_fd, self._ptr, input_file.fileno())

    def load_yaml_hierarchy(self, rootdir):
        _checked_lib_call(lib.netplan_parser_load_yaml_hierarchy, self._ptr, rootdir.encode('utf-8'))

    def load_nullable_fields(self, input_file: IO):
        _checked_lib_call(lib.netplan_parser_load_nullable_fields, self._ptr, input_file.fileno())

    def load_nullable_overrides(self, input_file: IO, constraint: str):
        _checked_lib_call(lib.netplan_parser_load_nullable_overrides,
                          self._ptr, input_file.fileno(), constraint.encode('utf-8'))


class State:
    _abi_loaded = False

    @classmethod
    def _load_abi(cls):
        if cls._abi_loaded:
            return

        lib.netplan_state_new.restype = _NetplanStateP
        lib.netplan_state_clear.argtypes = [ctypes.POINTER(_NetplanStateP)]

        lib.netplan_state_import_parser_results.argtypes = [_NetplanStateP, _NetplanParserP, _GErrorPP]
        lib.netplan_state_import_parser_results.restype = c_int

        lib.netplan_state_get_netdefs_size.argtypes = [_NetplanStateP]
        lib.netplan_state_get_netdefs_size.restype = c_int

        lib.netplan_state_get_netdef.argtypes = [_NetplanStateP, c_char_p]
        lib.netplan_state_get_netdef.restype = _NetplanNetDefinitionP

        lib.netplan_state_write_yaml_file.argtypes = [_NetplanStateP, c_char_p, c_char_p, _GErrorPP]
        lib.netplan_state_write_yaml_file.restype = c_int

        lib.netplan_state_update_yaml_hierarchy.argtypes = [_NetplanStateP, c_char_p, c_char_p, _GErrorPP]
        lib.netplan_state_update_yaml_hierarchy.restype = c_int

        lib.netplan_state_dump_yaml.argtypes = [_NetplanStateP, c_int, _GErrorPP]
        lib.netplan_state_dump_yaml.restype = c_int

        lib.netplan_netdef_get_embedded_switch_mode.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_embedded_switch_mode.restype = c_char_p

        lib.netplan_netdef_get_delay_virtual_functions_rebind.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_delay_virtual_functions_rebind.restype = c_int

        lib.netplan_state_get_backend.argtypes = [_NetplanStateP]
        lib.netplan_state_get_backend.restype = c_int

        cls._abi_loaded = True

    def __init__(self):
        self._load_abi()
        self._ptr = lib.netplan_state_new()

    def __del__(self):
        lib.netplan_state_clear(ctypes.byref(self._ptr))

    def import_parser_results(self, parser):
        _checked_lib_call(lib.netplan_state_import_parser_results, self._ptr, parser._ptr)

    def write_yaml_file(self, filename, rootdir):
        name = filename.encode('utf-8') if filename else None
        root = rootdir.encode('utf-8') if rootdir else None
        _checked_lib_call(lib.netplan_state_write_yaml_file, self._ptr, name, root)

    def update_yaml_hierarchy(self, default_filename, rootdir):
        name = default_filename.encode('utf-8')
        root = rootdir.encode('utf-8') if rootdir else None
        _checked_lib_call(lib.netplan_state_update_yaml_hierarchy, self._ptr, name, root)

    def dump_yaml(self, output_file):
        fd = output_file.fileno()
        _checked_lib_call(lib.netplan_state_dump_yaml, self._ptr, fd)

    def __len__(self):
        return lib.netplan_state_get_netdefs_size(self._ptr)

    def __getitem__(self, def_id):
        ptr = lib.netplan_state_get_netdef(self._ptr, def_id.encode('utf-8'))
        if not ptr:
            raise IndexError()
        return NetDefinition(self, ptr)

    @property
    def all_defs(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, None))

    @property
    def ethernets(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "ethernets"))

    @property
    def modems(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "modems"))

    @property
    def wifis(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "wifis"))

    @property
    def vlans(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "vlans"))

    @property
    def bridges(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "bridges"))

    @property
    def bonds(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "bonds"))

    @property
    def tunnels(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "tunnels"))

    @property
    def vrfs(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "vrfs"))

    @property
    def ovs_ports(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "_ovs-ports"))

    @property
    def nm_devices(self):
        return dict((nd.id, nd) for nd in _NetdefIterator(self, "nm-devices"))

    @property
    def backend(self):
        return lib.netplan_backend_name(lib.netplan_state_get_backend(self._ptr)).decode('utf-8')

    def dump_to_logs(self):
        # Convoluted way to dump the parsed config to the logs...
        with tempfile.TemporaryFile() as tmp:
            self.dump_yaml(output_file=tmp)
            logging.debug("Merged config:\n{}".format(tmp.read()))


class NetDefinition:
    _abi_loaded = False

    @classmethod
    def _load_abi(cls):
        if cls._abi_loaded:
            return

        lib.netplan_netdef_has_match.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_has_match.restype = c_int

        lib.netplan_netdef_get_id.argtypes = [_NetplanNetDefinitionP, c_char_p, c_size_t]
        lib.netplan_netdef_get_id.restype = c_ssize_t

        lib.netplan_netdef_get_filepath.argtypes = [_NetplanNetDefinitionP, c_char_p, c_size_t]
        lib.netplan_netdef_get_filepath.restype = c_ssize_t

        lib.netplan_netdef_get_backend.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_backend.restype = c_int

        lib.netplan_netdef_get_type.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_type.restype = c_int

        lib.netplan_netdef_get_set_name.argtypes = [_NetplanNetDefinitionP, c_char_p, c_size_t]
        lib.netplan_netdef_get_set_name.restype = c_ssize_t

        lib._netplan_netdef_get_critical.argtypes = [_NetplanNetDefinitionP]
        lib._netplan_netdef_get_critical.restype = c_int

        lib.netplan_netdef_get_sriov_link.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_sriov_link.restype = _NetplanNetDefinitionP

        lib.netplan_netdef_get_vlan_link.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_vlan_link.restype = _NetplanNetDefinitionP

        lib.netplan_netdef_get_bridge_link.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_bridge_link.restype = _NetplanNetDefinitionP

        lib.netplan_netdef_get_bond_link.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_bond_link.restype = _NetplanNetDefinitionP

        lib.netplan_netdef_get_peer_link.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_peer_link.restype = _NetplanNetDefinitionP

        lib._netplan_netdef_get_vlan_id.argtypes = [_NetplanNetDefinitionP]
        lib._netplan_netdef_get_vlan_id.restype = c_uint

        lib._netplan_netdef_get_sriov_vlan_filter.argtypes = [_NetplanNetDefinitionP]
        lib._netplan_netdef_get_sriov_vlan_filter.restype = c_int

        lib.netplan_netdef_match_interface.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_match_interface.restype = c_int

        lib.netplan_backend_name.argtypes = [c_int]
        lib.netplan_backend_name.restype = c_char_p

        lib.netplan_def_type_name.argtypes = [c_int]
        lib.netplan_def_type_name.restype = c_char_p

        lib._netplan_state_get_vf_count_for_def.argtypes = [_NetplanStateP, _NetplanNetDefinitionP, _GErrorPP]
        lib._netplan_state_get_vf_count_for_def.restype = c_int

        lib._netplan_netdef_is_trivial_compound_itf.argtypes = [_NetplanNetDefinitionP]
        lib._netplan_netdef_is_trivial_compound_itf.restype = c_int

        cls._abi_loaded = True

    def __eq__(self, other):
        if not hasattr(other, '_ptr'):
            return False
        return ctypes.addressof(self._ptr.contents) == ctypes.addressof(other._ptr.contents)

    def __init__(self, np_state, ptr):
        self._load_abi()
        self._ptr = ptr
        # We hold on to this to avoid the underlying pointer being invalidated by
        # the GC invoking netplan_state_free
        self._parent = np_state

    @property
    def has_match(self):
        return bool(lib.netplan_netdef_has_match(self._ptr))

    @property
    def set_name(self):
        return _string_realloc_call_no_error(lambda b: lib.netplan_netdef_get_set_name(self._ptr, b, len(b)))

    @property
    def critical(self):
        return bool(lib._netplan_netdef_get_critical(self._ptr))

    @property
    def sriov_link(self):
        link_ptr = lib.netplan_netdef_get_sriov_link(self._ptr)
        if link_ptr:
            return NetDefinition(self._parent, link_ptr)
        return None

    @property
    def vlan_link(self):
        link_ptr = lib.netplan_netdef_get_vlan_link(self._ptr)
        if link_ptr:
            return NetDefinition(self._parent, link_ptr)
        return None

    @property
    def bridge_link(self):
        link_ptr = lib.netplan_netdef_get_bridge_link(self._ptr)
        if link_ptr:
            return NetDefinition(self._parent, link_ptr)
        return None

    @property
    def bond_link(self):
        link_ptr = lib.netplan_netdef_get_bond_link(self._ptr)
        if link_ptr:
            return NetDefinition(self._parent, link_ptr)
        return None

    @property
    def peer_link(self):
        link_ptr = lib.netplan_netdef_get_peer_link(self._ptr)
        if link_ptr:
            return NetDefinition(self._parent, link_ptr)
        return None  # pragma: nocover (ovs ports are always defined in pairs)

    @property
    def vlan_id(self):
        vlan_id = lib._netplan_netdef_get_vlan_id(self._ptr)
        # No easy way to get UINT_MAX besides this...
        if vlan_id == c_uint(-1).value:
            return None
        return vlan_id

    @property
    def has_sriov_vlan_filter(self):
        return bool(lib._netplan_netdef_get_sriov_vlan_filter(self._ptr))

    @property
    def backend(self):
        return lib.netplan_backend_name(lib.netplan_netdef_get_backend(self._ptr)).decode('utf-8')

    @property
    def type(self):
        return lib.netplan_def_type_name(lib.netplan_netdef_get_type(self._ptr)).decode('utf-8')

    @property
    def id(self):
        return _string_realloc_call_no_error(lambda b: lib.netplan_netdef_get_id(self._ptr, b, len(b)))

    @property
    def filepath(self):
        return _string_realloc_call_no_error(lambda b: lib.netplan_netdef_get_filepath(self._ptr, b, len(b)))

    @property
    def embedded_switch_mode(self):
        mode = lib.netplan_netdef_get_embedded_switch_mode(self._ptr)
        return mode and mode.decode('utf-8')

    @property
    def delay_virtual_functions_rebind(self):
        return bool(lib.netplan_netdef_get_delay_virtual_functions_rebind(self._ptr))

    def match_interface(self, itf_name=None, itf_driver=None, itf_mac=None):
        return bool(lib.netplan_netdef_match_interface(
            self._ptr,
            itf_name and itf_name.encode('utf-8'),
            itf_mac and itf_mac.encode('utf-8'),
            itf_driver and itf_driver.encode('utf-8')))

    @property
    def vf_count(self):
        err = ctypes.POINTER(_GError)()
        count = lib._netplan_state_get_vf_count_for_def(self._parent._ptr, self._ptr, ctypes.byref(err))
        if count < 0:
            raise LibNetplanException(err.contents.message.decode('utf-8'))
        return count

    @property
    def is_trivial_compound_itf(self):
        '''
        Returns True if the interface is a compound interface (bond or bridge),
        and its configuration is trivial, without any variation from the defaults.
        '''
        return bool(lib._netplan_netdef_is_trivial_compound_itf(self._ptr))


class _NetdefIterator:
    _abi_loaded = False

    @classmethod
    def _load_abi(cls):
        if cls._abi_loaded:
            return

        if not hasattr(lib, '_netplan_iter_defs_per_devtype_init'):  # pragma: nocover (hard to unit-test against the WRONG lib)
            raise LibNetplanException('''
                The current version of libnetplan does not allow iterating by devtype.
                Please ensure that both the netplan CLI package and its library are up to date.
            ''')
        lib._netplan_state_new_netdef_pertype_iter.argtypes = [_NetplanStateP, c_char_p]
        lib._netplan_state_new_netdef_pertype_iter.restype = c_void_p

        lib._netplan_iter_defs_per_devtype_next.argtypes = [c_void_p]
        lib._netplan_iter_defs_per_devtype_next.restype = _NetplanNetDefinitionP

        lib._netplan_iter_defs_per_devtype_free.argtypes = [c_void_p]
        lib._netplan_iter_defs_per_devtype_free.restype = None

        lib._netplan_netdef_id.argtypes = [c_void_p]
        lib._netplan_netdef_id.restype = c_char_p

        cls._abi_loaded = True

    def __init__(self, np_state, devtype):
        self._load_abi()
        # To keep things valid, keep a reference to the parent state
        self.np_state = np_state
        self.iterator = lib._netplan_state_new_netdef_pertype_iter(np_state._ptr, devtype and devtype.encode('utf-8'))

    def __del__(self):
        lib._netplan_iter_defs_per_devtype_free(self.iterator)

    def __iter__(self):
        return self

    def __next__(self):
        next_value = lib._netplan_iter_defs_per_devtype_next(self.iterator)
        if not next_value:
            raise StopIteration
        return NetDefinition(self.np_state, next_value)


lib.netplan_util_create_yaml_patch.argtypes = [c_char_p, c_char_p, c_int, _GErrorPP]
lib.netplan_util_create_yaml_patch.restype = c_int

lib.netplan_util_dump_yaml_subtree.argtypes = [c_char_p, c_int, c_int, _GErrorPP]
lib.netplan_util_dump_yaml_subtree.restype = c_int


def create_yaml_patch(patch_object_path: List[str], patch_payload: str, patch_output):
    _checked_lib_call(lib.netplan_util_create_yaml_patch,
                      '\t'.join(patch_object_path).encode('utf-8'),
                      patch_payload.encode('utf-8'),
                      patch_output.fileno())


def dump_yaml_subtree(prefix, input_file, output_file):
    _checked_lib_call(lib.netplan_util_dump_yaml_subtree,
                      prefix.encode('utf-8'),
                      input_file.fileno(),
                      output_file.fileno())
