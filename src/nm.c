/*
 * Copyright (C) 2016-2021 Canonical, Ltd.
 * Author: Martin Pitt <martin.pitt@ubuntu.com>
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

#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <arpa/inet.h>

#include <glib.h>
#include <glib/gprintf.h>
#include <uuid.h>

#include "nm.h"
#include "parse.h"
#include "util.h"
#include "validation.h"
#include "parse-nm.h"

GString* udev_rules;

/**
 * Append NM device specifier of @def to @s.
 */
static void
g_string_append_netdef_match(GString* s, const NetplanNetDefinition* def)
{
    g_assert(!def->match.driver || def->set_name);
    if (def->match.mac || def->match.original_name || def->set_name || def->type >= NETPLAN_DEF_TYPE_VIRTUAL) {
        if (def->match.mac) {
            g_string_append_printf(s, "mac:%s,", def->match.mac);
        }
        /* MAC could change, e.g. for bond slaves. Ignore by interface-name as well */
        if (def->match.original_name || def->set_name || def->type >= NETPLAN_DEF_TYPE_VIRTUAL) {
            /* we always have the renamed name here */
            g_string_append_printf(s, "interface-name:%s,",
                    (def->type >= NETPLAN_DEF_TYPE_VIRTUAL) ? def->id
                                            : (def->set_name ?: def->match.original_name));
        }
    } else {
        /* no matches → match all devices of that type */
        switch (def->type) {
            case NETPLAN_DEF_TYPE_ETHERNET:
                g_string_append(s, "type:ethernet,");
                break;
            /* This cannot be reached with just NM and networkd backends, as
             * networkd does not support wifi and thus we'll never blacklist a
             * wifi device from NM. This would become relevant with another
             * wifi-supporting backend, but until then this just spoils 100%
             * code coverage.
            case NETPLAN_DEF_TYPE_WIFI:
                g_string_append(s, "type:wifi");
                break;
            */

            // LCOV_EXCL_START
            default:
                g_assert_not_reached();
            // LCOV_EXCL_STOP
        }
    }
}

/**
 * Infer if this is a modem netdef of type GSM.
 * This is done by checking for certain modem_params, which are only
 * applicable to GSM connections.
 */
static const gboolean
modem_is_gsm(const NetplanNetDefinition* def)
{
    if (   def->modem_params.apn
        || def->modem_params.auto_config
        || def->modem_params.device_id
        || def->modem_params.network_id
        || def->modem_params.pin
        || def->modem_params.sim_id
        || def->modem_params.sim_operator_id)
        return TRUE;

    return FALSE;
}

/**
 * Return NM "type=" string.
 */
static const char*
type_str(const NetplanNetDefinition* def)
{
    const NetplanDefType type = def->type;
    switch (type) {
        case NETPLAN_DEF_TYPE_ETHERNET:
            return "ethernet";
        case NETPLAN_DEF_TYPE_MODEM:
            if (modem_is_gsm(def))
                return "gsm";
            else
                return "cdma";
        case NETPLAN_DEF_TYPE_WIFI:
            return "wifi";
        case NETPLAN_DEF_TYPE_BRIDGE:
            return "bridge";
        case NETPLAN_DEF_TYPE_BOND:
            return "bond";
        case NETPLAN_DEF_TYPE_VLAN:
            return "vlan";
        case NETPLAN_DEF_TYPE_TUNNEL:
            if (def->tunnel.mode == NETPLAN_TUNNEL_MODE_WIREGUARD)
                return "wireguard";
            return "ip-tunnel";
        case NETPLAN_DEF_TYPE_NM:
            /* needs to be overriden by passthrough "connection.type" setting */
            return NULL;
        // LCOV_EXCL_START
        default:
            g_assert_not_reached();
        // LCOV_EXCL_STOP
    }
}

/**
 * Return NM wifi "mode=" string.
 */
static const char*
wifi_mode_str(const NetplanWifiMode mode)
{
    switch (mode) {
        case NETPLAN_WIFI_MODE_INFRASTRUCTURE:
            return "infrastructure";
        case NETPLAN_WIFI_MODE_ADHOC:
            return "adhoc";
        case NETPLAN_WIFI_MODE_AP:
            return "ap";
        // LCOV_EXCL_START
        default:
            g_assert_not_reached();
        // LCOV_EXCL_STOP
    }
}

/**
 * Return NM wifi "band=" string.
 */
static const char*
wifi_band_str(const NetplanWifiBand band)
{
    switch (band) {
        case NETPLAN_WIFI_BAND_5:
            return "a";
        case NETPLAN_WIFI_BAND_24:
            return "bg";
        // LCOV_EXCL_START
        default:
            g_assert_not_reached();
        // LCOV_EXCL_STOP
    }
}

/**
 * Return NM addr-gen-mode string.
 */
static const char*
addr_gen_mode_str(const NetplanAddrGenMode mode)
{
    switch (mode) {
        case NETPLAN_ADDRGEN_EUI64:
            return "0";
        case NETPLAN_ADDRGEN_STABLEPRIVACY:
            return "1";
        // LCOV_EXCL_START
        default:
            g_assert_not_reached();
        // LCOV_EXCL_STOP
    }
}

static void
write_search_domains(const NetplanNetDefinition* def, const char* group, GKeyFile *kf)
{
    if (def->search_domains) {
        const gchar* list[def->search_domains->len];
        for (unsigned i = 0; i < def->search_domains->len; ++i)
            list[i] = g_array_index(def->search_domains, char*, i);
        g_key_file_set_string_list(kf, group, "dns-search", list, def->search_domains->len);
    }
}

