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
#include <ctype.h>
#include <errno.h>
#include <sys/stat.h>

#include <glib.h>
#include <glib/gprintf.h>

#include "networkd.h"
#include "parse.h"
#include "util.h"

/**
 * Append WiFi frequencies to wpa_supplicant's freq_list=
 */
static void
wifi_append_freq(gpointer key, gpointer value, gpointer user_data)
{
    GString* s = user_data;
    g_string_append_printf(s, "%d ", GPOINTER_TO_INT(value));
}

/**
 * append wowlan_triggers= string for wpa_supplicant.conf
 */
static void
append_wifi_wowlan_flags(NetplanWifiWowlanFlag flag, GString* str) {
    if (flag & NETPLAN_WIFI_WOWLAN_TYPES[0].flag || flag >= NETPLAN_WIFI_WOWLAN_TCP) {
        g_fprintf(stderr, "ERROR: unsupported wowlan_triggers mask: 0x%x\n", flag);
        exit(1);
    }
    for (unsigned i = 0; NETPLAN_WIFI_WOWLAN_TYPES[i].name != NULL; ++i) {
        if (flag & NETPLAN_WIFI_WOWLAN_TYPES[i].flag) {
            g_string_append_printf(str, "%s ", NETPLAN_WIFI_WOWLAN_TYPES[i].name);
        }
    }
    /* replace trailing space with newline */
    str = g_string_overwrite(str, str->len-1, "\n");
}

/**
 * Append [Match] section of @def to @s.
 */
static void
append_match_section(const NetplanNetDefinition* def, GString* s, gboolean match_rename)
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
        if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL)
            g_string_append_printf(s, "Name=%s\n", def->id);
        else if (def->set_name)
            g_string_append_printf(s, "Name=%s\n", def->set_name);
        else if (def->match.original_name)
            g_string_append_printf(s, "Name=%s\n", def->match.original_name);
    }

    /* Workaround for bug LP: #1804861: something outputs netplan config
     * that includes using the MAC of the first phy member of a bond as
     * default value for the MAC of the bond device itself. This is
     * evil, it's an optional field and networkd knows what to do if
     * the MAC isn't specified; but work around this by adding an
     * arbitrary additional match condition on Path= for the phys.
     * This way, hopefully setting a MTU on the phy does not bleed over
     * to bond/bridge and any further virtual devices (VLANs?) on top of
     * it.
     * Make sure to add the extra match only if we're matching by MAC
     * already and dealing with a bond or bridge.
     */
    if (def->bond || def->bridge) {
        /* update if we support new device types */
        if (def->match.mac)
            g_string_append(s, "Type=!vlan bond bridge\n");
    }
}

static void
write_bridge_params(GString* s, const NetplanNetDefinition* def)
{
    GString *params = NULL;

    if (def->custom_bridging) {
        params = g_string_sized_new(200);

        if (def->bridge_params.ageing_time)
            g_string_append_printf(params, "AgeingTimeSec=%s\n", def->bridge_params.ageing_time);
        if (def->bridge_params.priority)
            g_string_append_printf(params, "Priority=%u\n", def->bridge_params.priority);
        if (def->bridge_params.forward_delay)
            g_string_append_printf(params, "ForwardDelaySec=%s\n", def->bridge_params.forward_delay);
        if (def->bridge_params.hello_time)
            g_string_append_printf(params, "HelloTimeSec=%s\n", def->bridge_params.hello_time);
        if (def->bridge_params.max_age)
            g_string_append_printf(params, "MaxAgeSec=%s\n", def->bridge_params.max_age);
        g_string_append_printf(params, "STP=%s\n", def->bridge_params.stp ? "true" : "false");

        g_string_append_printf(s, "\n[Bridge]\n%s", params->str);

        g_string_free(params, TRUE);
    }
}

static void
write_tunnel_params(GString* s, const NetplanNetDefinition* def)
{
    GString *params = NULL;

    params = g_string_sized_new(200);

    g_string_printf(params, "Independent=true\n");
    if (def->tunnel.mode == NETPLAN_TUNNEL_MODE_IPIP6 || def->tunnel.mode == NETPLAN_TUNNEL_MODE_IP6IP6)
        g_string_append_printf(params, "Mode=%s\n", tunnel_mode_to_string(def->tunnel.mode));
    g_string_append_printf(params, "Local=%s\n", def->tunnel.local_ip);
    g_string_append_printf(params, "Remote=%s\n", def->tunnel.remote_ip);
    if (def->tunnel.input_key)
        g_string_append_printf(params, "InputKey=%s\n", def->tunnel.input_key);
    if (def->tunnel.output_key)
        g_string_append_printf(params, "OutputKey=%s\n", def->tunnel.output_key);

    g_string_append_printf(s, "\n[Tunnel]\n%s", params->str);
    g_string_free(params, TRUE);
}

