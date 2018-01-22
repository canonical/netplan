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
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>

#include <glib.h>
#include <glib/gprintf.h>

#include "networkd.h"
#include "parse.h"
#include "util.h"

/**
 * Append [Match] section of @def to @s.
 */
static void
append_match_section(net_definition* def, GString* s, gboolean match_rename)
{
    /* Note: an empty [Match] section is interpreted as matching all devices,
     * which is what we want for the simple case that you only have one device
     * (of the given type) */

    g_string_append(s, "[Match]\n");
    if (def->match.driver)
        g_string_append_printf(s, "Driver=%s\n", def->match.driver);
    if (def->match.mac)
        g_string_append_printf(s, "MACAddress=%s\n", def->match.mac);
    /* name matching is special: if the .link renames the interface, the
     * .network has to use the renamed one, otherwise the original one */
    if (!match_rename && def->match.original_name)
        g_string_append_printf(s, "OriginalName=%s\n", def->match.original_name);
    if (match_rename) {
        if (def->type >= ND_VIRTUAL)
            g_string_append_printf(s, "Name=%s\n", def->id);
        else if (def->set_name)
            g_string_append_printf(s, "Name=%s\n", def->set_name);
        else if (def->match.original_name)
            g_string_append_printf(s, "Name=%s\n", def->match.original_name);
    }
}

static void
write_bridge_params(GString* s, net_definition* def)
{
    GString *params = NULL;

    if (def->custom_bridging) {
        params = g_string_sized_new(200);

        if (def->bridge_params.ageing_time)
            g_string_append_printf(params, "AgeingTimeSec=%u\n", def->bridge_params.ageing_time);
#if 0
	/* FIXME: Priority= is not valid for the bridge itself, although it should work as the
         *        STP priority of the bridge itself. It's not supported by networkd, but let's
         *        keep it around in case it becomes supported in the future.
         */
        if (def->bridge_params.priority)
            g_string_append_printf(params, "Priority=%u\n", def->bridge_params.priority);
#endif
        if (def->bridge_params.forward_delay)
            g_string_append_printf(params, "ForwardDelaySec=%u\n", def->bridge_params.forward_delay);
        if (def->bridge_params.hello_time)
            g_string_append_printf(params, "HelloTimeSec=%u\n", def->bridge_params.hello_time);
        if (def->bridge_params.max_age)
            g_string_append_printf(params, "MaxAgeSec=%u\n", def->bridge_params.max_age);
        g_string_append_printf(params, "STP=%s\n", def->bridge_params.stp ? "true" : "false");

        g_string_append_printf(s, "\n[Bridge]\n%s", params->str);

        g_string_free(params, TRUE);
    }
}

static void
write_link_file(net_definition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;

    /* Don't write .link files for virtual devices; they use .netdev instead */
    if (def->type >= ND_VIRTUAL)
        return;

    /* do we need to write a .link file? */
    if (!def->set_name && !def->wake_on_lan && !def->mtubytes && !def->set_mac)
        return;

    /* build file contents */
    s = g_string_sized_new(200);
    append_match_section(def, s, FALSE);

    g_string_append(s, "\n[Link]\n");
    if (def->set_name)
        g_string_append_printf(s, "Name=%s\n", def->set_name);
    /* FIXME: Should this be turned from bool to str and support multiple values? */
    g_string_append_printf(s, "WakeOnLan=%s\n", def->wake_on_lan ? "magic" : "off");
    if (def->mtubytes)
        g_string_append_printf(s, "MTUBytes=%u\n", def->mtubytes);
    if (def->set_mac)
        g_string_append_printf(s, "MACAddress=%s\n", def->set_mac);


    g_string_free_to_file(s, rootdir, path, ".link");
}