static void
write_routes(const NetplanNetDefinition* def, GKeyFile *kf, int family)
{
    const gchar* group = NULL;
    gchar* tmp_key = NULL;
    GString* tmp_val = NULL;

    if (family == AF_INET)
        group = "ipv4";
    else if (family == AF_INET6)
        group = "ipv6";
    g_assert(group != NULL);

    if (def->routes != NULL) {
        for (unsigned i = 0, j = 1; i < def->routes->len; ++i) {
            const NetplanIPRoute *cur_route = g_array_index(def->routes, NetplanIPRoute*, i);

            if (cur_route->family != family)
                continue;

            if (cur_route->type && g_ascii_strcasecmp(cur_route->type, "unicast") != 0) {
                g_fprintf(stderr, "ERROR: %s: NetworkManager only supports unicast routes\n", def->id);
                exit(1);
            }

            if (!g_strcmp0(cur_route->scope, "global")) {
                /* For IPv6 addresses, kernel and NetworkManager don't support a scope.
                 * For IPv4 addresses, NetworkManager determines the scope of addresses on its own
                 * ("link" for addresses without gateway, "global" for addresses with next-hop). */
                g_debug("%s: NetworkManager does not support setting a scope for routes, it will auto-detect them.", def->id);
            } else if (cur_route->scope) {
                /* Error out if scope is not set to its default value of 'global' */
                g_fprintf(stderr, "ERROR: %s: NetworkManager does not support setting a scope for routes\n", def->id);
                exit(1);
            }

            tmp_key = g_strdup_printf("route%d", j);
            tmp_val = g_string_new(NULL);
            g_string_printf(tmp_val, "%s,%s", cur_route->to, cur_route->via);
            if (cur_route->metric != NETPLAN_METRIC_UNSPEC)
                g_string_append_printf(tmp_val, ",%d", cur_route->metric);
            g_key_file_set_string(kf, group, tmp_key, tmp_val->str);
            g_free(tmp_key);
            g_string_free(tmp_val, TRUE);

            if (   cur_route->onlink
                || cur_route->advertised_receive_window
                || cur_route->congestion_window
                || cur_route->mtubytes
                || cur_route->table != NETPLAN_ROUTE_TABLE_UNSPEC
                || cur_route->from) {
                tmp_key = g_strdup_printf("route%d_options", j);
                tmp_val = g_string_new(NULL);
                if (cur_route->onlink) {
                    /* onlink for IPv6 addresses is only supported since nm-1.18.0. */
                    g_string_append_printf(tmp_val, "onlink=true,");
                }
                if (cur_route->advertised_receive_window != NETPLAN_ADVERTISED_RECEIVE_WINDOW_UNSPEC)
                    g_string_append_printf(tmp_val, "initrwnd=%u,", cur_route->advertised_receive_window);
                if (cur_route->congestion_window != NETPLAN_CONGESTION_WINDOW_UNSPEC)
                    g_string_append_printf(tmp_val, "initcwnd=%u,", cur_route->congestion_window);
                if (cur_route->mtubytes != NETPLAN_MTU_UNSPEC)
                    g_string_append_printf(tmp_val, "mtu=%u,", cur_route->mtubytes);
                if (cur_route->table != NETPLAN_ROUTE_TABLE_UNSPEC)
                    g_string_append_printf(tmp_val, "table=%u,", cur_route->table);
                if (cur_route->from)
                    g_string_append_printf(tmp_val, "src=%s,", cur_route->from);
                tmp_val->str[tmp_val->len - 1] = '\0'; //remove trailing comma
                g_key_file_set_string(kf, group, tmp_key, tmp_val->str);
                g_free(tmp_key);
                g_string_free(tmp_val, TRUE);
            }
            j++;
        }
    }
}