static void
write_link_file(const NetplanNetDefinition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;
    mode_t orig_umask;

    /* Don't write .link files for virtual devices; they use .netdev instead.
     * Don't write .link files for MODEM devices, as they aren't supported by networkd.
     */
    if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL || def->type == NETPLAN_DEF_TYPE_MODEM)
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


    orig_umask = umask(022);
    g_string_free_to_file(s, rootdir, path, ".link");
    umask(orig_umask);
}


static gboolean
interval_has_suffix(const char* param) {
    gchar* endptr;

    g_ascii_strtoull(param, &endptr, 10);
    if (*endptr == '\0')
        return FALSE;

    return TRUE;
}


static void
write_bond_parameters(const NetplanNetDefinition* def, GString* s)
{
    GString* params = NULL;

    params = g_string_sized_new(200);

    if (def->bond_params.mode)
        g_string_append_printf(params, "\nMode=%s", def->bond_params.mode);
    if (def->bond_params.lacp_rate)
        g_string_append_printf(params, "\nLACPTransmitRate=%s", def->bond_params.lacp_rate);
    if (def->bond_params.monitor_interval) {
        g_string_append(params, "\nMIIMonitorSec=");
        if (interval_has_suffix(def->bond_params.monitor_interval))
            g_string_append(params, def->bond_params.monitor_interval);
        else
            g_string_append_printf(params, "%sms", def->bond_params.monitor_interval);
    }
    if (def->bond_params.min_links)
        g_string_append_printf(params, "\nMinLinks=%d", def->bond_params.min_links);
    if (def->bond_params.transmit_hash_policy)
        g_string_append_printf(params, "\nTransmitHashPolicy=%s", def->bond_params.transmit_hash_policy);
    if (def->bond_params.selection_logic)
        g_string_append_printf(params, "\nAdSelect=%s", def->bond_params.selection_logic);
    if (def->bond_params.all_slaves_active)
        g_string_append_printf(params, "\nAllSlavesActive=%d", def->bond_params.all_slaves_active);
    if (def->bond_params.arp_interval) {
        g_string_append(params, "\nARPIntervalSec=");
        if (interval_has_suffix(def->bond_params.arp_interval))
            g_string_append(params, def->bond_params.arp_interval);
        else
            g_string_append_printf(params, "%sms", def->bond_params.arp_interval);
    }
    if (def->bond_params.arp_ip_targets && def->bond_params.arp_ip_targets->len > 0) {
        g_string_append_printf(params, "\nARPIPTargets=");
        for (unsigned i = 0; i < def->bond_params.arp_ip_targets->len; ++i) {
            if (i > 0)
                g_string_append_printf(params, " ");
            g_string_append_printf(params, "%s", g_array_index(def->bond_params.arp_ip_targets, char*, i));
        }
    }
    if (def->bond_params.arp_validate)
        g_string_append_printf(params, "\nARPValidate=%s", def->bond_params.arp_validate);
    if (def->bond_params.arp_all_targets)
        g_string_append_printf(params, "\nARPAllTargets=%s", def->bond_params.arp_all_targets);
    if (def->bond_params.up_delay) {
        g_string_append(params, "\nUpDelaySec=");
        if (interval_has_suffix(def->bond_params.up_delay))
            g_string_append(params, def->bond_params.up_delay);
        else
            g_string_append_printf(params, "%sms", def->bond_params.up_delay);
    }
    if (def->bond_params.down_delay) {
        g_string_append(params, "\nDownDelaySec=");
        if (interval_has_suffix(def->bond_params.down_delay))
            g_string_append(params, def->bond_params.down_delay);
        else
            g_string_append_printf(params, "%sms", def->bond_params.down_delay);
    }
    if (def->bond_params.fail_over_mac_policy)
        g_string_append_printf(params, "\nFailOverMACPolicy=%s", def->bond_params.fail_over_mac_policy);
    if (def->bond_params.gratuitous_arp)
        g_string_append_printf(params, "\nGratuitousARP=%d", def->bond_params.gratuitous_arp);
    /* TODO: add unsolicited_na, not documented as supported by NM. */
    if (def->bond_params.packets_per_slave)
        g_string_append_printf(params, "\nPacketsPerSlave=%d", def->bond_params.packets_per_slave);
    if (def->bond_params.primary_reselect_policy)
        g_string_append_printf(params, "\nPrimaryReselectPolicy=%s", def->bond_params.primary_reselect_policy);
    if (def->bond_params.resend_igmp)
        g_string_append_printf(params, "\nResendIGMP=%d", def->bond_params.resend_igmp);
    if (def->bond_params.learn_interval)
        g_string_append_printf(params, "\nLearnPacketIntervalSec=%s", def->bond_params.learn_interval);

    if (params->len)
        g_string_append_printf(s, "\n[Bond]%s\n", params->str);

    g_string_free(params, TRUE);
}

