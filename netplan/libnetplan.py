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

import ctypes
import ctypes.util
from ctypes import c_char_p, c_void_p, c_int


class LibNetplanException(Exception):
    pass


class _GError(ctypes.Structure):
    _fields_ = [("domain", ctypes.c_uint32), ("code", c_int), ("message", c_char_p)]


class _netplan_state(ctypes.Structure):
    pass


class _netplan_parser(ctypes.Structure):
    pass


class _netplan_net_definition(ctypes.Structure):
    pass


lib = ctypes.CDLL(ctypes.util.find_library('netplan'))
lib.netplan_parse_yaml.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.POINTER(_GError))]
lib.netplan_get_filename_by_id.restype = ctypes.c_char_p
lib.process_yaml_hierarchy.argtypes = [ctypes.c_char_p]
lib.process_yaml_hierarchy.restype = ctypes.c_int

_GErrorPP = ctypes.POINTER(ctypes.POINTER(_GError))
_NetplanParserP = ctypes.POINTER(_netplan_parser)
_NetplanStateP = ctypes.POINTER(_netplan_state)
_NetplanNetDefinitionP = ctypes.POINTER(_netplan_net_definition)

lib.netplan_get_id_from_nm_filename.restype = ctypes.c_char_p


def netplan_parse(path):
    # Clear old NetplanNetDefinitions from libnetplan memory
    lib.netplan_clear_netdefs()
    err = ctypes.POINTER(_GError)()
    ret = bool(lib.netplan_parse_yaml(path.encode(), ctypes.byref(err)))
    if not ret:
        raise Exception(err.contents.message.decode('utf-8'))
    lib.netplan_finish_parse(ctypes.byref(err))
    if err:
        raise Exception(err.contents.message.decode('utf-8'))
    return True


def _checked_lib_call(fn, *args):
    err = ctypes.POINTER(_GError)()
    ret = bool(fn(*args, ctypes.byref(err)))
    if not ret:
        raise LibNetplanException(err.contents.message.decode('utf-8'))


def netplan_get_filename_by_id(netdef_id, rootdir):
    res = lib.netplan_get_filename_by_id(netdef_id.encode(), rootdir.encode())
    return res.decode('utf-8') if res else None


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

        cls._abi_loaded = True

    def __init__(self):
        self._load_abi()
        self._ptr = lib.netplan_parser_new()

    def __del__(self):
        lib.netplan_parser_clear(ctypes.byref(self._ptr))

    def load_yaml(self, filename):
        _checked_lib_call(lib.netplan_parser_load_yaml, self._ptr, filename.encode('utf-8'))

    def load_yaml_hierarchy(self, rootdir):
        _checked_lib_call(lib.netplan_parser_load_yaml_hierarchy, self._ptr, rootdir.encode('utf-8'))


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

        lib.netplan_state_dump_yaml.argtypes = [_NetplanStateP, c_int, _GErrorPP]
        lib.netplan_state_dump_yaml.restype = c_int

        lib.netplan_netdef_get_embedded_switch_mode.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_embedded_switch_mode.restype = c_char_p

        lib.netplan_netdef_get_delay_virtual_functions_rebind.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_delay_virtual_functions_rebind.restype = c_int

        cls._abi_loaded = True

    def __init__(self):
        self._load_abi()
        self._ptr = lib.netplan_state_new()

    def __del__(self):
        lib.netplan_state_clear(ctypes.byref(self._ptr))

    def import_parser_results(self, parser):
        _checked_lib_call(lib.netplan_state_import_parser_results, self._ptr, parser._ptr)

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


class NetDefinition:
    _abi_loaded = False

    @classmethod
    def _load_abi(cls):
        if cls._abi_loaded:
            return

        lib.netplan_netdef_get_id.argtypes = [_NetplanNetDefinitionP]
        lib.netplan_netdef_get_id.restype = c_char_p

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
    def id(self):
        return lib.netplan_netdef_get_id(self._ptr).decode('utf-8')

    @property
    def embedded_switch_mode(self):
        mode = lib.netplan_netdef_get_embedded_switch_mode(self._ptr)
        return mode and mode.decode('utf-8')

    @property
    def delay_virtual_functions_rebind(self):
        return bool(lib.netplan_netdef_get_delay_virtual_functions_rebind(self._ptr))


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


class __GlobalState(State):
    def __init__(self):
        self._ptr = ctypes.cast(lib.global_state, _NetplanStateP)

    def __del__(self):
        pass


def netplan_get_ids_for_devtype(devtype, rootdir):
    err = ctypes.POINTER(_GError)()
    lib.netplan_clear_netdefs()
    lib.process_yaml_hierarchy(rootdir.encode('utf-8'))
    lib.netplan_finish_parse(ctypes.byref(err))
    if err:  # pragma: nocover (this is a "break in case of emergency" thing)
        raise Exception(err.contents.message.decode('utf-8'))
    nds = list(_NetdefIterator(__GlobalState(), devtype))
    return [nd.id for nd in nds]


lib.netplan_util_dump_yaml_subtree.argtypes = [c_char_p, c_int, c_int, _GErrorPP]
lib.netplan_util_dump_yaml_subtree.restype = c_int


def dump_yaml_subtree(prefix, input_file, output_file):
    _checked_lib_call(lib.netplan_util_dump_yaml_subtree,
                      prefix.encode('utf-8'),
                      input_file.fileno(),
                      output_file.fileno())