static void
write_bond_parameters(const NetplanNetDefinition* def, GKeyFile *kf)
{
    GString* tmp_val = NULL;
    if (def->bond_params.mode)
        g_key_file_set_string(kf, "bond", "mode", def->bond_params.mode);
    if (def->bond_params.lacp_rate)
        g_key_file_set_string(kf, "bond", "lacp_rate", def->bond_params.lacp_rate);
    if (def->bond_params.monitor_interval)
        g_key_file_set_string(kf, "bond", "miimon", def->bond_params.monitor_interval);
    if (def->bond_params.min_links)
        g_key_file_set_integer(kf, "bond", "min_links", def->bond_params.min_links);
    if (def->bond_params.transmit_hash_policy)
        g_key_file_set_string(kf, "bond", "xmit_hash_policy", def->bond_params.transmit_hash_policy);
    if (def->bond_params.selection_logic)
        g_key_file_set_string(kf, "bond", "ad_select", def->bond_params.selection_logic);
    if (def->bond_params.all_slaves_active)
        g_key_file_set_integer(kf, "bond", "all_slaves_active", def->bond_params.all_slaves_active);
    if (def->bond_params.arp_interval)
        g_key_file_set_string(kf, "bond", "arp_interval", def->bond_params.arp_interval);
    if (def->bond_params.arp_ip_targets) {
        tmp_val = g_string_new(NULL);
        for (unsigned i = 0; i < def->bond_params.arp_ip_targets->len; ++i) {
            if (i > 0)
                g_string_append_printf(tmp_val, ",");
            g_string_append_printf(tmp_val, "%s", g_array_index(def->bond_params.arp_ip_targets, char*, i));
        }
        g_key_file_set_string(kf, "bond", "arp_ip_target", tmp_val->str);
        g_string_free(tmp_val, TRUE);
    }
    if (def->bond_params.arp_validate)
        g_key_file_set_string(kf, "bond", "arp_validate", def->bond_params.arp_validate);
    if (def->bond_params.arp_all_targets)
        g_key_file_set_string(kf, "bond", "arp_all_targets", def->bond_params.arp_all_targets);
    if (def->bond_params.up_delay)
        g_key_file_set_string(kf, "bond", "updelay", def->bond_params.up_delay);
    if (def->bond_params.down_delay)
        g_key_file_set_string(kf, "bond", "downdelay", def->bond_params.down_delay);
    if (def->bond_params.fail_over_mac_policy)
        g_key_file_set_string(kf, "bond", "fail_over_mac", def->bond_params.fail_over_mac_policy);
    if (def->bond_params.gratuitous_arp) {
        g_key_file_set_integer(kf, "bond", "num_grat_arp", def->bond_params.gratuitous_arp);
        /* Work around issue in NM where unset unsolicited_na will overwrite num_grat_arp:
         * https://github.com/NetworkManager/NetworkManager/commit/42b0bef33c77a0921590b2697f077e8ea7805166 */
        g_key_file_set_integer(kf, "bond", "num_unsol_na", def->bond_params.gratuitous_arp);
    }
    if (def->bond_params.packets_per_slave)
        g_key_file_set_integer(kf, "bond", "packets_per_slave", def->bond_params.packets_per_slave);
    if (def->bond_params.primary_reselect_policy)
        g_key_file_set_string(kf, "bond", "primary_reselect", def->bond_params.primary_reselect_policy);
    if (def->bond_params.resend_igmp)
        g_key_file_set_integer(kf, "bond", "resend_igmp", def->bond_params.resend_igmp);
    if (def->bond_params.learn_interval)
        g_key_file_set_string(kf, "bond", "lp_interval", def->bond_params.learn_interval);
    if (def->bond_params.primary_slave)
        g_key_file_set_string(kf, "bond", "primary", def->bond_params.primary_slave);
}

static void
write_bridge_params(const NetplanNetDefinition* def, GKeyFile *kf)
{
    if (def->custom_bridging) {
        if (def->bridge_params.ageing_time)
            g_key_file_set_string(kf, "bridge", "ageing-time", def->bridge_params.ageing_time);
        if (def->bridge_params.priority)
            g_key_file_set_uint64(kf, "bridge", "priority", def->bridge_params.priority);
        if (def->bridge_params.forward_delay)
            g_key_file_set_string(kf, "bridge", "forward-delay", def->bridge_params.forward_delay);
        if (def->bridge_params.hello_time)
            g_key_file_set_string(kf, "bridge", "hello-time", def->bridge_params.hello_time);
        if (def->bridge_params.max_age)
            g_key_file_set_string(kf, "bridge", "max-age", def->bridge_params.max_age);
        g_key_file_set_boolean(kf, "bridge", "stp", def->bridge_params.stp);
    }
}

static void
write_wireguard_params(const NetplanNetDefinition* def, GKeyFile *kf)
{
    gchar* tmp_group = NULL;
    g_assert(def->tunnel.private_key);

    /* The key was already validated via validate_tunnel_grammar(), but we need
     * to differentiate between base64 key VS absolute path key-file. And a base64
     * string could (theoretically) start with '/', so we use is_wireguard_key()
     * as well to check for more specific characteristics (if needed). */
    if (def->tunnel.private_key[0] == '/' && !is_wireguard_key(def->tunnel.private_key)) {
        g_fprintf(stderr, "%s: private key needs to be base64 encoded when using the NM backend\n", def->id);
        exit(1);
    } else
        g_key_file_set_string(kf, "wireguard", "private-key", def->tunnel.private_key);

    if (def->tunnel.port)
        g_key_file_set_uint64(kf, "wireguard", "listen-port", def->tunnel.port);
    if (def->tunnel.fwmark)
        g_key_file_set_uint64(kf, "wireguard", "fwmark", def->tunnel.fwmark);

    for (guint i = 0; i < def->wireguard_peers->len; i++) {
        NetplanWireguardPeer *peer = g_array_index (def->wireguard_peers, NetplanWireguardPeer*, i);
        g_assert(peer->public_key);
        tmp_group = g_strdup_printf("wireguard-peer.%s", peer->public_key);

        if (peer->keepalive)
            g_key_file_set_integer(kf, tmp_group, "persistent-keepalive", peer->keepalive);
        if (peer->endpoint)
            g_key_file_set_string(kf, tmp_group, "endpoint", peer->endpoint);

        /* The key was already validated via validate_tunnel_grammar(), but we need
         * to differentiate between base64 key VS absolute path key-file. And a base64
         * string could (theoretically) start with '/', so we use is_wireguard_key()
         * as well to check for more specific characteristics (if needed). */
        if (peer->preshared_key) {
            if (peer->preshared_key[0] == '/' && !is_wireguard_key(peer->preshared_key)) {
                g_fprintf(stderr, "%s: shared key needs to be base64 encoded when using the NM backend\n", def->id);
                exit(1);
            } else {
                g_key_file_set_value(kf, tmp_group, "preshared-key", peer->preshared_key);
                g_key_file_set_uint64(kf, tmp_group, "preshared-key-flags", 0);
            }
        }
        if (peer->allowed_ips && peer->allowed_ips->len > 0) {
            const gchar* list[peer->allowed_ips->len];
            for (guint j = 0; j < peer->allowed_ips->len; ++j)
                list[j] = g_array_index(peer->allowed_ips, char*, j);
            g_key_file_set_string_list(kf, tmp_group, "allowed-ips", list, peer->allowed_ips->len);
        }
        g_free(tmp_group);
    }
}