static void
write_netdev_file(const NetplanNetDefinition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;
    mode_t orig_umask;

    g_assert(def->type >= NETPLAN_DEF_TYPE_VIRTUAL);

    if (def->type == NETPLAN_DEF_TYPE_VLAN && def->sriov_vlan_filter) {
        g_debug("%s is defined as a hardware SR-IOV filtered VLAN, postponing creation", def->id);
        return;
    }

    /* build file contents */
    s = g_string_sized_new(200);
    g_string_append_printf(s, "[NetDev]\nName=%s\n", def->id);

    if (def->set_mac)
        g_string_append_printf(s, "MACAddress=%s\n", def->set_mac);
    if (def->mtubytes)
        g_string_append_printf(s, "MTUBytes=%u\n", def->mtubytes);

    switch (def->type) {
        case NETPLAN_DEF_TYPE_BRIDGE:
            g_string_append(s, "Kind=bridge\n");
            write_bridge_params(s, def);
            break;

        case NETPLAN_DEF_TYPE_BOND:
            g_string_append(s, "Kind=bond\n");
            write_bond_parameters(def, s);
            break;

        case NETPLAN_DEF_TYPE_VLAN:
            g_string_append_printf(s, "Kind=vlan\n\n[VLAN]\nId=%u\n", def->vlan_id);
            break;

        case NETPLAN_DEF_TYPE_TUNNEL:
            switch(def->tunnel.mode) {
                case NETPLAN_TUNNEL_MODE_GRE:
                case NETPLAN_TUNNEL_MODE_GRETAP:
                case NETPLAN_TUNNEL_MODE_IPIP:
                case NETPLAN_TUNNEL_MODE_IP6GRE:
                case NETPLAN_TUNNEL_MODE_IP6GRETAP:
                case NETPLAN_TUNNEL_MODE_SIT:
                case NETPLAN_TUNNEL_MODE_VTI:
                case NETPLAN_TUNNEL_MODE_VTI6:
                    g_string_append_printf(s,
                                          "Kind=%s\n",
                                          tunnel_mode_to_string(def->tunnel.mode));
                    break;

                case NETPLAN_TUNNEL_MODE_IP6IP6:
                case NETPLAN_TUNNEL_MODE_IPIP6:
                    g_string_append(s, "Kind=ip6tnl\n");
                    break;

                // LCOV_EXCL_START
                default:
                    g_assert_not_reached();
                // LCOV_EXCL_STOP
            }

            write_tunnel_params(s, def);
            break;

        // LCOV_EXCL_START
        default:
            g_assert_not_reached();
        // LCOV_EXCL_STOP
    }

    /* these do not contain secrets and need to be readable by
     * systemd-networkd - LP: #1736965 */
    orig_umask = umask(022);
    g_string_free_to_file(s, rootdir, path, ".netdev");
    umask(orig_umask);
}

static void
write_route(NetplanIPRoute* r, GString* s)
{
    g_string_append_printf(s, "\n[Route]\n");

    g_string_append_printf(s, "Destination=%s\n", r->to);

    if (r->via)
        g_string_append_printf(s, "Gateway=%s\n", r->via);
    if (r->from)
        g_string_append_printf(s, "PreferredSource=%s\n", r->from);

    if (g_strcmp0(r->scope, "global") != 0)
        g_string_append_printf(s, "Scope=%s\n", r->scope);
    if (g_strcmp0(r->type, "unicast") != 0)
        g_string_append_printf(s, "Type=%s\n", r->type);
    if (r->onlink)
        g_string_append_printf(s, "GatewayOnlink=true\n");
    if (r->metric != NETPLAN_METRIC_UNSPEC)
        g_string_append_printf(s, "Metric=%d\n", r->metric);
    if (r->table != NETPLAN_ROUTE_TABLE_UNSPEC)
        g_string_append_printf(s, "Table=%d\n", r->table);
}

static void
write_ip_rule(NetplanIPRule* r, GString* s)
{
    g_string_append_printf(s, "\n[RoutingPolicyRule]\n");

    if (r->from)
        g_string_append_printf(s, "From=%s\n", r->from);
    if (r->to)
        g_string_append_printf(s, "To=%s\n", r->to);

    if (r->table != NETPLAN_ROUTE_TABLE_UNSPEC)
        g_string_append_printf(s, "Table=%d\n", r->table);
    if (r->priority != NETPLAN_IP_RULE_PRIO_UNSPEC)
        g_string_append_printf(s, "Priority=%d\n", r->priority);
    if (r->fwmark != NETPLAN_IP_RULE_FW_MARK_UNSPEC)
        g_string_append_printf(s, "FirewallMark=%d\n", r->fwmark);
    if (r->tos != NETPLAN_IP_RULE_TOS_UNSPEC)
        g_string_append_printf(s, "TypeOfService=%d\n", r->tos);
}

#define DHCP_OVERRIDES_ERROR                                            \
    "ERROR: %s: networkd requires that %s has the same value in both "  \
    "dhcp4_overrides and dhcp6_overrides\n"

