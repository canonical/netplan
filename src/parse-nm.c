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
#include <arpa/inet.h>

#include "netplan.h"
#include "parse-nm.h"
#include "parse.h"
#include "util.h"
#include "types.h"
#include "util-internal.h"
#include "validation.h"

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
    /* TODO: Vlans are not yet fully supported by the keyfile parser
    else if (!g_strcmp0(type_str, "vlan"))
        return NETPLAN_DEF_TYPE_VLAN;
    */
    /* TODO: Tunnels are not yet supported by the keyfile parser
    else if (!g_strcmp0(type_str, "ip-tunnel") || !g_strcmp0(type_str, "wireguard"))
        return NETPLAN_DEF_TYPE_TUNNEL;
    */
    /* TODO: Vxlans are not yet fully supported by the keyfile parser
    else if (!g_strcmp0(type_str, "vxlan"))
        return NETPLAN_DEF_TYPE_VXLAN;
    */
    /* TODO: Vrfs are not yet fully supported by the keyfile parser
    else if (!g_strcmp0(type_str, "vrf"))
        return NETPLAN_DEF_TYPE_VRF;
    */
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

static void
_kf_clear_key(GKeyFile* kf, const gchar* group, const gchar* key)
{
    gsize len = 1;
    g_key_file_remove_key(kf, group, key, NULL);
    g_strfreev(g_key_file_get_keys(kf, group, &len, NULL));
    /* clear group if this was the last key */
    if (len == 0)
        g_key_file_remove_group(kf, group, NULL);
}

static gboolean
kf_matches(GKeyFile* kf, const gchar* group, const gchar* key, const gchar* match)
{
    g_autofree gchar *kf_value = g_key_file_get_string(kf, group, key, NULL);
    return g_strcmp0(kf_value, match) == 0;
}

static void
set_true_on_match(GKeyFile* kf, const gchar* group, const gchar* key, const gchar* match, const void* dataptr)
{
    g_assert(dataptr);
    if (kf_matches(kf, group, key, match)) {
        *((gboolean*) dataptr) = TRUE;
        _kf_clear_key(kf, group, key);
    }
}

static void
handle_generic_bool(GKeyFile* kf, const gchar* group, const gchar* key, gboolean* dataptr)
{
    g_assert(dataptr);
    *dataptr = g_key_file_get_boolean(kf, group, key, NULL);
    _kf_clear_key(kf, group, key);
}

static void
handle_generic_str(GKeyFile* kf, const gchar* group, const gchar* key, char** dataptr)
{
    g_assert(dataptr);
    g_assert(!*dataptr);
    *dataptr = g_key_file_get_string(kf, group, key, NULL);
    if (*dataptr)
        _kf_clear_key(kf, group, key);
}

static void
handle_generic_uint(GKeyFile* kf, const gchar* group, const gchar* key, guint* dataptr, guint default_value)
{
    g_assert(dataptr);
    if (g_key_file_has_key(kf, group, key, NULL)) {
        guint data = g_key_file_get_uint64(kf, group, key, NULL);
        if (data != default_value)
            *dataptr = data;
        _kf_clear_key(kf, group, key);
    }
}

static void
handle_common(GKeyFile* kf, NetplanNetDefinition* nd, const gchar* group) {
    handle_generic_str(kf, group, "cloned-mac-address", &nd->set_mac);
    handle_generic_uint(kf, group, "mtu", &nd->mtubytes, NETPLAN_MTU_UNSPEC);
    handle_generic_str(kf, group, "mac-address", &nd->match.mac);
    if (nd->match.mac)
        nd->has_match = TRUE;
}

static void
handle_bridge_uint(GKeyFile* kf, const gchar* key, NetplanNetDefinition* nd, char** dataptr) {
    if (g_key_file_get_uint64(kf, "bridge", key, NULL)) {
        nd->custom_bridging = TRUE;
        *dataptr = g_strdup_printf("%"G_GUINT64_FORMAT, g_key_file_get_uint64(kf, "bridge", key, NULL));
        _kf_clear_key(kf, "bridge", key);
    }
}