static void
write_tunnel_params(const NetplanNetDefinition* def, GKeyFile *kf)
{
    g_key_file_set_integer(kf, "ip-tunnel", "mode", def->tunnel.mode);
    g_key_file_set_string(kf, "ip-tunnel", "local", def->tunnel.local_ip);
    g_key_file_set_string(kf, "ip-tunnel", "remote", def->tunnel.remote_ip);
    if (def->tunnel.ttl)
        g_key_file_set_uint64(kf, "ip-tunnel", "ttl", def->tunnel.ttl);
    if (def->tunnel.input_key)
        g_key_file_set_string(kf, "ip-tunnel", "input-key", def->tunnel.input_key);
    if (def->tunnel.output_key)
        g_key_file_set_string(kf, "ip-tunnel", "output-key", def->tunnel.output_key);
}

static void
write_dot1x_auth_parameters(const NetplanAuthenticationSettings* auth, GKeyFile *kf)
{
    if (auth->eap_method == NETPLAN_AUTH_EAP_NONE)
        return;

    switch (auth->eap_method) {
        case NETPLAN_AUTH_EAP_NONE: break; // LCOV_EXCL_LINE
        case NETPLAN_AUTH_EAP_TLS:
            g_key_file_set_string(kf, "802-1x", "eap", "tls");
            break;
        case NETPLAN_AUTH_EAP_PEAP:
            g_key_file_set_string(kf, "802-1x", "eap", "peap");
            break;
        case NETPLAN_AUTH_EAP_TTLS:
            g_key_file_set_string(kf, "802-1x", "eap", "ttls");
            break;
    }

    if (auth->identity)
        g_key_file_set_string(kf, "802-1x", "identity", auth->identity);
    if (auth->anonymous_identity)
        g_key_file_set_string(kf, "802-1x", "anonymous-identity", auth->anonymous_identity);
    if (auth->password && auth->key_management != NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK)
        g_key_file_set_string(kf, "802-1x", "password", auth->password);
    if (auth->ca_certificate)
        g_key_file_set_string(kf, "802-1x", "ca-cert", auth->ca_certificate);
    if (auth->client_certificate)
        g_key_file_set_string(kf, "802-1x", "client-cert", auth->client_certificate);
    if (auth->client_key)
        g_key_file_set_string(kf, "802-1x", "private-key", auth->client_key);
    if (auth->client_key_password)
        g_key_file_set_string(kf, "802-1x", "private-key-password", auth->client_key_password);
    if (auth->phase2_auth)
        g_key_file_set_string(kf, "802-1x", "phase2-auth", auth->phase2_auth);
}

static void
write_wifi_auth_parameters(const NetplanAuthenticationSettings* auth, GKeyFile *kf)
{
    if (auth->key_management == NETPLAN_AUTH_KEY_MANAGEMENT_NONE)
        return;

    switch (auth->key_management) {
        case NETPLAN_AUTH_KEY_MANAGEMENT_NONE: break; // LCOV_EXCL_LINE
        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK:
            g_key_file_set_string(kf, "wifi-security", "key-mgmt", "wpa-psk");
            if (auth->password)
                g_key_file_set_string(kf, "wifi-security", "psk", auth->password);
            break;
        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP:
            g_key_file_set_string(kf, "wifi-security", "key-mgmt", "wpa-eap");
            break;
        case NETPLAN_AUTH_KEY_MANAGEMENT_8021X:
            g_key_file_set_string(kf, "wifi-security", "key-mgmt", "ieee8021x");
            break;
    }

    write_dot1x_auth_parameters(auth, kf);
}

static void
maybe_generate_uuid(NetplanNetDefinition* def)
{
    if (uuid_is_null(def->uuid))
        uuid_generate(def->uuid);
}

/**
 * Special handling for passthrough mode: read key-value pairs from
 * "backend_settings.nm.passthrough" and inject them into the keyfile as-is.
 */
