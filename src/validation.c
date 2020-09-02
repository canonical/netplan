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
#include "error.h"
#include "util.h"


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
validate_tunnel_key(yaml_node_t* node, gchar* key, GError** error)
{
    /* Tunnel key should be a number or dotted quad, except for wireguard. */
    gchar* endptr;
    guint64 v = g_ascii_strtoull(key, &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT) {
        /* Not a simple uint, try for a dotted quad */
        if (!is_ip4_address(key))
            return yaml_error(node, error, "invalid tunnel key '%s'", key);
    }
    return TRUE;
}

static gboolean
validate_tunnel_grammar(NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
{
    if (nd->tunnel.mode == NETPLAN_TUNNEL_MODE_UNKNOWN)
        return yaml_error(node, error, "%s: missing 'mode' property for tunnel", nd->id);

    if (nd->tunnel.mode == NETPLAN_TUNNEL_MODE_WIREGUARD) {
        if (!nd->tunnel.private_key)
            return yaml_error(node, error, "%s: missing 'key' property (private key) for wireguard", nd->id);
        if (nd->tunnel.private_key[0] != '/' && !is_wireguard_key(nd->tunnel.private_key))
            return yaml_error(node, error, "%s: invalid wireguard private key", nd->id);
        if (!nd->wireguard_peers || nd->wireguard_peers->len == 0)
            return yaml_error(node, error, "%s: at least one peer is required.", nd->id);
        for (guint i = 0; i < nd->wireguard_peers->len; i++) {
            NetplanWireguardPeer *peer = g_array_index (nd->wireguard_peers, NetplanWireguardPeer*, i);

            if (!peer->public_key)
                return yaml_error(node, error, "%s: keys.public is required.", nd->id);
            if (!is_wireguard_key(peer->public_key))
                return yaml_error(node, error, "%s: invalid wireguard public key", nd->id);
            if (peer->preshared_key && peer->preshared_key[0] != '/' && !is_wireguard_key(peer->preshared_key))
                return yaml_error(node, error, "%s: invalid wireguard shared key", nd->id);
            if (!peer->allowed_ips || peer->allowed_ips->len == 0)
                return yaml_error(node, error, "%s: 'to' is required to define the allowed IPs.", nd->id);
            if (peer->keepalive > 65535)
                return yaml_error(node, error, "%s: keepalive must be 0-65535 inclusive.", nd->id);
        }
        return TRUE;
    } else {
        if (nd->tunnel.input_key && !validate_tunnel_key(node, nd->tunnel.input_key, error))
            return FALSE;
        if (nd->tunnel.output_key && !validate_tunnel_key(node, nd->tunnel.output_key, error))
            return FALSE;
    }

    /* Validate local/remote IPs */
    if (!nd->tunnel.local_ip)
        return yaml_error(node, error, "%s: missing 'local' property for tunnel", nd->id);
    if (!nd->tunnel.remote_ip)
        return yaml_error(node, error, "%s: missing 'remote' property for tunnel", nd->id);

    switch(nd->tunnel.mode) {
        case NETPLAN_TUNNEL_MODE_IPIP6:
        case NETPLAN_TUNNEL_MODE_IP6IP6:
        case NETPLAN_TUNNEL_MODE_IP6GRE:
        case NETPLAN_TUNNEL_MODE_IP6GRETAP:
        case NETPLAN_TUNNEL_MODE_VTI6:
            if (!is_ip6_address(nd->tunnel.local_ip))
                return yaml_error(node, error, "%s: 'local' must be a valid IPv6 address for this tunnel type", nd->id);
            if (!is_ip6_address(nd->tunnel.remote_ip))
                return yaml_error(node, error, "%s: 'remote' must be a valid IPv6 address for this tunnel type", nd->id);
            break;

        default:
            if (!is_ip4_address(nd->tunnel.local_ip))
                return yaml_error(node, error, "%s: 'local' must be a valid IPv4 address for this tunnel type", nd->id);
            if (!is_ip4_address(nd->tunnel.remote_ip))
                return yaml_error(node, error, "%s: 'remote' must be a valid IPv4 address for this tunnel type", nd->id);
            break;
    }

    return TRUE;
}

static gboolean
validate_tunnel_backend_rules(NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
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
                    return yaml_error(node, error,
                                      "%s: %s tunnel mode is not supported by networkd",
                                      nd->id,
                                      g_ascii_strup(tunnel_mode_to_string(nd->tunnel.mode), -1));
                    break;

                default:
                    if (nd->tunnel.input_key)
                        return yaml_error(node, error, "%s: 'input-key' is not required for this tunnel type", nd->id);
                    if (nd->tunnel.output_key)
                        return yaml_error(node, error, "%s: 'output-key' is not required for this tunnel type", nd->id);
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
                    return yaml_error(node, error,
                                      "%s: %s tunnel mode is not supported by NetworkManager",
                                      nd->id,
                                      g_ascii_strup(tunnel_mode_to_string(nd->tunnel.mode), -1));
                    break;

                default:
                    if (nd->tunnel.input_key)
                        return yaml_error(node, error, "%s: 'input-key' is not required for this tunnel type", nd->id);
                    if (nd->tunnel.output_key)
                        return yaml_error(node, error, "%s: 'output-key' is not required for this tunnel type", nd->id);
                    break;
            }
            break;

        default: break; //LCOV_EXCL_LINE
    }

    return TRUE;
}

