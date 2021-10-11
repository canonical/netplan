/*
 * Copyright (C) 2021 Canonical, Ltd.
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

#pragma once
#include <glib.h>

#define NETPLAN_PUBLIC __attribute__ ((visibility("default")))
#define NETPLAN_INTERNAL __attribute__ ((visibility("default")))
#define NETPLAN_ABI __attribute__ ((visibility("default")))

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

NETPLAN_PUBLIC NetplanState*
netplan_state_new();

NETPLAN_PUBLIC void
netplan_state_reset(NetplanState *state);

NETPLAN_PUBLIC void
netplan_state_clear(NetplanState **state);

NETPLAN_PUBLIC NetplanBackend
netplan_state_get_backend(const NetplanState *state);
NETPLAN_PUBLIC guint
netplan_state_get_netdefs_size(const NetplanState *state);

NETPLAN_PUBLIC void
write_netplan_conf(const NetplanNetDefinition* def, const char* rootdir);
