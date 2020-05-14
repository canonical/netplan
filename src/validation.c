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

/************************************************
 * Validation for grammar and backend rules.
 ************************************************/
static gboolean
validate_tunnel_grammar(NetplanNetDefinition* nd, yaml_node_t* node, GError** error)
{
    if (nd->tunnel.mode == NETPLAN_TUNNEL_MODE_UNKNOWN)
        return yaml_error(node, error, "%s: missing 'mode' property for tunnel", nd->id);

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

        // LCOV_EXCL_START
        default:
            break;
        // LCOV_EXCL_STOP
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

