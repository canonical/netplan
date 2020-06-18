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
#include "networkd.h"
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
    g_string_append(s, "RemainAfterExit=yes\n");
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
#define OPENVSWITCH_OVS_OFCTL "/usr/bin/ovs-ofctl"
#define append_systemd_cmd(s, command, ...) \
{ \
    g_string_append(s, "ExecStart="); \
    g_string_append_printf(s, command, __VA_ARGS__); \
    g_string_append(s, "\n"); \
}
#define append_systemd_stop(s, command, ...) \
{ \
    g_string_append(s, "ExecStop="); \
    g_string_append_printf(s, command, __VA_ARGS__); \
    g_string_append(s, "\n"); \
}

static char*
netplan_type_to_table_name(const NetplanDefType type)
{
    switch (type) {
        case NETPLAN_DEF_TYPE_BRIDGE:
            return "Bridge";
        case NETPLAN_DEF_TYPE_BOND:
            return "Port";
        default: /* For regular interfaces and others */
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
write_ovs_additional_data(GHashTable *data, const char* type, const gchar* id, GString* cmds, const char* setting)
{
    GHashTableIter iter;
    gchar* key;
    gchar* value;

    g_hash_table_iter_init(&iter, data);
    while (g_hash_table_iter_next(&iter, (gpointer) &key, (gpointer) &value)) {
        /* XXX: we need to check what happens when an invalid key=value pair
            gets supplied here. We might want to handle this somehow. */
        append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set %s %s %s:%s=%s",
                           type, id, setting, key, value);
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
    append_systemd_stop(cmds, OPENVSWITCH_OVS_VSCTL " del-port %s", def->id);
    g_string_free(s, TRUE);
    return def->bridge;
}

static void
write_ovs_tag_netplan(const gchar* id, GString* cmds)
{
    /* Mark this port as created by netplan */
    append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set Port %s external-ids:netplan=true",
                       id);
}

static void
write_ovs_bond_mode(const NetplanNetDefinition* def, GString* cmds)
{
    /* OVS supports only "active-backup", "balance-tcp" and "balance-slb":
     * http://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.txt */
    if (!strcmp(def->bond_params.mode, "active-backup") ||
        !strcmp(def->bond_params.mode, "balance-tcp") ||
        !strcmp(def->bond_params.mode, "balance-slb")) {
        append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set Port %s bond_mode=%s",
                           def->id, def->bond_params.mode);
    } else {
        g_fprintf(stderr, "%s: bond mode '%s' not supported by openvswitch\n",
                  def->id, def->bond_params.mode);
        exit(1);
    }
}

static void
write_ovs_bridge_interfaces(const NetplanNetDefinition* def, GString* cmds)
{
    NetplanNetDefinition* tmp_nd;
    GHashTableIter iter;
    gchar* key;

    append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " add-br %s", def->id);

    g_hash_table_iter_init(&iter, netdefs);
    while (g_hash_table_iter_next(&iter, (gpointer) &key, (gpointer) &tmp_nd)) {
        if (!g_strcmp0(def->id, tmp_nd->bridge)) {
            append_systemd_cmd(cmds,  OPENVSWITCH_OVS_VSCTL " add-port %s %s", def->id, tmp_nd->id);
            append_systemd_stop(cmds, OPENVSWITCH_OVS_VSCTL " del-port %s %s", def->id, tmp_nd->id);
        }
    }

    append_systemd_stop(cmds, OPENVSWITCH_OVS_VSCTL " del-br %s", def->id);
}

static void
write_ovs_protocols(const NetplanOVSSettings* ovs_settings, const gchar* bridge, GString* cmds)
{
    GString* s = g_string_new(g_array_index(ovs_settings->protocols, char*, 0));

    for (unsigned i = 1; i < ovs_settings->protocols->len; ++i)
        g_string_append_printf(s, ",%s", g_array_index(ovs_settings->protocols, char*, i));

    /* This is typically done per-bridge, but OVS also allows setting protocols
       for when establishing an OpenFlow session. */
    if (bridge) {
        append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set Bridge %s protocols=%s", bridge, s->str);
    }
    else {
        append_systemd_cmd(cmds, OPENVSWITCH_OVS_OFCTL " -O %s", s->str);
    }

    g_string_free(s, TRUE);
}

static gboolean
check_ovs_ssl(gchar* target)
{
    /* Check if target needs ssl */
    if (g_str_has_prefix(target, "ssl:") || g_str_has_prefix(target, "pssl:")) {
        /* Check if SSL is configured in ovs_settings_global.ssl */
        if (!ovs_settings_global.ssl.ca_certificate || !ovs_settings_global.ssl.client_certificate ||
            !ovs_settings_global.ssl.client_key) {
            g_fprintf(stderr, "ERROR: openvswitch bridge controller target '%s' needs SSL configuration, but global 'openvswitch.ssl' settings are not set\n", target);
            exit(1);
        }
        return TRUE;
    }
    return FALSE;
}