static void
write_fallback_key_value(GQuark key_id, gpointer value, gpointer user_data)
{
    GKeyFile *kf = user_data;
    gchar* val = value;
    /* Group name may contain dots, but key name may not.
     * The "tc" group is a special case, where it is the other way around, e.g.:
     *   tc->qdisc.root
     *   tc->tfilter.ffff: */
    const gchar* key = g_quark_to_string(key_id);
    gchar **group_key = g_strsplit(key, ".", -1);
    guint len = g_strv_length(group_key);
    g_autofree gchar* old_key = NULL;
    gboolean has_key = FALSE;
    g_autofree gchar* k = NULL;
    g_autofree gchar* group = NULL;
    if (!g_strcmp0(group_key[0], "tc") && len > 2) {
        k = g_strconcat(group_key[1], ".", group_key[2], NULL);
        group = g_strdup(group_key[0]);
    } else {
        k = group_key[len-1];
        group_key[len-1] = NULL; //remove key from array
        group = g_strjoinv(".", group_key); //re-combine group parts
    }

    has_key = g_key_file_has_key(kf, group, k, NULL);
    old_key = g_key_file_get_string(kf, group, k, NULL);
    g_key_file_set_string(kf, group, k, val);
    /* delete the dummy key, if this was just an empty group */
    if (!g_strcmp0(k, NETPLAN_NM_EMPTY_GROUP))
        g_key_file_remove_key(kf, group, k, NULL);
    else if (!has_key) {
        g_debug("NetworkManager: passing through fallback key: %s.%s=%s", group, k, val);
        g_key_file_set_comment(kf, group, k, "Netplan: passthrough setting", NULL);
    } else if (!!g_strcmp0(val, old_key)) {
        g_debug("NetworkManager: fallback override: %s.%s=%s", group, k, val);
        g_key_file_set_comment(kf, group, k, "Netplan: passthrough override", NULL);
    }

    g_strfreev(group_key);
}

/**
 * Generate NetworkManager configuration in @rootdir/run/NetworkManager/ for a
 * particular NetplanNetDefinition and NetplanWifiAccessPoint, as NM requires a separate
 * connection file for each SSID.
 * @def: The NetplanNetDefinition for which to create a connection
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 * @ap: The access point for which to create a connection. Must be %NULL for
 *      non-wifi types.
 */
