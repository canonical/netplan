/*
 * Copyright (C) 2019 Canonical, Ltd.
 * Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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
#include <glib/gstdio.h>
#include <gio/gio.h>
#include <arpa/inet.h>
#include <net/if.h>
#include <regex.h>

#include <yaml.h>

#include "parse.h"
#include "types-internal.h"
#include "names.h"
#include "error.h"
#include "util-internal.h"
#include "validation.h"

/* Check coherence for address types */

gboolean
is_ip4_address(const char* address)
{
    struct in_addr a4;
    int ret;

    ret = inet_pton(AF_INET, address, &a4);
    g_assert(ret >= 0);
    if (ret > 0)
        return TRUE;

    return FALSE;
}

gboolean
is_ip6_address(const char* address)
{
    struct in6_addr a6;
    int ret;

    ret = inet_pton(AF_INET6, address, &a6);
    g_assert(ret >= 0);
    if (ret > 0)
        return TRUE;

    return FALSE;
}

gboolean
is_hostname(const char *hostname)
{
    static const gchar *pattern = "^(([a-z0-9]|[a-z0-9][a-z0-9\\-]*[a-z0-9])\\.)*([a-z0-9]|[a-z0-9][a-z0-9\\-]*[a-z0-9])$";
    return g_regex_match_simple(pattern, hostname, G_REGEX_CASELESS, G_REGEX_MATCH_NOTEMPTY);
}

gboolean
is_wireguard_key(const char* key)
{
    /* Check if this is (most likely) a 265bit, base64 encoded wireguard key */
    if (strlen(key) == 44 && key[43] == '=' && key[42] != '=') {
        static const gchar *pattern = "^(?:[A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{3}=)+$";
        return g_regex_match_simple(pattern, key, 0, G_REGEX_MATCH_NOTEMPTY);
    }
    return FALSE;
}

/* Check coherence of OpenVSwitch controller targets */
gboolean
validate_ovs_target(gboolean host_first, gchar* s) {
    static guint dport = 6653; // the default port
    g_autofree gchar* host = NULL;
    g_autofree gchar* port = NULL;
    gchar** vec = NULL;

    /* Format tcp:host[:port] or ssl:host[:port] */
    if (host_first) {
        g_assert(s != NULL);
        // IP6 host, indicated by bracketed notation ([..IPv6..])
        if (s[0] == '[') {
            gchar* tmp = NULL;
            tmp = s+1; //get rid of leading '['
            // append default port to unify parsing
            if (!g_strrstr(tmp, "]:")) {
                gchar* host_port = g_strdup_printf("%s:%u", tmp, dport);
                vec = g_strsplit(host_port, "]:", 2);
                g_free(host_port);
            }
            else
                vec = g_strsplit(tmp, "]:", 2);
        // IP4 host
        } else {
            // append default port to unify parsing
            if (!g_strrstr(s, ":")) {
                gchar* host_port = g_strdup_printf("%s:%u", s, dport);
                vec = g_strsplit(host_port, ":", 2);
                g_free(host_port);
            }
            else
                vec = g_strsplit(s, ":", 2);
        }
        // host and port are always set
        host = g_strdup(vec[0]); //set host alias
        port = g_strdup(vec[1]); //set port alias
        g_assert(vec[2] == NULL);
        g_strfreev(vec);
    /* Format ptcp:[port][:host] or pssl:[port][:host] */
    } else {
        // special case: "ptcp:" (no port, no host)
        if (!g_strcmp0(s, ""))
            port = g_strdup_printf("%u", dport);
        else {
            vec = g_strsplit(s, ":", 2);
            port = g_strdup(vec[0]);
            host = g_strdup(vec[1]);
            // get rid of leading & trailing IPv6 brackets
            if (host && host[0] == '[') {
                char **split = g_strsplit_set(host, "[]", 3);
                g_free(host);
                host = g_strjoinv("", split);
                g_strfreev(split);
            }
            g_strfreev(vec);
        }
    }

    g_assert(port != NULL);
    // special case where IPv6 notation contains '%iface' name
    if (host && g_strrstr(host, "%")) {
        gchar** split = g_strsplit (host, "%", 2);
        g_free(host);
        host = g_strdup(split[0]); // designated scope for IPv6 link-level addresses
        g_assert(split[1] != NULL && split[2] == NULL);
        g_strfreev(split);
    }

    if (atoi(port) > 0 && atoi(port) <= 65535) {
        if (!host)
            return TRUE;
        else if (host && (is_ip4_address(host) || is_ip6_address(host)))
            return TRUE;
    }
    return FALSE;
}

