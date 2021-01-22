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

/**
 * NetworkManager writes the alias for '802-3-ethernet' (ethernet),
 * '802-11-wireless' (wifi) and '802-11-wireless-security' (wifi-security)
 * by default, so we only need to check for those. See:
 * https://bugzilla.gnome.org/show_bug.cgi?id=696940
 * https://gitlab.freedesktop.org/NetworkManager/NetworkManager/-/commit/c36200a225aefb2a3919618e75682646899b82c0
 * nm_keyfile_plugin_kf_set* from nm-keyfile-utils.c (libnm-core)
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
    /* Full fallback/passthrough mode */
    return NETPLAN_DEF_TYPE_OTHER;
}

static gboolean
write_backend_settings(yaml_event_t* event, yaml_emitter_t* emitter, GKeyFile* kf, char* uuid) {
    gchar **groups = NULL;
    gchar **keys = NULL;
    gchar *group_key = NULL;
    gchar *value = NULL;

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

    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    return TRUE;

    // LCOV_EXCL_START
error:
    g_strfreev(groups);
    g_strfreev(keys);
    g_free(group_key);
    g_free(value);
    return FALSE;
    // LCOV_EXCL_STOP
}

/* Adding a simple boolean value below, just to produce a valid "access-points:" mapping */
static gboolean
write_access_point(yaml_event_t* event, yaml_emitter_t* emitter, GKeyFile* kf, char* uuid, char* ssid, char* wifi_mode, const char* hidden)
{
    YAML_SCALAR_PLAIN(event, emitter, "access-points");
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_QUOTED(event, emitter, ssid);
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "hidden");
    YAML_SCALAR_PLAIN(event, emitter, hidden);
    YAML_SCALAR_PLAIN(event, emitter, "mode");
    if (wifi_mode && (!g_strcmp0(wifi_mode, "infrastructure") || !g_strcmp0(wifi_mode, "ap") || !g_strcmp0(wifi_mode, "adhoc"))) {
        YAML_SCALAR_PLAIN(event, emitter, wifi_mode);
        g_key_file_remove_key(kf, "wifi", "mode", NULL); //handled, remove passthrough
    } else {
        YAML_SCALAR_PLAIN(event, emitter, "INVALID-use-fallback");
    }

    if (!write_backend_settings(event, emitter, kf, uuid))
        goto error;

    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    return TRUE;
error:
    return FALSE;
}

static gboolean
write_match(yaml_event_t* event, yaml_emitter_t* emitter, char* interface_name)
{
    //FIXME: interface-name=
    YAML_SCALAR_PLAIN(event, emitter, "match");
    YAML_MAPPING_OPEN(event, emitter);

    YAML_SCALAR_PLAIN(event, emitter, "name");
    if (interface_name)
        YAML_SCALAR_QUOTED(event, emitter, interface_name)
    else //NM can apply this connection profile to any interface
        YAML_SCALAR_QUOTED(event, emitter, "*");
    YAML_MAPPING_CLOSE(event, emitter);
    return TRUE;
error:
    return FALSE;
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
    g_autofree gchar* interface_name = NULL;
    g_autofree gchar* wifi_mode = NULL;
    NetplanDefType nd_type = NETPLAN_DEF_TYPE_NONE;

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
    interface_name = g_key_file_get_string(kf, "connection", "interface-name", NULL);
    /* Special handling for WiFi "access-points:" mapping */
    nd_type = type_from_str(type);
    if (nd_type == NETPLAN_DEF_TYPE_WIFI) {
        //TODO: AP mode!
        hidden = (g_key_file_get_boolean(kf, "wifi", "hidden", NULL)) ? "true" : "false";
        wifi_mode = g_key_file_get_string(kf, "wifi", "mode", NULL);
        ssid = g_key_file_get_string(kf, "wifi", "ssid", NULL);
        if (!ssid) {
            g_warning("netplan: Keyfile: cannot find SSID for WiFi connection");
            return FALSE;
        }
    }
    /* NetworkManager produces one file per connection profile */
    filename = g_strconcat("90-NM-", uuid, ".yaml", NULL);
    yaml_path = g_strjoin("/", rootdir ?: "", "etc", "netplan", filename, NULL);

    /* Start rendering YAML output */
    yaml_emitter_t emitter_data;
    yaml_event_t event_data;
    yaml_emitter_t* emitter = &emitter_data;
    yaml_event_t* event = &event_data;
    FILE *output = fopen(yaml_path, "wb");

    YAML_OUT_START(event, emitter, output);
    /* build the netplan boilerplate YAML structure */
    YAML_SCALAR_PLAIN(event, emitter, "network");
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "version");
    YAML_SCALAR_PLAIN(event, emitter, "2");
    YAML_SCALAR_PLAIN(event, emitter, netplan_def_type_to_str[nd_type]); // ethernets/wifis/modems/others/...
    //FIXME: wireguard vs ip-tunnel, gsm vs cdma
    if (   nd_type == NETPLAN_DEF_TYPE_ETHERNET
        || nd_type == NETPLAN_DEF_TYPE_WIFI
        || nd_type == NETPLAN_DEF_TYPE_BRIDGE
        || nd_type == NETPLAN_DEF_TYPE_BOND
        || nd_type == NETPLAN_DEF_TYPE_VLAN)
        g_key_file_remove_key(kf, "connection", "type", NULL); //properly handled, remove passthrough //TODO: error handling?
    YAML_MAPPING_OPEN(event, emitter);
    /* Define the actual connection profile with netdef ID: "NM-<UUID>" */
    nd_id = g_strconcat("NM-", uuid, NULL);
    YAML_SCALAR_PLAIN(event, emitter, nd_id);
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "renderer");
    YAML_SCALAR_PLAIN(event, emitter, "NetworkManager"); // use "renderer: NetworkManager"
    if (!write_match(event, emitter, interface_name)) goto error;
    g_key_file_remove_key(kf, "connection", "interface-name", NULL); //properly handled, remove passthrough
    /* If this connection is of TYPE_WIFI, we need an "access-points:" mapping,
     * although the passthrough/fallback mechanism can only handle a single SSID (for now). */
    if (nd_type == NETPLAN_DEF_TYPE_WIFI) {
        write_access_point(event, emitter, kf, uuid, ssid, wifi_mode, hidden);
        g_key_file_remove_key(kf, "wifi", "hidden", NULL); //properly handled, remove passthrough
    } else if (!write_backend_settings(event, emitter, kf, uuid))
        goto error;

    /* Close remaining mappings */
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);

    /* Tear down the YAML emitter */
    YAML_OUT_STOP(event, emitter);
    fclose(output);
    return TRUE;

    // LCOV_EXCL_START
error:
    yaml_emitter_delete(emitter);
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
