/*
 * Copyright (C) 2016 Canonical, Ltd.
 * Author: Martin Pitt <martin.pitt@ubuntu.com>
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

GString* udev_rules;

/**
 * Append NM device specifier of @def to @s.
 */
static void
g_string_append_netdef_match(GString* s, const net_definition* def)
{
    g_assert(!def->match.driver || def->set_name);
    if (def->match.mac) {
        g_string_append_printf(s, "mac:%s", def->match.mac);
    } else if (def->match.original_name || def->set_name || def->type >= ND_VIRTUAL) {
        /* we always have the renamed name here */
        g_string_append_printf(s, "interface-name:%s",
                (def->type >= ND_VIRTUAL) ? def->id
                                          : (def->set_name ?: def->match.original_name));
    } else {
        /* no matches → match all devices of that type */
        switch (def->type) {
            case ND_ETHERNET:
                g_string_append(s, "type:ethernet");
                break;
            /* This cannot be reached with just NM and networkd backends, as
             * networkd does not support wifi and thus we'll never blacklist a
             * wifi device from NM. This would become relevant with another
             * wifi-supporting backend, but until then this just spoils 100%
             * code coverage.
            case ND_WIFI:
                g_string_append(s, "type:wifi");
                break;
            */

            /* LCOV_EXCL_START */
            default:
                g_assert_not_reached();
            /* LCOV_EXCL_STOP */
        }
    }
}

/**
 * Return NM "type=" string.
 */
static const char*
type_str(netdef_type type)
{
    switch (type) {
        case ND_ETHERNET:
            return "ethernet";
        case ND_WIFI:
            return "wifi";
        case ND_BRIDGE:
            return "bridge";
        case ND_BOND:
            return "bond";
        case ND_VLAN:
            return "vlan";
        /* LCOV_EXCL_START */
        default:
            g_assert_not_reached();
        /* LCOV_EXCL_STOP */
    }
}

/**
 * Return NM wifi "mode=" string.
 */
static const char*
wifi_mode_str(wifi_mode mode)
{
    switch (mode) {
        case WIFI_MODE_INFRASTRUCTURE:
            return "infrastructure";
        case WIFI_MODE_ADHOC:
            return "adhoc";
        case WIFI_MODE_AP:
            return "ap";
        /* LCOV_EXCL_START */
        default:
            g_assert_not_reached();
        /* LCOV_EXCL_STOP */
    }
}

static void
write_search_domains(const net_definition* def, GString *s)
{
    if (def->search_domains) {
        g_string_append(s, "dns-search=");
        for (unsigned i = 0; i < def->search_domains->len; ++i)
            g_string_append_printf(s, "%s;", g_array_index(def->search_domains, char*, i));
        g_string_append(s, "\n");
    }
}

static void
write_routes(const net_definition* def, GString *s, int family)
{
    if (def->routes != NULL) {
        for (unsigned i = 0, j = 1; i < def->routes->len; ++i) {
            ip_route *cur_route = g_array_index(def->routes, ip_route*, i);

            if (cur_route->family != family)
                continue;

            g_string_append_printf(s, "route%d=%s,%s",
                                   j, cur_route->to, cur_route->via);
            if (cur_route->metric != METRIC_UNSPEC)
                g_string_append_printf(s, ",%d", cur_route->metric);
            g_string_append(s, "\n");
            j++;
        }
    }
}