static void
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
            g_free(kf_value);
            /* Append "address/prefix" */
            if (split[0]) {
                /* no need to free 's', this will stay in the netdef */
                gchar* s = g_strdup(split[0]);
                g_array_append_val(*ip_arr, s);
            }
            if (!split[1])
                _kf_clear_key(kf, group, key);
            else
                /* XXX: how to handle additional values (like "gateway") in split[n]? */
                unhandled_data = TRUE;
            g_strfreev(split);
            g_free(key);
        }
        /* clear keyfile once all data was handled */
        if (!unhandled_data)
            _kf_clear_key(kf, group, "method");
    }
}

static void
parse_routes(GKeyFile* kf, const gchar* group, GArray** routes_arr)
{
    g_assert(routes_arr);
    NetplanIPRoute *route = NULL;
    gchar *key = NULL;
    gchar *kf_value = NULL;
    gchar *options_key = NULL;
    gchar *options_kf_value = NULL;
    gchar **split = NULL;
    for (unsigned i = 1;; ++i) {
        gboolean unhandled_data = FALSE;
        key = g_strdup_printf("route%u", i);
        kf_value = g_key_file_get_string(kf, group, key, NULL);
        options_key = g_strdup_printf("route%u_options", i);
        options_kf_value = g_key_file_get_string(kf, group, options_key, NULL);
        if (!options_kf_value)
            g_free(options_key);
        if (!kf_value) {
            g_free(key);
            break;
        }
        if (!*routes_arr)
            *routes_arr = g_array_new(FALSE, TRUE, sizeof(NetplanIPRoute*));
        route = g_new0(NetplanIPRoute, 1);
        route->type = g_strdup("unicast");
        route->family = G_MAXUINT; /* 0 is a valid family ID */
        route->metric = NETPLAN_METRIC_UNSPEC; /* 0 is a valid metric */
        g_debug("%s: adding new route (kf)", key);

        if (g_strcmp0(group, "ipv4") == 0)
            route->family = AF_INET;
        else if (g_strcmp0(group, "ipv6") == 0)
            route->family = AF_INET6;

        split = g_strsplit(kf_value, ",", 3);
        /* Append "to" (address/prefix) */
        if (split[0])
            route->to = g_strdup(split[0]); //no need to free, will stay in netdef
        /* Append gateway/via IP */
        if (split[0] && split[1] &&
            g_strcmp0(split[1], get_unspecified_address(route->family)) != 0) {
            route->scope = g_strdup("global");
            route->via = g_strdup(split[1]); //no need to free, will stay in netdef
        } else {
            /* If the gateway (via) is unspecified, it means that this route is
             * only valid on the local network (see nm-keyfile.c ->
             * read_one_ip_address_or_route()), e.g.:
             * ip route add NETWORK dev DEV [metric METRIC] */
            route->scope = g_strdup("link");
        }

        /* Append metric */
        if (split[0] && split[1] && split[2] && strtoul(split[2], NULL, 10) != NETPLAN_METRIC_UNSPEC)
            route->metric = strtoul(split[2], NULL, 10);
        g_strfreev(split);

        /* Parse route options */
        if (options_kf_value) {
            g_debug("%s: adding new route_options (kf)", options_key);
            split = g_strsplit(options_kf_value, ",", -1);
            for (unsigned i = 0; split[i]; ++i) {
                g_debug("processing route_option: %s", split[i]);
                gchar **kv = g_strsplit(split[i], "=", 2);
                if (g_strcmp0(kv[0], "onlink") == 0)
                    route->onlink = (g_strcmp0(kv[1], "true") == 0);
                else if (g_strcmp0(kv[0], "initrwnd") == 0)
                    route->advertised_receive_window = strtoul(kv[1], NULL, 10);
                else if (g_strcmp0(kv[0], "initcwnd") == 0)
                    route->congestion_window = strtoul(kv[1], NULL, 10);
                else if (g_strcmp0(kv[0], "mtu") == 0)
                    route->mtubytes = strtoul(kv[1], NULL, 10);
                else if (g_strcmp0(kv[0], "table") == 0)
                    route->table = strtoul(kv[1], NULL, 10);
                else if (g_strcmp0(kv[0], "src") == 0)
                    route->from = g_strdup(kv[1]); //no need to free, will stay in netdef
                else
                    unhandled_data = TRUE;
                g_strfreev(kv);
            }
            g_strfreev(split);

            if (!unhandled_data)
                _kf_clear_key(kf, group, options_key);
            g_free(options_key);
            g_free(options_kf_value);
        }

        /* Add route to array, clear keyfile */
        g_array_append_val(*routes_arr, route);
        if (!unhandled_data)
            _kf_clear_key(kf, group, key);
        g_free(key);
        g_free(kf_value);
    }
}