static void
write_nm_conf_access_point(NetplanNetDefinition* def, const char* rootdir, const NetplanWifiAccessPoint* ap)
{
    g_autoptr(GKeyFile) kf = NULL;
    g_autoptr(GError) error = NULL;
    g_autofree gchar* conf_path = NULL;
    g_autofree gchar* full_path = NULL;
    g_autofree gchar* nd_nm_id = NULL;
    const gchar* nm_type = NULL;
    gchar* tmp_key = NULL;
    mode_t orig_umask;
    char uuidstr[37];
    const char *match_interface_name = NULL;

    if (def->type == NETPLAN_DEF_TYPE_WIFI)
        g_assert(ap);
    else
        g_assert(ap == NULL);

    if (def->type == NETPLAN_DEF_TYPE_VLAN && def->sriov_vlan_filter) {
        g_debug("%s is defined as a hardware SR-IOV filtered VLAN, postponing creation", def->id);
        return;
    }

    kf = g_key_file_new();
    if (ap && ap->backend_settings.nm.name)
        g_key_file_set_string(kf, "connection", "id", ap->backend_settings.nm.name);
    else if (def->backend_settings.nm.name)
        g_key_file_set_string(kf, "connection", "id", def->backend_settings.nm.name);
    else {
        /* Auto-generate a name for the connection profile, if not specified */
        if (ap)
            nd_nm_id = g_strdup_printf("netplan-%s-%s", def->id, ap->ssid);
        else
            nd_nm_id = g_strdup_printf("netplan-%s", def->id);
        g_key_file_set_string(kf, "connection", "id", nd_nm_id);
    }

    nm_type = type_str(def);
    if (nm_type)
        g_key_file_set_string(kf, "connection", "type", nm_type);

    if (ap && ap->backend_settings.nm.uuid)
        g_key_file_set_string(kf, "connection", "uuid", ap->backend_settings.nm.uuid);
    else if (def->backend_settings.nm.uuid)
        g_key_file_set_string(kf, "connection", "uuid", def->backend_settings.nm.uuid);
    /* VLAN devices refer to us as their parent; if our ID is not a name but we
     * have matches, parent= must be the connection UUID, so put it into the
     * connection */
    if (def->has_vlans && def->has_match) {
        maybe_generate_uuid(def);
        uuid_unparse(def->uuid, uuidstr);
        g_key_file_set_string(kf, "connection", "uuid", uuidstr);
    }

    if (def->type < NETPLAN_DEF_TYPE_VIRTUAL) {
        /* physical (existing) devices use matching; driver matching is not
         * supported, MAC matching is done below (different keyfile section),
         * so only match names here */
        if (def->set_name)
            g_key_file_set_string(kf, "connection", "interface-name", def->set_name);
        else if (!def->has_match)
            g_key_file_set_string(kf, "connection", "interface-name", def->id);
        else if (def->match.original_name) {
            if (strpbrk(def->match.original_name, "*[]?"))
                match_interface_name = def->match.original_name;
            else
                g_key_file_set_string(kf, "connection", "interface-name", def->match.original_name);
        }
        /* else matches on something other than the name, do not restrict interface-name */
    } else {
        /* virtual (created) devices set a name */
        if (strlen(def->id) > 15)
            g_debug("interface-name longer than 15 characters is not supported");
        else
            g_key_file_set_string(kf, "connection", "interface-name", def->id);

        if (def->type == NETPLAN_DEF_TYPE_BRIDGE)
            write_bridge_params(def, kf);
    }
    if (def->type == NETPLAN_DEF_TYPE_MODEM) {
        const char* modem_type = modem_is_gsm(def) ? "gsm" : "cdma";

        /* Use NetworkManager's auto configuration feature if no APN, username, or password is specified */
        if (def->modem_params.auto_config || (!def->modem_params.apn &&
                !def->modem_params.username && !def->modem_params.password)) {
            g_key_file_set_boolean(kf, modem_type, "auto-config", TRUE);
        } else {
            if (def->modem_params.apn)
                g_key_file_set_string(kf, modem_type, "apn", def->modem_params.apn);
            if (def->modem_params.password)
                g_key_file_set_string(kf, modem_type, "password", def->modem_params.password);
            if (def->modem_params.username)
                g_key_file_set_string(kf, modem_type, "username", def->modem_params.username);
        }

        if (def->modem_params.device_id)
            g_key_file_set_string(kf, modem_type, "device-id", def->modem_params.device_id);
        if (def->mtubytes)
            g_key_file_set_uint64(kf, modem_type, "mtu", def->mtubytes);
        if (def->modem_params.network_id)
            g_key_file_set_string(kf, modem_type, "network-id", def->modem_params.network_id);
        if (def->modem_params.number)
            g_key_file_set_string(kf, modem_type, "number", def->modem_params.number);
        if (def->modem_params.pin)
            g_key_file_set_string(kf, modem_type, "pin", def->modem_params.pin);
        if (def->modem_params.sim_id)
            g_key_file_set_string(kf, modem_type, "sim-id", def->modem_params.sim_id);
        if (def->modem_params.sim_operator_id)
            g_key_file_set_string(kf, modem_type, "sim-operator-id", def->modem_params.sim_operator_id);
    }
    if (def->bridge) {
        g_key_file_set_string(kf, "connection", "slave-type", "bridge");
        g_key_file_set_string(kf, "connection", "master", def->bridge);

        if (def->bridge_params.path_cost)
            g_key_file_set_uint64(kf, "bridge-port", "path-cost", def->bridge_params.path_cost);
        if (def->bridge_params.port_priority)
            g_key_file_set_uint64(kf, "bridge-port", "priority", def->bridge_params.port_priority);
    }
    if (def->bond) {
        g_key_file_set_string(kf, "connection", "slave-type", "bond");
        g_key_file_set_string(kf, "connection", "master", def->bond);
    }

    if (def->ipv6_mtubytes) {
        g_fprintf(stderr, "ERROR: %s: NetworkManager definitions do not support ipv6-mtu\n", def->id);
        exit(1);
    }

    if (def->type < NETPLAN_DEF_TYPE_VIRTUAL) {
        if (def->type == NETPLAN_DEF_TYPE_ETHERNET)
            g_key_file_set_integer(kf, "ethernet", "wake-on-lan", def->wake_on_lan ? 1 : 0);

        const char* con_type = NULL;
        switch (def->type) {
            case NETPLAN_DEF_TYPE_WIFI:
                con_type = "wifi";
            case NETPLAN_DEF_TYPE_MODEM:
                /* Avoid adding an [ethernet] section into the [gsm/cdma] description. */
                break;
            default:
                con_type = "ethernet";
        }

        if (con_type) {
            if (!def->set_name && def->match.mac)
                g_key_file_set_string(kf, con_type, "mac-address", def->match.mac);
            if (def->set_mac)
                g_key_file_set_string(kf, con_type, "cloned-mac-address", def->set_mac);
            if (def->mtubytes)
                g_key_file_set_uint64(kf, con_type, "mtu", def->mtubytes);
            if (def->wowlan && def->wowlan > NETPLAN_WIFI_WOWLAN_DEFAULT)
                g_key_file_set_uint64(kf, con_type, "wake-on-wlan", def->wowlan);
        }
    } else {
        if (def->set_mac)
            g_key_file_set_string(kf, "ethernet", "cloned-mac-address", def->set_mac);
        if (def->mtubytes)
            g_key_file_set_uint64(kf, "ethernet", "mtu", def->mtubytes);
    }

    if (def->type == NETPLAN_DEF_TYPE_VLAN) {
        g_assert(def->vlan_id < G_MAXUINT);
        g_assert(def->vlan_link != NULL);
        g_key_file_set_uint64(kf, "vlan", "id", def->vlan_id);
        if (def->vlan_link->has_match) {
            /* we need to refer to the parent's UUID as we don't have an
             * interface name with match: */
            maybe_generate_uuid(def->vlan_link);
            uuid_unparse(def->vlan_link->uuid, uuidstr);
            g_key_file_set_string(kf, "vlan", "parent", uuidstr);
        } else {
            /* if we have an interface name, use that as parent */
            g_key_file_set_string(kf, "vlan", "parent", def->vlan_link->id);
        }
    }

    if (def->type == NETPLAN_DEF_TYPE_BOND)
        write_bond_parameters(def, kf);

    if (def->type == NETPLAN_DEF_TYPE_TUNNEL) {
        if (def->tunnel.mode == NETPLAN_TUNNEL_MODE_WIREGUARD)
            write_wireguard_params(def, kf);
        else
            write_tunnel_params(def, kf);
    }

    if (match_interface_name) {
        const gchar* list[1] = {match_interface_name};
        g_key_file_set_string_list(kf, "match", "interface-name", list, 1);
    }

    if (ap && ap->mode == NETPLAN_WIFI_MODE_AP)
        g_key_file_set_string(kf, "ipv4", "method", "shared");
    else if (def->dhcp4)
        g_key_file_set_string(kf, "ipv4", "method", "auto");
    else if (def->ip4_addresses)
        /* This requires adding at least one address (done below) */
        g_key_file_set_string(kf, "ipv4", "method", "manual");
    else if (def->type == NETPLAN_DEF_TYPE_TUNNEL)
        /* sit tunnels will not start in link-local apparently */
        g_key_file_set_string(kf, "ipv4", "method", "disabled");
    else
        /* Without any address, this is the only available mode */
        g_key_file_set_string(kf, "ipv4", "method", "link-local");

    if (def->ip4_addresses) {
        for (unsigned i = 0; i < def->ip4_addresses->len; ++i) {
            tmp_key = g_strdup_printf("address%i", i+1);
            g_key_file_set_string(kf, "ipv4", tmp_key, g_array_index(def->ip4_addresses, char*, i));
            g_free(tmp_key);
        }
    }
    if (def->gateway4)
        g_key_file_set_string(kf, "ipv4", "gateway", def->gateway4);
    if (def->ip4_nameservers) {
        const gchar* list[def->ip4_nameservers->len];
        for (unsigned i = 0; i < def->ip4_nameservers->len; ++i)
            list[i] = g_array_index(def->ip4_nameservers, char*, i);
        g_key_file_set_string_list(kf, "ipv4", "dns", list, def->ip4_nameservers->len);
    }

    /* We can only write search domains and routes if we have an address */
    if (def->ip4_addresses || def->dhcp4) {
        write_search_domains(def, "ipv4", kf);
        write_routes(def, kf, AF_INET);
    }

    if (!def->dhcp4_overrides.use_routes) {
        g_key_file_set_boolean(kf, "ipv4", "ignore-auto-routes", TRUE);
        g_key_file_set_boolean(kf, "ipv4", "never-default", TRUE);
    }

    if (def->dhcp4 && def->dhcp4_overrides.metric != NETPLAN_METRIC_UNSPEC)
        g_key_file_set_uint64(kf, "ipv4", "route-metric", def->dhcp4_overrides.metric);

    if (def->dhcp6 || def->ip6_addresses || def->gateway6 || def->ip6_nameservers || def->ip6_addr_gen_mode) {
        g_key_file_set_string(kf, "ipv6", "method", def->dhcp6 ? "auto" : "manual");

        if (def->ip6_addresses) {
            for (unsigned i = 0; i < def->ip6_addresses->len; ++i) {
                tmp_key = g_strdup_printf("address%i", i+1);
                g_key_file_set_string(kf, "ipv6", tmp_key, g_array_index(def->ip6_addresses, char*, i));
                g_free(tmp_key);
            }
        }
        if (def->ip6_addr_gen_token) {
            /* Token implies EUI-64, i.e mode=0 */
            g_key_file_set_integer(kf, "ipv6", "addr-gen-mode", 0);
            g_key_file_set_string(kf, "ipv6", "token", def->ip6_addr_gen_token);
        } else if (def->ip6_addr_gen_mode)
            g_key_file_set_string(kf, "ipv6", "addr-gen-mode", addr_gen_mode_str(def->ip6_addr_gen_mode));
        if (def->ip6_privacy)
            g_key_file_set_integer(kf, "ipv6", "ip6-privacy", 2);
        if (def->gateway6)
            g_key_file_set_string(kf, "ipv6", "gateway", def->gateway6);
        if (def->ip6_nameservers) {
            const gchar* list[def->ip6_nameservers->len];
            for (unsigned i = 0; i < def->ip6_nameservers->len; ++i)
                list[i] = g_array_index(def->ip6_nameservers, char*, i);
            g_key_file_set_string_list(kf, "ipv6", "dns", list, def->ip6_nameservers->len);
        }
        /* nm-settings(5) specifies search-domain for both [ipv4] and [ipv6] --
         * We need to specify it here for the IPv6-only case - see LP: #1786726 */
        write_search_domains(def, "ipv6", kf);

        /* We can only write valid routes if there is a DHCPv6 or static IPv6 address */
        write_routes(def, kf, AF_INET6);

        if (!def->dhcp6_overrides.use_routes) {
            g_key_file_set_boolean(kf, "ipv6", "ignore-auto-routes", TRUE);
            g_key_file_set_boolean(kf, "ipv6", "never-default", TRUE);
        }

        if (def->dhcp6_overrides.metric != NETPLAN_METRIC_UNSPEC)
            g_key_file_set_uint64(kf, "ipv6", "route-metric", def->dhcp6_overrides.metric);
    }
    else
        g_key_file_set_string(kf, "ipv6", "method", "ignore");

    if (def->backend_settings.nm.passthrough) {
        g_debug("NetworkManager: using keyfile passthrough mode");
        /* Write all key-value pairs from the hashtable into the keyfile,
         * potentially overriding existing values, if not fully supported. */
        g_datalist_foreach(&def->backend_settings.nm.passthrough, write_fallback_key_value, kf);
    }

    if (ap) {
        g_autofree char* escaped_ssid = g_uri_escape_string(ap->ssid, NULL, TRUE);
        conf_path = g_strjoin(NULL, "run/NetworkManager/system-connections/netplan-", def->id, "-", escaped_ssid, ".nmconnection", NULL);

        g_key_file_set_string(kf, "wifi", "ssid", ap->ssid);
        if (ap->mode < NETPLAN_WIFI_MODE_OTHER)
            g_key_file_set_string(kf, "wifi", "mode", wifi_mode_str(ap->mode));
        if (ap->bssid)
            g_key_file_set_string(kf, "wifi", "bssid", ap->bssid);
        if (ap->hidden)
            g_key_file_set_boolean(kf, "wifi", "hidden", TRUE);
        if (ap->band == NETPLAN_WIFI_BAND_5 || ap->band == NETPLAN_WIFI_BAND_24) {
            g_key_file_set_string(kf, "wifi", "band", wifi_band_str(ap->band));
            /* Channel is only unambiguous, if band is set. */
            if (ap->channel) {
                /* Validate WiFi channel */
                if (ap->band == NETPLAN_WIFI_BAND_5)
                    wifi_get_freq5(ap->channel);
                else
                    wifi_get_freq24(ap->channel);
                g_key_file_set_uint64(kf, "wifi", "channel", ap->channel);
            }
        }
        if (ap->has_auth) {
            write_wifi_auth_parameters(&ap->auth, kf);
        }
        if (ap->backend_settings.nm.passthrough) {
            g_debug("NetworkManager: using AP keyfile passthrough mode");
            /* Write all key-value pairs from the hashtable into the keyfile,
             * potentially overriding existing values, if not fully supported.
             * AP passthrough values have higher priority than ND passthrough,
             * because they are more specific and bound to the current SSID's
             * NM connection profile. */
            g_datalist_foreach((GData**)&ap->backend_settings.nm.passthrough, write_fallback_key_value, kf);
        }
    } else {
        conf_path = g_strjoin(NULL, "run/NetworkManager/system-connections/netplan-", def->id, ".nmconnection", NULL);
        if (def->has_auth) {
            write_dot1x_auth_parameters(&def->auth, kf);
        }
    }

    /* NM connection files might contain secrets, and NM insists on tight permissions */
    full_path = g_strjoin(G_DIR_SEPARATOR_S, rootdir ?: "", conf_path, NULL);
    orig_umask = umask(077);
    safe_mkdir_p_dir(full_path);
    if (!g_key_file_save_to_file(kf, full_path, &error)) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "ERROR: cannot create file %s: %s\n", full_path, error->message);
        exit(1);
        // LCOV_EXCL_STO
    }
    umask(orig_umask);
}

