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

from collections import defaultdict
from enum import IntEnum
import re

from ._netplan_cffi import ffi, lib


# Errors and error domains

# NOTE: if new errors or domains are added,
# include/types.h must be updated with the new entries
class NETPLAN_ERROR_DOMAINS(IntEnum):
    NETPLAN_PARSER_ERROR = 1
    NETPLAN_VALIDATION_ERROR = 2
    NETPLAN_FILE_ERROR = 3
    NETPLAN_BACKEND_ERROR = 4
    NETPLAN_EMITTER_ERROR = 5
    NETPLAN_FORMAT_ERROR = 6


class NETPLAN_PARSER_ERRORS(IntEnum):
    NETPLAN_ERROR_INVALID_YAML = 0
    NETPLAN_ERROR_INVALID_CONFIG = 1


class NETPLAN_VALIDATION_ERRORS(IntEnum):
    NETPLAN_ERROR_CONFIG_GENERIC = 0
    NETPLAN_ERROR_CONFIG_VALIDATION = 1


class NETPLAN_BACKEND_ERRORS(IntEnum):
    NETPLAN_ERROR_UNSUPPORTED = 0
    NETPLAN_ERROR_VALIDATION = 1


class NETPLAN_EMITTER_ERRORS(IntEnum):
    NETPLAN_ERROR_YAML_EMITTER = 0


class NETPLAN_FORMAT_ERRORS(IntEnum):
    NETPLAN_ERROR_FORMAT_INVALID_YAML = 0


class NetplanException(Exception):
    def __init__(self, message=None, domain=None, error=None):
        self.domain = domain
        self.error = error
        self.message = message

    def __str__(self):
        return self.message


class NetplanFileException(NetplanException):
    @property
    def errno(self):
        return self.error


class NetplanValidationException(NetplanException):
    '''
    Netplan Validation errors are expected to contain the YAML file name
    from where the error was found.

    A validation error might happen after the parsing stage. libnetplan walks
    through its internal representation of the network configuration and checks
    if all the requirements are met. For example, if it finds that the key
    "set-name" is used by an interface, it will check if "match" is present.
    As "set-name" requires "match" to work, it will emit a validation error
    if it's not found.
    '''

    SCHEMA_VALIDATION_ERROR_MSG_REGEX = (
            r'(?P<file_path>.*\.yaml): (?P<message>.*)'
            )

    def __init__(self, message=None, domain=None, error=None):
        super().__init__(message, domain, error)

        schema_error = re.match(self.SCHEMA_VALIDATION_ERROR_MSG_REGEX, message)
        if not schema_error:
            # This shouldn't happen
            raise ValueError(f'The validation error message does not have the expected format: {message}')

        self.filename = schema_error["file_path"]
        self.message = schema_error["message"]


class NetplanParserException(NetplanException):
    '''
    Netplan Parser errors are expected to contain the YAML file name
    and line and column numbers from where the error was found.

    A parser error might happen during the parsing stage. Parsing errors
    might be due to invalid YAML files or invalid Netplan grammar. libnetplan
    will check for this kind of issues while it's walking through the YAML
    files, so it has access to the location where the error was found.
    '''

    SCHEMA_PARSER_ERROR_MSG_REGEX = (
            r'(?P<file_path>.*):(?P<error_line>\d+):(?P<error_col>\d+): (?P<message>(\s|.)*)'
            )

    def __init__(self, message=None, domain=None, error=None):
        super().__init__(message, domain, error)

        # Parser errors from libnetplan have the form:
        #
        # filename.yaml:4:14: Error in network definition: invalid boolean value 'falsea'
        #
        schema_error = re.match(self.SCHEMA_PARSER_ERROR_MSG_REGEX, message)
        if not schema_error:
            # This shouldn't happen
            raise ValueError(f'The parser error message does not have the expected format: {message}')

        self.filename = schema_error["file_path"]
        self.line = schema_error["error_line"]
        self.column = schema_error["error_col"]
        self.message = schema_error["message"]


class NetplanBackendException(NetplanException):
    pass


class NetplanEmitterException(NetplanException):
    pass


class NetplanFormatException(NetplanException):
    pass


# Used in case the "domain" received from libnetplan doesn't exist
NETPLAN_EXCEPTIONS_FALLBACK = defaultdict(lambda: NetplanException)

# If a domain that doesn't exist is queried, it will fallback to NETPLAN_EXCEPTIONS_FALLBACK
# which will return NetplanException for any key accessed.
NETPLAN_EXCEPTIONS = defaultdict(lambda: NETPLAN_EXCEPTIONS_FALLBACK, {
        NETPLAN_ERROR_DOMAINS.NETPLAN_PARSER_ERROR: {
            NETPLAN_PARSER_ERRORS.NETPLAN_ERROR_INVALID_YAML: NetplanParserException,
            NETPLAN_PARSER_ERRORS.NETPLAN_ERROR_INVALID_CONFIG: NetplanParserException,
            },

        NETPLAN_ERROR_DOMAINS.NETPLAN_VALIDATION_ERROR: {
            NETPLAN_VALIDATION_ERRORS.NETPLAN_ERROR_CONFIG_GENERIC: NetplanException,
            NETPLAN_VALIDATION_ERRORS.NETPLAN_ERROR_CONFIG_VALIDATION: NetplanValidationException,
            },

        # FILE_ERRORS are "errno" values and they all throw the same exception
        NETPLAN_ERROR_DOMAINS.NETPLAN_FILE_ERROR: defaultdict(lambda: NetplanFileException),

        NETPLAN_ERROR_DOMAINS.NETPLAN_BACKEND_ERROR: {
            NETPLAN_BACKEND_ERRORS.NETPLAN_ERROR_UNSUPPORTED: NetplanBackendException,
            NETPLAN_BACKEND_ERRORS.NETPLAN_ERROR_VALIDATION: NetplanBackendException,
            },

        NETPLAN_ERROR_DOMAINS.NETPLAN_EMITTER_ERROR: {
            NETPLAN_EMITTER_ERRORS.NETPLAN_ERROR_YAML_EMITTER: NetplanEmitterException,
            },

        NETPLAN_ERROR_DOMAINS.NETPLAN_FORMAT_ERROR: {
            NETPLAN_FORMAT_ERRORS.NETPLAN_ERROR_FORMAT_INVALID_YAML: NetplanFormatException,
            }
        })


def _checked_lib_call(fn, *args):
    ref = ffi.new('NetplanError **')
    ret = bool(fn(*args, ref))
    if not ret:
        err = ref[0]
        if err == ffi.NULL:  # pragma: nocover (should never happen)
            raise NetplanException("Unknown error", 0, 0)
        domain_code = lib.netplan_error_code(err)
        error_domain = domain_code >> 32  # upper 32 bits
        error_code = int(ffi.cast('uint32_t', domain_code))  # lower 32 bits
        error_message = _string_realloc_call_no_error(lambda b: lib.netplan_error_message(err, b, len(b)))
        exception = NETPLAN_EXCEPTIONS[error_domain][error_code]
        raise exception(error_message, error_domain, error_code)
    return ret


def _string_realloc_call_no_error(function: callable):
    size = 16
    while size < 1048576:  # 1MB
        buf = ffi.new('char[]', size)
        code = function(buf)
        if code == -2:
            size = size * 2
            continue

        if code < 0:  # pragma: nocover
            raise NetplanException("Unknown error: %d" % code)
        elif code == 0:
            return None  # pragma: nocover as it's hard to trigger for now
        else:
            return ffi.string(buf).decode('utf-8')
    raise NetplanException('Halting due to string buffer size > 1M')  # pragma: nocover
