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
#include "parse.h"

static const NetplanDefType
type_from_str(const char* type_str)
{
    if (!g_strcmp0(type_str, "ethernet") || !g_strcmp0(type_str, "802-3-ethernet"))
        return NETPLAN_DEF_TYPE_ETHERNET;
    else if (!g_strcmp0(type_str, "wifi") || !g_strcmp0(type_str, "802-11-wireless"))
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
    /* Full fallback/passthrough mode */
    return NETPLAN_DEF_TYPE_OTHER;
}

/**
 * Render keyfile data to YAML
 */
gboolean
netplan_render_yaml_from_nm_keyfile(GKeyFile* kf, const char* rootdir)
{
    const gchar *hidden = NULL;
    g_autofree gchar *nd_id = NULL;
    g_autofree gchar *uuid = NULL;
    g_autofree gchar *ssid = NULL;
    g_autofree gchar *filename = NULL;
    g_autofree gchar *yaml_path = NULL;
    g_autofree gchar *type = NULL;
    NetplanDefType nd_type = NETPLAN_DEF_TYPE_NONE;
    gchar **groups = NULL;
    gchar **keys = NULL;
    gchar *group_key = NULL;
    gchar *value = NULL;

    uuid = g_key_file_get_string(kf, "connection", "uuid", NULL);
    if (!uuid) {
        g_warning("netplan: Keyfile: cannot find connection.uuid");
        return FALSE;
    }
    type = g_key_file_get_string(kf, "connection", "type", NULL);
    if (!type) {
        g_warning("netplan: Keyfile: cannot find connection.type");
        return FALSE;
    }
    /* Special handling for WiFi "access-points:" mapping */
    nd_type = type_from_str(type);
    if (nd_type == NETPLAN_DEF_TYPE_WIFI) {
        /* "wifi" is an alias for "802-11-wireless" */
        hidden = (   g_key_file_get_boolean(kf, "wifi", "hidden", NULL)
                  || g_key_file_get_boolean(kf, "802-11-wireless", "hidden", NULL)) ? "true" : "false";
        ssid = g_key_file_get_string(kf, "wifi", "ssid", NULL);
        if (!ssid)
            ssid = g_key_file_get_string(kf, "802-11-wireless", "ssid", NULL);
        if (!ssid) {
            g_warning("netplan: Keyfile: cannot find SSID for WiFi connection");
            return FALSE;
        }
    }
    /* NetworkManager produces one file per connection profile */
    filename = g_strconcat("90-NM-", uuid, ".yaml", NULL);
    yaml_path = g_strjoin("/", rootdir ?: "", "etc", "netplan", filename, NULL);

    /* Start rendering YAML output */
    yaml_emitter_t emitter;
    yaml_event_t event;
    FILE *output = fopen(yaml_path, "wb");

    YAML_OUT_START(event, emitter, output);
    /* build the netplan boilerplate YAML structure */
    YAML_SCALAR_PLAIN(event, emitter, "network");
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "version");
    YAML_SCALAR_PLAIN(event, emitter, "2");
    YAML_SCALAR_PLAIN(event, emitter, netplan_def_type_to_str[nd_type]); // ethernets/wifis/modems/others/...
    YAML_MAPPING_OPEN(event, emitter);
    /* Define the actual connection profile with netdef ID: "NM-<UUID>" */
    nd_id = g_strconcat("NM-", uuid, NULL);
    YAML_SCALAR_PLAIN(event, emitter, nd_id);
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "renderer");
    YAML_SCALAR_PLAIN(event, emitter, "NetworkManager"); // use "renderer: NetworkManager"
    /* If this connection is of TYPE_WIFI, we need an "access-points:" mapping,
     * although the passthrough/fallback mechanism can only handle a single SSID (for now). */
    if (nd_type == NETPLAN_DEF_TYPE_WIFI)
        YAML_NETPLAN_WIFI_AP(event, emitter, ssid, hidden);
    /* Backend specific configuration */
    YAML_SCALAR_PLAIN(event, emitter, "networkmanager");
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "uuid");
    YAML_SCALAR_PLAIN(event, emitter, uuid);
    YAML_SCALAR_PLAIN(event, emitter, "passthrough");
    YAML_MAPPING_OPEN(event, emitter);

    /* Pass through the key-value paris from the keyfile */
    gsize klen = 0;
    gsize glen = 0;
    groups = g_key_file_get_groups(kf, &glen);
    if (!groups) goto error;
    for(unsigned i = 0; i < glen; ++i) {
        klen = 0;
        keys = g_key_file_get_keys(kf, groups[i], &klen, NULL);
        if (!keys) continue; /* empty group */
        for(unsigned j = 0; j < klen; ++j) {
            value = g_key_file_get_string(kf, groups[i], keys[j], NULL);
            if (!value) {
                // LCOV_EXCL_START
                g_warning("netplan: Keyfile: cannot read value of %s.%s", groups[i], keys[j]);
                continue;
                // LCOV_EXCL_STOP
            }
            group_key = g_strconcat(groups[i], ".", keys[j], NULL);
            YAML_SCALAR_PLAIN(event, emitter, group_key);
            YAML_SCALAR_QUOTED(event, emitter, value);
            g_free(group_key);
            g_free(value);
        }
        g_strfreev(keys);
    }
    g_strfreev(groups);

    /* Close remaining mappings */
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);

    /* Tear down the YAML emitter */
    YAML_OUT_STOP(event, emitter);
    fclose(output);
    return TRUE;

    // LCOV_EXCL_START
error:
    g_strfreev(groups);
    g_strfreev(keys);
    g_free(group_key);
    g_free(value);
    yaml_emitter_delete(&emitter);
    fclose(output);
    return FALSE;
    // LCOV_EXCL_STOP
}

/* For testing only */
gboolean
_netplan_render_yaml_from_nm_keyfile_str(const char* keyfile_str, const char* rootdir)
{
    /* Pass through the test-data (keyfile string) during testing,
     * until we cann pass the real GKeyFile data from Python */
    g_autoptr(GKeyFile) kf = g_key_file_new();
    g_key_file_load_from_data(kf, keyfile_str, -1, 0, NULL);
    return netplan_render_yaml_from_nm_keyfile(kf, rootdir);
}