/**
 * Generate NetworkManager configuration in @rootdir/run/NetworkManager/ for a
 * particular NetplanNetDefinition.
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
void
write_nm_conf(NetplanNetDefinition* def, const char* rootdir)
{
    if (def->backend != NETPLAN_BACKEND_NM) {
        g_debug("NetworkManager: definition %s is not for us (backend %i)", def->id, def->backend);
        return;
    }

    if (def->match.driver && !def->set_name) {
        g_fprintf(stderr, "ERROR: %s: NetworkManager definitions do not support matching by driver\n", def->id);
        exit(1);
    }

    if (def->address_options) {
        g_fprintf(stderr, "ERROR: %s: NetworkManager does not support address options\n", def->id);
        exit(1);
    }

    if (def->type == NETPLAN_DEF_TYPE_WIFI) {
        GHashTableIter iter;
        gpointer key;
        const NetplanWifiAccessPoint* ap;
        g_assert(def->access_points);
        g_hash_table_iter_init(&iter, def->access_points);
        while (g_hash_table_iter_next(&iter, &key, (gpointer) &ap))
            write_nm_conf_access_point(def, rootdir, ap);
    } else {
        g_assert(def->access_points == NULL);
        write_nm_conf_access_point(def, rootdir, NULL);
    }
}

static void
nd_append_non_nm_ids(gpointer data, gpointer str)
{
    const NetplanNetDefinition* nd = data;

    if (nd->backend != NETPLAN_BACKEND_NM) {
        if (nd->match.driver) {
            /* TODO: NetworkManager supports (non-globbing) "driver:..." matching nowadays */
            /* NM cannot match on drivers, so ignore these via udev rules */
            if (!udev_rules)
                udev_rules = g_string_new(NULL);
            g_string_append_printf(udev_rules, "ACTION==\"add|change\", SUBSYSTEM==\"net\", ENV{ID_NET_DRIVER}==\"%s\", ENV{NM_UNMANAGED}=\"1\"\n", nd->match.driver);
        } else {
            g_string_append_netdef_match((GString*) str, nd);
        }
    }
}

