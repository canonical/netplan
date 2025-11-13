/*
 * Copyright (C) 2020 Canonical, Ltd.
 * Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@ubuntu.com>
 *         Lukas 'slyon' Märdian <lukas.maerdian@canonical.com>
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
#include <glib/gprintf.h>

#include "openvswitch.h"
#include "networkd.h"
#include "parse.h"
#include "util.h"
#include "util-internal.h"

/**
 * Generate the OpenVSwitch systemd units for configuration of the selected netdef
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
gboolean
_netplan_netdef_write_ovs(const NetplanState* np_state, const NetplanNetDefinition* def, const char* rootdir, gboolean* has_been_written, GError** error)
{
    g_autoptr(GString) cmds = g_string_new(NULL);
    g_autofree char* base_config_path = NULL;
    g_autofree char* escaped_netdef_id = g_uri_escape_string(def->id, NULL, TRUE);

    SET_OPT_OUT_PTR(has_been_written, FALSE);

    /* TODO: maybe dynamically query the ovs-vsctl tool path? */

    /* For OVS specific settings, we expect the backend to be set to OVS.
     * The OVS backend is implicitly set, if an interface contains an empty "openvswitch: {}"
     * key, or an "openvswitch:" key, containing more than "external-ids" and/or "other-config". */
    if (def->backend == NETPLAN_BACKEND_OVS) {
        /* Try writing out a base config */
        /* TODO: make use of netplan_netdef_get_output_filename() */
        base_config_path = g_strjoin(NULL, "run/systemd/network/10-netplan-", escaped_netdef_id, NULL);
        if (!_netplan_netdef_write_network_file(np_state, def, rootdir, base_config_path, has_been_written, error))
            return FALSE;
    }
    return TRUE;
}

/**
 * Finalize the OpenVSwitch configuration (global config)
 */
NETPLAN_DEPRECATED gboolean
netplan_state_finish_ovs_write(__unused const NetplanState* np_state, __unused const char* rootdir, __unused GError** error)
{
    return TRUE; // no-op
}

/**
 * Clean up all generated configurations in @rootdir from previous runs.
 */

NETPLAN_DEPRECATED gboolean
_netplan_ovs_cleanup(const char* rootdir)
{
    // Drop after next release (once the sd-generator binary is established), as
    // systemd units are now generated in /run/systemd/generator.late/
    _netplan_unlink_glob(rootdir, "/run/systemd/system/systemd-networkd.service.wants/netplan-ovs-*.service");
    _netplan_unlink_glob(rootdir, "/run/systemd/system/netplan-ovs-*.service");
    return TRUE;
}
