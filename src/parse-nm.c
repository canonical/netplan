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

#include "netplan.h"
#include "parse-nm.h"
#include "parse.h"
#include "util.h"

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
    /* Unsupported type, needs to be specified via passthrough */
    return NETPLAN_DEF_TYPE_NM;
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

static gboolean
_kf_clear_key(GKeyFile* kf, const gchar* group, const gchar* key)
{
    gsize len = 1;
    gboolean ret = FALSE;
    ret = g_key_file_remove_key(kf, group, key, NULL);
    g_strfreev(g_key_file_get_keys(kf, group, &len, NULL));
    /* clear group if this was the last key */
    if (len == 0)
        ret &= g_key_file_remove_group(kf, group, NULL);
    return ret;
}

/* Read the key-value pairs from the keyfile and pass them through to a map */
static void
read_passthrough(GKeyFile* kf, GData** list)
{
    gchar **groups = NULL;
    gchar **keys = NULL;
    gchar *group_key = NULL;
    gchar *value = NULL;
    gsize klen = 0;
    gsize glen = 0;

    if (!*list)
        g_datalist_init(list);
    groups = g_key_file_get_groups(kf, &glen);
    if (groups) {
        for (unsigned i = 0; i < glen; ++i) {
            klen = 0;
            keys = g_key_file_get_keys(kf, groups[i], &klen, NULL);
            if (klen == 0) {
                /* empty group */
                g_datalist_set_data_full(list, g_strconcat(groups[i], ".", NETPLAN_NM_EMPTY_GROUP, NULL), g_strdup(""), g_free);
                continue;
            }
            for (unsigned j = 0; j < klen; ++j) {
                value = g_key_file_get_string(kf, groups[i], keys[j], NULL);
                if (!value) {
                    // LCOV_EXCL_START
                    g_warning("netplan: Keyfile: cannot read value of %s.%s", groups[i], keys[j]);
                    continue;
                    // LCOV_EXCL_STOP
                }
                group_key = g_strconcat(groups[i], ".", keys[j], NULL);
                g_datalist_set_data_full(list, group_key, value, g_free);
                /* no need to free group_key and value: they stay in the list */
            }
            g_strfreev(keys);
        }
        g_strfreev(groups);
    }
}

/**
 * Parse keyfile into a NetplanNetDefinition struct
 * @filename: full path to the NetworkManager keyfile
 */