STATIC gboolean
validate_interface_name_length(const NetplanNetDefinition* netdef)
{
    gboolean validation = TRUE;
    char* iface = NULL;

    if (netdef->type >= NETPLAN_DEF_TYPE_VIRTUAL && netdef->type < NETPLAN_DEF_TYPE_NM) {
        if (strnlen(netdef->id, IF_NAMESIZE) == IF_NAMESIZE) {
            iface = netdef->id;
            validation = FALSE;
        }
    } else if (netdef->set_name) {
        if (strnlen(netdef->set_name, IF_NAMESIZE) == IF_NAMESIZE) {
            iface = netdef->set_name;
            validation = FALSE;
        }
    }

    /* TODO: make this a hard failure in the future, but keep it as a warning
     *       for now, to not break netplan generate at boot. */
    if (iface)
        g_warning("Interface name '%s' is too long. It will be ignored by the backend.", iface);

    return validation;
}

/************************************************
 * Validation for grammar and backend rules.
 ************************************************/
STATIC gboolean
validate_tunnel_key(const NetplanParser* npp, yaml_node_t* node, gchar* key, GError** error)
{
    /* Tunnel key should be a number or dotted quad, except for wireguard. */
    gchar* endptr;
    guint64 v = g_ascii_strtoull(key, &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT) {
        /* Not a simple uint, try for a dotted quad */
        if (!is_ip4_address(key))
            return yaml_error(npp, node, error, "invalid tunnel key '%s'", key);
    }
    return TRUE;
}