static void
write_bond_parameters(const net_definition* def, GString *s)
{
    GString* params = NULL;

    params = g_string_sized_new(200);

    if (def->bond_params.mode)
        g_string_append_printf(params, "\nmode=%s", def->bond_params.mode);
    if (def->bond_params.lacp_rate)
        g_string_append_printf(params, "\nlacp_rate=%s", def->bond_params.lacp_rate);
    if (def->bond_params.monitor_interval)
        g_string_append_printf(params, "\nmiimon=%d", def->bond_params.monitor_interval);
    if (def->bond_params.min_links)
        g_string_append_printf(params, "\nmin_links=%d", def->bond_params.min_links);
    if (def->bond_params.transmit_hash_policy)
        g_string_append_printf(params, "\nxmit_hash_policy=%s", def->bond_params.transmit_hash_policy);
    if (def->bond_params.selection_logic)
        g_string_append_printf(params, "\nad_select=%s", def->bond_params.selection_logic);
    if (def->bond_params.all_slaves_active)
        g_string_append_printf(params, "\nall_slaves_active=%d", def->bond_params.all_slaves_active);
    if (def->bond_params.arp_interval)
        g_string_append_printf(params, "\narp_interval=%d", def->bond_params.arp_interval);
    if (def->bond_params.arp_ip_targets) {
        g_string_append_printf(params, "\narp_ip_target=");
        for (unsigned i = 0; i < def->bond_params.arp_ip_targets->len; ++i) {
            if (i > 0)
                g_string_append_printf(params, ",");
            g_string_append_printf(params, "%s", g_array_index(def->bond_params.arp_ip_targets, char*, i));
        }
    }
    if (def->bond_params.arp_validate)
        g_string_append_printf(params, "\narp_validate=%s", def->bond_params.arp_validate);
    if (def->bond_params.arp_all_targets)
        g_string_append_printf(params, "\narp_all_targets=%s", def->bond_params.arp_all_targets);
    if (def->bond_params.up_delay)
        g_string_append_printf(params, "\nupdelay=%d", def->bond_params.up_delay);
    if (def->bond_params.down_delay)
        g_string_append_printf(params, "\ndowndelay=%d", def->bond_params.down_delay);
    if (def->bond_params.fail_over_mac_policy)
        g_string_append_printf(params, "\nfail_over_mac=%s", def->bond_params.fail_over_mac_policy);
    if (def->bond_params.gratuitious_arp)
        g_string_append_printf(params, "\nnum_grat_arp=%d", def->bond_params.gratuitious_arp);
    /* TODO: add unsolicited_na, not documented as supported by NM. */
    if (def->bond_params.packets_per_slave)
        g_string_append_printf(params, "\npackets_per_slave=%d", def->bond_params.packets_per_slave);
    if (def->bond_params.primary_reselect_policy)
        g_string_append_printf(params, "\nprimary_reselect=%s", def->bond_params.primary_reselect_policy);
    if (def->bond_params.resend_igmp)
        g_string_append_printf(params, "\nresend_igmp=%d", def->bond_params.resend_igmp);
    if (def->bond_params.learn_interval)
        g_string_append_printf(params, "\nlp_interval=%d", def->bond_params.learn_interval);
    if (def->bond_params.primary_slave)
        g_string_append_printf(params, "\nprimary=%s", def->bond_params.primary_slave);

    if (params->len > 0)
        g_string_append_printf(s, "\n[bond]%s\n", params->str);

    g_string_free(params, TRUE);
}

static void
write_bridge_params(const net_definition* def, GString *s)
{
    GString* params = NULL;

    if (def->custom_bridging) {
        params = g_string_sized_new(200);

        if (def->bridge_params.ageing_time)
            g_string_append_printf(params, "ageing-time=%u\n", def->bridge_params.ageing_time);
        if (def->bridge_params.priority)
            g_string_append_printf(params, "priority=%u\n", def->bridge_params.priority);
        if (def->bridge_params.forward_delay)
            g_string_append_printf(params, "forward-delay=%u\n", def->bridge_params.forward_delay);
        if (def->bridge_params.hello_time)
            g_string_append_printf(params, "hello-time=%u\n", def->bridge_params.hello_time);
        if (def->bridge_params.max_age)
            g_string_append_printf(params, "max-age=%u\n", def->bridge_params.max_age);
        g_string_append_printf(params, "stp=%s\n", def->bridge_params.stp ? "true" : "false");

        g_string_append_printf(s, "\n[bridge]\n%s", params->str);

        g_string_free(params, TRUE);
    }
}

static void
maybe_generate_uuid(net_definition* def)
{
    if (uuid_is_null(def->uuid))
        uuid_generate(def->uuid);
}

/**
 * Generate NetworkManager configuration in @rootdir/run/NetworkManager/ for a
 * particular net_definition and wifi_access_point, as NM requires a separate
 * connection file for each SSID.
 * @def: The net_definition for which to create a connection
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 * @ap: The access point for which to create a connection. Must be %NULL for
 *      non-wifi types.
 */