static void
combine_dhcp_overrides(const NetplanNetDefinition* def, NetplanDHCPOverrides* combined_dhcp_overrides)
{
    /* if only one of dhcp4 or dhcp6 is enabled, those overrides are used */
    if (def->dhcp4 && !def->dhcp6) {
        *combined_dhcp_overrides = def->dhcp4_overrides;
    } else if (!def->dhcp4 && def->dhcp6) {
        *combined_dhcp_overrides = def->dhcp6_overrides;
    } else {
        /* networkd doesn't support separately configuring dhcp4 and dhcp6, so
         * we enforce that they are the same.
         */
        if (def->dhcp4_overrides.use_dns != def->dhcp6_overrides.use_dns) {
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "use-dns");
            exit(1);
        }
        if (g_strcmp0(def->dhcp4_overrides.use_domains, def->dhcp6_overrides.use_domains) != 0){
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "use-domains");
            exit(1);
        }
        if (def->dhcp4_overrides.use_ntp != def->dhcp6_overrides.use_ntp) {
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "use-ntp");
            exit(1);
        }
        if (def->dhcp4_overrides.send_hostname != def->dhcp6_overrides.send_hostname) {
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "send-hostname");
            exit(1);
        }
        if (def->dhcp4_overrides.use_hostname != def->dhcp6_overrides.use_hostname) {
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "use-hostname");
            exit(1);
        }
        if (def->dhcp4_overrides.use_mtu != def->dhcp6_overrides.use_mtu) {
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "use-mtu");
            exit(1);
        }
        if (g_strcmp0(def->dhcp4_overrides.hostname, def->dhcp6_overrides.hostname) != 0) {
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "hostname");
            exit(1);
        }
        if (def->dhcp4_overrides.metric != def->dhcp6_overrides.metric) {
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "route-metric");
            exit(1);
        }
        if (def->dhcp4_overrides.use_routes != def->dhcp6_overrides.use_routes) {
            g_fprintf(stderr, DHCP_OVERRIDES_ERROR, def->id, "use-routes");
            exit(1);
        }
        /* Just use dhcp4_overrides now, since we know they are the same. */
        *combined_dhcp_overrides = def->dhcp4_overrides;
    }
}