void
write_nm_conf_finish(const char* rootdir)
{
    GString *s = NULL;
    gsize len;

    if (!netdefs || g_hash_table_size(netdefs) == 0)
        return;

    /* Set all devices not managed by us to unmanaged, so that NM does not
     * auto-connect and interferes */
    s = g_string_new("[keyfile]\n# devices managed by networkd\nunmanaged-devices+=");
    len = s->len;
    g_list_foreach(netdefs_ordered, nd_append_non_nm_ids, s);
    if (s->len > len)
        g_string_free_to_file(s, rootdir, "run/NetworkManager/conf.d/netplan.conf", NULL);
    else
        g_string_free(s, TRUE);

    /* write generated udev rules */
    if (udev_rules)
        g_string_free_to_file(udev_rules, rootdir, "run/udev/rules.d/90-netplan.rules", NULL);
}

/**
 * Clean up all generated configurations in @rootdir from previous runs.
 */
void
cleanup_nm_conf(const char* rootdir)
{
    g_autofree char* confpath = g_strjoin(NULL, rootdir ?: "", "/run/NetworkManager/conf.d/netplan.conf", NULL);
    g_autofree char* global_manage_path = g_strjoin(NULL, rootdir ?: "", "/run/NetworkManager/conf.d/10-globally-managed-devices.conf", NULL);
    unlink(confpath);
    unlink(global_manage_path);
    unlink_glob(rootdir, "/run/NetworkManager/system-connections/netplan-*");
}
