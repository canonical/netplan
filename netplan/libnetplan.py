# Copyright (C) 2018-2020 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
# Author: Lukas 'slyon' Märdian <lukas.maerdian@canonical.com>
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


class LibNetplanException(Exception):
    pass


class _GError(ctypes.Structure):
    _fields_ = [("domain", ctypes.c_uint32), ("code", ctypes.c_int), ("message", ctypes.c_char_p)]


lib = ctypes.CDLL(ctypes.util.find_library('netplan'))
lib.netplan_parse_yaml.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.POINTER(_GError))]
lib.netplan_get_filename_by_id.restype = ctypes.c_char_p
lib.process_yaml_hierarchy.argtypes = [ctypes.c_char_p]
lib.process_yaml_hierarchy.restype = ctypes.c_int

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


def netplan_get_filename_by_id(netdef_id, rootdir):
    res = lib.netplan_get_filename_by_id(netdef_id.encode(), rootdir.encode())
    return res.decode('utf-8') if res else None


class _NetdefIdIterator:
    _abi_checked = False

    @classmethod
    def c_abi_sanity_check(cls):
        if cls._abi_checked:
            return

        if not hasattr(lib, '_netplan_iter_defs_per_devtype_init'):  # pragma: nocover (hard to unit-test against the WRONG lib)
            raise LibNetplanException('''
                The current version of libnetplan does not allow iterating by devtype.
                Please ensure that both the netplan CLI package and its library are up to date.
            ''')
        lib._netplan_iter_defs_per_devtype_init.argtypes = [ctypes.c_char_p]
        lib._netplan_iter_defs_per_devtype_init.restype = ctypes.c_void_p

        lib._netplan_iter_defs_per_devtype_next.argtypes = [ctypes.c_void_p]
        lib._netplan_iter_defs_per_devtype_next.restype = ctypes.c_void_p

        lib._netplan_iter_defs_per_devtype_free.argtypes = [ctypes.c_void_p]
        lib._netplan_iter_defs_per_devtype_free.restype = None

        lib._netplan_netdef_id.argtypes = [ctypes.c_void_p]
        lib._netplan_netdef_id.restype = ctypes.c_char_p

        cls._abi_checked = True

    def __init__(self, devtype):
        self.c_abi_sanity_check()
        self.iterator = lib._netplan_iter_defs_per_devtype_init(devtype.encode('utf-8'))

    def __del__(self):
        lib._netplan_iter_defs_per_devtype_free(self.iterator)

    def __iter__(self):
        return self

    def __next__(self):
        next_value = lib._netplan_iter_defs_per_devtype_next(self.iterator)
        if next_value is None:
            raise StopIteration
        return next_value


def netplan_get_ids_for_devtype(devtype, rootdir):
    err = ctypes.POINTER(_GError)()
    lib.netplan_clear_netdefs()
    lib.process_yaml_hierarchy(rootdir.encode('utf-8'))
    lib.netplan_finish_parse(ctypes.byref(err))
    if err:  # pragma: nocover (this is a "break in case of emergency" thing)
        raise Exception(err.contents.message.decode('utf-8'))
    nds = list(_NetdefIdIterator(devtype))
    return [lib._netplan_netdef_id(nd).decode('utf-8') for nd in nds]
