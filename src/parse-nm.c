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

static gboolean
kf_matches(GKeyFile* kf, const gchar* group, const gchar* key, const gchar* match)
{
    g_autofree gchar *kf_value = NULL;
    kf_value = g_key_file_get_string(kf, group, key, NULL);
    return g_strcmp0(kf_value, match) == 0;
}

static gboolean
set_true_on_match(GKeyFile* kf, const gchar* group, const gchar* key, const gchar* match, const void* dataptr)
{
    g_assert(dataptr);
    if (kf_matches(kf, group, key, match)) {
        *((gboolean*) dataptr) = TRUE;
        _kf_clear_key(kf, group, key);
        return TRUE;
    }
    return FALSE;
}

static gboolean
handle_generic_str(GKeyFile* kf, const gchar* group, const gchar* key, char** dataptr)
{
    g_assert(dataptr);
    g_assert(!*dataptr);
    *dataptr = g_key_file_get_string(kf, group, key, NULL);
    if (*dataptr)
        _kf_clear_key(kf, group, key);
    return TRUE;
}

static gboolean
parse_addresses(GKeyFile* kf, const gchar* group, GArray** ip_arr)
{
    g_assert(ip_arr);
    if (kf_matches(kf, group, "method", "manual")) {
        gboolean unhandled_data = FALSE;
        gchar *key = NULL;
        gchar *kf_value = NULL;
        gchar **split = NULL;
        for (unsigned i = 1;; ++i) {
            key = g_strdup_printf("address%u", i);
            kf_value = g_key_file_get_string(kf, group, key, NULL);
            if (!kf_value) {
                g_free(key);
                break;
            }
            if (!*ip_arr)
                *ip_arr = g_array_new(FALSE, FALSE, sizeof(char*));
            split = g_strsplit(kf_value, ",", 2);
            /* Append "address/prefix" */
            if (split[0]) {
                /* no need to free 's', this will stay in the netdef */
                char* s = g_strdup(split[0]);
                g_array_append_val(*ip_arr, s);
            }
            if (!split[1])
                _kf_clear_key(kf, group, key);
            else
                unhandled_data = TRUE; //FIXME: how to handle additional values (like "gateway") in split[n]?
            g_free(key);
            g_strfreev(split);
            g_free(kf_value);
        }
        /* clear keyfile once all data was handled */
        if (!unhandled_data)
            _kf_clear_key(kf, group, "method");
    }
    return TRUE;
}

static gboolean
parse_dhcp_overrides(GKeyFile* kf, const gchar* group, NetplanDHCPOverrides* dataptr)
{
    g_autoptr(GError) err = NULL;
    if (   g_key_file_get_boolean(kf, group, "ignore-auto-routes", NULL)
        && g_key_file_get_boolean(kf, group, "never-default", NULL)) {
        (*dataptr).use_routes = FALSE;
        _kf_clear_key(kf, group, "ignore-auto-routes");
        _kf_clear_key(kf, group, "never-default");
    }
    if (g_key_file_get_uint64(kf, group, "route-metric", &err) != NETPLAN_METRIC_UNSPEC) {
        if (!err) {
            (*dataptr).metric = g_key_file_get_uint64(kf, group, "route-metric", NULL);
            _kf_clear_key(kf, group, "route-metric");
        }
    }
    return TRUE;
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

    /* DHCPv4/v6 */
    set_true_on_match(kf, "ipv4", "method", "auto", &nd->dhcp4);
    set_true_on_match(kf, "ipv6", "method", "auto", &nd->dhcp6);
    parse_dhcp_overrides(kf, "ipv4", &nd->dhcp4_overrides);
    parse_dhcp_overrides(kf, "ipv6", &nd->dhcp6_overrides);

    /* Manuall IPv4/6 addresses */
    parse_addresses(kf, "ipv4", &nd->ip4_addresses);
    parse_addresses(kf, "ipv6", &nd->ip6_addresses);

    /* Default gateways */
    handle_generic_str(kf, "ipv4", "gateway", &nd->gateway4);
    handle_generic_str(kf, "ipv6", "gateway", &nd->gateway6);

    /* Modem parameters
     * NM differentiates between GSM and CDMA connections, while netplan
     * combines them as "modems". We need to parse a basic set of parameters
     * to enable the generator (in nm.c) to detect GSM vs CDMA connections,
     * using its modem_is_gsm() util. */
    nd->modem_params.auto_config = g_key_file_get_boolean(kf, "gsm", "auto-config", NULL);
    _kf_clear_key(kf, "gsm", "auto-config");
    handle_generic_str(kf, "gsm", "apn", &nd->modem_params.apn);
    handle_generic_str(kf, "gsm", "device-id", &nd->modem_params.device_id);
    handle_generic_str(kf, "gsm", "network-id", &nd->modem_params.network_id);
    handle_generic_str(kf, "gsm", "pin", &nd->modem_params.pin);
    handle_generic_str(kf, "gsm", "sim-id", &nd->modem_params.sim_id);
    handle_generic_str(kf, "gsm", "sim-operator-id", &nd->modem_params.sim_operator_id);

    /* wake-on-lan, do not clear passthrough as we do not fully support this setting */
    if (g_key_file_has_group(kf, "ethernet")) {
        if (!g_key_file_has_key(kf, "ethernet", "wake-on-lan", NULL)) {
            nd->wake_on_lan = TRUE; //NM's default is "1"
        } else {
            //XXX: fix delta between options in NM (0x1, 0x2, 0x4, ...) and netplan (bool)
            nd->wake_on_lan = g_key_file_get_uint64(kf, "ethernet", "wake-on-lan", NULL) > 0;
        }
    }
    if (g_key_file_has_group(kf, "wifi")) {
        if (g_key_file_get_uint64(kf, "wifi", "wake-on-wlan", NULL)) {
            nd->wowlan = g_key_file_get_uint64(kf, "wifi", "wake-on-wlan", NULL);
            _kf_clear_key(kf, "wifi", "wake-on-wlan");
        } else {
            nd->wowlan = NETPLAN_WIFI_WOWLAN_DEFAULT;
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
