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

#include <glob.h>
#include <glib.h>
#include "types-internal.h"

#include <glib.h>
#include "netplan.h"

#define SET_OPT_OUT_PTR(ptr,val) { if (ptr) *ptr = val; }

#define __unused __attribute__((unused))

extern GHashTable*
wifi_frequency_24;

extern GHashTable*
wifi_frequency_5;

NETPLAN_ABI void
safe_mkdir_p_dir(const char* file_path);

NETPLAN_INTERNAL void
g_string_free_to_file(GString* s, const char* rootdir, const char* path, const char* suffix);

NETPLAN_INTERNAL void
unlink_glob(const char* rootdir, const char* _glob);

NETPLAN_INTERNAL int
find_yaml_glob(const char* rootdir, glob_t* out_glob);

NETPLAN_ABI const char*
get_global_network(int ip_family);

NETPLAN_ABI const char*
get_unspecified_address(int ip_family);

NETPLAN_ABI int
wifi_get_freq24(int channel);

NETPLAN_ABI int
wifi_get_freq5(int channel);

NETPLAN_ABI gchar*
systemd_escape(char* string);

#define OPENVSWITCH_OVS_VSCTL "/usr/bin/ovs-vsctl"

void
mark_data_as_dirty(NetplanParser* npp, const void* data_ptr);

const char*
tunnel_mode_to_string(NetplanTunnelMode mode);

NetplanBackend
get_default_backend_for_type(NetplanBackend global_backend, NetplanDefType type);

NetplanNetDefinition*
netplan_netdef_new(NetplanParser* npp, const char* id, NetplanDefType type, NetplanBackend renderer);

const char *
netplan_parser_get_filename(NetplanParser* npp);

NETPLAN_INTERNAL void
process_input_file(const char* f);

NETPLAN_INTERNAL gboolean
process_yaml_hierarchy(const char* rootdir);

gboolean
has_openvswitch(const NetplanOVSSettings* ovs, NetplanBackend backend, GHashTable *ovs_ports);

ssize_t
netplan_copy_string(const char* input, char* out_buffer, size_t out_size);

gboolean
complex_object_is_dirty(const NetplanNetDefinition* def, const void* obj, size_t obj_size);

gboolean
is_multicast_address(const char*);

NETPLAN_INTERNAL int
_netplan_state_get_vf_count_for_def(const NetplanState* np_state, const NetplanNetDefinition* netdef, NetplanError** error);

NETPLAN_INTERNAL gboolean
_netplan_netdef_get_sriov_vlan_filter(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL gboolean
_netplan_netdef_get_critical(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL gboolean
_netplan_netdef_get_optional(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL ssize_t
_netplan_netdef_get_embedded_switch_mode(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buf_size);

NETPLAN_INTERNAL gboolean
_netplan_netdef_get_delay_vf_rebind(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL gboolean
netplan_netdef_get_delay_virtual_functions_rebind(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL guint
_netplan_netdef_get_vlan_id(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL gboolean
_netplan_netdef_is_trivial_compound_itf(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL gboolean //FIXME: avoid exporting private symbol
is_route_present(const NetplanNetDefinition* netdef, const NetplanIPRoute* route);

NETPLAN_INTERNAL gboolean //FIXME: avoid exporting private symbol
is_route_rule_present(const NetplanNetDefinition* netdef, const NetplanIPRule* rule);

NETPLAN_INTERNAL gboolean //FIXME: avoid exporting private symbol
is_string_in_array(GArray* array, const char* value);

NETPLAN_INTERNAL struct netdef_address_iter*
_netplan_new_netdef_address_iter(NetplanNetDefinition* netdef);

NETPLAN_INTERNAL NetplanAddressOptions*
_netplan_netdef_address_iter_next(struct netdef_address_iter* it);

NETPLAN_INTERNAL void
_netplan_netdef_address_free_iter(struct netdef_address_iter* it);

NETPLAN_INTERNAL struct netdef_pertype_iter*
_netplan_state_new_netdef_pertype_iter(NetplanState* np_state, const char* def_type);

NETPLAN_INTERNAL NetplanNetDefinition*
_netplan_netdef_pertype_iter_next(struct netdef_pertype_iter* it);

NETPLAN_INTERNAL void
_netplan_netdef_pertype_iter_free(struct netdef_pertype_iter* it);