static void
write_nm_conf_access_point(net_definition* def, const char* rootdir, const wifi_access_point* ap)
{
    GString *s = NULL;
    g_autofree char* conf_path = NULL;
    mode_t orig_umask;
    char uuidstr[37];

    if (def->type == ND_WIFI)
        g_assert(ap);
    else
        g_assert(ap == NULL);

    s = g_string_new(NULL);
    g_string_append_printf(s, "[connection]\nid=netplan-%s", def->id);
    if (ap)
        g_string_append_printf(s, "-%s", ap->ssid);
    g_string_append_printf(s, "\ntype=%s\n", type_str(def->type));

    /* VLAN devices refer to us as their parent; if our ID is not a name but we
     * have matches, parent= must be the connection UUID, so put it into the
     * connection */
    if (def->has_vlans && def->has_match) {
        maybe_generate_uuid(def);
        uuid_unparse(def->uuid, uuidstr);
        g_string_append_printf(s, "uuid=%s\n", uuidstr);
    }

    if (def->type < ND_VIRTUAL) {
        /* physical (existing) devices use matching; driver matching is not
         * supported, MAC matching is done below (different keyfile section),
         * so only match names here */
        if (def->set_name)
            g_string_append_printf(s, "interface-name=%s\n", def->set_name);
        else if (!def->has_match)
            g_string_append_printf(s, "interface-name=%s\n", def->id);
        else if (def->match.original_name) {
            /* NM does not support interface name globbing */
            if (strpbrk(def->match.original_name, "*[]?")) {
                g_fprintf(stderr, "ERROR: %s: NetworkManager definitions do not support name globbing\n", def->id);
                exit(1);
            }
            g_string_append_printf(s, "interface-name=%s\n", def->match.original_name);
        }
        /* else matches on something other than the name, do not restrict interface-name */
    } else {
        /* virtual (created) devices set a name */
        g_string_append_printf(s, "interface-name=%s\n", def->id);

        if (def->type == ND_BRIDGE)
            write_bridge_params(def, s);
    }
    if (def->bridge) {
        g_string_append_printf(s, "slave-type=bridge\nmaster=%s\n", def->bridge);

        if (def->bridge_params.path_cost || def->bridge_params.port_priority)
            g_string_append_printf(s, "\n[bridge-port]\n");
        if (def->bridge_params.path_cost)
            g_string_append_printf(s, "path-cost=%u\n", def->bridge_params.path_cost);
        if (def->bridge_params.port_priority)
            g_string_append_printf(s, "priority=%u\n", def->bridge_params.port_priority);
    }
    if (def->bond)
        g_string_append_printf(s, "slave-type=bond\nmaster=%s\n", def->bond);

    if (def->type < ND_VIRTUAL) {
        GString *link_str = NULL;

        link_str = g_string_new(NULL);

        g_string_append_printf(s, "\n[ethernet]\nwake-on-lan=%i\n", def->wake_on_lan ? 1 : 0);

        if (!def->set_name && def->match.mac) {
            g_string_append_printf(link_str, "mac-address=%s\n", def->match.mac);
        }
        if (def->set_mac) {
            g_string_append_printf(link_str, "cloned-mac-address=%s\n", def->set_mac);
        }
        if (def->mtubytes) {
            g_string_append_printf(link_str, "mtu=%d\n", def->mtubytes);
        }

        if (link_str->len > 0) {
            switch (def->type) {
                case ND_WIFI:
                    g_string_append_printf(s, "\n[802-11-wireless]\n%s", link_str->str);  break;
                default:
                    g_string_append_printf(s, "\n[802-3-ethernet]\n%s", link_str->str);  break;
            }
        }

        g_string_free(link_str, TRUE);
    } else {
        GString *link_str = NULL;

        link_str = g_string_new(NULL);

        if (def->set_mac) {
            g_string_append_printf(link_str, "cloned-mac-address=%s\n", def->set_mac);
        }
        if (def->mtubytes) {
            g_string_append_printf(link_str, "mtu=%d\n", def->mtubytes);
        }

        if (link_str->len > 0) {
            g_string_append_printf(s, "\n[802-3-ethernet]\n%s", link_str->str);
        }

        g_string_free(link_str, TRUE);
    }

    if (def->type == ND_VLAN) {
        g_assert(def->vlan_id < G_MAXUINT);
        g_assert(def->vlan_link != NULL);
        g_string_append_printf(s, "\n[vlan]\nid=%u\nparent=", def->vlan_id);
        if (def->vlan_link->has_match) {
            /* we need to refer to the parent's UUID as we don't have an
             * interface name with match: */
            maybe_generate_uuid(def->vlan_link);
            uuid_unparse(def->vlan_link->uuid, uuidstr);
            g_string_append_printf(s, "%s\n", uuidstr);
        } else {
            /* if we have an interface name, use that as parent */
            g_string_append_printf(s, "%s\n", def->vlan_link->id);
        }
    }

    if (def->type == ND_BOND)
        write_bond_parameters(def, s);

    g_string_append(s, "\n[ipv4]\n");

    if (ap && ap->mode == WIFI_MODE_AP)
        g_string_append(s, "method=shared\n");
    else if (def->dhcp4)
        g_string_append(s, "method=auto\n");
    else if (def->ip4_addresses)
        /* This requires adding at least one address (done below) */
        g_string_append(s, "method=manual\n");
    else
        /* Without any address, this is the only available mode */
        g_string_append(s, "method=link-local\n");

    if (def->ip4_addresses)
        for (unsigned i = 0; i < def->ip4_addresses->len; ++i)
            g_string_append_printf(s, "address%i=%s\n", i+1, g_array_index(def->ip4_addresses, char*, i));
    if (def->gateway4)
        g_string_append_printf(s, "gateway=%s\n", def->gateway4);
    if (def->ip4_nameservers) {
        g_string_append(s, "dns=");
        for (unsigned i = 0; i < def->ip4_nameservers->len; ++i)
            g_string_append_printf(s, "%s;", g_array_index(def->ip4_nameservers, char*, i));
        g_string_append(s, "\n");
    }
    write_search_domains(def, s);
    write_routes(def, s, AF_INET);

    if (def->dhcp6 || def->ip6_addresses || def->gateway6 || def->ip6_nameservers) {
        g_string_append(s, "\n[ipv6]\n");
        g_string_append(s, def->dhcp6 ? "method=auto\n" : "method=manual\n");
        if (def->ip6_addresses)
            for (unsigned i = 0; i < def->ip6_addresses->len; ++i)
                g_string_append_printf(s, "address%i=%s\n", i+1, g_array_index(def->ip6_addresses, char*, i));
        if (def->gateway6)
            g_string_append_printf(s, "gateway=%s\n", def->gateway6);
        if (def->ip6_nameservers) {
            g_string_append(s, "dns=");
            for (unsigned i = 0; i < def->ip6_nameservers->len; ++i)
                g_string_append_printf(s, "%s;", g_array_index(def->ip6_nameservers, char*, i));
            g_string_append(s, "\n");
        }
        /* nm-settings(5) specifies search-domain for both [ipv4] and [ipv6] --
         * do we really need to repeat it here? */
        write_search_domains(def, s);

        /* We can only write valid routes if there is a DHCPv6 or static IPv6 address */
        write_routes(def, s, AF_INET6);
    }
    else {
        g_string_append(s, "\n[ipv6]\nmethod=ignore\n");
    }

    conf_path = g_strjoin(NULL, "run/NetworkManager/system-connections/netplan-", def->id, NULL);

    if (ap) {
        g_autofree char* escaped_ssid = g_uri_escape_string(ap->ssid, NULL, TRUE);
        conf_path = g_strjoin(NULL, "run/NetworkManager/system-connections/netplan-", def->id, "-", escaped_ssid, NULL);

        g_string_append_printf(s, "\n[wifi]\nssid=%s\nmode=%s\n", ap->ssid, wifi_mode_str(ap->mode));
        if (ap->password)
            g_string_append_printf(s, "\n[wifi-security]\nkey-mgmt=wpa-psk\npsk=%s\n", ap->password);
    } else {
        conf_path = g_strjoin(NULL, "run/NetworkManager/system-connections/netplan-", def->id, NULL);
    }

    /* NM connection files might contain secrets, and NM insists on tight permissions */
    orig_umask = umask(077);
    g_string_free_to_file(s, rootdir, conf_path, NULL);
    umask(orig_umask);
}