static void
write_ovs_bridge_controller_targets(const NetplanOVSController* controller, const gchar* bridge, GString* cmds)
{
    gchar* target = g_array_index(controller->addresses, char*, 0);
    gboolean needs_ssl = check_ovs_ssl(target);
    GString* s = g_string_new(target);

    for (unsigned i = 1; i < controller->addresses->len; ++i) {
        target = g_array_index(controller->addresses, char*, i);
        if (!needs_ssl)
            needs_ssl = check_ovs_ssl(target);
        g_string_append_printf(s, " %s", target);
    }

    append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set-controller %s %s", bridge, s->str);
    g_string_free(s, TRUE);
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
    gchar* dependency = NULL;
    const char* type = netplan_type_to_table_name(def->type);
    g_autofree char* base_config_path = NULL;

    id_escaped = systemd_escape(def->id);

    /* TODO: error out on non-existing ovs-vsctl tool */
    /* TODO: maybe dynamically query the ovs-vsctl tool path? */

    /* For other, more OVS specific settings, we expect the backend to be set to OVS.
     * The OVS backend is implicitly set, if an interface contains an empty "openvswitch: {}"
     * key, or an "openvswitch:" key containing only "external-ids" or "other-config". */
    if (def->backend == NETPLAN_BACKEND_OVS) {
        switch (def->type) {
            case NETPLAN_DEF_TYPE_BOND:
                dependency = write_ovs_bond_interfaces(def, cmds);
                write_ovs_tag_netplan(def->id, cmds);
                /* Set LACP mode, default to "off" */
                append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set Port %s lacp=%s",
                                   def->id, def->ovs_settings.lacp? def->ovs_settings.lacp : "off");
                if (def->bond_params.mode) {
                    write_ovs_bond_mode(def, cmds);
                }
                break;

            case NETPLAN_DEF_TYPE_BRIDGE:
                write_ovs_bridge_interfaces(def, cmds);
                write_ovs_tag_netplan(def->id, cmds);
                /* Set fail-mode, default to "standalone" */
                append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set-fail-mode %s %s",
                                   def->id, def->ovs_settings.fail_mode? def->ovs_settings.fail_mode : "standalone");
                /* Enable/disable mcast-snooping */ 
                append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set Bridge %s mcast_snooping_enable=%s",
                                   def->id, def->ovs_settings.mcast_snooping? "true" : "false");
                /* Enable/disable rstp */
                append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set Bridge %s rstp_enable=%s",
                                   def->id, def->ovs_settings.rstp? "true" : "false");
                /* Set protocols */
                if (def->ovs_settings.protocols && def->ovs_settings.protocols->len > 0) {
                    write_ovs_protocols(&(def->ovs_settings), def->id, cmds);
                }
                /* Set controller target addresses */
                if (def->ovs_settings.controller.addresses && def->ovs_settings.controller.addresses->len > 0) {
                    write_ovs_bridge_controller_targets(&(def->ovs_settings.controller), def->id, cmds);
                    /* Set controller connection mode, only applicable if at least one controller target address was set */
                    if (def->ovs_settings.controller.connection_mode)
                        append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set controller %s connection-mode=%s", def->id, def->ovs_settings.controller.connection_mode);
                }
                break;

            case NETPLAN_DEF_TYPE_PORT:
                g_assert(def->peer);
                dependency = def->bridge?: def->bond;
                if (!dependency) {
                    g_fprintf(stderr, "%s: OpenVSwitch patch port needs to be assigned to a bridge/bond\n", def->id);
                    exit(1);
                }
                append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set Interface %s type=patch", def->id);
                append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set Interface %s options:peer=%s", def->id, def->peer);
                append_systemd_stop(cmds, OPENVSWITCH_OVS_VSCTL " --if-exists del-port %s", def->id);
                break;

            default: g_assert_not_reached(); // LCOV_EXCL_LINE
        }

        /* Try writing out a base config */
        base_config_path = g_strjoin(NULL, "run/systemd/network/10-netplan-", id_escaped, NULL);
        write_network_file(def, rootdir, base_config_path);
    } else {
        g_debug("openvswitch: definition %s is not for us (backend %i)", def->id, def->backend);
    }

    /* Set "external-ids" and "other-config" after NETPLAN_BACKEND_OVS interfaces, as bonds,
     * bridges, etc. might just be created before.*/

    /* Common OVS settings can be specified even for non-OVS interfaces */
    if (def->ovs_settings.external_ids && g_hash_table_size(def->ovs_settings.external_ids) > 0) {
        write_ovs_additional_data(def->ovs_settings.external_ids, type,
                                  def->id, cmds, "external-ids");
    }

    if (def->ovs_settings.other_config && g_hash_table_size(def->ovs_settings.other_config) > 0) {
        write_ovs_additional_data(def->ovs_settings.other_config, type,
                                  def->id, cmds, "other-config");
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

    if (ovs_settings_global.protocols && ovs_settings_global.protocols->len > 0) {
        write_ovs_protocols(&ovs_settings_global, NULL, cmds);
    }

    if (ovs_settings_global.ssl.client_key && ovs_settings_global.ssl.client_certificate &&
        ovs_settings_global.ssl.ca_certificate) {
        append_systemd_cmd(cmds, OPENVSWITCH_OVS_VSCTL " set-ssl %s %s %s",
                           ovs_settings_global.ssl.client_key,
                           ovs_settings_global.ssl.client_certificate,
                           ovs_settings_global.ssl.ca_certificate);
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