static void
write_network_file(const NetplanNetDefinition* def, const char* rootdir, const char* path)
{
    GString* network = NULL;
    GString* link = NULL;
    GString* s = NULL;
    mode_t orig_umask;

    if (def->type == NETPLAN_DEF_TYPE_VLAN && def->sriov_vlan_filter) {
        g_debug("%s is defined as a hardware SR-IOV filtered VLAN, postponing creation", def->id);
        return;
    }

    /* Prepare the [Link] section of the .network file. */
    link = g_string_sized_new(200);

    /* Prepare the [Network] section */
    network = g_string_sized_new(200);

    if (def->optional || def->optional_addresses) {
        if (def->optional) {
            g_string_append(link, "RequiredForOnline=no\n");
        }
        for (unsigned i = 0; NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name != NULL; ++i) {
            if (def->optional_addresses & NETPLAN_OPTIONAL_ADDRESS_TYPES[i].flag) {
            g_string_append_printf(link, "OptionalAddresses=%s\n", NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name);
            }
        }
    }

    if (def->mtubytes) {
        g_string_append_printf(link, "MTUBytes=%d\n", def->mtubytes);
    }

    if (def->emit_lldp) {
        g_string_append(network, "EmitLLDP=true\n");
    }

    if (def->dhcp4 && def->dhcp6)
        g_string_append(network, "DHCP=yes\n");
    else if (def->dhcp4)
        g_string_append(network, "DHCP=ipv4\n");
    else if (def->dhcp6)
        g_string_append(network, "DHCP=ipv6\n");

    /* Set link local addressing -- this does not apply to bond and bridge
     * member interfaces, which always get it disabled.
     */
    if (!def->bond && !def->bridge && (def->linklocal.ipv4 || def->linklocal.ipv6)) {
        if (def->linklocal.ipv4 && def->linklocal.ipv6)
            g_string_append(network, "LinkLocalAddressing=yes\n");
        else if (def->linklocal.ipv4)
            g_string_append(network, "LinkLocalAddressing=ipv4\n");
        else if (def->linklocal.ipv6)
            g_string_append(network, "LinkLocalAddressing=ipv6\n");
    } else {
        g_string_append(network, "LinkLocalAddressing=no\n");
    }

    if (def->ip4_addresses)
        for (unsigned i = 0; i < def->ip4_addresses->len; ++i)
            g_string_append_printf(network, "Address=%s\n", g_array_index(def->ip4_addresses, char*, i));
    if (def->ip6_addresses)
        for (unsigned i = 0; i < def->ip6_addresses->len; ++i)
            g_string_append_printf(network, "Address=%s\n", g_array_index(def->ip6_addresses, char*, i));
    if (def->ip6_addr_gen_mode) {
        /* TODO: Figure out how we can configure ipv6-address-generation for networkd.
         *       IPv6Token= seems to be the corresponding option, but it doesn't do
         *       exactly what we need and has quite some restrictions, c.f.:
         *       https://github.com/systemd/systemd/issues/4625
         *       https://github.com/systemd/systemd/pull/14415 */
        g_fprintf(stderr, "ERROR: %s: ipv6-address-generation is not supported by networkd\n", def->id);
        exit(1);
    }
    if (def->accept_ra == NETPLAN_RA_MODE_ENABLED)
        g_string_append_printf(network, "IPv6AcceptRA=yes\n");
    else if (def->accept_ra == NETPLAN_RA_MODE_DISABLED)
        g_string_append_printf(network, "IPv6AcceptRA=no\n");
    if (def->ip6_privacy)
        g_string_append(network, "IPv6PrivacyExtensions=yes\n");
    if (def->gateway4)
        g_string_append_printf(network, "Gateway=%s\n", def->gateway4);
    if (def->gateway6)
        g_string_append_printf(network, "Gateway=%s\n", def->gateway6);
    if (def->ip4_nameservers)
        for (unsigned i = 0; i < def->ip4_nameservers->len; ++i)
            g_string_append_printf(network, "DNS=%s\n", g_array_index(def->ip4_nameservers, char*, i));
    if (def->ip6_nameservers)
        for (unsigned i = 0; i < def->ip6_nameservers->len; ++i)
            g_string_append_printf(network, "DNS=%s\n", g_array_index(def->ip6_nameservers, char*, i));
    if (def->search_domains) {
        g_string_append_printf(network, "Domains=%s", g_array_index(def->search_domains, char*, 0));
        for (unsigned i = 1; i < def->search_domains->len; ++i)
            g_string_append_printf(network, " %s", g_array_index(def->search_domains, char*, i));
        g_string_append(network, "\n");
    }

    if (def->ipv6_mtubytes) {
        g_string_append_printf(network, "IPv6MTUBytes=%d\n", def->ipv6_mtubytes);
    }

    if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL)
        g_string_append(network, "ConfigureWithoutCarrier=yes\n");

    if (def->bridge) {
        g_string_append_printf(network, "Bridge=%s\n", def->bridge);

        if (def->bridge_params.path_cost || def->bridge_params.port_priority)
            g_string_append_printf(network, "\n[Bridge]\n");
        if (def->bridge_params.path_cost)
            g_string_append_printf(network, "Cost=%u\n", def->bridge_params.path_cost);
        if (def->bridge_params.port_priority)
            g_string_append_printf(network, "Priority=%u\n", def->bridge_params.port_priority);
    }
    if (def->bond) {
        g_string_append_printf(network, "Bond=%s\n", def->bond);

        if (def->bond_params.primary_slave)
            g_string_append_printf(network, "PrimarySlave=true\n");
    }

    if (def->has_vlans) {
        /* iterate over all netdefs to find VLANs attached to us */
        GList *l = netdefs_ordered;
        const NetplanNetDefinition* nd;
        for (; l != NULL; l = l->next) {
            nd = l->data;
            if (nd->vlan_link == def && !nd->sriov_vlan_filter)
                g_string_append_printf(network, "VLAN=%s\n", nd->id);
        }
    }

    if (def->routes != NULL) {
        for (unsigned i = 0; i < def->routes->len; ++i) {
            NetplanIPRoute* cur_route = g_array_index (def->routes, NetplanIPRoute*, i);
            write_route(cur_route, network);
        }
    }
    if (def->ip_rules != NULL) {
        for (unsigned i = 0; i < def->ip_rules->len; ++i) {
            NetplanIPRule* cur_rule = g_array_index (def->ip_rules, NetplanIPRule*, i);
            write_ip_rule(cur_rule, network);
        }
    }

    if (def->dhcp4 || def->dhcp6 || def->critical) {
        /* NetworkManager compatible route metrics */
        g_string_append(network, "\n[DHCP]\n");
    }

    if (def->critical)
        g_string_append_printf(network, "CriticalConnection=true\n");

    if (def->dhcp4 || def->dhcp6) {
        if (g_strcmp0(def->dhcp_identifier, "duid") != 0)
            g_string_append_printf(network, "ClientIdentifier=%s\n", def->dhcp_identifier);

        NetplanDHCPOverrides combined_dhcp_overrides;
        combine_dhcp_overrides(def, &combined_dhcp_overrides);

        if (combined_dhcp_overrides.metric == NETPLAN_METRIC_UNSPEC) {
            g_string_append_printf(network, "RouteMetric=%i\n", (def->type == NETPLAN_DEF_TYPE_WIFI ? 600 : 100));
        } else {
            g_string_append_printf(network, "RouteMetric=%u\n",
                                   combined_dhcp_overrides.metric);
        }

        /* Only set MTU from DHCP if use-mtu dhcp-override is not false. */
        if (!combined_dhcp_overrides.use_mtu) {
            /* isc-dhcp dhclient compatible UseMTU, networkd default is to
             * not accept MTU, which breaks clouds */
            g_string_append_printf(network, "UseMTU=false\n");
        } else {
            g_string_append_printf(network, "UseMTU=true\n");
        }

        /* Only write DHCP options that differ from the networkd default. */
        if (!combined_dhcp_overrides.use_routes)
            g_string_append_printf(network, "UseRoutes=false\n");
        if (!combined_dhcp_overrides.use_dns)
            g_string_append_printf(network, "UseDNS=false\n");
        if (combined_dhcp_overrides.use_domains)
            g_string_append_printf(network, "UseDomains=%s\n", combined_dhcp_overrides.use_domains);
        if (!combined_dhcp_overrides.use_ntp)
            g_string_append_printf(network, "UseNTP=false\n");
        if (!combined_dhcp_overrides.send_hostname)
            g_string_append_printf(network, "SendHostname=false\n");
        if (!combined_dhcp_overrides.use_hostname)
            g_string_append_printf(network, "UseHostname=false\n");
        if (combined_dhcp_overrides.hostname)
            g_string_append_printf(network, "Hostname=%s\n", combined_dhcp_overrides.hostname);
    }

    if (network->len > 0 || link->len > 0) {
        s = g_string_sized_new(200);
        append_match_section(def, s, TRUE);

        if (link->len > 0)
            g_string_append_printf(s, "\n[Link]\n%s", link->str);
        if (network->len > 0)
            g_string_append_printf(s, "\n[Network]\n%s", network->str);

        g_string_free(link, TRUE);
        g_string_free(network, TRUE);

        /* these do not contain secrets and need to be readable by
         * systemd-networkd - LP: #1736965 */
        orig_umask = umask(022);
        g_string_free_to_file(s, rootdir, path, ".network");
        umask(orig_umask);
    }
}

