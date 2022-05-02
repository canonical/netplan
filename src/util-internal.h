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

#define __USE_MISC
#include <glob.h>
#include <glib.h>
#include "types.h"

#include <glib.h>
#include "netplan.h"

#define SET_OPT_OUT_PTR(ptr,val) { if (ptr) *ptr = val; }

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

NETPLAN_INTERNAL gboolean
netplan_util_create_yaml_patch(const char* conf_obj_path, const char* obj_payload, int out_fd, GError** error);

#define OPENVSWITCH_OVS_VSCTL "/usr/bin/ovs-vsctl"

void
mark_data_as_dirty(NetplanParser* npp, void* data_ptr);

const char*
tunnel_mode_to_string(NetplanTunnelMode mode);

NetplanBackend
get_default_backend_for_type(NetplanBackend global_backend, NetplanDefType type);

NetplanNetDefinition*
netplan_netdef_new(NetplanParser* npp, const char* id, NetplanDefType type, NetplanBackend renderer);

const char *
netplan_parser_get_filename(NetplanParser* npp);

NETPLAN_INTERNAL gboolean
netplan_parser_load_yaml_hierarchy(NetplanParser* npp, const char* rootdir, GError** error);

NETPLAN_INTERNAL void
process_input_file(const char* f);

NETPLAN_INTERNAL gboolean
process_yaml_hierarchy(const char* rootdir);

gboolean
has_openvswitch(const NetplanOVSSettings* ovs, NetplanBackend backend, GHashTable *ovs_ports);

ssize_t
netplan_copy_string(const char* input, char* out_buffer, size_t out_size);
