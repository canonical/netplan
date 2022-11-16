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
#include <stdlib.h>
#include "types.h"

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

NETPLAN_PUBLIC gboolean
netplan_state_finish_nm_write(
        const NetplanState* np_state,
        const char* rootdir,
        NetplanError** error);

NETPLAN_PUBLIC gboolean
netplan_state_finish_ovs_write(
        const NetplanState* np_state,
        const char* rootdir,
        NetplanError** error);

/* Write the selected yaml file. All definitions that originate from this file,
 * as well as those without any given origin, are written to it.
 */
NETPLAN_PUBLIC gboolean
netplan_state_write_yaml_file(
        const NetplanState* np_state,
        const char* filename,
        const char* rootdir,
        NetplanError** error);

NETPLAN_PUBLIC gboolean
netplan_state_finish_sriov_write(
        const NetplanState* np_state,
        const char* rootdir,
        NetplanError** error);

/* Update all the YAML files that were used to create this state.
 * The definitions without clear origin are written to @default_filename.
 */
NETPLAN_PUBLIC gboolean
netplan_state_update_yaml_hierarchy(
        const NetplanState* np_state,
        const char* default_filename,
        const char* rootdir,
        NetplanError** error);

/* Dump the whole yaml configuration into the given file, regardless of the origin
 * of each definition.
 */
NETPLAN_PUBLIC gboolean
netplan_state_dump_yaml(
        const NetplanState* np_state,
        int output_fd,
        NetplanError** error);

NETPLAN_PUBLIC gboolean
netplan_netdef_write_yaml(
        const NetplanState* np_state,
        const NetplanNetDefinition* netdef,
        const char* rootdir,
        NetplanError** error);

NETPLAN_PUBLIC ssize_t
netplan_netdef_get_filepath(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);

NETPLAN_PUBLIC NetplanBackend
netplan_netdef_get_backend(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC NetplanDefType
netplan_netdef_get_type(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC ssize_t
netplan_netdef_get_id(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buf_size);

NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_bridge_link(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_bond_link(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_peer_link(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_vlan_link(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_sriov_link(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC ssize_t
netplan_netdef_get_set_name(const NetplanNetDefinition* netdef, char* out_buf, size_t out_size);

NETPLAN_PUBLIC gboolean
netplan_netdef_has_match(const NetplanNetDefinition* netdef);


/********** Old API below this ***********/

NETPLAN_DEPRECATED NETPLAN_PUBLIC const char *
netplan_netdef_get_filename(const NetplanNetDefinition* netdef);

NETPLAN_PUBLIC void
write_netplan_conf(const NetplanNetDefinition* def, const char* rootdir);