static void
parse_dhcp_overrides(GKeyFile* kf, const gchar* group, NetplanDHCPOverrides* dataptr)
{
    g_assert(dataptr);
    if (   g_key_file_get_boolean(kf, group, "ignore-auto-routes", NULL)
        && g_key_file_get_boolean(kf, group, "never-default", NULL)) {
        (*dataptr).use_routes = FALSE;
        _kf_clear_key(kf, group, "ignore-auto-routes");
        _kf_clear_key(kf, group, "never-default");
    }
    handle_generic_uint(kf, group, "route-metric", &(*dataptr).metric, NETPLAN_METRIC_UNSPEC);
}

static void
parse_search_domains(GKeyFile* kf, const gchar* group, GArray** domains_arr)
{
    /* Keep "dns-search" as fallback/passthrough, as netplan cannot
     * differentiate between ipv4.dns-search and ipv6.dns-search */
    g_assert(domains_arr);
    gsize len = 0;
    gchar **split = g_key_file_get_string_list(kf, group, "dns-search", &len, NULL);
    if (split) {
        if (len == 0) {
            //do not clear "dns-search", keep as fallback
            //_kf_clear_key(kf, group, "dns-search");
            return;
        }
        if (!*domains_arr)
            *domains_arr = g_array_new(FALSE, FALSE, sizeof(char*));
        for(unsigned i = 0; split[i]; ++i) {
            char* s = g_strdup(split[i]); //no need to free, will stay in netdef
            g_array_append_val(*domains_arr, s);
        }
        //do not clear "dns-search", keep as fallback
        //_kf_clear_key(kf, group, "dns-search");
        g_strfreev(split);
    }
}

static void
parse_nameservers(GKeyFile* kf, const gchar* group, GArray** nameserver_arr)
{
    g_assert(nameserver_arr);
    gchar **split = g_key_file_get_string_list(kf, group, "dns", NULL, NULL);
    if (split) {
        if (!*nameserver_arr)
            *nameserver_arr = g_array_new(FALSE, FALSE, sizeof(char*));
        for(unsigned i = 0; split[i]; ++i) {
            if (strlen(split[i]) > 0) {
                gchar* s = g_strdup(split[i]); //no need to free, will stay in netdef
                g_array_append_val(*nameserver_arr, s);
            }
        }
        _kf_clear_key(kf, group, "dns");
        g_strfreev(split);
    }
}

static void
parse_dot1x_auth(GKeyFile* kf, NetplanAuthenticationSettings* auth)
{
    g_assert(auth);
    g_autofree gchar* method = g_key_file_get_string(kf, "802-1x", "eap", NULL);

    if (method && g_strcmp0(method, "tls") == 0) {
        auth->eap_method = NETPLAN_AUTH_EAP_TLS;
        _kf_clear_key(kf, "802-1x", "eap");
    } else if (method && g_strcmp0(method, "peap") == 0) {
        auth->eap_method = NETPLAN_AUTH_EAP_PEAP;
        _kf_clear_key(kf, "802-1x", "eap");
    } else if (method && g_strcmp0(method, "ttls") == 0) {
        auth->eap_method = NETPLAN_AUTH_EAP_TTLS;
        _kf_clear_key(kf, "802-1x", "eap");
    }

    handle_generic_str(kf, "802-1x", "identity", &auth->identity);
    handle_generic_str(kf, "802-1x", "anonymous-identity", &auth->anonymous_identity);
    if (!auth->password)
        handle_generic_str(kf, "802-1x", "password", &auth->password);
    handle_generic_str(kf, "802-1x", "ca-cert", &auth->ca_certificate);
    handle_generic_str(kf, "802-1x", "client-cert", &auth->client_certificate);
    handle_generic_str(kf, "802-1x", "private-key", &auth->client_key);
    handle_generic_str(kf, "802-1x", "private-key-password", &auth->client_key_password);
    handle_generic_str(kf, "802-1x", "phase2-auth", &auth->phase2_auth);
}

