/*
 * Copyright (C) 2021 Canonical, Ltd.
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

#include <glib.h>
#include <yaml.h>

#include "nm-keyfile.h"
#include "serialize.h"
#include "parse.h"

/**
 * NetworkManager writes the alias for '802-3-ethernet' (ethernet),
 * '802-11-wireless' (wifi) and '802-11-wireless-security' (wifi-security)
 * by default, so we only need to check for those. See:
 * https://bugzilla.gnome.org/show_bug.cgi?id=696940
 * https://gitlab.freedesktop.org/NetworkManager/NetworkManager/-/commit/c36200a225aefb2a3919618e75682646899b82c0
 */
static const NetplanDefType
type_from_str(const char* type_str)
{
    if (!g_strcmp0(type_str, "ethernet"))
        return NETPLAN_DEF_TYPE_ETHERNET;
    else if (!g_strcmp0(type_str, "wifi"))
        return NETPLAN_DEF_TYPE_WIFI;
    else if (!g_strcmp0(type_str, "gsm") || !g_strcmp0(type_str, "cdma"))
        return NETPLAN_DEF_TYPE_MODEM;
    else if (!g_strcmp0(type_str, "bridge"))
        return NETPLAN_DEF_TYPE_BRIDGE;
    else if (!g_strcmp0(type_str, "bond"))
        return NETPLAN_DEF_TYPE_BOND;
    else if (!g_strcmp0(type_str, "vlan"))
        return NETPLAN_DEF_TYPE_VLAN;
    else if (!g_strcmp0(type_str, "ip-tunnel") || !g_strcmp0(type_str, "wireguard"))
        return NETPLAN_DEF_TYPE_TUNNEL;
    /* Unsupported type, needs to be specified via passthrough */
    return NETPLAN_DEF_TYPE_OTHER;
}

static const NetplanWifiMode
ap_type_from_str(const char* type_str)
{
    if (!g_strcmp0(type_str, "infrastructure"))
        return NETPLAN_WIFI_MODE_INFRASTRUCTURE;
    else if (!g_strcmp0(type_str, "ap"))
        return NETPLAN_WIFI_MODE_AP;
    else if (!g_strcmp0(type_str, "adhoc"))
        return NETPLAN_WIFI_MODE_ADHOC;
    /* Unsupported mode, like "mesh" */
    return NETPLAN_WIFI_MODE_OTHER;
}

/* Read the key-value pairs from the keyfile and pass them through to a map */
static void
read_passthrough(GKeyFile* kf, GHashTable** out_map)
{
    gchar **groups = NULL;
    gchar **keys = NULL;
    gchar *group_key = NULL;
    gchar *value = NULL;
    gsize klen = 0;
    gsize glen = 0;

    if (!*out_map)
        *out_map = g_hash_table_new(g_str_hash, g_str_equal);
    groups = g_key_file_get_groups(kf, &glen);
    if (groups) {
        for(unsigned i = 0; i < glen; ++i) {
            klen = 0;
            keys = g_key_file_get_keys(kf, groups[i], &klen, NULL);
            if (!keys) continue; // empty group
            for(unsigned j = 0; j < klen; ++j) {
                value = g_key_file_get_string(kf, groups[i], keys[j], NULL);
                if (!value) {
                    // LCOV_EXCL_START
                    g_warning("netplan: Keyfile: cannot read value of %s.%s", groups[i], keys[j]);
                    continue;
                    // LCOV_EXCL_STOP
                }
                group_key = g_strconcat(groups[i], ".", keys[j], NULL);
                g_hash_table_insert(*out_map, group_key, value);
                /* no need to free group_key and value: they stay in the map */
            }
            g_strfreev(keys);
        }
        g_strfreev(groups);
    }
}

/**
 * Render keyfile data to YAML
 */
