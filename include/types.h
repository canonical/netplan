/*
 * Copyright (C) 2022-2024 Canonical, Ltd.
 * Author: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
 * Author: Lukas Märdian <slyon@ubuntu.com>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; version 3.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

/**
 * @file  types.h
 * @brief Definition of public Netplan types.
 */

#pragma once

/// Symbols that are considered part of Netplan public API.
#define NETPLAN_PUBLIC __attribute__ ((visibility("default")))
/// Symbols that are used internally by Netplan.
/// @warning Do not use those symbols in an external codebase, they might be dropped or changed without notice.
#define NETPLAN_INTERNAL __attribute__ ((visibility("default")))
/// Symbols that are outdated and should not be used anymore.
/// @note Those symbols will be dropped in the future.
#define NETPLAN_DEPRECATED __attribute__ ((deprecated))

/// Error of value `-2` to indicate an issue with the buffer.
#define NETPLAN_BUFFER_TOO_SMALL -2


/****************************************************
 * Parsed definitions
 ****************************************************/

#include <glib.h>

/// Network interface types supported by Netplan.
typedef enum {
    NETPLAN_DEF_TYPE_NONE,
    /* physical devices */
    NETPLAN_DEF_TYPE_ETHERNET,
    NETPLAN_DEF_TYPE_WIFI,
    NETPLAN_DEF_TYPE_MODEM,
    /* virtual devices */
    NETPLAN_DEF_TYPE_VIRTUAL,
    NETPLAN_DEF_TYPE_BRIDGE = NETPLAN_DEF_TYPE_VIRTUAL,
    NETPLAN_DEF_TYPE_BOND,
    NETPLAN_DEF_TYPE_VLAN,
    NETPLAN_DEF_TYPE_TUNNEL,
    NETPLAN_DEF_TYPE_PORT,
    NETPLAN_DEF_TYPE_VRF,
    /* Type fallback/passthrough */
    NETPLAN_DEF_TYPE_NM,
    NETPLAN_DEF_TYPE_DUMMY,     /* wokeignore:rule=dummy */
    NETPLAN_DEF_TYPE_VETH,
    NETPLAN_DEF_TYPE_XFRM,
    /* Place holder type used to fill gaps when a netdef
     * requires links to another netdef (such as vlan_link)
     * but it's not strictly mandatory
     * It's intended to be used only when renderer is NetworkManager
     * Keep the PLACEHOLDER_ and MAX_ elements at the end of the enum
     */
    NETPLAN_DEF_TYPE_NM_PLACEHOLDER_,
    NETPLAN_DEF_TYPE_MAX_
} NetplanDefType;

/// Private data structure to contain parsed but unvalidated Netplan configuration.
/// See @ref netplan_parser_new and related accessor functions.
typedef struct netplan_parser NetplanParser;

/// Private data structure to contain validated Netplan configuration, ready for writing to disk.
/// See @ref netplan_state_new and related accessor functions.
typedef struct netplan_state NetplanState;

/// Private data structure to contain individual settings per Netplan ID.
/// See @ref netplan_state_get_netdef, @ref netplan_netdef_get_id and related accessor functions.
typedef struct netplan_net_definition NetplanNetDefinition;

/// Renderer backends supported by Netplan.
typedef enum {
    NETPLAN_BACKEND_NONE,
    NETPLAN_BACKEND_NETWORKD,
    NETPLAN_BACKEND_NM,
    NETPLAN_BACKEND_OVS,
    NETPLAN_BACKEND_MAX_,
} NetplanBackend;

/// Private data structure for error reporting.
/// See @ref netplan_error_code, @ref netplan_error_message and @ref netplan_error_clear.
typedef GError NetplanError;

/// Private data structure to iterate through a list of @ref NetplanNetDefinition inside @ref NetplanState.
/// See @ref netplan_state_iterator_init and related accessor functions.
typedef struct _NetplanStateIterator NetplanStateIterator;

/**
 * @brief   Defining a non-opaque placeholder type for the private `struct netplan_state_iterator`.
 * @details Do not use directly. Use @ref NetplanStateIterator instead. Enables consumers to place the iterator at the stack.
 * @note    The idea is based on the GLib implementation of iterators.
 */
struct _NetplanStateIterator {
    void* placeholder; ///< Just a placeholder in memory
};

/*
 * Errors and error domains
 *
 * NOTE: if new errors or domains are added,
 * python-cffi/netplan/_utils.py must be updated with the new entries.
 */

/// Defining different classes of @ref NetplanError.
enum NETPLAN_ERROR_DOMAINS {
    NETPLAN_PARSER_ERROR = 1, ///< See @ref NETPLAN_PARSER_ERRORS
    NETPLAN_VALIDATION_ERROR, ///< See @ref NETPLAN_VALIDATION_ERRORS
    NETPLAN_FILE_ERROR, ///< Returns `errno` as the @ref NetplanError code and a corresponding message.
    NETPLAN_BACKEND_ERROR, ///< See @ref NETPLAN_BACKEND_ERRORS
    NETPLAN_EMITTER_ERROR, ///< See @ref NETPLAN_EMITTER_ERRORS
    NETPLAN_FORMAT_ERROR, ///< See @ref NETPLAN_FORMAT_ERRORS
};

/**
 * @brief   Errors for domain @ref NETPLAN_PARSER_ERROR.
 * @details Such errors are expected to contain the file name,
 *          line and column numbers.
 */
enum NETPLAN_PARSER_ERRORS {
    NETPLAN_ERROR_INVALID_YAML,
    NETPLAN_ERROR_INVALID_CONFIG,
    NETPLAN_ERROR_INVALID_FLAG,
};

/**
 * @brief   Errors for domain @ref NETPLAN_VALIDATION_ERROR.
 * @details Such errors are expected to contain only the YAML file name
 *          where the error was found.
 */
enum NETPLAN_VALIDATION_ERRORS {
    NETPLAN_ERROR_CONFIG_GENERIC,
    NETPLAN_ERROR_CONFIG_VALIDATION,
};

/// @brief Errors for domain @ref NETPLAN_BACKEND_ERROR.
enum NETPLAN_BACKEND_ERRORS {
    NETPLAN_ERROR_UNSUPPORTED,
    NETPLAN_ERROR_VALIDATION,
};

/// @brief Errors for domain @ref NETPLAN_EMITTER_ERROR.
enum NETPLAN_EMITTER_ERRORS {
    NETPLAN_ERROR_YAML_EMITTER,
};

/**
 * @brief   Errors for domain @ref NETPLAN_FORMAT_ERROR.
 * @details Such errors are generic errors emitted from contexts where information
 *          such as the file name is not known.
 */
enum NETPLAN_FORMAT_ERRORS {
    NETPLAN_ERROR_FORMAT_INVALID_YAML,
};

/**
 * @brief   Flags used to change the parser behavior.
 */
enum NETPLAN_PARSER_FLAGS {
    NETPLAN_PARSER_IGNORE_ERRORS = 1 << 0, ///< Ignore parsing errors such as bad YAML files and definitions.
    NETPLAN_PARSER_FLAGS_MAX_,
};
