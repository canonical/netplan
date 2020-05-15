/*
 * Copyright (C) 2020 Canonical, Ltd.
 * Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@ubuntu.com>
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

#include <glib.h>
#include <glib/gprintf.h>

#include "openvswitch.h"
#include "parse.h"
#include "util.h"

static void
write_ovs_systemd_unit(const char* id, const GString* cmds, const char* rootdir)
{
    g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/systemd-networkd.service.wants/netplan-ovs-", id, ".service", NULL);
    g_autofree char* slink = g_strjoin(NULL, "/run/systemd/system/netplan-ovs-", id, ".service", NULL);
    g_autofree char* path = g_strjoin(NULL, "/run/systemd/system/netplan-ovs-", id, ".service", NULL);

    GString* s = g_string_new("[Unit]\n");
    g_string_append_printf(s, "Description=OpenVSwitch configuration for %s\n", id);
    g_string_append(s, "DefaultDependencies=no\n");
    g_string_append_printf(s, "Requires=sys-subsystem-net-devices-%s.device\n", id);
    g_string_append_printf(s, "After=sys-subsystem-net-devices-%s.device\n", id);
    g_string_append(s, "Before=network.target\nWants=network.target\n\n");

    g_string_append(s, "[Service]\nType=oneshot\n");
    g_string_append(s, cmds->str);

    g_string_free_to_file(s, rootdir, path, NULL);

    safe_mkdir_p_dir(link);
    if (symlink(slink, link) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to create enablement symlink: %m\n");
        exit(1);
        // LCOV_EXCL_STOP
    }
}

#define OPENVSWITCH_OVS_VSCTL "/usr/bin/ovs-vsctl"
#define append_systemd_cmd(s, command, ...) \
{ \
    g_string_append(s, "ExecStart="); \
    g_string_append_printf(s, command, __VA_ARGS__); \
    g_string_append(s, "\n"); \
}

static char*
netplan_type_to_table_name(const NetplanDefType type)
{
    switch (type) {
        case NETPLAN_DEF_TYPE_BRIDGE:
            return "Bridge";
        default:
            return "Interface";
    }
}

static void
write_ovs_additional_data(GHashTable *data, const NetplanDefType type, const gchar* id_escaped, GString* cmds, const char* setting)
{
    GHashTableIter iter;
    gchar* key;
    gchar* value;

    g_hash_table_iter_init(&iter, data);
    while (g_hash_table_iter_next(&iter, (gpointer) &key, (gpointer) &value)) {
        append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set %s %s %s:%s=%s",
                           netplan_type_to_table_name(type), id_escaped, setting, key, value);
    }
}

/**
 * Generate the OpenVSwitch systemd units for configuration of the selected netdef
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
void
write_ovs_conf(const NetplanNetDefinition* def, const char* rootdir)
{
    GString* cmds = g_string_new(NULL);
    g_autofree gchar* id_escaped = NULL; // TODO: Check if this works

    id_escaped = systemd_escape(def->id);

    /* TODO: error out on non-existing ovs-vsctl tool */
    /* TODO: maybe dynamically query the ovs-vsctl tool path? */

    /* Common OVS settings can be specified even for non-OVS interfaces */
    if (def->ovs_settings.external_ids && g_hash_table_size(def->ovs_settings.external_ids) > 0) {
        write_ovs_additional_data(def->ovs_settings.external_ids, def->type,
                                          id_escaped, cmds, "external-ids");
    }

    if (def->ovs_settings.other_config && g_hash_table_size(def->ovs_settings.other_config) > 0) {
        write_ovs_additional_data(def->ovs_settings.other_config, def->type,
                                          id_escaped, cmds, "other-config");
    }

    /* For other, more OVS specific settings, we expect the backend to be set to OVS */
    if (def->backend == NETPLAN_BACKEND_OVS) {
        /* TODO */
    } else {
        g_debug("openvswitch: definition %s is not for us (backend %i)", def->id, def->backend);
    }

    /* If we need to configure anything for this netdef, write the required systemd unit */
    if (cmds->len > 0)
        write_ovs_systemd_unit(id_escaped, cmds, rootdir);
    g_string_free(cmds, TRUE);
}

/**
 * Finalize the OpenVSwitch configuration (global config)
 */
void
write_ovs_conf_finish(const char* rootdir)
{
    /* TODO: Write the global config here */
}

/**
 * Clean up all generated configurations in @rootdir from previous runs.
 */
void
cleanup_ovs_conf(const char* rootdir)
{
    //unlink_glob(rootdir, "/run/systemd/system/systemd-networkd.service.wants/netplan-ovs-*.service");
    //unlink_glob(rootdir, "/run/systemd/system/netplan-ovs-*.service");
}