static void
write_rules_file(const NetplanNetDefinition* def, const char* rootdir)
{
    GString* s = NULL;
    g_autofree char* path = g_strjoin(NULL, "run/udev/rules.d/99-netplan-", def->id, ".rules", NULL);
    mode_t orig_umask;

    /* do we need to write a .rules file?
     * It's only required for reliably setting the name of a physical device
     * until systemd issue #9006 is resolved. */
    if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL)
        return;

    /* Matching by name does not work.
     *
     * As far as I can tell, if you match by the name coming out of
     * initrd, systemd complains that a link file is matching on a
     * renamed name. If you match by the unstable kernel name, the
     * device no longer has that name when udevd reads the file, so
     * the rule doesn't fire. So only support mac and driver. */
    if (!def->set_name || (!def->match.mac && !def->match.driver))
        return;

    /* build file contents */
    s = g_string_sized_new(200);

    g_string_append(s, "SUBSYSTEM==\"net\", ACTION==\"add\", ");

    if (def->match.driver) {
        g_string_append_printf(s,"DRIVERS==\"%s\", ", def->match.driver);
    } else {
        g_string_append(s, "DRIVERS==\"?*\", ");
    }

    if (def->match.mac)
        g_string_append_printf(s, "ATTR{address}==\"%s\", ", def->match.mac);

    g_string_append_printf(s, "NAME=\"%s\"\n", def->set_name);

    orig_umask = umask(022);
    g_string_free_to_file(s, rootdir, path, NULL);
    umask(orig_umask);
}

