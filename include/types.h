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

typedef struct netplan_state_iterator NetplanStateIterator;
