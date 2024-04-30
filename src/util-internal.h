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

NETPLAN_INTERNAL void
_netplan_safe_mkdir_p_dir(const char* file_path);

NETPLAN_INTERNAL void
_netplan_g_string_free_to_file(GString* s, const char* rootdir, const char* path, const char* suffix);

NETPLAN_INTERNAL void
_netplan_unlink_glob(const char* rootdir, const char* _glob);

NETPLAN_INTERNAL int
_netplan_find_yaml_glob(const char* rootdir, glob_t* out_glob);

const char*
get_global_network(int ip_family);

const char*
get_unspecified_address(int ip_family);

int
wifi_get_freq24(int channel);

int
wifi_get_freq5(int channel);

gchar*
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

NetplanNetDefinition*
_netplan_parser_find_bond_for_primary_member(const NetplanParser* npp, const char* primary);

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
_netplan_netdef_get_delay_virtual_functions_rebind(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL guint
_netplan_netdef_get_vlan_id(const NetplanNetDefinition* netdef);

NETPLAN_INTERNAL ssize_t
_netplan_netdef_get_bond_mode(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buf_size);

NETPLAN_INTERNAL gboolean
_netplan_netdef_is_trivial_compound_itf(const NetplanNetDefinition* netdef);

gboolean
is_route_present(const NetplanNetDefinition* netdef, const NetplanIPRoute* route);

gboolean
is_route_rule_present(const NetplanNetDefinition* netdef, const NetplanIPRule* rule);

gboolean
is_string_in_array(GArray* array, const char* value);

gboolean
_is_auth_key_management_psk(const NetplanAuthenticationSettings* auth);

gboolean
_is_macaddress_special_nm_option(const char* value);

gboolean
_is_macaddress_special_nd_option(const char* value);

gboolean
_is_valid_macaddress(const char* value);

NETPLAN_INTERNAL struct address_iter*
_netplan_netdef_new_address_iter(NetplanNetDefinition* netdef);

NETPLAN_INTERNAL NetplanAddressOptions*
_netplan_address_iter_next(struct address_iter* it);

NETPLAN_INTERNAL void
_netplan_address_iter_free(struct address_iter* it);

NETPLAN_INTERNAL struct nameserver_iter*
_netplan_netdef_new_nameserver_iter(NetplanNetDefinition* netdef);

NETPLAN_INTERNAL char*
_netplan_nameserver_iter_next(struct nameserver_iter* it);

NETPLAN_INTERNAL void
_netplan_nameserver_iter_free(struct nameserver_iter* it);

NETPLAN_INTERNAL struct nameserver_iter*
_netplan_netdef_new_search_domain_iter(NetplanNetDefinition* netdef);

NETPLAN_INTERNAL char*
_netplan_search_domain_iter_next(struct nameserver_iter* it);

NETPLAN_INTERNAL void
_netplan_search_domain_iter_free(struct nameserver_iter* it);

NETPLAN_INTERNAL struct route_iter*
_netplan_netdef_new_route_iter(NetplanNetDefinition* netdef);

NETPLAN_INTERNAL NetplanIPRoute*
_netplan_route_iter_next(struct route_iter* it);

NETPLAN_INTERNAL void
_netplan_route_iter_free(struct route_iter* it);

NETPLAN_INTERNAL struct netdef_pertype_iter*
_netplan_state_new_netdef_pertype_iter(NetplanState* np_state, const char* def_type);

NETPLAN_INTERNAL NetplanNetDefinition*
_netplan_netdef_pertype_iter_next(struct netdef_pertype_iter* it);

NETPLAN_INTERNAL void
_netplan_netdef_pertype_iter_free(struct netdef_pertype_iter* it);

/**
 * @brief   Get the `gateway4` setting of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small, its content is not `NUL`-terminated.
 * @param[in]  netdef          The @ref NetplanNetDefinition to query
 * @param[out] out_buffer      A pre-allocated buffer to write the output string into, owned by the caller
 * @param[in]  out_buffer_size The maximum size (in bytes) available for @p out_buffer
 * @return                     The size of the copied string, including the final `NUL` character.
 *                             If the buffer is too small, returns @ref NETPLAN_BUFFER_TOO_SMALL instead.
 */
NETPLAN_INTERNAL ssize_t
_netplan_netdef_get_gateway4(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);

/**
 * @brief   Get the `gateway6` setting of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small, its content is not `NUL`-terminated.
 * @param[in]  netdef          The @ref NetplanNetDefinition to query
 * @param[out] out_buffer      A pre-allocated buffer to write the output string into, owned by the caller
 * @param[in]  out_buffer_size The maximum size (in bytes) available for @p out_buffer
 * @return                     The size of the copied string, including the final `NUL` character.
 *                             If the buffer is too small, returns @ref NETPLAN_BUFFER_TOO_SMALL instead.
 */
NETPLAN_INTERNAL ssize_t
_netplan_netdef_get_gateway6(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);