STATIC gboolean
validate_tunnel_grammar(const NetplanParser* npp, NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
{
    if (nd->tunnel.mode == NETPLAN_TUNNEL_MODE_UNKNOWN)
        return yaml_error(npp, node, error, "%s: missing or invalid 'mode' property for tunnel", nd->id);

    if (nd->tunnel.mode == NETPLAN_TUNNEL_MODE_WIREGUARD) {
        if (!nd->tunnel.private_key && nd->tunnel_private_key_flags == NETPLAN_KEY_FLAG_NONE)
            g_warning("%s: missing 'key' property (private key) for wireguard", nd->id);
        if (nd->tunnel.private_key && nd->tunnel.private_key[0] != '/' && !is_wireguard_key(nd->tunnel.private_key))
            return yaml_error(npp, node, error, "%s: invalid wireguard private key", nd->id);
        if (!nd->wireguard_peers || nd->wireguard_peers->len == 0) {
            g_warning("%s: at least one peer is required.", nd->id);
        } else {
            for (guint i = 0; i < nd->wireguard_peers->len; i++) {
                NetplanWireguardPeer *peer = g_array_index (nd->wireguard_peers, NetplanWireguardPeer*, i);

                if (!peer->allowed_ips || peer->allowed_ips->len == 0)
                    g_warning("%s: 'allowed-ips' is required for wireguard peers.", nd->id);
                if (peer->keepalive > 65535)
                    return yaml_error(npp, node, error, "%s: keepalive must be 0-65535 inclusive.", nd->id);

                if (!peer->public_key)
                    return yaml_error(npp, node, error, "%s: a public key is required.", nd->id);
                if (!is_wireguard_key(peer->public_key))
                    return yaml_error(npp, node, error, "%s: invalid wireguard public key", nd->id);
                if (peer->preshared_key && peer->preshared_key[0] != '/' && !is_wireguard_key(peer->preshared_key))
                    return yaml_error(npp, node, error, "%s: invalid wireguard shared key", nd->id);
            }
        }
        return TRUE;
    } else {
        if (nd->tunnel.input_key && !validate_tunnel_key(npp, node, nd->tunnel.input_key, error))
            return FALSE;
        if (nd->tunnel.output_key && !validate_tunnel_key(npp, node, nd->tunnel.output_key, error))
            return FALSE;
    }

    /* Validate local/remote IPs */
    if (nd->tunnel.mode != NETPLAN_TUNNEL_MODE_VXLAN) {
        if (!nd->tunnel.remote_ip)
            return yaml_error(npp, node, error, "%s: missing 'remote' property for tunnel", nd->id);
    }
    if (nd->tunnel_ttl && nd->tunnel_ttl > 255)
        return yaml_error(npp, node, error, "%s: 'ttl' property for tunnel must be in range [1...255]", nd->id);

    switch(nd->tunnel.mode) {
        case NETPLAN_TUNNEL_MODE_IPIP6:
        case NETPLAN_TUNNEL_MODE_IP6IP6:
        case NETPLAN_TUNNEL_MODE_IP6GRE:
        case NETPLAN_TUNNEL_MODE_IP6GRETAP:
        case NETPLAN_TUNNEL_MODE_VTI6:
            if (nd->tunnel.local_ip && !is_ip6_address(nd->tunnel.local_ip))
                return yaml_error(npp, node, error, "%s: 'local' must be a valid IPv6 address for this tunnel type", nd->id);
            if (!is_ip6_address(nd->tunnel.remote_ip))
                return yaml_error(npp, node, error, "%s: 'remote' must be a valid IPv6 address for this tunnel type", nd->id);
            break;

        case NETPLAN_TUNNEL_MODE_VXLAN:
            if ((nd->tunnel.local_ip && nd->tunnel.remote_ip) &&
                (is_ip6_address(nd->tunnel.local_ip) != is_ip6_address(nd->tunnel.remote_ip)))
                return yaml_error(npp, node, error, "%s: 'local' and 'remote' must be of same IP family type", nd->id);
            break;

        default:
            if (nd->tunnel.local_ip && !is_ip4_address(nd->tunnel.local_ip))
                return yaml_error(npp, node, error, "%s: 'local' must be a valid IPv4 address for this tunnel type", nd->id);
            if (!is_ip4_address(nd->tunnel.remote_ip))
                return yaml_error(npp, node, error, "%s: 'remote' must be a valid IPv4 address for this tunnel type", nd->id);
            break;
    }

    return TRUE;
}

STATIC gboolean
validate_tunnel_backend_rules(const NetplanParser* npp, NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
{
    /* Backend-specific validation rules for tunnels */
    switch (nd->backend) {
        case NETPLAN_BACKEND_NETWORKD:
            switch (nd->tunnel.mode) {
                case NETPLAN_TUNNEL_MODE_VTI:
                case NETPLAN_TUNNEL_MODE_VTI6:
                case NETPLAN_TUNNEL_MODE_WIREGUARD:
                case NETPLAN_TUNNEL_MODE_GRE:
                case NETPLAN_TUNNEL_MODE_IP6GRE:
                case NETPLAN_TUNNEL_MODE_GRETAP:
                case NETPLAN_TUNNEL_MODE_IP6GRETAP:
                    break;

                /* TODO: Remove this exception and fix ISATAP handling with the
                 *       networkd backend.
                 *       systemd-networkd has grown ISATAP support in 918049a.
                 */
                case NETPLAN_TUNNEL_MODE_ISATAP:
                    return yaml_error(npp, node, error,
                                      "%s: %s tunnel mode is not supported by networkd",
                                      nd->id,
                                      g_ascii_strup(netplan_tunnel_mode_name(nd->tunnel.mode), -1));
                    break;

                default:
                    if (nd->tunnel.input_key)
                        return yaml_error(npp, node, error, "%s: 'input-key' is not required for this tunnel type", nd->id);
                    if (nd->tunnel.output_key)
                        return yaml_error(npp, node, error, "%s: 'output-key' is not required for this tunnel type", nd->id);
                    break;
            }
            break;

        case NETPLAN_BACKEND_NM:
            switch (nd->tunnel.mode) {
                case NETPLAN_TUNNEL_MODE_GRE:
                case NETPLAN_TUNNEL_MODE_IP6GRE:
                case NETPLAN_TUNNEL_MODE_WIREGUARD:
                case NETPLAN_TUNNEL_MODE_GRETAP:
                case NETPLAN_TUNNEL_MODE_IP6GRETAP:
                    break;
                default:
                    if (nd->tunnel.input_key)
                        return yaml_error(npp, node, error, "%s: 'input-key' is not required for this tunnel type", nd->id);
                    if (nd->tunnel.output_key)
                        return yaml_error(npp, node, error, "%s: 'output-key' is not required for this tunnel type", nd->id);
                    break;
            }
            break;

        default: break; //LCOV_EXCL_LINE
    }

    return TRUE;
}

gboolean
validate_netdef_grammar(const NetplanParser* npp, NetplanNetDefinition* nd, GError** error)
{
    int missing_id_count = g_hash_table_size(npp->missing_id);
    gboolean valid = FALSE;
    NetplanBackend backend = nd->backend;

    g_assert(nd->type != NETPLAN_DEF_TYPE_NONE);

    /* Skip all validation if we're missing some definition IDs (devices).
     * The ones we have yet to see may be necessary for validation to succeed,
     * we can complete it on the next parser pass. */
    if (missing_id_count > 0)
        return TRUE;

    /* set-name: requires match: */
    if (nd->set_name && !nd->has_match)
        return yaml_error(npp, NULL, error, "%s: 'set-name:' requires 'match:' properties", nd->id);

    if (nd->type == NETPLAN_DEF_TYPE_WIFI && nd->access_points == NULL)
        return yaml_error(npp, NULL, error, "%s: No access points defined", nd->id);

    if (nd->type == NETPLAN_DEF_TYPE_VLAN) {
        if (!nd->vlan_link)
            return yaml_error(npp, NULL, error, "%s: missing 'link' property", nd->id);
        nd->vlan_link->has_vlans = TRUE;
        if (nd->vlan_id == G_MAXUINT)
            return yaml_error(npp, NULL, error, "%s: missing 'id' property", nd->id);
        if (nd->vlan_id > 4094)
            return yaml_error(npp, NULL, error, "%s: invalid id '%u' (allowed values are 0 to 4094)", nd->id, nd->vlan_id);
    }

    if (nd->type == NETPLAN_DEF_TYPE_TUNNEL &&
        nd->tunnel.mode == NETPLAN_TUNNEL_MODE_VXLAN) {
        if (nd->vxlan->vni == 0)
            return yaml_error(npp, NULL, error,
                              "%s: missing 'id' property (VXLAN VNI)", nd->id);
        if (nd->vxlan->vni < 1 || nd->vxlan->vni > 16777215)
            return yaml_error(npp, NULL, error, "%s: VXLAN 'id' (VNI) "
                              "must be in range [1..16777215]", nd->id);
        if (nd->vxlan->flow_label != G_MAXUINT && nd->vxlan->flow_label > 1048575)
            return yaml_error(npp, NULL, error, "%s: VXLAN 'flow-label' "
                              "must be in range [0..1048575]", nd->id);
    }

    if (nd->type == NETPLAN_DEF_TYPE_VRF) {
        if (nd->vrf_table == G_MAXUINT)
            return yaml_error(npp, NULL, error, "%s: missing 'table' property", nd->id);
    }

    if (nd->type == NETPLAN_DEF_TYPE_TUNNEL) {
        valid = validate_tunnel_grammar(npp, nd, NULL, error);
        if (!valid)
            goto netdef_grammar_error;
    }

    if (nd->type == NETPLAN_DEF_TYPE_VETH) {
        if (!nd->veth_peer_link)
            return yaml_error(npp, NULL, error, "%s: virtual-ethernet missing 'peer' property", nd->id);
    }

    if (nd->ip6_addr_gen_mode != NETPLAN_ADDRGEN_DEFAULT && nd->ip6_addr_gen_token)
        return yaml_error(npp, NULL, error, "%s: ipv6-address-generation and ipv6-address-token are mutually exclusive", nd->id);

    if (nd->backend == NETPLAN_BACKEND_OVS) {
        // LCOV_EXCL_START
        if (!g_file_test(OPENVSWITCH_OVS_VSCTL, G_FILE_TEST_EXISTS)) {
            /* Tested via integration test */
            return yaml_error(npp, NULL, error, "%s: The 'ovs-vsctl' tool is required to setup OpenVSwitch interfaces.", nd->id);
        }
        // LCOV_EXCL_STOP
    }

    if (nd->type == NETPLAN_DEF_TYPE_NM && (!nd->backend_settings.passthrough || !g_datalist_get_data(&nd->backend_settings.passthrough, "connection.type")))
        return yaml_error(npp, NULL, error, "%s: network type 'nm-devices:' needs to provide a 'connection.type' via passthrough", nd->id);

    if (npp->current.netdef)
        validate_interface_name_length(npp->current.netdef);

    if (backend == NETPLAN_BACKEND_NONE)
        backend = npp->global_backend;

    if (nd->has_backend_settings_nm && backend != NETPLAN_BACKEND_NM) {
            return yaml_error(npp, NULL, error, "%s: networkmanager backend settings found but renderer is not NetworkManager.", nd->id);
    }

    valid = TRUE;

netdef_grammar_error:
    return valid;
}

gboolean
validate_backend_rules(const NetplanParser* npp, NetplanNetDefinition* nd, GError** error)
{
    gboolean valid = FALSE;
    /* Set a placeholder, NULL yaml_node_t for error reporting */
    yaml_node_t* node = NULL;

    g_assert(nd->type != NETPLAN_DEF_TYPE_NONE);

    if (nd->type == NETPLAN_DEF_TYPE_TUNNEL) {
        valid = validate_tunnel_backend_rules(npp, nd, node, error);
        if (!valid)
            goto backend_rules_error;
    }

    valid = TRUE;

backend_rules_error:
    return valid;
}

gboolean
validate_sriov_rules(const NetplanParser* npp, NetplanNetDefinition* nd, GError** error)
{
    /* The SR-IOV checks need to be executed after all netdefs have been parsed;
     * only then can we calculate the PF/VF dependencies between the different
     * network definitions. */
    NetplanNetDefinition* def;
    GHashTableIter iter;
    gboolean valid = FALSE;
    /* Set a placeholder, NULL yaml_node_t for error reporting */
    yaml_node_t* node = NULL;

    g_assert(nd->type != NETPLAN_DEF_TYPE_NONE);

    if (nd->type == NETPLAN_DEF_TYPE_ETHERNET) {
        /* Is it defined as SR-IOV PF, explicitly? */
        gboolean is_sriov_pf = nd->sriov_explicit_vf_count < G_MAXUINT;
        /* Does it have any VF pointing to it? (to mark it a PF implicitly) */
        if (!is_sriov_pf) {
            g_hash_table_iter_init(&iter, npp->parsed_defs);
            while (g_hash_table_iter_next(&iter, NULL, (gpointer) &def)) {
                if (def->sriov_link == nd) {
                    is_sriov_pf = TRUE;
                    break;
                }
            }
        }
        gboolean eswitch_mode = (nd->embedded_switch_mode ||
                                 nd->sriov_delay_virtual_functions_rebind);
        if (eswitch_mode && !is_sriov_pf) {
            valid = yaml_error(npp, node, error, "%s: This is not a SR-IOV PF", nd->id);
            goto sriov_rules_error;
        }
    }
    valid = TRUE;

sriov_rules_error:
    return valid;
}

gboolean
adopt_and_validate_vrf_routes(__unused const NetplanParser *npp, GHashTable *netdefs, GError **error)
{
    gpointer key, value;
    GHashTableIter iter;

    g_hash_table_iter_init (&iter, netdefs);
    while (g_hash_table_iter_next (&iter, &key, &value))
    {
        NetplanNetDefinition *nd = value;
        if (nd->type != NETPLAN_DEF_TYPE_VRF)
            continue;

        /* Routes */
        if (nd->routes) {
            for (size_t i = 0; i < nd->routes->len; i++) {
                NetplanIPRoute* r = g_array_index(nd->routes, NetplanIPRoute*, i);
                if (r->table == nd->vrf_table) {
                    g_debug("%s: Ignoring redundant routes table %d (matches VRF table)", nd->id, r->table);
                    continue;
                } else if (r->table != NETPLAN_ROUTE_TABLE_UNSPEC) {
                    g_set_error(error, NETPLAN_VALIDATION_ERROR, NETPLAN_ERROR_CONFIG_GENERIC,
                            "%s: VRF routes table mismatch (%d != %d)", nd->id, nd->vrf_table, r->table);
                    return FALSE;
                } else {
                    r->table = nd->vrf_table;
                    g_debug("%s: Adopted VRF routes table to %d", nd->id, nd->vrf_table);
                }
            }
        }

        /* IP Rules */
        if (nd->ip_rules) {
            for (size_t i = 0; i < nd->ip_rules->len; i++) {
                NetplanIPRule* r = g_array_index(nd->ip_rules, NetplanIPRule*, i);
                if (r->table == nd->vrf_table) {
                    g_debug("%s: Ignoring redundant routing-policy table %d (matches VRF table)", nd->id, r->table);
                    continue;
                } else if (r->table != NETPLAN_ROUTE_TABLE_UNSPEC && r->table != nd->vrf_table) {
                    g_set_error(error, NETPLAN_VALIDATION_ERROR, NETPLAN_ERROR_CONFIG_GENERIC,
                            "%s: VRF routing-policy table mismatch (%d != %d)", nd->id, nd->vrf_table, r->table);
                    return FALSE;
                } else {
                    r->table = nd->vrf_table;
                    g_debug("%s: Adopted VRF routing-policy table to %d", nd->id, nd->vrf_table);
                }
            }
        }
    }

    return TRUE;
}

struct _defroute_entry {
    gint family;
    guint table;
    guint metric;
    const char *netdef_id;
};

STATIC void
defroute_err(struct _defroute_entry *entry, const char *new_netdef_id, GError **error) {
    char table_name[128] = {};
    char metric_name[128] = {};

    g_assert(entry->family == AF_INET || entry->family == AF_INET6);

    // XXX: handle 254 as an alias for main ?
    if (entry->table == NETPLAN_ROUTE_TABLE_UNSPEC)
        strncpy(table_name, "table: main", sizeof(table_name) - 1);
    else
        snprintf(table_name, sizeof(table_name) - 1, "table: %d", entry->table);

    if (entry->metric == NETPLAN_METRIC_UNSPEC)
        strncpy(metric_name, "metric: default", sizeof(metric_name) - 1);
    else
        snprintf(metric_name, sizeof(metric_name) - 1, "metric: %u", entry->metric);

    g_set_error(error, NETPLAN_VALIDATION_ERROR, NETPLAN_ERROR_CONFIG_GENERIC,
            "Conflicting default route declarations for %s (%s, %s), first declared in %s but also in %s",
            (entry->family == AF_INET) ? "IPv4" : "IPv6",
            table_name,
            metric_name,
            entry->netdef_id,
            new_netdef_id);
}

STATIC gboolean
check_defroute(struct _defroute_entry *candidate,
               GSList **entries,
               GError **error)
{
    struct _defroute_entry *entry;
    GSList *it;

    g_assert(entries != NULL);
    it = *entries;

    while (it) {
        struct _defroute_entry *e = it->data;
        if (e->family == candidate->family &&
                e->table == candidate->table &&
                e->metric == candidate->metric) {
            defroute_err(e, candidate->netdef_id, error);
            return FALSE;
        }
        it = it->next;
    }
    entry = g_malloc(sizeof(*entry));
    *entry = *candidate;
    *entries = g_slist_prepend(*entries, entry);
    return TRUE;
}

gboolean
validate_default_route_consistency(__unused const NetplanParser* npp, GHashTable *netdefs, GError ** error)
{
    struct _defroute_entry candidate = {};
    GSList *defroutes = NULL;
    gboolean ret = TRUE;
    gpointer key, value;
    GHashTableIter iter;

    g_hash_table_iter_init (&iter, netdefs);
    while (g_hash_table_iter_next (&iter, &key, &value))
    {
        NetplanNetDefinition *nd = value;
        candidate.netdef_id = key;
        candidate.metric = NETPLAN_METRIC_UNSPEC;
        candidate.table = NETPLAN_ROUTE_TABLE_UNSPEC;
        if (nd->gateway4) {
            candidate.family = AF_INET;
            if (!check_defroute(&candidate, &defroutes, error)) {
                ret = FALSE;
                break;
            }
        }
        if (nd->gateway6) {
            candidate.family = AF_INET6;
            if (!check_defroute(&candidate, &defroutes, error)) {
                ret = FALSE;
                break;
            }
        }

        if (!nd->routes)
            continue;

        for (size_t i = 0; i < nd->routes->len; i++) {
            NetplanIPRoute* r = g_array_index(nd->routes, NetplanIPRoute*, i);
            char *suffix = strrchr(r->to, '/');
            if (g_strcmp0(suffix, "/0") == 0 || g_strcmp0(r->to, "default") == 0) {
                candidate.family = r->family;
                candidate.table = r->table;
                candidate.metric = r->metric;
                if (!check_defroute(&candidate, &defroutes, error)) {
                    ret = FALSE;
                    break;
                }
            }
        }
    }
    g_slist_free_full(defroutes, g_free);
    return ret;
}

gboolean
validate_veth_pair(__unused const NetplanState* np_state, const NetplanNetDefinition* netdef, GError** error)
{

    NetplanNetDefinition* veth_peer = netdef->veth_peer_link;

    /* If the veth's peer type is the placeholder, it wasn't defined yet so it's not a non-veth device */
    if (veth_peer && veth_peer->type != NETPLAN_DEF_TYPE_NM_PLACEHOLDER_) {
        if (veth_peer->type != NETPLAN_DEF_TYPE_VETH) {
            g_set_error(error, NETPLAN_VALIDATION_ERROR, NETPLAN_ERROR_CONFIG_GENERIC,
                        "%s: virtual-ethernet peer '%s' is not a virtual-ethernet interface\n", netdef->id, veth_peer->id);
            return FALSE;
        }

        /* If the veth's peer has a peer link and its type is the placeholder, it's because it's not
         * referring to the correct interface as its peer.
         * Example: A.peer = B, B.peer = C and C is a placeholder.
         */
        if (veth_peer->veth_peer_link && veth_peer->veth_peer_link->type == NETPLAN_DEF_TYPE_NM_PLACEHOLDER_) {
            g_set_error(error, NETPLAN_VALIDATION_ERROR, NETPLAN_ERROR_CONFIG_GENERIC,
                        "%s: virtual-ethernet peer '%s' does not have a peer itself\n", netdef->id, veth_peer->id);
            return FALSE;
        }

        if (veth_peer->veth_peer_link && veth_peer->veth_peer_link != netdef) {
            g_set_error(error, NETPLAN_VALIDATION_ERROR, NETPLAN_ERROR_CONFIG_GENERIC,
                        "%s: virtual-ethernet peer '%s' is another virtual-ethernet's (%s) peer already\n",
                        netdef->id, veth_peer->id, veth_peer->veth_peer_link->id);
            return FALSE;
        }
    }

    return TRUE;
}
