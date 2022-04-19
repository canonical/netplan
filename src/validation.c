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
#include <regex.h>

#include <yaml.h>

#include "parse.h"
#include "types.h"
#include "parse-globals.h"
#include "names.h"
#include "error.h"
#include "util-internal.h"
#include "validation.h"

/* Check sanity for address types */

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

/* Check sanity of OpenVSwitch controller targets */
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
            if (!g_strrstr(tmp, "]:"))
                vec = g_strsplit(g_strdup_printf("%s:%u", tmp, dport), "]:", 2);
            else
                vec = g_strsplit(tmp, "]:", 2);
        // IP4 host
        } else {
            // append default port to unify parsing
            if (!g_strrstr(s, ":"))
                vec = g_strsplit(g_strdup_printf("%s:%u", s, dport), ":", 2);
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

/************************************************
 * Validation for grammar and backend rules.
 ************************************************/
static gboolean
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

static gboolean
validate_tunnel_grammar(const NetplanParser* npp, NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
{
    if (nd->tunnel.mode == NETPLAN_TUNNEL_MODE_UNKNOWN)
        return yaml_error(npp, node, error, "%s: missing 'mode' property for tunnel", nd->id);

    if (nd->tunnel.mode == NETPLAN_TUNNEL_MODE_WIREGUARD) {
        if (!nd->tunnel.private_key)
            return yaml_error(npp, node, error, "%s: missing 'key' property (private key) for wireguard", nd->id);
        if (nd->tunnel.private_key[0] != '/' && !is_wireguard_key(nd->tunnel.private_key))
            return yaml_error(npp, node, error, "%s: invalid wireguard private key", nd->id);
        if (!nd->wireguard_peers || nd->wireguard_peers->len == 0)
            return yaml_error(npp, node, error, "%s: at least one peer is required.", nd->id);
        for (guint i = 0; i < nd->wireguard_peers->len; i++) {
            NetplanWireguardPeer *peer = g_array_index (nd->wireguard_peers, NetplanWireguardPeer*, i);

            if (!peer->public_key)
                return yaml_error(npp, node, error, "%s: keys.public is required.", nd->id);
            if (!is_wireguard_key(peer->public_key))
                return yaml_error(npp, node, error, "%s: invalid wireguard public key", nd->id);
            if (peer->preshared_key && peer->preshared_key[0] != '/' && !is_wireguard_key(peer->preshared_key))
                return yaml_error(npp, node, error, "%s: invalid wireguard shared key", nd->id);
            if (!peer->allowed_ips || peer->allowed_ips->len == 0)
                return yaml_error(npp, node, error, "%s: 'to' is required to define the allowed IPs.", nd->id);
            if (peer->keepalive > 65535)
                return yaml_error(npp, node, error, "%s: keepalive must be 0-65535 inclusive.", nd->id);
        }
        return TRUE;
    } else {
        if (nd->tunnel.input_key && !validate_tunnel_key(npp, node, nd->tunnel.input_key, error))
            return FALSE;
        if (nd->tunnel.output_key && !validate_tunnel_key(npp, node, nd->tunnel.output_key, error))
            return FALSE;
    }

    /* Validate local/remote IPs */
    if (!nd->tunnel.local_ip)
        return yaml_error(npp, node, error, "%s: missing 'local' property for tunnel", nd->id);
    if (!nd->tunnel.remote_ip)
        return yaml_error(npp, node, error, "%s: missing 'remote' property for tunnel", nd->id);
    if (nd->tunnel_ttl && nd->tunnel_ttl > 255)
        return yaml_error(npp, node, error, "%s: 'ttl' property for tunnel must be in range [1...255]", nd->id);

    switch(nd->tunnel.mode) {
        case NETPLAN_TUNNEL_MODE_IPIP6:
        case NETPLAN_TUNNEL_MODE_IP6IP6:
        case NETPLAN_TUNNEL_MODE_IP6GRE:
        case NETPLAN_TUNNEL_MODE_IP6GRETAP:
        case NETPLAN_TUNNEL_MODE_VTI6:
            if (!is_ip6_address(nd->tunnel.local_ip))
                return yaml_error(npp, node, error, "%s: 'local' must be a valid IPv6 address for this tunnel type", nd->id);
            if (!is_ip6_address(nd->tunnel.remote_ip))
                return yaml_error(npp, node, error, "%s: 'remote' must be a valid IPv6 address for this tunnel type", nd->id);
            break;

        default:
            if (!is_ip4_address(nd->tunnel.local_ip))
                return yaml_error(npp, node, error, "%s: 'local' must be a valid IPv4 address for this tunnel type", nd->id);
            if (!is_ip4_address(nd->tunnel.remote_ip))
                return yaml_error(npp, node, error, "%s: 'remote' must be a valid IPv4 address for this tunnel type", nd->id);
            break;
    }

    return TRUE;
}

static gboolean
validate_tunnel_backend_rules(const NetplanParser* npp, NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
{
    /* Backend-specific validation rules for tunnels */
    switch (nd->backend) {
        case NETPLAN_BACKEND_NETWORKD:
            switch (nd->tunnel.mode) {
                case NETPLAN_TUNNEL_MODE_VTI:
                case NETPLAN_TUNNEL_MODE_VTI6:
                case NETPLAN_TUNNEL_MODE_WIREGUARD:
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
                    break;

                case NETPLAN_TUNNEL_MODE_GRETAP:
                case NETPLAN_TUNNEL_MODE_IP6GRETAP:
                    return yaml_error(npp, node, error,
                                      "%s: %s tunnel mode is not supported by NetworkManager",
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

        default: break; //LCOV_EXCL_LINE
    }

    return TRUE;
}

gboolean
validate_netdef_grammar(const NetplanParser* npp, NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
{
    int missing_id_count = g_hash_table_size(npp->missing_id);
    gboolean valid = FALSE;

    g_assert(nd->type != NETPLAN_DEF_TYPE_NONE);

    /* Skip all validation if we're missing some definition IDs (devices).
     * The ones we have yet to see may be necessary for validation to succeed,
     * we can complete it on the next parser pass. */
    if (missing_id_count > 0)
        return TRUE;

    /* set-name: requires match: */
    if (nd->set_name && !nd->has_match)
        return yaml_error(npp, node, error, "%s: 'set-name:' requires 'match:' properties", nd->id);

    if (nd->type == NETPLAN_DEF_TYPE_WIFI && nd->access_points == NULL)
        return yaml_error(npp, node, error, "%s: No access points defined", nd->id);

    if (nd->type == NETPLAN_DEF_TYPE_VLAN) {
        if (!nd->vlan_link)
            return yaml_error(npp, node, error, "%s: missing 'link' property", nd->id);
        nd->vlan_link->has_vlans = TRUE;
        if (nd->vlan_id == G_MAXUINT)
            return yaml_error(npp, node, error, "%s: missing 'id' property", nd->id);
        if (nd->vlan_id > 4094)
            return yaml_error(npp, node, error, "%s: invalid id '%u' (allowed values are 0 to 4094)", nd->id, nd->vlan_id);
    }

    if (nd->type == NETPLAN_DEF_TYPE_VXLAN) {
        if (nd->vxlan_vni == G_MAXUINT)
            return yaml_error(npp, node, error, "%s: missing 'vni' property", nd->id);
        if (nd->vxlan_vni > 16777216)
            return yaml_error(npp, node, error, "%s: invalid vni '%u' (allowed values are 0 to 16777216)", nd->id, nd->vxlan_vni);
        if (nd->vxlan_params.ttl > 255)
            return yaml_error(npp, node, error, "%s: invalid ttl '%u' (allowed values are 0 to 255)", nd->id, nd->vxlan_params.ttl);
        if (nd->vxlan_params.flow_label > 1048575)
            return yaml_error(npp, node, error, "%s: invalid flow-label '%u' (allowed values are 0 to 1048575)", nd->id, nd->vxlan_params.flow_label);
    }

    if (nd->type == NETPLAN_DEF_TYPE_VRF) {
        if (nd->vrf_table == G_MAXUINT)
            return yaml_error(npp, node, error, "%s: missing 'table' property", nd->id);
    }

    if (nd->type == NETPLAN_DEF_TYPE_TUNNEL) {
        valid = validate_tunnel_grammar(npp, nd, node, error);
        if (!valid)
            goto netdef_grammar_error;
    }

    if (nd->ip6_addr_gen_mode != NETPLAN_ADDRGEN_DEFAULT && nd->ip6_addr_gen_token)
        return yaml_error(npp, node, error, "%s: ipv6-address-generation and ipv6-address-token are mutually exclusive", nd->id);

    if (nd->backend == NETPLAN_BACKEND_OVS) {
        // LCOV_EXCL_START
        if (!g_file_test(OPENVSWITCH_OVS_VSCTL, G_FILE_TEST_EXISTS)) {
            /* Tested via integration test */
            return yaml_error(npp, node, error, "%s: The 'ovs-vsctl' tool is required to setup OpenVSwitch interfaces.", nd->id);
        }
        // LCOV_EXCL_STOP
    }

    if (nd->type == NETPLAN_DEF_TYPE_NM && (!nd->backend_settings.nm.passthrough || !g_datalist_get_data(&nd->backend_settings.nm.passthrough, "connection.type")))
        return yaml_error(npp, node, error, "%s: network type 'nm-devices:' needs to provide a 'connection.type' via passthrough", nd->id);

    valid = TRUE;

netdef_grammar_error:
    return valid;
}

gboolean
validate_backend_rules(const NetplanParser* npp, NetplanNetDefinition* nd, GError** error)
{
    gboolean valid = FALSE;
    /* Set a dummy, NULL yaml_node_t for error reporting */
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
    /* Set a dummy, NULL yaml_node_t for error reporting */
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

struct _defroute_entry {
    int family;
    int table;
    int metric;
    const char *netdef_id;
};

static void
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
        snprintf(metric_name, sizeof(metric_name) - 1, "metric: %d", entry->metric);

    g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT,
            "Conflicting default route declarations for %s (%s, %s), first declared in %s but also in %s",
            (entry->family == AF_INET) ? "IPv4" : "IPv6",
            table_name,
            metric_name,
            entry->netdef_id,
            new_netdef_id);
}

static gboolean
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
validate_default_route_consistency(const NetplanParser* npp, GHashTable *netdefs, GError ** error)
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
