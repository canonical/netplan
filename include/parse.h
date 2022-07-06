/*
 * Copyright (C) 2016 Canonical, Ltd.
 * Author: Martin Pitt <martin.pitt@ubuntu.com>
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
#include "netplan.h"
#include <glib.h>

/****************************************************
 * Parsed definitions
 ****************************************************/

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
    NETPLAN_DEF_TYPE_MAX_
} NetplanDefType;

typedef struct netplan_parser NetplanParser;

/****************************************************
 * Functions
 ****************************************************/

NETPLAN_PUBLIC NetplanParser*
netplan_parser_new();

NETPLAN_PUBLIC void
netplan_parser_reset(NetplanParser *npp);

NETPLAN_PUBLIC void
netplan_parser_clear(NetplanParser **npp);

NETPLAN_PUBLIC gboolean
netplan_parser_load_yaml(NetplanParser* npp, const char* filename, GError** error);

NETPLAN_PUBLIC gboolean
netplan_state_import_parser_results(NetplanState* np_state, NetplanParser* npp, GError** error);

NETPLAN_PUBLIC gboolean
netplan_parser_load_yaml_from_fd(NetplanParser* npp, int input_fd, GError** error);

NETPLAN_PUBLIC gboolean
netplan_parser_load_nullable_fields(NetplanParser* npp, int input_fd, GError** error);

/********** Old API below this ***********/

NETPLAN_PUBLIC gboolean
netplan_parse_yaml(const char* filename, GError** error);

NETPLAN_PUBLIC GHashTable*
netplan_finish_parse(GError** error);

NETPLAN_PUBLIC guint
netplan_clear_netdefs();

NETPLAN_PUBLIC NetplanBackend
netplan_get_global_backend();
