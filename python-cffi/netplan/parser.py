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

from typing import Union, IO

from ._netplan_cffi import ffi, lib
from ._utils import _checked_lib_call


class Parser():
    def __init__(self):
        self._ptr = lib.netplan_parser_new()

    def __del__(self):
        ref = ffi.new('NetplanParser **', self._ptr)
        lib.netplan_parser_clear(ref)

    def load_yaml(self, input_file: Union[str, IO]):
        if isinstance(input_file, str):
            return _checked_lib_call(lib.netplan_parser_load_yaml, self._ptr, input_file.encode('utf-8'))
        else:
            return _checked_lib_call(lib.netplan_parser_load_yaml_from_fd, self._ptr, input_file.fileno())

    def load_yaml_hierarchy(self, rootdir: str = None):
        root = rootdir.encode('utf-8') if rootdir else ffi.NULL
        return _checked_lib_call(lib.netplan_parser_load_yaml_hierarchy, self._ptr, root)

    def load_keyfile(self, input_file: str):  # TODO: load from File/fd (i.e. input_file: Union[str, IO])
        return _checked_lib_call(lib.netplan_parser_load_keyfile, self._ptr, input_file.encode('utf-8'))

    def load_nullable_fields(self, input_file: IO):
        return _checked_lib_call(lib.netplan_parser_load_nullable_fields, self._ptr, input_file.fileno())

    def _load_nullable_overrides(self, input_file: IO, constraint: str):
        return _checked_lib_call(lib.netplan_parser_load_nullable_overrides,
                                 self._ptr, input_file.fileno(), constraint.encode('utf-8'))