gboolean
netplan_parse_keyfile(const char* filename, GError** error)
{
    g_autofree gchar *nd_id = NULL;
    g_autofree gchar *uuid = NULL;
    g_autofree gchar *type = NULL;
    g_autofree gchar* wifi_mode = NULL;
    g_autofree gchar* ssid = NULL;
    g_autofree gchar* netdef_id = NULL;
    NetplanNetDefinition* nd = NULL;
    NetplanWifiAccessPoint* ap = NULL;
    g_autoptr(GKeyFile) kf = g_key_file_new();
    NetplanDefType nd_type = NETPLAN_DEF_TYPE_NONE;
    if (!g_key_file_load_from_file(kf, filename, G_KEY_FILE_NONE, error)) {
        g_warning("netplan: cannot load keyfile");
        return FALSE;
    }

    ssid = g_key_file_get_string(kf, "wifi", "ssid", NULL);
    if (!ssid)
        ssid = g_key_file_get_string(kf, "802-11-wireless", "ssid", NULL);

    netdef_id = netplan_get_id_from_nm_filename(filename, ssid);
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
    nd_type = type_from_str(type);

    /* Use previously existing netdef IDs, if available, to override connections
     * Else: generate a "NM-<UUID>" ID */
    if (netdef_id)
        nd_id = g_strdup(netdef_id);
    else
        nd_id = g_strconcat("NM-", uuid, NULL);
    nd = netplan_netdef_new(nd_id, nd_type, NETPLAN_BACKEND_NM);

    /* Handle uuid & NM name/id */
    nd->backend_settings.nm.uuid = g_strdup(uuid);
    _kf_clear_key(kf, "connection", "uuid");
    nd->backend_settings.nm.name = g_key_file_get_string(kf, "connection", "id", NULL);
    if (nd->backend_settings.nm.name)
        _kf_clear_key(kf, "connection", "id");

    if (nd_type == NETPLAN_DEF_TYPE_NM)
        goto only_passthrough; //do not try to handle any keys for connections types unknown to netplan

    /* remove supported values from passthrough, which have been handled */
    if (   nd_type == NETPLAN_DEF_TYPE_ETHERNET
        || nd_type == NETPLAN_DEF_TYPE_WIFI
        || nd_type == NETPLAN_DEF_TYPE_MODEM
        || nd_type == NETPLAN_DEF_TYPE_BRIDGE
        || nd_type == NETPLAN_DEF_TYPE_BOND
        || nd_type == NETPLAN_DEF_TYPE_VLAN)
        _kf_clear_key(kf, "connection", "type");

    /* Handle match: Netplan usually defines a connection per interface, while
     * NM connection profiles are usually applied to any interface of matching
     * type (like wifi/ethernet/...). */
    if (nd->type < NETPLAN_DEF_TYPE_VIRTUAL) {
        nd->match.original_name = g_key_file_get_string(kf, "connection", "interface-name", NULL);
        if (nd->match.original_name)
            _kf_clear_key(kf, "connection", "interface-name");
        /* Set match, even if it is empty, so the NM renderer will not force
         * the netdef ID as interface-name */
        nd->has_match = TRUE;
    }

    /* Modem parameters
     * NM differentiates between GSM and CDMA connections, while netplan
     * combines them as "modems". We need to parse a basic set of parameters
     * to enable the generator (in nm.c) to detect GSM vs CDMA connections,
     * using its modem_is_gsm() util. */
    nd->modem_params.auto_config = g_key_file_get_boolean(kf, "gsm", "auto-config", NULL);
    _kf_clear_key(kf, "gsm", "auto-config");
    nd->modem_params.apn = g_key_file_get_string(kf, "gsm", "apn", NULL);
    if (nd->modem_params.apn)
        _kf_clear_key(kf, "gsm", "apn");
    nd->modem_params.device_id = g_key_file_get_string(kf, "gsm", "device-id", NULL);
    if (nd->modem_params.device_id)
        _kf_clear_key(kf, "gsm", "device-id");
    nd->modem_params.network_id = g_key_file_get_string(kf, "gsm", "network-id", NULL);
    if (nd->modem_params.network_id)
        _kf_clear_key(kf, "gsm", "network-id");
    nd->modem_params.pin = g_key_file_get_string(kf, "gsm", "pin", NULL);
    if (nd->modem_params.pin)
        _kf_clear_key(kf, "gsm", "pin");
    nd->modem_params.sim_id = g_key_file_get_string(kf, "gsm", "sim-id", NULL);
    if (nd->modem_params.sim_id)
        _kf_clear_key(kf, "gsm", "sim-id");
    nd->modem_params.sim_operator_id = g_key_file_get_string(kf, "gsm", "sim-operator-id", NULL);
    if (nd->modem_params.sim_operator_id)
        _kf_clear_key(kf, "gsm", "sim-operator-id");

    /* wake-on-lan, do not clear passthrough as we do not fully support this setting */
    if (g_key_file_has_group(kf, "ethernet")) {
        if (!g_key_file_has_key(kf, "ethernet", "wake-on-lan", NULL)) {
            nd->wake_on_lan = TRUE; //NM's default is "1"
        } else {
            //XXX: fix delta between options in NM (0x1, 0x2, 0x4, ...) and netplan (bool)
            nd->wake_on_lan = g_key_file_get_uint64(kf, "ethernet", "wake-on-lan", NULL) > 0;
        }
    }

    /* Special handling for WiFi "access-points:" mapping */
    if (nd->type == NETPLAN_DEF_TYPE_WIFI) {
        ap = g_new0(NetplanWifiAccessPoint, 1);
        ap->ssid = g_key_file_get_string(kf, "wifi", "ssid", NULL);
        if (!ap->ssid) {
            g_warning("netplan: Keyfile: cannot find SSID for WiFi connection");
            return FALSE;
        } else
            _kf_clear_key(kf, "wifi", "ssid");

        wifi_mode = g_key_file_get_string(kf, "wifi", "mode", NULL);
        if (wifi_mode) {
            ap->mode = ap_type_from_str(wifi_mode);
            if (ap->mode != NETPLAN_WIFI_MODE_OTHER)
                _kf_clear_key(kf, "wifi", "mode");
        }

        ap->hidden = g_key_file_get_boolean(kf, "wifi", "hidden", NULL);
        _kf_clear_key(kf, "wifi", "hidden");

        if (!nd->access_points)
            nd->access_points = g_hash_table_new(g_str_hash, g_str_equal);
        g_hash_table_insert(nd->access_points, ap->ssid, ap);

        /* Last: handle passthrough for everything left in the keyfile
         *       Also, transfer backend_settings from netdef to AP */
        ap->backend_settings.nm.uuid = nd->backend_settings.nm.uuid;
        ap->backend_settings.nm.name = nd->backend_settings.nm.name;
        /* No need to clear nm.uuid & nm.name from def->backend_settings,
         * as we have only one AP. */
        read_passthrough(kf, &ap->backend_settings.nm.passthrough);
    } else {
only_passthrough:
        /* Last: handle passthrough for everything left in the keyfile */
        read_passthrough(kf, &nd->backend_settings.nm.passthrough);
    }

    g_key_file_free(kf);
    return TRUE;
}