static void
append_wpa_auth_conf(GString* s, const NetplanAuthenticationSettings* auth, const char* id)
{
    switch (auth->key_management) {
        case NETPLAN_AUTH_KEY_MANAGEMENT_NONE:
            g_string_append(s, "  key_mgmt=NONE\n");
            break;

        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK:
            g_string_append(s, "  key_mgmt=WPA-PSK\n");
            break;

        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP:
            g_string_append(s, "  key_mgmt=WPA-EAP\n");
            break;

        case NETPLAN_AUTH_KEY_MANAGEMENT_8021X:
            g_string_append(s, "  key_mgmt=IEEE8021X\n");
            break;
    }

    switch (auth->eap_method) {
        case NETPLAN_AUTH_EAP_NONE:
            break;

        case NETPLAN_AUTH_EAP_TLS:
            g_string_append(s, "  eap=TLS\n");
            break;

        case NETPLAN_AUTH_EAP_PEAP:
            g_string_append(s, "  eap=PEAP\n");
            break;

        case NETPLAN_AUTH_EAP_TTLS:
            g_string_append(s, "  eap=TTLS\n");
            break;
    }

    if (auth->identity) {
        g_string_append_printf(s, "  identity=\"%s\"\n", auth->identity);
    }
    if (auth->anonymous_identity) {
        g_string_append_printf(s, "  anonymous_identity=\"%s\"\n", auth->anonymous_identity);
    }
    if (auth->password) {
        if (auth->key_management == NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK) {
            size_t len = strlen(auth->password);
            if (len == 64) {
                /* must be a hex-digit key representation */
                for (unsigned i = 0; i < 64; ++i)
                    if (!isxdigit(auth->password[i])) {
                        g_fprintf(stderr, "ERROR: %s: PSK length of 64 is only supported for hex-digit representation\n", id);
                        exit(1);
                    }
                /* this is required to be unquoted */
                g_string_append_printf(s, "  psk=%s\n", auth->password);
            } else if (len < 8 || len > 63) {
                /* per wpa_supplicant spec, passphrase needs to be between 8
                   and 63 characters */
                g_fprintf(stderr, "ERROR: %s: ASCII passphrase must be between 8 and 63 characters (inclusive)\n", id);
                exit(1);
            } else {
                g_string_append_printf(s, "  psk=\"%s\"\n", auth->password);
            }
        } else {
            if (strncmp(auth->password, "hash:", 5) == 0) {
                g_string_append_printf(s, "  password=%s\n", auth->password);
            } else {
                g_string_append_printf(s, "  password=\"%s\"\n", auth->password);
            }
        }
    }
    if (auth->ca_certificate) {
        g_string_append_printf(s, "  ca_cert=\"%s\"\n", auth->ca_certificate);
    }
    if (auth->client_certificate) {
        g_string_append_printf(s, "  client_cert=\"%s\"\n", auth->client_certificate);
    }
    if (auth->client_key) {
        g_string_append_printf(s, "  private_key=\"%s\"\n", auth->client_key);
    }
    if (auth->client_key_password) {
        g_string_append_printf(s, "  private_key_passwd=\"%s\"\n", auth->client_key_password);
    }
    if (auth->phase2_auth) {
        g_string_append_printf(s, "  phase2=\"auth=%s\"\n", auth->phase2_auth);
    }

}

/* netplan-feature: generated-supplicant */
static void
write_wpa_unit(const NetplanNetDefinition* def, const char* rootdir)
{
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdouth = NULL;
    g_autofree gchar *stderrh = NULL;
    gint exit_status = 0;

    gchar *argv[] = {"bin" "/" "systemd-escape", def->id, NULL};
    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdouth, &stderrh, &exit_status, &err);
    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to ask systemd to escape %s; exit %d\nstdout: '%s'\nstderr: '%s'", def->id, exit_status, stdouth, stderrh);
        exit(1);
        // LCOV_EXCL_STOP
    }
    g_strstrip(stdouth);

    GString* s = g_string_new("[Unit]\n");
    g_autofree char* path = g_strjoin(NULL, "/run/systemd/system/netplan-wpa-", stdouth, ".service", NULL);
    g_string_append_printf(s, "Description=WPA supplicant for netplan %s\n", stdouth);
    g_string_append(s, "DefaultDependencies=no\n");
    g_string_append_printf(s, "Requires=sys-subsystem-net-devices-%s.device\n", stdouth);
    g_string_append_printf(s, "After=sys-subsystem-net-devices-%s.device\n", stdouth);
    g_string_append(s, "Before=network.target\nWants=network.target\n\n");
    g_string_append(s, "[Service]\nType=simple\n");
    g_string_append_printf(s, "ExecStart=/sbin/wpa_supplicant -c /run/netplan/wpa-%s.conf -i%s", stdouth, stdouth);

    if (def->type != NETPLAN_DEF_TYPE_WIFI) {
        g_string_append(s, " -Dwired\n");
    }
    g_string_free_to_file(s, rootdir, path, NULL);
}