static void
parse_bond_arp_ip_targets(GKeyFile* kf, GArray **targets_arr)
{
    g_assert(targets_arr);
    g_autofree gchar *v = g_key_file_get_string(kf, "bond", "arp_ip_target", NULL);
    if (v) {
        gchar** split = g_strsplit(v, ",", -1);
        for (unsigned i = 0; split[i]; ++i) {
            if (!*targets_arr)
                *targets_arr = g_array_new(FALSE, FALSE, sizeof(char *));
            gchar *s = g_strdup(split[i]);
            g_array_append_val(*targets_arr, s);
        }
        _kf_clear_key(kf, "bond", "arp_ip_target");
        g_strfreev(split);
    }
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
netplan_parser_load_keyfile(NetplanParser* npp, const char* filename, GError** error)
{
    g_autofree gchar *nd_id = NULL;
    g_autofree gchar *uuid = NULL;
    g_autofree gchar *type = NULL;
    g_autofree gchar* wifi_mode = NULL;
    g_autofree gchar* ssid = NULL;
    g_autofree gchar* netdef_id = NULL;
    gchar *tmp_str = NULL;
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

    tmp_str = g_key_file_get_string(kf, "connection", "interface-name", NULL);
    /* Use previously existing netdef IDs, if available, to override connections
     * Else: generate a "NM-<UUID>" ID */
    if (netdef_id) {
        nd_id = g_strdup(netdef_id);
        if (g_strcmp0(netdef_id, tmp_str) == 0)
            _kf_clear_key(kf, "connection", "interface-name");
    } else if (tmp_str && nd_type >= NETPLAN_DEF_TYPE_VIRTUAL && nd_type < NETPLAN_DEF_TYPE_NM) {
        /* netdef ID equals "interface-name" for virtual devices (bridge/bond/...) */
        nd_id = g_strdup(tmp_str);
        _kf_clear_key(kf, "connection", "interface-name");
    } else
        nd_id = g_strconcat("NM-", uuid, NULL);
    g_free(tmp_str);
    nd = netplan_netdef_new(npp, nd_id, nd_type, NETPLAN_BACKEND_NM);

    /* Handle uuid & NM name/id */
    nd->backend_settings.nm.uuid = g_strdup(uuid);
    _kf_clear_key(kf, "connection", "uuid");
    nd->backend_settings.nm.name = g_key_file_get_string(kf, "connection", "id", NULL);
    if (nd->backend_settings.nm.name)
        _kf_clear_key(kf, "connection", "id");

    if (nd_type == NETPLAN_DEF_TYPE_NM)
        goto only_passthrough; //do not try to handle any keys for connections types unknown to netplan

    /* Handle some differing NM/netplan defaults */
    tmp_str = g_key_file_get_string(kf, "ipv6", "method", NULL);
    if ( g_key_file_has_group(kf, "ipv6") && g_strcmp0(tmp_str, "ignore") != 0 &&
        !g_key_file_has_key(kf, "ipv6", "ip6-privacy", NULL)) {
        /* put NM's default into passthrough, as this is not currently supported by netplan */
        g_key_file_set_integer(kf, "ipv6", "ip6-privacy", -1);
    }
    g_free(tmp_str);

    /* remove supported values from passthrough, which have been handled */
    if (   nd_type == NETPLAN_DEF_TYPE_ETHERNET
        || nd_type == NETPLAN_DEF_TYPE_WIFI
        || nd_type == NETPLAN_DEF_TYPE_MODEM
        || nd_type == NETPLAN_DEF_TYPE_BRIDGE
        || nd_type == NETPLAN_DEF_TYPE_BOND)
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

    /* Manual IPv4/6 addresses */
    parse_addresses(kf, "ipv4", &nd->ip4_addresses);
    parse_addresses(kf, "ipv6", &nd->ip6_addresses);

    /* Default gateways */
    handle_generic_str(kf, "ipv4", "gateway", &nd->gateway4);
    handle_generic_str(kf, "ipv6", "gateway", &nd->gateway6);

    /* Routes */
    parse_routes(kf, "ipv4", &nd->routes);
    parse_routes(kf, "ipv6", &nd->routes);

    /* DNS: XXX: How to differentiate ip4/ip6 search_domains? */
    parse_search_domains(kf, "ipv4", &nd->search_domains);
    parse_search_domains(kf, "ipv6", &nd->search_domains);
    parse_nameservers(kf, "ipv4", &nd->ip4_nameservers);
    parse_nameservers(kf, "ipv6", &nd->ip6_nameservers);

    /* IP6 addr-gen
     * Different than suggested by the docs, NM stores 'addr-gen-mode' as string */
    tmp_str = g_key_file_get_string(kf, "ipv6", "addr-gen-mode", NULL);
    if (tmp_str) {
        if (g_strcmp0(tmp_str, "stable-privacy") == 0) {
            nd->ip6_addr_gen_mode = NETPLAN_ADDRGEN_STABLEPRIVACY;
            _kf_clear_key(kf, "ipv6", "addr-gen-mode");
        } else if (g_strcmp0(tmp_str, "eui64") == 0) {
            nd->ip6_addr_gen_mode = NETPLAN_ADDRGEN_EUI64;
            _kf_clear_key(kf, "ipv6", "addr-gen-mode");
        }
    }
    g_free(tmp_str);
    handle_generic_str(kf, "ipv6", "token", &nd->ip6_addr_gen_token);

    /* ip6-privacy is not fully supported, NM supports additional modes, like -1 or 1
     * handle known modes, but keep any unsupported "ip6-privacy" value in passthrough */
    if (g_key_file_has_group(kf, "ipv6")) {
        if (g_key_file_has_key(kf, "ipv6", "ip6-privacy", NULL)) {
            int ip6_privacy = g_key_file_get_integer(kf, "ipv6", "ip6-privacy", NULL);
            if (ip6_privacy == 0) {
                nd->ip6_privacy = FALSE;
                _kf_clear_key(kf, "ipv6", "ip6-privacy");
            } else if (ip6_privacy == 2) {
                nd->ip6_privacy = TRUE;
                _kf_clear_key(kf, "ipv6", "ip6-privacy");
            }
        }
    }

    /* Modem parameters
     * NM differentiates between GSM and CDMA connections, while netplan
     * combines them as "modems". We need to parse a basic set of parameters
     * to enable the generator (in nm.c) to detect GSM vs CDMA connections,
     * using its modem_is_gsm() util. */
    handle_generic_bool(kf, "gsm", "auto-config", &nd->modem_params.auto_config);
    handle_generic_str(kf, "gsm", "apn", &nd->modem_params.apn);
    handle_generic_str(kf, "gsm", "device-id", &nd->modem_params.device_id);
    handle_generic_str(kf, "gsm", "network-id", &nd->modem_params.network_id);
    handle_generic_str(kf, "gsm", "pin", &nd->modem_params.pin);
    handle_generic_str(kf, "gsm", "sim-id", &nd->modem_params.sim_id);
    handle_generic_str(kf, "gsm", "sim-operator-id", &nd->modem_params.sim_operator_id);

    /* GSM & CDMA */
    handle_generic_uint(kf, "cdma", "mtu", &nd->mtubytes, NETPLAN_MTU_UNSPEC);
    handle_generic_uint(kf, "gsm", "mtu", &nd->mtubytes, NETPLAN_MTU_UNSPEC);
    handle_generic_str(kf, "gsm", "number", &nd->modem_params.number);
    if (!nd->modem_params.number)
        handle_generic_str(kf, "cdma", "number", &nd->modem_params.number);
    handle_generic_str(kf, "gsm", "password", &nd->modem_params.password);
    if (!nd->modem_params.password)
        handle_generic_str(kf, "cdma", "password", &nd->modem_params.password);
    handle_generic_str(kf, "gsm", "username", &nd->modem_params.username);
    if (!nd->modem_params.username)
        handle_generic_str(kf, "cdma", "username", &nd->modem_params.username);

    /* Ethernets */
    if (g_key_file_has_group(kf, "ethernet")) {
        /* wake-on-lan, do not clear passthrough as we do not fully support this setting */
        if (!g_key_file_has_key(kf, "ethernet", "wake-on-lan", NULL)) {
            nd->wake_on_lan = TRUE; //NM's default is "1"
        } else {
            guint value = g_key_file_get_uint64(kf, "ethernet", "wake-on-lan", NULL);
            //XXX: fix delta between options in NM (0x1, 0x2, 0x4, ...) and netplan (bool)
            nd->wake_on_lan = value > 0; // netplan only knows about "off" or "on"
            if (value == 0)
                _kf_clear_key(kf, "ethernet", "wake-on-lan"); // value "off" is supported
        }

        handle_common(kf, nd, "ethernet");
    }

    /* Wifis */
    if (g_key_file_has_group(kf, "wifi")) {
        if (g_key_file_get_uint64(kf, "wifi", "wake-on-wlan", NULL)) {
            nd->wowlan = g_key_file_get_uint64(kf, "wifi", "wake-on-wlan", NULL);
            _kf_clear_key(kf, "wifi", "wake-on-wlan");
        } else {
            nd->wowlan = NETPLAN_WIFI_WOWLAN_DEFAULT;
        }

        handle_common(kf, nd, "wifi");
    }

    /* Cleanup some implicit keys */
    tmp_str = g_key_file_get_string(kf, "ipv6", "method", NULL);
    if (tmp_str && g_strcmp0(tmp_str, "ignore") == 0 &&
        !(nd->dhcp6 || nd->ip6_addresses || nd->gateway6 ||
            nd->ip6_nameservers || nd->ip6_addr_gen_mode))
        _kf_clear_key(kf, "ipv6", "method");
    g_free(tmp_str);

    tmp_str = g_key_file_get_string(kf, "ipv4", "method", NULL);
    if (tmp_str && g_strcmp0(tmp_str, "link-local") == 0 &&
        !(nd->dhcp4 || nd->ip4_addresses || nd->gateway4 ||
            nd->ip4_nameservers))
        _kf_clear_key(kf, "ipv4", "method");
    g_free(tmp_str);

    /* Vlan: XXX: find a way to parse the "link:" (parent) connection */
    handle_generic_uint(kf, "vlan", "id", &nd->vlan_id, G_MAXUINT);

    /* Bridge: XXX: find a way to parse the bridge-port.priority & bridge-port.path-cost values */
    handle_generic_uint(kf, "bridge", "priority", &nd->bridge_params.priority, 0);
    if (nd->bridge_params.priority)
        nd->custom_bridging = TRUE;
    handle_bridge_uint(kf, "ageing-time", nd, &nd->bridge_params.ageing_time);
    handle_bridge_uint(kf, "hello-time", nd, &nd->bridge_params.hello_time);
    handle_bridge_uint(kf, "forward-delay", nd, &nd->bridge_params.forward_delay);
    handle_bridge_uint(kf, "max-age", nd, &nd->bridge_params.max_age);
    /* STP needs to be handled last, for its different default value in custom_bridging mode */
    if (g_key_file_has_key(kf, "bridge", "stp", NULL)) {
        nd->custom_bridging = TRUE;
        handle_generic_bool(kf, "bridge", "stp", &nd->bridge_params.stp);
    } else if(nd->custom_bridging) {
        nd->bridge_params.stp = TRUE; //set default value if not specified otherwise
    }

    /* Bonds */
    handle_generic_str(kf, "bond", "mode", &nd->bond_params.mode);
    handle_generic_str(kf, "bond", "lacp_rate", &nd->bond_params.lacp_rate);
    handle_generic_str(kf, "bond", "miimon", &nd->bond_params.monitor_interval);
    handle_generic_str(kf, "bond", "xmit_hash_policy", &nd->bond_params.transmit_hash_policy);
    handle_generic_str(kf, "bond", "ad_select", &nd->bond_params.selection_logic);
    handle_generic_str(kf, "bond", "arp_interval", &nd->bond_params.arp_interval);
    handle_generic_str(kf, "bond", "arp_validate", &nd->bond_params.arp_validate);
    handle_generic_str(kf, "bond", "arp_all_targets", &nd->bond_params.arp_all_targets);
    handle_generic_str(kf, "bond", "updelay", &nd->bond_params.up_delay);
    handle_generic_str(kf, "bond", "downdelay", &nd->bond_params.down_delay);
    handle_generic_str(kf, "bond", "fail_over_mac", &nd->bond_params.fail_over_mac_policy);
    handle_generic_str(kf, "bond", "primary_reselect", &nd->bond_params.primary_reselect_policy);
    handle_generic_str(kf, "bond", "lp_interval", &nd->bond_params.learn_interval);
    handle_generic_str(kf, "bond", "primary", &nd->bond_params.primary_slave);
    handle_generic_uint(kf, "bond", "min_links", &nd->bond_params.min_links, 0);
    handle_generic_uint(kf, "bond", "resend_igmp", &nd->bond_params.resend_igmp, 0);
    handle_generic_uint(kf, "bond", "packets_per_slave", &nd->bond_params.packets_per_slave, 0);
    handle_generic_uint(kf, "bond", "num_grat_arp", &nd->bond_params.gratuitous_arp, 0);
    /* num_unsol_na might overwrite num_grat_arp, but we're fine if they are equal:
     * https://github.com/NetworkManager/NetworkManager/commit/42b0bef33c77a0921590b2697f077e8ea7805166 */
    if (g_key_file_get_uint64(kf, "bond", "num_unsol_na", NULL) == nd->bond_params.gratuitous_arp)
        _kf_clear_key(kf, "bond", "num_unsol_na");
    handle_generic_bool(kf, "bond", "all_slaves_active", &nd->bond_params.all_slaves_active);
    parse_bond_arp_ip_targets(kf, &nd->bond_params.arp_ip_targets);

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

        tmp_str = g_key_file_get_string(kf, "ipv4", "method", NULL);
        if (tmp_str && g_strcmp0(tmp_str, "shared") == 0) {
            ap->mode = NETPLAN_WIFI_MODE_AP;
            _kf_clear_key(kf, "ipv4", "method");
        }
        g_free(tmp_str);

        handle_generic_bool(kf, "wifi", "hidden", &ap->hidden);
        handle_generic_str(kf, "wifi", "bssid", &ap->bssid);

        /* Wifi band & channel */
        tmp_str = g_key_file_get_string(kf, "wifi", "band", NULL);
        if (tmp_str && g_strcmp0(tmp_str, "a") == 0) {
            ap->band = NETPLAN_WIFI_BAND_5;
            _kf_clear_key(kf, "wifi", "band");
        } else if (tmp_str && g_strcmp0(tmp_str, "bg") == 0) {
            ap->band = NETPLAN_WIFI_BAND_24;
            _kf_clear_key(kf, "wifi", "band");
        }
        g_free(tmp_str);
        handle_generic_uint(kf, "wifi", "channel", &ap->channel, 0);

        /* Wifi security */
        tmp_str = g_key_file_get_string(kf, "wifi-security", "key-mgmt", NULL);
        if (tmp_str && g_strcmp0(tmp_str, "wpa-psk") == 0) {
            ap->auth.key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK;
            ap->has_auth = TRUE;
            _kf_clear_key(kf, "wifi-security", "key-mgmt");
        } else if (tmp_str && g_strcmp0(tmp_str, "wpa-eap") == 0) {
            ap->auth.key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP;
            ap->has_auth = TRUE;
            _kf_clear_key(kf, "wifi-security", "key-mgmt");
        } else if (tmp_str && g_strcmp0(tmp_str, "ieee8021x") == 0) {
            ap->auth.key_management = NETPLAN_AUTH_KEY_MANAGEMENT_8021X;
            ap->has_auth = TRUE;
            _kf_clear_key(kf, "wifi-security", "key-mgmt");
        }
        g_free(tmp_str);

        handle_generic_str(kf, "wifi-security", "psk", &ap->auth.password);
        if (ap->auth.password)
            ap->has_auth = TRUE;

        parse_dot1x_auth(kf, &ap->auth);
        if (ap->auth.eap_method != NETPLAN_AUTH_EAP_NONE)
            ap->has_auth = TRUE;

        if (!nd->access_points)
            nd->access_points = g_hash_table_new(g_str_hash, g_str_equal);
        g_hash_table_insert(nd->access_points, ap->ssid, ap);

        /* Last: handle passthrough for everything left in the keyfile
         *       Also, transfer backend_settings from netdef to AP */
        ap->backend_settings.nm.uuid = g_strdup(nd->backend_settings.nm.uuid);
        ap->backend_settings.nm.name = g_strdup(nd->backend_settings.nm.name);
        /* No need to clear nm.uuid & nm.name from def->backend_settings,
         * as we have only one AP. */
        read_passthrough(kf, &ap->backend_settings.nm.passthrough);
    } else {
only_passthrough:
        /* Last: handle passthrough for everything left in the keyfile */
        read_passthrough(kf, &nd->backend_settings.nm.passthrough);
    }

    g_key_file_free(kf);

    /* validate definition-level conditions */
    if (!npp->missing_id)
        npp->missing_id = g_hash_table_new_full(g_str_hash, g_str_equal, NULL, g_free);
    if (!validate_netdef_grammar(npp, nd, NULL, error))
        return FALSE;
    return TRUE;
}
