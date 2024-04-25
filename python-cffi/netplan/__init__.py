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

from io import StringIO
import json
import os
from typing import Union, List, IO

from ._netplan_cffi import lib
from .netdef import NetDefinition, NetDefinitionIterator
from .parser import Parser
from .state import State
from ._utils import _checked_lib_call
from ._utils import (NetplanException, NetplanBackendException,
                     NetplanEmitterException, NetplanFileException,
                     NetplanFormatException, NetplanParserException,
                     NetplanValidationException)


def _dump_yaml_subtree(prefix: List[str], input_file: IO, output_file: IO):
    if isinstance(input_file, StringIO):
        input_fd = os.memfd_create(name='netplan_temp_input_file')
        data = input_file.getvalue()
        os.write(input_fd, data.encode('utf-8'))
        os.lseek(input_fd, 0, os.SEEK_SET)
    else:
        input_fd = input_file.fileno()

    if isinstance(output_file, StringIO):
        output_fd = os.memfd_create(name='netplan_temp_output_file')
    else:
        output_fd = output_file.fileno()

    _checked_lib_call(lib.netplan_util_dump_yaml_subtree, '\t'.join(prefix).encode('utf-8'), input_fd, output_fd)

    if isinstance(input_file, StringIO):
        os.close(input_fd)

    if isinstance(output_file, StringIO):
        size = os.lseek(output_fd, 0, os.SEEK_CUR)
        os.lseek(output_fd, 0, os.SEEK_SET)
        data = os.read(output_fd, size)
        output_file.write(data.decode('utf-8'))
        os.close(output_fd)


def _create_yaml_patch(patch_object_path: List[str], patch_payload: Union[str, dict], patch_output: IO):
    if isinstance(patch_payload, dict):
        patch_payload = json.dumps(patch_payload)
    _checked_lib_call(lib.netplan_util_create_yaml_patch,
                      '\t'.join(patch_object_path).encode('utf-8'),
                      patch_payload.encode('utf-8'),
                      patch_output.fileno())


# Re-export submodules
__all__ = ['Parser', 'State', 'NetDefinition', 'NetDefinitionIterator',
           '_dump_yaml_subtree', '_create_yaml_patch',
           'NetplanException', 'NetplanBackendException', 'NetplanEmitterException',
           'NetplanFileException', 'NetplanFormatException', 'NetplanParserException',
           'NetplanValidationException']
