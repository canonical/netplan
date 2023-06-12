/*
 * Copyright (C) 2022 Canonical, Ltd.
 * Author: Danilo Egea Gondolfo <danilo.egea.gondolfo@canonical.com>
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

#pragma once

#define NETPLAN_PUBLIC __attribute__ ((visibility("default")))
#define NETPLAN_INTERNAL __attribute__ ((visibility("default")))
#define NETPLAN_ABI __attribute__ ((visibility("default")))

#define NETPLAN_DEPRECATED __attribute__ ((deprecated))

#define NETPLAN_BUFFER_TOO_SMALL -2


/****************************************************
 * Parsed definitions
 ****************************************************/

#include <glib.h>

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
    /* Place holder type used to fill gaps when a netdef
     * requires links to another netdef (such as vlan_link)
     * but it's not strictly mandatory
     * It's intended to be used only when renderer is NetworkManager
     */
    NETPLAN_DEF_TYPE_NM_PLACEHOLDER_,
    NETPLAN_DEF_TYPE_MAX_
} NetplanDefType;

typedef struct netplan_parser NetplanParser;

/**
 * Represent a configuration stanza
 */
typedef struct netplan_net_definition NetplanNetDefinition;
typedef struct netplan_state NetplanState;

typedef enum {
    NETPLAN_BACKEND_NONE,
    NETPLAN_BACKEND_NETWORKD,
    NETPLAN_BACKEND_NM,
    NETPLAN_BACKEND_OVS,
    NETPLAN_BACKEND_MAX_,
} NetplanBackend;

typedef GError NetplanError;

typedef struct _NetplanStateIterator NetplanStateIterator;

struct _NetplanStateIterator {
    void* placeholder;
};

/*
 * Errors and error domains
 *
 * NOTE: if new errors or domains are added,
 * netplan/libnetplan.py must be updated with the new entries.
 */

enum NETPLAN_ERROR_DOMAINS {
    NETPLAN_PARSER_ERROR = 1,
    NETPLAN_VALIDATION_ERROR,
    NETPLAN_FILE_ERROR,
    NETPLAN_BACKEND_ERROR,
    NETPLAN_EMITTER_ERROR,
    NETPLAN_FORMAT_ERROR,
};

/*
 * Errors for domain NETPLAN_PARSER_ERROR
 *
 * PARSER_ERRORS are expected to contain the file name, line and column numbers
 */
enum NETPLAN_PARSER_ERRORS {
    NETPLAN_ERROR_INVALID_YAML,
    NETPLAN_ERROR_INVALID_CONFIG
};

/*
 * Errors for domain NETPLAN_VALIDATION_ERROR
 *
 * VALIDATION_ERRORS are expected to contain only the YAML file name
 * where the error was found.
 */
enum NETPLAN_VALIDATION_ERRORS {
    NETPLAN_ERROR_CONFIG_GENERIC,
    NETPLAN_ERROR_CONFIG_VALIDATION,
};

/*
 * Errors for domain NETPLAN_BACKEND_ERROR
 */
enum NETPLAN_BACKEND_ERRORS {
    NETPLAN_ERROR_UNSUPPORTED,
    NETPLAN_ERROR_VALIDATION,
};

/*
 * Errors for domain NETPLAN_EMITTER_ERROR
 */
enum NETPLAN_EMITTER_ERRORS {
    NETPLAN_ERROR_YAML_EMITTER,
};

/*
 * Errors for domain NETPLAN_FORMAT_ERROR
 *
 * FORMAT_ERRORS are generic errors emitted from contexts where information
 * like the file name is not known.
 */
enum NETPLAN_FORMAT_ERRORS {
    NETPLAN_ERROR_FORMAT_INVALID_YAML,
};