/**
 * Generate NetworkManager configuration in @rootdir/run/NetworkManager/ for a
 * particular net_definition.
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
void
write_nm_conf(net_definition* def, const char* rootdir)
{
    if (def->backend != BACKEND_NM) {
        g_debug("NetworkManager: definition %s is not for us (backend %i)", def->id, def->backend);
        return;
    }

    if (def->match.driver && !def->set_name) {
        g_fprintf(stderr, "ERROR: %s: NetworkManager definitions do not support matching by driver\n", def->id);
        exit(1);
    }

    /* for wifi we need to create a separate connection file for every SSID */
    if (def->type == ND_WIFI) {
        GHashTableIter iter;
        gpointer key;
        wifi_access_point* ap;
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
nd_append_non_nm_ids(gpointer key, gpointer value, gpointer str)
{
    net_definition* nd = value;

    if (nd->backend != BACKEND_NM) {
        if (nd->match.driver) {
            /* NM cannot match on drivers, so ignore these via udev rules */
            if (!udev_rules)
                udev_rules = g_string_new(NULL);
            g_string_append_printf(udev_rules, "ACTION==\"add|change\", SUBSYSTEM==\"net\", ENV{ID_NET_DRIVER}==\"%s\", ENV{NM_UNMANAGED}=\"1\"\n", nd->match.driver);
        } else {
            g_string_append_netdef_match((GString*) str, nd);
            g_string_append((GString*) str, ",");
        }
    }
}

void
write_nm_conf_finish(const char* rootdir)
{
    GString *s = NULL;
    gsize len;

    if (g_hash_table_size(netdefs) == 0)
        return;

    /* Set all devices not managed by us to unmanaged, so that NM does not
     * auto-connect and interferes */
    s = g_string_new("[keyfile]\n# devices managed by networkd\nunmanaged-devices+=");
    len = s->len;
    g_hash_table_foreach(netdefs, nd_append_non_nm_ids, s);
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