gboolean
netplan_render_yaml_from_nm_keyfile(GKeyFile* kf, const char* rootdir)
{
    g_autofree gchar *nd_id = NULL;
    g_autofree gchar *uuid = NULL;
    g_autofree gchar *ssid = NULL;
    g_autofree gchar *filename = NULL;
    g_autofree gchar *yaml_path = NULL;
    g_autofree gchar *type = NULL;
    g_autofree gchar* wifi_mode = NULL;
    NetplanDefType nd_type = NETPLAN_DEF_TYPE_NONE;
    NetplanNetDefinition* nd = NULL;
    NetplanWifiAccessPoint* ap = NULL;

    uuid = g_key_file_get_string(kf, "connection", "uuid", NULL);
    if (!uuid) {
        g_warning("netplan: Keyfile: cannot find connection.uuid");
        return FALSE;
    }
    nd_id = g_strconcat("NM-", uuid, NULL);

    /* NetworkManager produces one file per connection profile */
    filename = g_strconcat("90-NM-", uuid, ".yaml", NULL);
    yaml_path = g_strjoin("/", rootdir ?: "", "etc", "netplan", filename, NULL);

    type = g_key_file_get_string(kf, "connection", "type", NULL);
    if (!type) {
        g_warning("netplan: Keyfile: cannot find connection.type");
        return FALSE;
    }
    nd_type = type_from_str(type);

    nd = netplan_netdef_new(nd_id, nd_type, NETPLAN_BACKEND_NM);
    /* remove supported values from passthrough, which have been handled */
    if (   nd_type == NETPLAN_DEF_TYPE_ETHERNET
        || nd_type == NETPLAN_DEF_TYPE_WIFI
        || nd_type == NETPLAN_DEF_TYPE_BRIDGE
        || nd_type == NETPLAN_DEF_TYPE_BOND
        || nd_type == NETPLAN_DEF_TYPE_VLAN)
        g_key_file_remove_key(kf, "connection", "type", NULL);

    /* Handle uuid & NM name/id */
    nd->backend_settings.nm.uuid = g_strdup(uuid);
    g_key_file_remove_key(kf, "connection", "uuid", NULL);
    nd->backend_settings.nm.name = g_key_file_get_string(kf, "connection", "id", NULL);
    if (nd->backend_settings.nm.name)
        g_key_file_remove_key(kf, "connection", "id", NULL);

    /* Handle match */
    nd->match.original_name = g_key_file_get_string(kf, "connection", "interface-name", NULL);
    if (nd->match.original_name)
        g_key_file_remove_key(kf, "connection", "interface-name", NULL);
    else
        nd->match.original_name = g_strdup("*");
    nd->has_match = TRUE;

    /* Special handling for WiFi "access-points:" mapping */
    if (nd->type == NETPLAN_DEF_TYPE_WIFI) {
        ap = g_new0(NetplanWifiAccessPoint, 1);
        ap->ssid = g_key_file_get_string(kf, "wifi", "ssid", NULL);
        if (!ap->ssid) {
            g_warning("netplan: Keyfile: cannot find SSID for WiFi connection");
            return FALSE;
        } else
            g_key_file_remove_key(kf, "wifi", "ssid", NULL);

        wifi_mode = g_key_file_get_string(kf, "wifi", "mode", NULL);
        if (wifi_mode) {
            ap->mode = ap_type_from_str(wifi_mode);
            if (ap->mode != NETPLAN_WIFI_MODE_OTHER)
                g_key_file_remove_key(kf, "wifi", "mode", NULL);
        }

        ap->hidden = g_key_file_get_boolean(kf, "wifi", "hidden", NULL);
        g_key_file_remove_key(kf, "wifi", "hidden", NULL);

        if (!nd->access_points)
            nd->access_points = g_hash_table_new(g_str_hash, g_str_equal);
        g_hash_table_insert(nd->access_points, ap->ssid, ap);

        /* Last: handle passthrough for everything left in the keyfile
         *       Also, transfer backend_settings from netdef to AP */
        ap->backend_settings.nm.uuid = nd->backend_settings.nm.uuid;
        ap->backend_settings.nm.name = nd->backend_settings.nm.name;
        nd->backend_settings.nm.uuid = NULL;
        nd->backend_settings.nm.name = NULL;
        read_passthrough(kf, &ap->backend_settings.nm.passthrough);
    } else {
        /* Last: handle passthrough for everything left in the keyfile */
        read_passthrough(kf, &nd->backend_settings.nm.passthrough);
    }

    return netplan_render_netdef(nd, yaml_path);
}

/**
 * Helper function for testing only, to pass through the test-data
 * (keyfile string) until we cann pass the real GKeyFile data from python. */
gboolean
_netplan_render_yaml_from_nm_keyfile_str(const char* keyfile_str, const char* rootdir)
{
    g_autoptr(GKeyFile) kf = g_key_file_new();
    g_key_file_load_from_data(kf, keyfile_str, -1, 0, NULL);
    return netplan_render_yaml_from_nm_keyfile(kf, rootdir);
}

/**
 * Extract the netplan netdef ID from a NetworkManager connection profile (keyfile),
 * generated by netplan. Used by the NetworkManager YAML backend.
 */
gchar*
netplan_get_id_from_nm_filename(const char* filename, const char* ssid)
{
    g_autofree gchar* escaped_ssid = NULL;
    g_autofree gchar* suffix = NULL;
    const char* nm_prefix = "/run/NetworkManager/system-connections/netplan-";
    const char* start = filename;
    const char* end = NULL;
    gsize id_len = 0;

    if (!g_str_has_prefix(filename, nm_prefix))
        return NULL;

    if (ssid) {
        escaped_ssid = g_uri_escape_string(ssid, NULL, TRUE);
        suffix = g_strdup_printf("-%s.nmconnection", escaped_ssid);
        end = g_strrstr(filename, suffix);
    } else
        end = g_strrstr(filename, ".nmconnection");

    if (!end)
        return NULL;

    /* Move pointer to start of netplan ID inside filename string */
    start = start + strlen(nm_prefix);
    id_len = end - start;
    return g_strndup(start, id_len);
}
