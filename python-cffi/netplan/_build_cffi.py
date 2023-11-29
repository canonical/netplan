#!/usr/bin/env python3

# Copyright (C) 2023 Canonical, Ltd.
# Author: Lukas Märdian <slyon@ubuntu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys

from cffi import FFI
ffibuilder = FFI()

# cdef() expects a single string declaring the C types, functions and
# globals needed to use the shared object. It must be in valid C syntax.
ffibuilder.cdef("""
    #define UINT_MAX ...
    typedef int gboolean;
    typedef unsigned int guint;
    typedef int gint;
    typedef struct GError NetplanError;
    typedef struct netplan_parser NetplanParser;
    typedef struct netplan_state NetplanState;
    typedef struct netplan_net_definition NetplanNetDefinition;
    typedef enum { ... } NetplanBackend;
    typedef enum { ... } NetplanDefType;
    typedef enum { ... } NetplanCriticalOption;

    // TODO: Introduce getters for .address/.lifetime/.label to avoid exposing the raw struct
    typedef struct {
        char* address;
        char* lifetime;
        char* label;
    } NetplanAddressOptions;
    struct address_iter { ...; };
    struct nameserver_iter { ...; };
    struct route_iter { ...; };

    // TODO: Introduce getters for all these fields to avoid exposing the raw struct
    typedef struct {
        gint family;
        char* type;
        char* scope;
        guint table;
        char* from;
        char* to;
        char* via;
        gboolean onlink;
        guint metric;
        guint mtubytes;
        guint congestion_window;
        guint advertised_receive_window;
    } NetplanIPRoute;

    // Error handling
    uint64_t netplan_error_code(NetplanError* error);
    ssize_t netplan_error_message(NetplanError* error, char* buf, size_t buf_size);

    // Parser
    NetplanParser* netplan_parser_new();
    void netplan_parser_clear(NetplanParser **npp);
    gboolean netplan_parser_load_yaml(NetplanParser* npp, const char* filename, NetplanError** error);
    gboolean netplan_parser_load_yaml_from_fd(NetplanParser* npp, int input_fd, NetplanError** error);
    gboolean netplan_parser_load_yaml_hierarchy(NetplanParser* npp, const char* rootdir, NetplanError** error);
    gboolean netplan_parser_load_keyfile(NetplanParser* npp, const char* filename, NetplanError** error);
    gboolean netplan_parser_load_nullable_fields(NetplanParser* npp, int input_fd, NetplanError** error);
    gboolean netplan_parser_load_nullable_overrides(
        NetplanParser* npp, int input_fd, const char* constraint, NetplanError** error);

    // State
    NetplanState* netplan_state_new();
    void netplan_state_clear(NetplanState** np_state);
    NetplanBackend netplan_state_get_backend(const NetplanState* np_state);
    gboolean netplan_state_import_parser_results(NetplanState* np_state, NetplanParser* npp, NetplanError** error);
    gboolean netplan_state_update_yaml_hierarchy(
        const NetplanState* np_state, const char* default_filename, const char* rootdir, NetplanError** error);
    gboolean netplan_state_write_yaml_file(
        const NetplanState* np_state, const char* filename, const char* rootdir, NetplanError** error);
    gboolean netplan_state_dump_yaml(const NetplanState* np_state, int output_fd, NetplanError** error);
    NetplanNetDefinition* netplan_state_get_netdef(const NetplanState* np_state, const char* id);
    guint netplan_state_get_netdefs_size(const NetplanState* np_state);

    // NetDefinition
    ssize_t netplan_netdef_get_id(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);
    NetplanDefType netplan_netdef_get_type(const NetplanNetDefinition* netdef);
    NetplanBackend netplan_netdef_get_backend(const NetplanNetDefinition* netdef);
    ssize_t netplan_netdef_get_filepath(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);
    NetplanNetDefinition* netplan_netdef_get_bridge_link(const NetplanNetDefinition* netdef);
    NetplanNetDefinition* netplan_netdef_get_bond_link(const NetplanNetDefinition* netdef);
    NetplanNetDefinition* netplan_netdef_get_peer_link(const NetplanNetDefinition* netdef);
    NetplanNetDefinition* netplan_netdef_get_vlan_link(const NetplanNetDefinition* netdef);
    NetplanNetDefinition* netplan_netdef_get_sriov_link(const NetplanNetDefinition* netdef);
    ssize_t netplan_netdef_get_set_name(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);
    gboolean netplan_netdef_has_match(const NetplanNetDefinition* netdef);
    gboolean netplan_netdef_get_delay_virtual_functions_rebind(const NetplanNetDefinition* netdef);
    gboolean netplan_netdef_match_interface(
        const NetplanNetDefinition* netdef, const char* name, const char* mac, const char* driver_name);
    gboolean netplan_netdef_get_dhcp4(const NetplanNetDefinition* netdef);
    gboolean netplan_netdef_get_dhcp6(const NetplanNetDefinition* netdef);
    ssize_t netplan_netdef_get_macaddress(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);

    // NetDefinition (internal)
    ssize_t _netplan_netdef_get_embedded_switch_mode(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buf_size);
    gboolean _netplan_netdef_get_sriov_vlan_filter(const NetplanNetDefinition* netdef);
    guint _netplan_netdef_get_vlan_id(const NetplanNetDefinition* netdef);
    NetplanCriticalOption _netplan_netdef_get_critical(const NetplanNetDefinition* netdef);
    gboolean _netplan_netdef_is_trivial_compound_itf(const NetplanNetDefinition* netdef);
    int _netplan_state_get_vf_count_for_def(
        const NetplanState* np_state, const NetplanNetDefinition* netdef, NetplanError** error);

    // Iterators (internal)
    struct netdef_pertype_iter* _netplan_state_new_netdef_pertype_iter(NetplanState* np_state, const char* def_type);
    NetplanNetDefinition* _netplan_netdef_pertype_iter_next(struct netdef_pertype_iter* it);
    void _netplan_netdef_pertype_iter_free(struct netdef_pertype_iter* it);
    struct address_iter* _netplan_netdef_new_address_iter(NetplanNetDefinition* netdef);
    NetplanAddressOptions* _netplan_address_iter_next(struct address_iter* it);
    void _netplan_address_iter_free(struct address_iter* it);
    struct nameserver_iter* _netplan_netdef_new_nameserver_iter(NetplanNetDefinition* netdef);
    char* _netplan_nameserver_iter_next(struct nameserver_iter* it);
    void _netplan_nameserver_iter_free(struct nameserver_iter* it);
    struct nameserver_iter* _netplan_netdef_new_search_domain_iter(NetplanNetDefinition* netdef);
    char* _netplan_search_domain_iter_next(struct nameserver_iter* it);
    void _netplan_search_domain_iter_free(struct nameserver_iter* it);
    struct route_iter* _netplan_netdef_new_route_iter(NetplanNetDefinition* netdef);
    NetplanIPRoute* _netplan_route_iter_next(struct route_iter* it);
    void _netplan_route_iter_free(struct route_iter* it);

    // Utils
    gboolean netplan_util_dump_yaml_subtree(const char* prefix, int input_fd, int output_fd, NetplanError** error);
    gboolean netplan_util_create_yaml_patch(const char* conf_obj_path, const char* obj_payload, int out_fd, NetplanError** error);

    // Names (internal)
    const char* netplan_backend_name(NetplanBackend val);
    const char* netplan_def_type_name(NetplanDefType val);
""")

cffi_inc = os.getenv('CFFI_INC', sys.argv[1])
cffi_lib = os.getenv('CFFI_LIB', sys.argv[2])

# set_source() gives the name of the python extension module to
# produce, and some C source code as a string.  This C code needs
# to make the declarated functions, types and globals available,
# so it is often just the "#include".
ffibuilder.set_source_pkgconfig(
    "_netplan_cffi", ['glib-2.0'],
    """
    #include <glib.h>

    // C API of libnetplan.so
    #include "netplan.h"
    #include "parse.h"
    #include "parse-nm.h"
    #include "util.h"

    // internal headers (private API)
    #include "util-internal.h"
    #include "names.h"
    """,
    include_dirs=[cffi_inc],
    library_dirs=[cffi_lib],
    libraries=['glib-2.0'])   # library name, for the linker

if __name__ == "__main__":
    ffibuilder.distutils_extension('.')
