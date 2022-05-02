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
#include <stdlib.h>

#define NETPLAN_PUBLIC __attribute__ ((visibility("default")))
#define NETPLAN_INTERNAL __attribute__ ((visibility("default")))
#define NETPLAN_ABI __attribute__ ((visibility("default")))

#define NETPLAN_DEPRECATED __attribute__ ((deprecated))

#define NETPLAN_BUFFER_TOO_SMALL -2

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
netplan_state_reset(NetplanState* np_state);

NETPLAN_PUBLIC void
netplan_state_clear(NetplanState** np_state);

NETPLAN_PUBLIC NetplanBackend
netplan_state_get_backend(const NetplanState* np_state);

NETPLAN_PUBLIC guint
netplan_state_get_netdefs_size(const NetplanState* np_state);

NETPLAN_PUBLIC NetplanNetDefinition*
netplan_state_get_netdef(const NetplanState* np_state, const char* id);

/* Write the selected yaml file. All definitions that originate from this file,
 * as well as those without any given origin, are written to it.
 */
NETPLAN_PUBLIC gboolean
netplan_state_write_yaml_file(
        const NetplanState* np_state,
        const char* filename,
        const char* rootdir,
        GError** error);

/* Update all the YAML files that were used to create this state.
 * The definitions without clear origin are written to @default_filename.
 */
NETPLAN_PUBLIC gboolean
netplan_state_update_yaml_hierarchy(
        const NetplanState* np_state,
        const char* default_filename,
        const char* rootdir,
        GError** error);

/* Dump the whole yaml configuration into the given file, regardless of the origin
 * of each definition.
 */
NETPLAN_PUBLIC gboolean
netplan_state_dump_yaml(
        const NetplanState* np_state,
        int output_fd,
        GError** error);

NETPLAN_PUBLIC gboolean
netplan_netdef_write_yaml(
        const NetplanState* np_state,
        const NetplanNetDefinition* netdef,
        const char* rootdir,
        GError** error);

NETPLAN_PUBLIC ssize_t
netplan_netdef_get_filepath(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);

/********** Old API below this ***********/

NETPLAN_DEPRECATED NETPLAN_PUBLIC const char *
netplan_netdef_get_filename(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC void
write_netplan_conf(const NetplanNetDefinition* def, const char* rootdir);
