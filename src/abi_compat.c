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
#include "names.h"
#include "networkd.h"
#include "nm.h"
#include "openvswitch.h"

#include <unistd.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <errno.h>

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

NetplanBackend
netplan_get_global_backend()
{
    return netplan_state_get_backend(&global_state);
}

/**
 * Clear NetplanNetDefinition hashtable
 */
guint
netplan_clear_netdefs()
{
    guint n = netplan_state_get_netdefs_size(&global_state);
    netplan_state_reset(&global_state);
    return n;
}

NETPLAN_INTERNAL void
write_network_file(const NetplanNetDefinition* def, const char* rootdir, const char* path)
{
    GError* error = NULL;
    if (!netplan_netdef_write_network_file(&global_state, def, rootdir, path, NULL, &error))
    {
        g_fprintf(stderr, "%s", error->message);
        exit(1);
    }
}

/**
 * Generate networkd configuration in @rootdir/run/systemd/network/ from the
 * parsed #netdefs.
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 * Returns: TRUE if @def applies to networkd, FALSE otherwise.
 */
gboolean
write_networkd_conf(const NetplanNetDefinition* def, const char* rootdir)
{
    GError* error = NULL;
    gboolean has_been_written;
    if (!netplan_netdef_write_networkd(&global_state, def, rootdir, &has_been_written, &error))
    {
        g_fprintf(stderr, "%s", error->message);
        exit(1);
    }
    return has_been_written;
}

NETPLAN_INTERNAL void
cleanup_networkd_conf(const char* rootdir)
{
    netplan_networkd_cleanup(rootdir);
}

// There only for compatibility purposes, the proper implementation is now directly
// in the `generate` binary.
// LCOV_EXCL_START
NETPLAN_ABI void
enable_networkd(const char* generator_dir)
{
    g_autofree char* link = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "multi-user.target.wants", "systemd-networkd.service", NULL);
    g_debug("We created networkd configuration, adding %s enablement symlink", link);
    safe_mkdir_p_dir(link);
    if (symlink("../systemd-networkd.service", link) < 0 && errno != EEXIST) {
        g_fprintf(stderr, "failed to create enablement symlink: %m\n");
        exit(1);
    }

    g_autofree char* link2 = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "network-online.target.wants", "systemd-networkd-wait-online.service", NULL);
    safe_mkdir_p_dir(link2);
    if (symlink("/lib/systemd/system/systemd-networkd-wait-online.service", link2) < 0 && errno != EEXIST) {
        g_fprintf(stderr, "failed to create enablement symlink: %m\n");
        exit(1);
    }
}
// LCOV_EXCL_STOP

NETPLAN_INTERNAL void
write_nm_conf(NetplanNetDefinition* def, const char* rootdir)
{
    GError* error = NULL;
    if (!netplan_netdef_write_nm(&global_state, def, rootdir, NULL, &error)) {
        g_fprintf(stderr, "%s", error->message);
        exit(1);
    }
}

NETPLAN_INTERNAL void
write_nm_conf_finish(const char* rootdir)
{
    /* Original implementation had no error possible!! */
    g_assert(netplan_state_finish_nm_write(&global_state, rootdir, NULL));
}

NETPLAN_INTERNAL void
cleanup_nm_conf(const char* rootdir)
{
    netplan_nm_cleanup(rootdir);
}