static void
write_bond_parameters(net_definition* def, GString* s)
{
    GString* params = NULL;

    params = g_string_sized_new(200);

    if (def->bond_params.mode)
        g_string_append_printf(params, "\nMode=%s", def->bond_params.mode);
    if (def->bond_params.lacp_rate)
        g_string_append_printf(params, "\nLACPTransmitRate=%s", def->bond_params.lacp_rate);
    if (def->bond_params.monitor_interval)
        g_string_append_printf(params, "\nMIIMonitorSec=%d", def->bond_params.monitor_interval);
    if (def->bond_params.min_links)
        g_string_append_printf(params, "\nMinLinks=%d", def->bond_params.min_links);
    if (def->bond_params.transmit_hash_policy)
        g_string_append_printf(params, "\nTransmitHashPolicy=%s", def->bond_params.transmit_hash_policy);
    if (def->bond_params.selection_logic)
        g_string_append_printf(params, "\nAdSelect=%s", def->bond_params.selection_logic);
    if (def->bond_params.all_slaves_active)
        g_string_append_printf(params, "\nAllSlavesActive=%d", def->bond_params.all_slaves_active);
    if (def->bond_params.arp_interval)
        g_string_append_printf(params, "\nARPIntervalSec=%d", def->bond_params.arp_interval);
    if (def->bond_params.arp_ip_targets && def->bond_params.arp_ip_targets->len > 0) {
        g_string_append_printf(params, "\nARPIPTargets=");
        for (unsigned i = 0; i < def->bond_params.arp_ip_targets->len; ++i) {
            if (i > 0)
                g_string_append_printf(params, ",");
            g_string_append_printf(params, "%s", g_array_index(def->bond_params.arp_ip_targets, char*, i));
        }
    }
    if (def->bond_params.arp_validate)
        g_string_append_printf(params, "\nARPValidate=%s", def->bond_params.arp_validate);
    if (def->bond_params.arp_all_targets)
        g_string_append_printf(params, "\nARPAllTargets=%s", def->bond_params.arp_all_targets);
    if (def->bond_params.up_delay)
        g_string_append_printf(params, "\nUpDelaySec=%d", def->bond_params.up_delay);
    if (def->bond_params.down_delay)
        g_string_append_printf(params, "\nDownDelaySec=%d", def->bond_params.down_delay);
    if (def->bond_params.fail_over_mac_policy)
        g_string_append_printf(params, "\nFailOverMACPolicy=%s", def->bond_params.fail_over_mac_policy);
    if (def->bond_params.gratuitious_arp)
        g_string_append_printf(params, "\nGratuitiousARP=%d", def->bond_params.gratuitious_arp);
    /* TODO: add unsolicited_na, not documented as supported by NM. */
    if (def->bond_params.packets_per_slave)
        g_string_append_printf(params, "\nPacketsPerSlave=%d", def->bond_params.packets_per_slave);
    if (def->bond_params.primary_reselect_policy)
        g_string_append_printf(params, "\nPrimaryReselectPolicy=%s", def->bond_params.primary_reselect_policy);
    if (def->bond_params.resend_igmp)
        g_string_append_printf(params, "\nResendIGMP=%d", def->bond_params.resend_igmp);
    if (def->bond_params.learn_interval)
        g_string_append_printf(params, "\nLearnPacketIntervalSec=%d", def->bond_params.learn_interval);

    if (params->len)
        g_string_append_printf(s, "\n[Bond]%s\n", params->str);

    g_string_free(params, TRUE);
}

static void
write_netdev_file(net_definition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;

    g_assert(def->type >= ND_VIRTUAL);

    /* build file contents */
    s = g_string_sized_new(200);
    g_string_append_printf(s, "[NetDev]\nName=%s\n", def->id);

    if (def->set_mac)
        g_string_append_printf(s, "MACAddress=%s\n", def->set_mac);
    if (def->mtubytes)
        g_string_append_printf(s, "MTUBytes=%u\n", def->mtubytes);

    switch (def->type) {
        case ND_BRIDGE:
            g_string_append(s, "Kind=bridge\n");
            write_bridge_params(s, def);
            break;

        case ND_BOND:
            g_string_append(s, "Kind=bond\n");
            write_bond_parameters(def, s);
            break;

        case ND_VLAN:
            g_string_append_printf(s, "Kind=vlan\n\n[VLAN]\nId=%u\n", def->vlan_id);
            break;

        /* LCOV_EXCL_START */
        default:
            g_assert_not_reached();
        /* LCOV_EXCL_STOP */
    }

    g_string_free_to_file(s, rootdir, path, ".netdev");
}

