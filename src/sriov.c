/*
 * Copyright (C) 2020-2022 Canonical, Ltd.
 * Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
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

#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>

#include <glib.h>
#include <glib/gstdio.h>
#include <glib-object.h>

#include "util-internal.h"
#include "sriov.h"

/**
 * Finalize the SR-IOV configuration (global config)
 */
NETPLAN_DEPRECATED gboolean
netplan_state_finish_sriov_write(__unused const NetplanState* np_state, __unused const char* rootdir, __unused GError** error)
{
    return TRUE; // no-op
}

gboolean
_netplan_sriov_cleanup(const char* rootdir)
{
    _netplan_unlink_glob(rootdir, "/run/udev/rules.d/*-sriov-netplan-*.rules");
    // Drop after next release (once the sd-generator binary is established), as
    // systemd units are now generated in /run/systemd/generator.late/
    _netplan_unlink_glob(rootdir, "/run/systemd/system/netplan-sriov-*.service");
    return TRUE;
}

int
_netplan_state_get_vf_count_for_def(const NetplanState* np_state, const NetplanNetDefinition* netdef, GError** error)
{
    GHashTableIter iter;
    gpointer key, value;
    guint count = 0;

    g_hash_table_iter_init(&iter, np_state->netdefs);
    while (g_hash_table_iter_next (&iter, &key, &value)) {
        const NetplanNetDefinition* def = value;
        if (def->sriov_link == netdef)
            count++;
    }

    if (netdef->sriov_explicit_vf_count != G_MAXUINT && count > netdef->sriov_explicit_vf_count) {
        g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, "more VFs allocated than the explicit size declared: %d > %d", count, netdef->sriov_explicit_vf_count);
        return -1;
    }

    if (netdef->sriov_explicit_vf_count != G_MAXUINT) {
        g_assert(netdef->sriov_explicit_vf_count <= G_MAXINT);
        count = netdef->sriov_explicit_vf_count;
    }

    g_assert(count <= G_MAXINT);
    return (int)count;
}
