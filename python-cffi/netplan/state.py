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

# from enum import IntEnum
from io import StringIO
import os
from typing import IO

from ._netplan_cffi import ffi, lib
from .netdef import NetDefinition, NetDefinitionIterator
from .parser import Parser
from ._utils import _checked_lib_call


# class NETPLAN_STORAGE(IntEnum):
#     ETC = 0
#     RUN = 1
#     LIB = 2


class State():
    def __init__(self):
        self._ptr = lib.netplan_state_new()

    def __del__(self):
        ref = ffi.new('NetplanState **', self._ptr)
        lib.netplan_state_clear(ref)

    def __getitem__(self, netdef_id: str):
        ptr = lib.netplan_state_get_netdef(self._ptr, netdef_id.encode('utf-8'))
        if not ptr:
            raise IndexError()
        return NetDefinition(self, ptr)

    def __len__(self):
        return lib.netplan_state_get_netdefs_size(self._ptr)

    def import_parser_results(self, parser: Parser):
        _checked_lib_call(lib.netplan_state_import_parser_results, self._ptr, parser._ptr)

    # def write_yaml(filter: str, default_filename: str = None,
    #                storage: NETPLAN_STORAGE = NETPLAN_STORAGE.ETC, rootdir str = None):
    #     # TODO: https://bugs.launchpad.net/netplan/+bug/2003727
    #     raise NotImplementedError

    def _write_yaml_file(self, filename: str = None, rootdir: str = None):
        name = filename.encode('utf-8') if filename else ffi.NULL
        root = rootdir.encode('utf-8') if rootdir else ffi.NULL
        _checked_lib_call(lib.netplan_state_write_yaml_file, self._ptr, name, root)

    def _update_yaml_hierarchy(self, default_filename: str, rootdir: str = None):
        name = default_filename.encode('utf-8')
        root = rootdir.encode('utf-8') if rootdir else ffi.NULL
        _checked_lib_call(lib.netplan_state_update_yaml_hierarchy, self._ptr, name, root)

    def _dump_yaml(self, output_file: IO):
        if isinstance(output_file, StringIO):
            fd = os.memfd_create(name='netplan_temp_file')
            _checked_lib_call(lib.netplan_state_dump_yaml, self._ptr, fd)
            size = os.lseek(fd, 0, os.SEEK_CUR)
            os.lseek(fd, 0, os.SEEK_SET)
            data = os.read(fd, size)
            os.close(fd)
            output_file.write(data.decode('utf-8'))
        else:
            fd = output_file.fileno()
            _checked_lib_call(lib.netplan_state_dump_yaml, self._ptr, fd)

    @property
    def backend(self) -> str:
        return ffi.string(lib.netplan_backend_name(lib.netplan_state_get_backend(self._ptr))).decode('utf-8')

    @property
    def netdefs(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, None))

    @property
    def ethernets(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "ethernets"))

    @property
    def modems(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "modems"))

    @property
    def wifis(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "wifis"))

    @property
    def vlans(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "vlans"))

    @property
    def bridges(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "bridges"))

    @property
    def bonds(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "bonds"))

    @property
    def dummy_devices(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "dummy-devices"))

    @property
    def tunnels(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "tunnels"))

    @property
    def virtual_ethernets(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "virtual-ethernets"))

    @property
    def vrfs(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "vrfs"))

    @property
    def ovs_ports(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "_ovs-ports"))

    @property
    def nm_devices(self) -> NetDefinitionIterator:
        return dict((nd.id, nd) for nd in NetDefinitionIterator(self, "nm-devices"))