static void
write_network_file(net_definition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;

    /* do we need to write a .network file? */
    if (!def->dhcp4 && !def->dhcp6 && !def->bridge && !def->bond &&
        !def->ip4_addresses && !def->ip6_addresses && !def->gateway4 && !def->gateway6 &&
        !def->ip4_nameservers && !def->ip6_nameservers && !def->has_vlans)
        return;

    /* build file contents */
    s = g_string_sized_new(200);
    append_match_section(def, s, TRUE);

    g_string_append(s, "\n[Network]\n");
    if (def->dhcp4 && def->dhcp6)
        g_string_append(s, "DHCP=yes\n");
    else if (def->dhcp4)
        g_string_append(s, "DHCP=ipv4\n");
    else if (def->dhcp6)
        g_string_append(s, "DHCP=ipv6\n");
    if (def->ip4_addresses)
        for (unsigned i = 0; i < def->ip4_addresses->len; ++i)
            g_string_append_printf(s, "Address=%s\n", g_array_index(def->ip4_addresses, char*, i));
    if (def->ip6_addresses)
        for (unsigned i = 0; i < def->ip6_addresses->len; ++i)
            g_string_append_printf(s, "Address=%s\n", g_array_index(def->ip6_addresses, char*, i));
    if (!def->accept_ra)
        g_string_append_printf(s, "IPv6AcceptRA=no\n");
    if (def->gateway4)
        g_string_append_printf(s, "Gateway=%s\n", def->gateway4);
    if (def->gateway6)
        g_string_append_printf(s, "Gateway=%s\n", def->gateway6);
    if (def->ip4_nameservers)
        for (unsigned i = 0; i < def->ip4_nameservers->len; ++i)
            g_string_append_printf(s, "DNS=%s\n", g_array_index(def->ip4_nameservers, char*, i));
    if (def->ip6_nameservers)
        for (unsigned i = 0; i < def->ip6_nameservers->len; ++i)
            g_string_append_printf(s, "DNS=%s\n", g_array_index(def->ip6_nameservers, char*, i));
    if (def->search_domains) {
        g_string_append_printf(s, "Domains=%s", g_array_index(def->search_domains, char*, 0));
        for (unsigned i = 1; i < def->search_domains->len; ++i)
            g_string_append_printf(s, " %s", g_array_index(def->search_domains, char*, i));
        g_string_append(s, "\n");
    }
    if (def->bridge) {
        g_string_append_printf(s, "Bridge=%s\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n", def->bridge);

        if (def->bridge_params.path_cost || def->bridge_params.port_priority)
            g_string_append_printf(s, "\n[Bridge]\n");
        if (def->bridge_params.path_cost)
            g_string_append_printf(s, "Cost=%u\n", def->bridge_params.path_cost);
        if (def->bridge_params.port_priority)
            g_string_append_printf(s, "Priority=%u\n", def->bridge_params.port_priority);
    }
    if (def->bond) {
        g_string_append_printf(s, "Bond=%s\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n", def->bond);

        if (def->bond_params.primary_slave)
            g_string_append_printf(s, "PrimarySlave=true\n");
    }

    if (def->has_vlans) {
        /* iterate over all netdefs to find VLANs attached to us */
        GHashTableIter i;
        net_definition* nd;
        g_hash_table_iter_init(&i, netdefs);
        while (g_hash_table_iter_next (&i, NULL, (gpointer*) &nd))
            if (nd->vlan_link == def)
                g_string_append_printf(s, "VLAN=%s\n", nd->id);
    }
    if (def->routes != NULL) {
        for (unsigned i = 0; i < def->routes->len; ++i) {
            ip_route* cur_route = g_array_index (def->routes, ip_route*, i);
            g_string_append_printf(s, "\n[Route]\nDestination=%s\nGateway=%s\n",
                                   cur_route->to, cur_route->via);
            if (cur_route->metric != METRIC_UNSPEC)
                g_string_append_printf(s, "Metric=%d\n", cur_route->metric);
        }
    }

    if (def->dhcp4 || def->dhcp6) {
        /* isc-dhcp dhclient compatible UseMTU, networkd default is to
         * not accept MTU, which breaks clouds */
        g_string_append_printf(s, "\n[DHCP]\nUseMTU=true\n");
        /* NetworkManager compatible route metrics */
        g_string_append_printf(s, "RouteMetric=%i\n", (def->type == ND_WIFI ? 600 : 100));
    }

    g_string_free_to_file(s, rootdir, path, ".network");
}

