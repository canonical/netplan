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

#include <glib.h>
#include <glib/gprintf.h>

#include "openvswitch.h"
#include "parse.h"
#include "util.h"

static void
write_ovs_systemd_unit(const char* id, const GString* cmds, const char* rootdir, gboolean physical, const char* dependency)
{
    g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/systemd-networkd.service.wants/netplan-ovs-", id, ".service", NULL);
    g_autofree char* path = g_strjoin(NULL, "/run/systemd/system/netplan-ovs-", id, ".service", NULL);

    GString* s = g_string_new("[Unit]\n");
    g_string_append_printf(s, "Description=OpenVSwitch configuration for %s\n", id);
    g_string_append(s, "DefaultDependencies=no\n");
    if (physical) {
        g_string_append_printf(s, "Requires=sys-subsystem-net-devices-%s.device\n", id);
        g_string_append_printf(s, "After=sys-subsystem-net-devices-%s.device\n", id);
    }
    g_string_append(s, "Before=network.target\nWants=network.target\n");
    if (dependency) {
        g_string_append_printf(s, "Requires=netplan-ovs-%s.service\n", dependency);
        g_string_append_printf(s, "After=netplan-ovs-%s.service\n", dependency);
    }

    g_string_append(s, "\n[Service]\nType=oneshot\n");
    g_string_append(s, cmds->str);

    g_string_free_to_file(s, rootdir, path, NULL);

    safe_mkdir_p_dir(link);
    if (symlink(path, link) < 0 && errno != EEXIST) {
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
        default: /* For regular interfaces, bonds and others */
            return "Interface";
    }
}

static gboolean
netplan_type_is_physical(const NetplanDefType type)
{
    switch (type) {
        case NETPLAN_DEF_TYPE_ETHERNET:
        // case NETPLAN_DEF_TYPE_WIFI:
        // case NETPLAN_DEF_TYPE_MODEM:
            return TRUE;
        default:
            return FALSE;
    }
}

static void
write_ovs_additional_data(GHashTable *data, const char* type, const gchar* id_escaped, GString* cmds, const char* setting)
{
    GHashTableIter iter;
    gchar* key;
    gchar* value;

    g_hash_table_iter_init(&iter, data);
    while (g_hash_table_iter_next(&iter, (gpointer) &key, (gpointer) &value)) {
        /* XXX: we need to check what happens when an invalid key=value pair
            gets supplied here. We might want to handle this somehow. */
        append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set %s %s %s:%s=%s",
                           type, id_escaped, setting, key, value);
    }
}

static char*
write_ovs_bond_interfaces(const NetplanNetDefinition* def, GString* cmds)
{
    NetplanNetDefinition* tmp_nd;
    GHashTableIter iter;
    gchar* key;
    guint i = 0;
    GString* s = NULL;

    if (!def->bridge) {
        g_fprintf(stderr, "Bond %s needs to be a slave of an OpenVSwitch bridge\n", def->id);
        exit(1);
    }
    tmp_nd = g_hash_table_lookup(netdefs, def->bridge);
    if (!tmp_nd || tmp_nd->backend != NETPLAN_BACKEND_OVS) {
        g_fprintf(stderr, "Bond %s: %s needs to be handled by OpenVSwitch\n", def->id, tmp_nd->id);
        exit(1);
    }

    s = g_string_new(OPENVSWITCH_OVS_VSCTL " add-bond");
    g_string_append_printf(s, " %s %s", def->bridge, def->id);

    g_hash_table_iter_init(&iter, netdefs);
    while (g_hash_table_iter_next(&iter, (gpointer) &key, (gpointer) &tmp_nd)) {
        if (!g_strcmp0(def->id, tmp_nd->bond)) {
            /* Append and count bond interfaces */
            g_string_append_printf(s, " %s", tmp_nd->id);
            i++;
        }
    }
    if (i < 2) {
        g_fprintf(stderr, "Bond %s needs to have at least 2 slave interfaces\n", def->id);
        exit(1);
    }

    append_systemd_cmd(cmds, s->str, def->bridge, def->id);
    g_string_free(s, TRUE);
    return def->bridge;
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
    g_autofree gchar* id_escaped = NULL;
    g_autofree gchar* dependency = NULL;
    const char* type = netplan_type_to_table_name(def->type);

    id_escaped = systemd_escape(def->id);

    /* TODO: error out on non-existing ovs-vsctl tool */
    /* TODO: maybe dynamically query the ovs-vsctl tool path? */

    /* Common OVS settings can be specified even for non-OVS interfaces */
    if (def->ovs_settings.external_ids && g_hash_table_size(def->ovs_settings.external_ids) > 0) {
        write_ovs_additional_data(def->ovs_settings.external_ids, type,
                                  id_escaped, cmds, "external-ids");
    }

    if (def->ovs_settings.other_config && g_hash_table_size(def->ovs_settings.other_config) > 0) {
        write_ovs_additional_data(def->ovs_settings.other_config, type,
                                  id_escaped, cmds, "other-config");
    }

    /* For other, more OVS specific settings, we expect the backend to be set to OVS.
     * The OVS backend is implicitly set, if an interface contains the "openvswitch:" key. */
    if (def->backend == NETPLAN_BACKEND_OVS) {
        switch (def->type) {
            case NETPLAN_DEF_TYPE_BOND:
                dependency = write_ovs_bond_interfaces(def, cmds);
                append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set port %s lacp=%s",
                                   def->id, def->ovs_settings.lacp? def->ovs_settings.lacp : "off");
                break;

            default:
                break;
        }
    } else {
        g_debug("openvswitch: definition %s is not for us (backend %i)", def->id, def->backend);
    }

    /* If we need to configure anything for this netdef, write the required systemd unit */
    if (cmds->len > 0)
        write_ovs_systemd_unit(id_escaped, cmds, rootdir, netplan_type_is_physical(def->type), dependency);
    g_string_free(cmds, TRUE);
}

/**
 * Finalize the OpenVSwitch configuration (global config)
 */
void
write_ovs_conf_finish(const char* rootdir)
{
    GString* cmds = g_string_new(NULL);

    /* Global external-ids and other-config settings */
    if (ovs_settings_global.external_ids && g_hash_table_size(ovs_settings_global.external_ids) > 0) {
        write_ovs_additional_data(ovs_settings_global.external_ids, "open_vswitch",
                                  ".", cmds, "external-ids");
    }

    if (ovs_settings_global.other_config && g_hash_table_size(ovs_settings_global.other_config) > 0) {
        write_ovs_additional_data(ovs_settings_global.other_config, "open_vswitch",
                                  ".", cmds, "other-config");
    }

    /* TODO: Add any additional base OVS config we might need */

    if (cmds->len > 0)
        write_ovs_systemd_unit("global", cmds, rootdir, FALSE, NULL);
    g_string_free(cmds, TRUE);
}

/**
 * Clean up all generated configurations in @rootdir from previous runs.
 */
void
cleanup_ovs_conf(const char* rootdir)
{
    unlink_glob(rootdir, "/run/systemd/system/systemd-networkd.service.wants/netplan-ovs-*.service");
    unlink_glob(rootdir, "/run/systemd/system/netplan-ovs-*.service");
}