static void
write_wpa_conf(const NetplanNetDefinition* def, const char* rootdir)
{
    GHashTableIter iter;
    GString* s = g_string_new("ctrl_interface=/run/wpa_supplicant\n\n");
    g_autofree char* path = g_strjoin(NULL, "run/netplan/wpa-", def->id, ".conf", NULL);
    mode_t orig_umask;

    g_debug("%s: Creating wpa_supplicant configuration file %s", def->id, path);
    if (def->type == NETPLAN_DEF_TYPE_WIFI) {
        if (def->wowlan && def->wowlan > NETPLAN_WIFI_WOWLAN_DEFAULT) {
            g_string_append(s, "wowlan_triggers=");
            append_wifi_wowlan_flags(def->wowlan, s);
        }
        NetplanWifiAccessPoint* ap;
        g_hash_table_iter_init(&iter, def->access_points);
        while (g_hash_table_iter_next(&iter, NULL, (gpointer) &ap)) {
            g_string_append_printf(s, "network={\n  ssid=\"%s\"\n", ap->ssid);
            if (ap->bssid) {
                g_string_append_printf(s, "  bssid=%s\n", ap->bssid);
            }
            if (ap->band == NETPLAN_WIFI_BAND_24) {
                // initialize 2.4GHz frequency hashtable
                if(!wifi_frequency_24)
                    wifi_get_freq24(1);
                if (ap->channel) {
                    g_string_append_printf(s, "  freq_list=%d\n", wifi_get_freq24(ap->channel));
                } else {
                    g_string_append_printf(s, "  freq_list=");
                    g_hash_table_foreach(wifi_frequency_24, wifi_append_freq, s);
                    // overwrite last whitespace with newline
                    s = g_string_overwrite(s, s->len-1, "\n");
                }
            } else if (ap->band == NETPLAN_WIFI_BAND_5) {
                // initialize 5GHz frequency hashtable
                if(!wifi_frequency_5)
                    wifi_get_freq5(7);
                if (ap->channel) {
                    g_string_append_printf(s, "  freq_list=%d\n", wifi_get_freq5(ap->channel));
                } else {
                    g_string_append_printf(s, "  freq_list=");
                    g_hash_table_foreach(wifi_frequency_5, wifi_append_freq, s);
                    // overwrite last whitespace with newline
                    s = g_string_overwrite(s, s->len-1, "\n");
                }
            }
            switch (ap->mode) {
                case NETPLAN_WIFI_MODE_INFRASTRUCTURE:
                    /* default in wpasupplicant */
                    break;
                case NETPLAN_WIFI_MODE_ADHOC:
                    g_string_append(s, "  mode=1\n");
                    break;
                case NETPLAN_WIFI_MODE_AP:
                    g_fprintf(stderr, "ERROR: %s: networkd does not support wifi in access point mode\n", def->id);
                    exit(1);
            }

            /* wifi auth trumps netdef auth */
            if (ap->has_auth) {
                append_wpa_auth_conf(s, &ap->auth, ap->ssid);
            }
            else {
                g_string_append(s, "  key_mgmt=NONE\n");
            }
            g_string_append(s, "}\n");
        }
    }
    else {
        /* wired 802.1x auth or similar */
        g_string_append(s, "network={\n");
        append_wpa_auth_conf(s, &def->auth, def->id);
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
write_networkd_conf(const NetplanNetDefinition* def, const char* rootdir)
{
    g_autofree char* path_base = g_strjoin(NULL, "run/systemd/network/10-netplan-", def->id, NULL);

    /* We want this for all backends when renaming, as *.link and *.rules files are
     * evaluated by udev, not networkd itself or NetworkManager. */
    write_link_file(def, rootdir, path_base);
    write_rules_file(def, rootdir);

    if (def->backend != NETPLAN_BACKEND_NETWORKD) {
        g_debug("networkd: definition %s is not for us (backend %i)", def->id, def->backend);
        return FALSE;
    }

    if (def->type == NETPLAN_DEF_TYPE_MODEM) {
        g_fprintf(stderr, "ERROR: %s: networkd backend does not support GSM/CDMA modem configuration\n", def->id);
        exit(1);
    }

    if (def->type == NETPLAN_DEF_TYPE_WIFI || def->has_auth) {
        g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/systemd-networkd.service.wants/netplan-wpa-", def->id, ".service", NULL);
        g_autofree char* slink = g_strjoin(NULL, "/run/systemd/system/netplan-wpa-", def->id, ".service", NULL);
        if (def->type == NETPLAN_DEF_TYPE_WIFI && def->has_match) {
            g_fprintf(stderr, "ERROR: %s: networkd backend does not support wifi with match:, only by interface name\n", def->id);
            exit(1);
        }

        g_debug("Creating wpa_supplicant config");
        write_wpa_conf(def, rootdir);

        g_debug("Creating wpa_supplicant unit %s", slink);
        write_wpa_unit(def, rootdir);

        g_debug("Creating wpa_supplicant service enablement link %s", link);
        safe_mkdir_p_dir(link);

        if (symlink(slink, link) < 0 && errno != EEXIST) {
            // LCOV_EXCL_START
            g_fprintf(stderr, "failed to create enablement symlink: %m\n");
            exit(1);
            // LCOV_EXCL_STOP
        }

    }

    if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL)
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
    unlink_glob(rootdir, "/run/netplan/wpa-*.conf");
    unlink_glob(rootdir, "/run/systemd/system/netplan-wpa-*.service");
    unlink_glob(rootdir, "/run/udev/rules.d/99-netplan-*");
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
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to create enablement symlink: %m\n");
        exit(1);
        // LCOV_EXCL_STOP
    }

    g_autofree char* link2 = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "network-online.target.wants", "systemd-networkd-wait-online.service", NULL);
    safe_mkdir_p_dir(link2);
    if (symlink("/lib/systemd/system/systemd-networkd-wait-online.service", link2) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to create enablement symlink: %m\n");
        exit(1);
        // LCOV_EXCL_STOP
    }
}