gboolean
validate_netdef_grammar(NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
{
    int missing_id_count = g_hash_table_size(missing_id);
    gboolean valid = FALSE;

    g_assert(nd->type != NETPLAN_DEF_TYPE_NONE);

    /* Skip all validation if we're missing some definition IDs (devices).
     * The ones we have yet to see may be necessary for validation to succeed,
     * we can complete it on the next parser pass. */
    if (missing_id_count > 0)
        return TRUE;

    /* set-name: requires match: */
    if (nd->set_name && !nd->has_match)
        return yaml_error(node, error, "%s: 'set-name:' requires 'match:' properties", nd->id);

    if (nd->type == NETPLAN_DEF_TYPE_WIFI && nd->access_points == NULL)
        return yaml_error(node, error, "%s: No access points defined", nd->id);

    if (nd->type == NETPLAN_DEF_TYPE_VLAN) {
        if (!nd->vlan_link)
            return yaml_error(node, error, "%s: missing 'link' property", nd->id);
        nd->vlan_link->has_vlans = TRUE;
        if (nd->vlan_id == G_MAXUINT)
            return yaml_error(node, error, "%s: missing 'id' property", nd->id);
        if (nd->vlan_id > 4094)
            return yaml_error(node, error, "%s: invalid id '%u' (allowed values are 0 to 4094)", nd->id, nd->vlan_id);
    }

    if (nd->type == NETPLAN_DEF_TYPE_TUNNEL) {
        valid = validate_tunnel_grammar(nd, node, error);
        if (!valid)
            goto netdef_grammar_error;
    }

    if (nd->ip6_addr_gen_mode != NETPLAN_ADDRGEN_DEFAULT && nd->ip6_addr_gen_token)
        return yaml_error(node, error, "%s: ipv6-address-generation and ipv6-address-token are mutually exclusive", nd->id);

    if (nd->backend == NETPLAN_BACKEND_OVS) {
        // LCOV_EXCL_START
        if (!g_file_test(OPENVSWITCH_OVS_VSCTL, G_FILE_TEST_EXISTS)) {
            /* Tested via integration test */
            return yaml_error(node, error, "%s: The 'ovs-vsctl' tool is required to setup OpenVSwitch interfaces.", nd->id);
        }
        // LCOV_EXCL_STOP
    }

    valid = TRUE;

netdef_grammar_error:
    return valid;
}

gboolean
validate_backend_rules(NetplanNetDefinition* nd, GError** error)
{
    gboolean valid = FALSE;
    /* Set a dummy, NULL yaml_node_t for error reporting */
    yaml_node_t* node = NULL;

    g_assert(nd->type != NETPLAN_DEF_TYPE_NONE);

    if (nd->type == NETPLAN_DEF_TYPE_TUNNEL) {
        valid = validate_tunnel_backend_rules(nd, node, error);
        if (!valid)
            goto backend_rules_error;
    }

    valid = TRUE;

backend_rules_error:
    return valid;
}

