/*
 * Copyright (C) 2021 Canonical, Ltd.
 * Author: Simon Chopin <simon.chopin@canonical.com>
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

/*
 * The whole point of this file is to export the former ABI as simple wrappers
 * around the newer API. Most functions should thus be relatively short, the meat
 * of things being in the newer API implementation.
 */

#include "netplan.h"
#include "types.h"
#include "util-internal.h"
#include "parse-nm.h"
#include "parse-globals.h"
#include "names.h"
#include "networkd.h"
#include "nm.h"
#include "sriov.h"
#include "openvswitch.h"
#include "util.h"

#include <unistd.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <errno.h>
#include <fcntl.h>

/* These arrays are not useful per-say, but allow us to export the various
 * struct offsets of the netplan_state members to the linker, which can use
 * them in a linker script to create symbols pointing to the internal data
 * members of the global_state global object.
 */

/* The +8 is to prevent the compiler removing the array if the array is empty,
 * i.e. the data member is the first in the struct definition.
 */
__attribute__((used)) __attribute__((section("netdefs_offset")))
char _netdefs_off[8+offsetof(struct netplan_state, netdefs)] = {};

__attribute__((used)) __attribute__((section("netdefs_ordered_offset")))
char _netdefs_ordered_off[8+offsetof(struct netplan_state, netdefs_ordered)] = {};

__attribute__((used)) __attribute__((section("ovs_settings_offset")))
char _ovs_settings_global_off[8+offsetof(struct netplan_state, ovs_settings)] = {};

__attribute__((used)) __attribute__((section("global_backend_offset")))
char _global_backend_off[8+offsetof(struct netplan_state, backend)] = {};

NETPLAN_ABI
NetplanState global_state = {};

// LCOV_EXCL_START
NetplanBackend
netplan_get_global_backend()
{
    return netplan_state_get_backend(&global_state);
}
// LCOV_EXCL_STOP

/**
 * Clear NetplanNetDefinition hashtable
 */
guint
netplan_clear_netdefs()
{
    guint n = netplan_state_get_netdefs_size(&global_state);
    netplan_state_reset(&global_state);
    netplan_parser_reset(&global_parser);
    return n;
}
// LCOV_EXCL_STOP

gboolean
netplan_parse_yaml(const char* filename, GError** error)
{
    return netplan_parser_load_yaml(&global_parser, filename, error);
}

/**
 * Post-processing after parsing all config files
 */
GHashTable *
netplan_finish_parse(GError** error)
{
    if (netplan_state_import_parser_results(&global_state, &global_parser, error))
        return global_state.netdefs;
    return NULL; // LCOV_EXCL_LINE
}

/**
 * Generate the Netplan YAML configuration for the selected netdef
 * @def: NetplanNetDefinition (as pointer), the data to be serialized
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
void
write_netplan_conf(const NetplanNetDefinition* def, const char* rootdir)
{
    netplan_netdef_write_yaml(&global_state, def, rootdir, NULL);
}

/**
 * Generate the Netplan YAML configuration for all currently parsed netdefs
 * @file_hint: Name hint for the generated output YAML file
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
NETPLAN_ABI void
write_netplan_conf_full(const char* file_hint, const char* rootdir)
{
    g_autofree gchar *path = NULL;
    netplan_finish_parse(NULL);
    if (!netplan_state_has_nondefault_globals(&global_state) &&
        !netplan_state_get_netdefs_size(&global_state))
        return;
    path = g_build_path(G_DIR_SEPARATOR_S, rootdir ?: G_DIR_SEPARATOR_S, "etc", "netplan", file_hint, NULL);
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0640);
    netplan_state_dump_yaml(&global_state, fd, NULL);
    close(fd);
}

NETPLAN_PUBLIC gboolean
netplan_parse_keyfile(const char* filename, GError** error)
{
    return netplan_parser_load_keyfile(&global_parser, filename, error);
}

// LCOV_EXCL_START
void process_input_file(const char *f)
{
    GError* error = NULL;

    g_debug("Processing input file %s..", f);
    if (!netplan_parser_load_yaml(&global_parser, f, &error)) {
        g_fprintf(stderr, "%s\n", error->message);
        exit(1);
    }
}

gboolean
process_yaml_hierarchy(const char* rootdir)
{
    GError* error = NULL;
    if (!netplan_parser_load_yaml_hierarchy(&global_parser, rootdir, &error)) {
        g_fprintf(stderr, "%s\n", error->message);
        exit(1);
    }
    return TRUE;
}
// LCOV_EXCL_STOP

/**
 * Helper function for testing only
 */
NETPLAN_INTERNAL void
_write_netplan_conf(const char* netdef_id, const char* rootdir)
{
    GHashTable* ht = NULL;
    const NetplanNetDefinition* def = NULL;
    ht = netplan_finish_parse(NULL);
    def = g_hash_table_lookup(ht, netdef_id);
    if (def)
        write_netplan_conf(def, rootdir);
    else
        g_warning("_write_netplan_conf: netdef_id (%s) not found.", netdef_id); // LCOV_EXCL_LINE
}

/**
 * Get the filename from which the given netdef has been parsed.
 * @rootdir: ID of the netdef to be looked up
 * @rootdir: parse files from this root directory
 */
gchar*
netplan_get_filename_by_id(const char* netdef_id, const char* rootdir)
{
    NetplanParser* npp = netplan_parser_new();
    NetplanState* np_state = netplan_state_new();
    char *filepath = NULL;
    GError* error = NULL;

    if (!netplan_parser_load_yaml_hierarchy(npp, rootdir, &error) ||
            !netplan_state_import_parser_results(np_state, npp, &error)) {
        g_fprintf(stderr, "%s\n", error->message);
        return NULL;
    }
    netplan_parser_clear(&npp);

    NetplanNetDefinition* netdef = netplan_state_get_netdef(np_state, netdef_id);
    if (netdef)
        filepath = g_strdup(netdef->filepath);
    netplan_state_clear(&np_state);
    return filepath;
}

// LCOV_EXCL_START
NETPLAN_INTERNAL struct netdef_pertype_iter*
_netplan_state_new_netdef_pertype_iter(NetplanState* np_state, const char* devtype);

NETPLAN_INTERNAL struct netdef_pertype_iter*
_netplan_iter_defs_per_devtype_init(const char *devtype)
{
    return _netplan_state_new_netdef_pertype_iter(&global_state, devtype);
}

NETPLAN_ABI const char *
netplan_netdef_get_filename(const NetplanNetDefinition* netdef)
{
    g_assert(netdef);
    return netdef->filepath;
}
// LCOV_EXCL_STOP