static void
write_wpa_conf(net_definition* def, const char* rootdir)
{
    GHashTableIter iter;
    wifi_access_point* ap;
    GString* s = g_string_new("ctrl_interface=/run/wpa_supplicant\n\n");
    g_autofree char* path = g_strjoin(NULL, "run/netplan/wpa-", def->id, ".conf", NULL);
    mode_t orig_umask;

    g_debug("%s: Creating wpa_supplicant configuration file %s", def->id, path);
    g_hash_table_iter_init(&iter, def->access_points);
    while (g_hash_table_iter_next(&iter, NULL, (gpointer) &ap)) {
        g_string_append_printf(s, "network={\n  ssid=\"%s\"\n", ap->ssid);
        if (ap->password)
            g_string_append_printf(s, "  psk=\"%s\"\n", ap->password);
        else
            g_string_append(s, "  key_mgmt=NONE\n");
        switch (ap->mode) {
            case WIFI_MODE_INFRASTRUCTURE:
                /* default in wpasupplicant */
                break;
            case WIFI_MODE_ADHOC:
                g_string_append(s, "  mode=1\n");
                break;
            case WIFI_MODE_AP:
                g_fprintf(stderr, "ERROR: %s: networkd does not support wifi in access point mode\n", def->id);
                exit(1);
        }
        g_string_append(s, "}\n");
    }

    /* use tight permissions as this contains secrets */
    orig_umask = umask(077);
    g_string_free_to_file(s, rootdir, path, NULL);
    umask(orig_umask);
}

/**
 * Generate networkd configuration in @rootdir/run/systemd/network/ from the
 * parsed #netdefs.
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 * Returns: TRUE if @def applies to networkd, FALSE otherwise.
 */
gboolean
write_networkd_conf(net_definition* def, const char* rootdir)
{
    g_autofree char* path_base = g_strjoin(NULL, "run/systemd/network/10-netplan-", def->id, NULL);

    /* We want this for all backends when renaming, as *.link files are
     * evaluated by udev, not networkd itself or NetworkManager. */
    write_link_file(def, rootdir, path_base);

    if (def->backend != BACKEND_NETWORKD) {
        g_debug("networkd: definition %s is not for us (backend %i)", def->id, def->backend);
        return FALSE;
    }

    if (def->type == ND_WIFI) {
        g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/multi-user.target.wants/netplan-wpa@", def->id, ".service", NULL);
        if (def->has_match) {
            g_fprintf(stderr, "ERROR: %s: networkd backend does not support wifi with match:, only by interface name\n", def->id);
            exit(1);
        }

        write_wpa_conf(def, rootdir);

        g_debug("Creating wpa_supplicant service enablement link %s", link);
        safe_mkdir_p_dir(link);
        if (symlink("/lib/systemd/system/netplan-wpa@.service", link) < 0 && errno != EEXIST) {
            g_fprintf(stderr, "failed to create enablement symlink: %m\n"); /* LCOV_EXCL_LINE */
            exit(1); /* LCOV_EXCL_LINE */
        }

    }

    if (def->type >= ND_VIRTUAL)
        write_netdev_file(def, rootdir, path_base);
    write_network_file(def, rootdir, path_base);
    return TRUE;
}

/**
 * Clean up all generated configurations in @rootdir from previous runs.
 */
void
cleanup_networkd_conf(const char* rootdir)
{
    unlink_glob(rootdir, "/run/systemd/network/10-netplan-*");
    unlink_glob(rootdir, "/run/netplan/*");
    unlink_glob(rootdir, "/run/systemd/system/multi-user.target.wants/netplan-wpa@*.service");
}

/**
 * Create enablement symlink for systemd-networkd.service.
 */
void
enable_networkd(const char* generator_dir)
{
    g_autofree char* link = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "multi-user.target.wants", "systemd-networkd.service", NULL);
    g_debug("We created networkd configuration, adding %s enablement symlink", link);
    safe_mkdir_p_dir(link);
    if (symlink("../systemd-networkd.service", link) < 0 && errno != EEXIST) {
        g_fprintf(stderr, "failed to create enablement symlink: %m\n"); /* LCOV_EXCL_LINE */
        exit(1); /* LCOV_EXCL_LINE */
    }

    g_autofree char* link2 = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "network-online.target.wants", "systemd-networkd-wait-online.service", NULL);
    safe_mkdir_p_dir(link2);
    if (symlink("/lib/systemd/system/systemd-networkd-wait-online.service", link2) < 0 && errno != EEXIST) {
        g_fprintf(stderr, "failed to create enablement symlink: %m\n"); /* LCOV_EXCL_LINE */
        exit(1); /* LCOV_EXCL_LINE */
    }
}
