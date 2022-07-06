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
#include "parse-globals.h"
#include "names.h"
#include "util.h"
#include "util-internal.h"
#include "validation.h"

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
static gboolean
append_wifi_wowlan_flags(NetplanWifiWowlanFlag flag, GString* str, GError** error) {
    if (flag & NETPLAN_WIFI_WOWLAN_TYPES[0].flag || flag >= NETPLAN_WIFI_WOWLAN_TCP) {
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "ERROR: unsupported wowlan_triggers mask: 0x%x\n", flag);
        return FALSE;
    }
    for (unsigned i = 0; NETPLAN_WIFI_WOWLAN_TYPES[i].name != NULL; ++i) {
        if (flag & NETPLAN_WIFI_WOWLAN_TYPES[i].flag) {
            g_string_append_printf(str, "%s ", NETPLAN_WIFI_WOWLAN_TYPES[i].name);
        }
    }
    /* replace trailing space with newline */
    str = g_string_overwrite(str, str->len-1, "\n");
    return TRUE;
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
    if (def->match.driver && strchr(def->match.driver, '\t')) {
        gchar **split = g_strsplit(def->match.driver, "\t", 0);
        g_string_append_printf(s, "Driver=%s", split[0]);
        for (unsigned i = 1; split[i]; ++i)
            g_string_append_printf(s, " %s", split[i]);
        g_string_append(s, "\n");
        g_strfreev(split);
    } else if (def->match.driver)
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

    /* Workaround for bugs LP: #1804861 and LP: #1888726: something outputs
     * netplan config that includes using the MAC of the first phy member of a
     * bond as default value for the MAC of the bond device itself. This is
     * evil, it's an optional field and networkd knows what to do if the MAC
     * isn't specified; but work around this by adding an arbitrary additional
     * match condition on Path= for the phys. This way, hopefully setting a MTU
     * on the phy does not bleed over to bond/bridge and any further virtual
     * devices (VLANs?) on top of it.
     * Make sure to add the extra match only if we're matching by MAC
     * already and dealing with a bond, bridge or vlan.
     */
    if (def->bond || def->bridge || def->has_vlans) {
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
        g_string_append_printf(params, "Mode=%s\n", netplan_tunnel_mode_name(def->tunnel.mode));
    g_string_append_printf(params, "Local=%s\n", def->tunnel.local_ip);
    g_string_append_printf(params, "Remote=%s\n", def->tunnel.remote_ip);
    if (def->tunnel_ttl)
        g_string_append_printf(params, "TTL=%u\n", def->tunnel_ttl);
    if (def->tunnel.input_key)
        g_string_append_printf(params, "InputKey=%s\n", def->tunnel.input_key);
    if (def->tunnel.output_key)
        g_string_append_printf(params, "OutputKey=%s\n", def->tunnel.output_key);

    g_string_append_printf(s, "\n[Tunnel]\n%s", params->str);
    g_string_free(params, TRUE);
}

static void
write_wireguard_params(GString* s, const NetplanNetDefinition* def)
{
    GString *params = NULL;
    params = g_string_sized_new(200);

    g_assert(def->tunnel.private_key);
    /* The "PrivateKeyFile=" setting is available as of systemd-netwokrd v242+
     * Base64 encoded PrivateKey= or absolute PrivateKeyFile= fields are mandatory.
     *
     * The key was already validated via validate_tunnel_grammar(), but we need
     * to differentiate between base64 key VS absolute path key-file. And a base64
     * string could (theoretically) start with '/', so we use is_wireguard_key()
     * as well to check for more specific characteristics (if needed). */
    if (def->tunnel.private_key[0] == '/' && !is_wireguard_key(def->tunnel.private_key))
        g_string_append_printf(params, "PrivateKeyFile=%s\n", def->tunnel.private_key);
    else
        g_string_append_printf(params, "PrivateKey=%s\n", def->tunnel.private_key);

    if (def->tunnel.port)
        g_string_append_printf(params, "ListenPort=%u\n", def->tunnel.port);
    /* This is called FirewallMark= as of systemd v243, but we keep calling it FwMark= for
       backwards compatibility. FwMark= is still supported, but deprecated:
       https://github.com/systemd/systemd/pull/12478 */
    if (def->tunnel.fwmark)
        g_string_append_printf(params, "FwMark=%u\n", def->tunnel.fwmark);

    g_string_append_printf(s, "\n[WireGuard]\n%s", params->str);
    g_string_free(params, TRUE);

    for (guint i = 0; i < def->wireguard_peers->len; i++) {
        NetplanWireguardPeer *peer = g_array_index (def->wireguard_peers, NetplanWireguardPeer*, i);
        GString *peer_s = g_string_sized_new(200);

        g_string_append_printf(peer_s, "PublicKey=%s\n", peer->public_key);
        g_string_append(peer_s, "AllowedIPs=");
        for (guint i = 0; i < peer->allowed_ips->len; ++i) {
            if (i > 0 )
                g_string_append_c(peer_s, ',');
            g_string_append_printf(peer_s, "%s", g_array_index(peer->allowed_ips, char*, i));
        }
        g_string_append_c(peer_s, '\n');

        if (peer->keepalive)
            g_string_append_printf(peer_s, "PersistentKeepalive=%d\n", peer->keepalive);
        if (peer->endpoint)
            g_string_append_printf(peer_s, "Endpoint=%s\n", peer->endpoint);
        /* The key was already validated via validate_tunnel_grammar(), but we need
         * to differentiate between base64 key VS absolute path key-file. And a base64
         * string could (theoretically) start with '/', so we use is_wireguard_key()
         * as well to check for more specific characteristics (if needed). */
        if (peer->preshared_key) {
            if (peer->preshared_key[0] == '/' && !is_wireguard_key(peer->preshared_key))
                g_string_append_printf(peer_s, "PresharedKeyFile=%s\n", peer->preshared_key);
            else
                g_string_append_printf(peer_s, "PresharedKey=%s\n", peer->preshared_key);
        }

        g_string_append_printf(s, "\n[WireGuardPeer]\n%s", peer_s->str);
        g_string_free(peer_s, TRUE);
    }
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
    if (!def->set_name &&
        !def->wake_on_lan &&
        !def->mtubytes &&
        (def->receive_checksum_offload == NETPLAN_TRISTATE_UNSET) &&
        (def->transmit_checksum_offload == NETPLAN_TRISTATE_UNSET) &&
        (def->tcp_segmentation_offload == NETPLAN_TRISTATE_UNSET) &&
        (def->tcp6_segmentation_offload == NETPLAN_TRISTATE_UNSET) &&
        (def->generic_segmentation_offload == NETPLAN_TRISTATE_UNSET) &&
        (def->generic_receive_offload == NETPLAN_TRISTATE_UNSET) &&
        (def->large_receive_offload == NETPLAN_TRISTATE_UNSET))
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

    /* Offload options */
    if (def->receive_checksum_offload != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(s, "ReceiveChecksumOffload=%s\n",
        (def->receive_checksum_offload ? "true" : "false"));

    if (def->transmit_checksum_offload != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(s, "TransmitChecksumOffload=%s\n",
        (def->transmit_checksum_offload ? "true" : "false"));

    if (def->tcp_segmentation_offload != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(s, "TCPSegmentationOffload=%s\n",
        (def->tcp_segmentation_offload ? "true" : "false"));

    if (def->tcp6_segmentation_offload != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(s, "TCP6SegmentationOffload=%s\n",
        (def->tcp6_segmentation_offload ? "true" : "false"));

    if (def->generic_segmentation_offload != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(s, "GenericSegmentationOffload=%s\n",
        (def->generic_segmentation_offload ? "true" : "false"));

    if (def->generic_receive_offload != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(s, "GenericReceiveOffload=%s\n",
        (def->generic_receive_offload ? "true" : "false"));

    if (def->large_receive_offload != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(s, "LargeReceiveOffload=%s\n",
        (def->large_receive_offload ? "true" : "false"));

    orig_umask = umask(022);
    g_string_free_to_file(s, rootdir, path, ".link");
    umask(orig_umask);
}

static gboolean
write_regdom(const NetplanNetDefinition* def, const char* rootdir, GError** error)
{
    g_assert(def->regulatory_domain);
    g_autofree gchar* id_escaped = NULL;
    g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/network.target.wants/netplan-regdom.service", NULL);
    g_autofree char* path = g_strjoin(NULL, "/run/systemd/system/netplan-regdom.service", NULL);

    GString* s = g_string_new("[Unit]\n");
    g_string_append(s, "Description=Netplan regulatory-domain configuration\n");
    g_string_append(s, "After=network.target\n");
    g_string_append(s, "ConditionFileIsExecutable="SBINDIR"/iw\n");
    g_string_append(s, "\n[Service]\nType=oneshot\n");
    g_string_append_printf(s, "ExecStart="SBINDIR"/iw reg set %s\n", def->regulatory_domain);

    g_string_free_to_file(s, rootdir, path, NULL);
    safe_mkdir_p_dir(link);
    if (symlink(path, link) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_set_error(error, G_FILE_ERROR, G_FILE_ERROR_FAILED, "failed to create enablement symlink: %m\n");
        return FALSE;
        // LCOV_EXCL_STOP
    }
    return TRUE;
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

        case NETPLAN_DEF_TYPE_VRF:
            g_string_append_printf(s, "Kind=vrf\n\n[VRF]\nTable=%u\n", def->vrf_table);
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
                case NETPLAN_TUNNEL_MODE_WIREGUARD:
                    g_string_append_printf(s, "Kind=%s\n",
                                           netplan_tunnel_mode_name(def->tunnel.mode));
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
            if (def->tunnel.mode == NETPLAN_TUNNEL_MODE_WIREGUARD)
                write_wireguard_params(s, def);
            else
                write_tunnel_params(s, def);
            break;

        default: g_assert_not_reached(); // LCOV_EXCL_LINE
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
    const char *to;
    g_string_append_printf(s, "\n[Route]\n");

    if (g_strcmp0(r->to, "default") == 0)
        to = get_global_network(r->family);
    else
        to = r->to;
    g_string_append_printf(s, "Destination=%s\n", to);

    if (r->via)
        g_string_append_printf(s, "Gateway=%s\n", r->via);
    if (r->from)
        g_string_append_printf(s, "PreferredSource=%s\n", r->from);

    if (g_strcmp0(r->scope, "global") != 0)
        g_string_append_printf(s, "Scope=%s\n", r->scope);
    if (g_strcmp0(r->type, "unicast") != 0)
        g_string_append_printf(s, "Type=%s\n", r->type);
    if (r->onlink)
        g_string_append_printf(s, "GatewayOnLink=true\n");
    if (r->metric != NETPLAN_METRIC_UNSPEC)
        g_string_append_printf(s, "Metric=%d\n", r->metric);
    if (r->table != NETPLAN_ROUTE_TABLE_UNSPEC)
        g_string_append_printf(s, "Table=%d\n", r->table);
    if (r->mtubytes != NETPLAN_MTU_UNSPEC)
        g_string_append_printf(s, "MTUBytes=%u\n", r->mtubytes);
    if (r->congestion_window != NETPLAN_CONGESTION_WINDOW_UNSPEC)
        g_string_append_printf(s, "InitialCongestionWindow=%u\n", r->congestion_window);
    if (r->advertised_receive_window != NETPLAN_ADVERTISED_RECEIVE_WINDOW_UNSPEC)
        g_string_append_printf(s, "InitialAdvertisedReceiveWindow=%u\n", r->advertised_receive_window);
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

static void
write_addr_option(NetplanAddressOptions* o, GString* s)
{
    g_string_append_printf(s, "\n[Address]\n");
    g_assert(o->address);
    g_string_append_printf(s, "Address=%s\n", o->address);

    if (o->lifetime)
        g_string_append_printf(s, "PreferredLifetime=%s\n", o->lifetime);
    if (o->label)
        g_string_append_printf(s, "Label=%s\n", o->label);
}

#define DHCP_OVERRIDES_ERROR                                            \
    "ERROR: %s: networkd requires that %s has the same value in both "  \
    "dhcp4_overrides and dhcp6_overrides\n"

static gboolean
combine_dhcp_overrides(const NetplanNetDefinition* def, NetplanDHCPOverrides* combined_dhcp_overrides, GError** error)
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
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "use-dns");
            return FALSE;
        }
        if (g_strcmp0(def->dhcp4_overrides.use_domains, def->dhcp6_overrides.use_domains) != 0){
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "use-domains");
            return FALSE;
        }
        if (def->dhcp4_overrides.use_ntp != def->dhcp6_overrides.use_ntp) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "use-ntp");
            return FALSE;
        }
        if (def->dhcp4_overrides.send_hostname != def->dhcp6_overrides.send_hostname) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "send-hostname");
            return FALSE;
        }
        if (def->dhcp4_overrides.use_hostname != def->dhcp6_overrides.use_hostname) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "use-hostname");
            return FALSE;
        }
        if (def->dhcp4_overrides.use_mtu != def->dhcp6_overrides.use_mtu) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "use-mtu");
            return FALSE;
        }
        if (g_strcmp0(def->dhcp4_overrides.hostname, def->dhcp6_overrides.hostname) != 0) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "hostname");
            return FALSE;
        }
        if (def->dhcp4_overrides.metric != def->dhcp6_overrides.metric) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "route-metric");
            return FALSE;
        }
        if (def->dhcp4_overrides.use_routes != def->dhcp6_overrides.use_routes) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, DHCP_OVERRIDES_ERROR, def->id, "use-routes");
            return FALSE;
        }
        /* Just use dhcp4_overrides now, since we know they are the same. */
        *combined_dhcp_overrides = def->dhcp4_overrides;
    }
    return TRUE;
}

/**
 * Write the needed networkd .network configuration for the selected netplan definition.
 */
gboolean
netplan_netdef_write_network_file(
        const NetplanState* np_state,
        const NetplanNetDefinition* def,
        const char *rootdir,
        const char* path,
        gboolean* has_been_written,
        GError** error)
{
    GString* network = NULL;
    GString* link = NULL;
    GString* s = NULL;
    mode_t orig_umask;
    gboolean is_optional = def->optional;

    SET_OPT_OUT_PTR(has_been_written, FALSE);

    if (def->type == NETPLAN_DEF_TYPE_VLAN && def->sriov_vlan_filter) {
        g_debug("%s is defined as a hardware SR-IOV filtered VLAN, postponing creation", def->id);
        return TRUE;
    }

    /* Prepare the [Link] section of the .network file. */
    link = g_string_sized_new(200);

    /* Prepare the [Network] section */
    network = g_string_sized_new(200);

    /* The ActivationPolicy setting is available in systemd v248+ */
    if (def->activation_mode) {
        const char* mode;
        if (g_strcmp0(def->activation_mode, "manual") == 0)
            mode = "manual";
        else /* "off" */
            mode = "always-down";
        g_string_append_printf(link, "ActivationPolicy=%s\n", mode);
        /* When activation-mode is used we default to being optional.
         * Otherwise systemd might wait indefinitely for the interface to
         * become online.
         */
        is_optional = TRUE;
    }

    if (is_optional || def->optional_addresses) {
        if (is_optional) {
            g_string_append(link, "RequiredForOnline=no\n");
        }
        for (unsigned i = 0; NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name != NULL; ++i) {
            if (def->optional_addresses & NETPLAN_OPTIONAL_ADDRESS_TYPES[i].flag) {
            g_string_append_printf(link, "OptionalAddresses=%s\n", NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name);
            }
        }
    }

    if (def->mtubytes)
        g_string_append_printf(link, "MTUBytes=%u\n", def->mtubytes);
    if (def->set_mac)
        g_string_append_printf(link, "MACAddress=%s\n", def->set_mac);

    if (def->emit_lldp)
        g_string_append(network, "EmitLLDP=true\n");

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
    if (def->ip6_addr_gen_token) {
        g_string_append_printf(network, "IPv6Token=static:%s\n", def->ip6_addr_gen_token);
    } else if (def->ip6_addr_gen_mode > NETPLAN_ADDRGEN_EUI64) {
        /* EUI-64 mode is enabled by default, if no IPv6Token= is specified */
        /* TODO: Enable stable-privacy mode for networkd, once PR#16618 has been released:
         *       https://github.com/systemd/systemd/pull/16618 */
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "ERROR: %s: ipv6-address-generation mode is not supported by networkd\n", def->id);
        return FALSE;
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

    if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL || def->ignore_carrier)
        g_string_append(network, "ConfigureWithoutCarrier=yes\n");

    if (def->bridge && def->backend != NETPLAN_BACKEND_OVS) {
        g_string_append_printf(network, "Bridge=%s\n", def->bridge);

        if (def->bridge_params.path_cost || def->bridge_params.port_priority)
            g_string_append_printf(network, "\n[Bridge]\n");
        if (def->bridge_params.path_cost)
            g_string_append_printf(network, "Cost=%u\n", def->bridge_params.path_cost);
        if (def->bridge_params.port_priority)
            g_string_append_printf(network, "Priority=%u\n", def->bridge_params.port_priority);
    }
    if (def->bond && def->backend != NETPLAN_BACKEND_OVS) {
        g_string_append_printf(network, "Bond=%s\n", def->bond);

        if (def->bond_params.primary_slave)
            g_string_append_printf(network, "PrimarySlave=true\n");
    }

    if (def->has_vlans && def->backend != NETPLAN_BACKEND_OVS) {
        /* iterate over all netdefs to find VLANs attached to us */
        GList *l = np_state->netdefs_ordered;
        const NetplanNetDefinition* nd;
        for (; l != NULL; l = l->next) {
            nd = l->data;
            if (nd->vlan_link == def && !nd->sriov_vlan_filter)
                g_string_append_printf(network, "VLAN=%s\n", nd->id);
        }
    }

    /* VRF linkage */
    if (def->vrf_link)
        g_string_append_printf(network, "VRF=%s\n", def->vrf_link->id);

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

    if (def->address_options) {
        for (unsigned i = 0; i < def->address_options->len; ++i) {
            NetplanAddressOptions* opts = g_array_index(def->address_options, NetplanAddressOptions*, i);
            write_addr_option(opts, network);
        }
    }

    if (def->dhcp4 || def->dhcp6 || def->critical) {
        /* NetworkManager compatible route metrics */
        g_string_append(network, "\n[DHCP]\n");
    }

    if (def->critical)
        g_string_append_printf(network, "CriticalConnection=true\n");

    if (def->dhcp4 || def->dhcp6) {
        if (def->dhcp_identifier)
            g_string_append_printf(network, "ClientIdentifier=%s\n", def->dhcp_identifier);

        NetplanDHCPOverrides combined_dhcp_overrides;
        if (!combine_dhcp_overrides(def, &combined_dhcp_overrides, error))
            return FALSE;

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

    /* IP-over-InfiniBand, IPoIB */
    if (def->ib_mode != NETPLAN_IB_MODE_KERNEL) {
        g_string_append_printf(network, "\n[IPoIB]\nMode=%s\n", netplan_infiniband_mode_name(def->ib_mode));
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

    SET_OPT_OUT_PTR(has_been_written, TRUE);
    return TRUE;
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

static gboolean
append_wpa_auth_conf(GString* s, const NetplanAuthenticationSettings* auth, const char* id, GError** error)
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

        default: break; // LCOV_EXCL_LINE
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

        default: break; // LCOV_EXCL_LINE
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
                        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "ERROR: %s: PSK length of 64 is only supported for hex-digit representation\n", id);
                        return FALSE;
                    }
                /* this is required to be unquoted */
                g_string_append_printf(s, "  psk=%s\n", auth->password);
            } else if (len < 8 || len > 63) {
                /* per wpa_supplicant spec, passphrase needs to be between 8
                   and 63 characters */
                g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "ERROR: %s: ASCII passphrase must be between 8 and 63 characters (inclusive)\n", id);
                return FALSE;
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
    return TRUE;
}

/* netplan-feature: generated-supplicant */
static void
write_wpa_unit(const NetplanNetDefinition* def, const char* rootdir)
{
    g_autofree gchar *stdouth = NULL;
    mode_t orig_umask;

    stdouth = systemd_escape(def->id);

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
    } else {
        g_string_append(s, " -Dnl80211,wext\n");
    }
    orig_umask = umask(022);
    g_string_free_to_file(s, rootdir, path, NULL);
    umask(orig_umask);
}

static gboolean
write_wpa_conf(const NetplanNetDefinition* def, const char* rootdir, GError** error)
{
    GHashTableIter iter;
    GString* s = g_string_new("ctrl_interface=/run/wpa_supplicant\n\n");
    g_autofree char* path = g_strjoin(NULL, "run/netplan/wpa-", def->id, ".conf", NULL);
    mode_t orig_umask;

    g_debug("%s: Creating wpa_supplicant configuration file %s", def->id, path);
    if (def->type == NETPLAN_DEF_TYPE_WIFI) {
        if (def->wowlan && def->wowlan > NETPLAN_WIFI_WOWLAN_DEFAULT) {
            g_string_append(s, "wowlan_triggers=");
            if (!append_wifi_wowlan_flags(def->wowlan, s, error))
                return FALSE;
        }
        /* available as of wpa_supplicant version 0.6.7 */
        if (def->regulatory_domain) {
            g_string_append_printf(s, "country=%s\n", def->regulatory_domain);
        }
        NetplanWifiAccessPoint* ap;
        g_hash_table_iter_init(&iter, def->access_points);
        while (g_hash_table_iter_next(&iter, NULL, (gpointer) &ap)) {
            g_string_append_printf(s, "network={\n  ssid=\"%s\"\n", ap->ssid);
            if (ap->bssid) {
                g_string_append_printf(s, "  bssid=%s\n", ap->bssid);
            }
            if (ap->hidden) {
                g_string_append(s, "  scan_ssid=1\n");
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
                default:
                    g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "ERROR: %s: %s: networkd does not support this wifi mode\n", def->id, ap->ssid);
                    return FALSE;
            }

            /* wifi auth trumps netdef auth */
            if (ap->has_auth) {
                if (!append_wpa_auth_conf(s, &ap->auth, ap->ssid, error))
                    return FALSE;
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
        if (!append_wpa_auth_conf(s, &def->auth, def->id, error))
            return FALSE;
        g_string_append(s, "}\n");
    }

    /* use tight permissions as this contains secrets */
    orig_umask = umask(077);
    g_string_free_to_file(s, rootdir, path, NULL);
    umask(orig_umask);
    return TRUE;
}

/**
 * Generate networkd configuration in @rootdir/run/systemd/network/ from the
 * parsed #netdefs.
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 * @has_been_written: TRUE if @def applies to networkd, FALSE otherwise.
 * Returns: FALSE on error.
 */
NETPLAN_INTERNAL gboolean
netplan_netdef_write_networkd(
        const NetplanState* np_state,
        const NetplanNetDefinition* def,
        const char *rootdir,
        gboolean* has_been_written,
        GError** error)
{
    g_autofree char* path_base = g_strjoin(NULL, "run/systemd/network/10-netplan-", def->id, NULL);
    SET_OPT_OUT_PTR(has_been_written, FALSE);

    /* We want this for all backends when renaming, as *.link and *.rules files are
     * evaluated by udev, not networkd itself or NetworkManager. The regulatory
     * domain applies to all backends, too. */
    write_link_file(def, rootdir, path_base);
    write_rules_file(def, rootdir);
    if (def->regulatory_domain)
        write_regdom(def, rootdir, NULL); /* overwrites global regdom */

    if (def->backend != NETPLAN_BACKEND_NETWORKD) {
        g_debug("networkd: definition %s is not for us (backend %i)", def->id, def->backend);
        return TRUE;
    }

    if (def->type == NETPLAN_DEF_TYPE_MODEM) {
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "ERROR: %s: networkd backend does not support GSM/CDMA modem configuration\n", def->id);
        return FALSE;
    }

    if (def->type == NETPLAN_DEF_TYPE_WIFI || def->has_auth) {
        g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/systemd-networkd.service.wants/netplan-wpa-", def->id, ".service", NULL);
        g_autofree char* slink = g_strjoin(NULL, "/run/systemd/system/netplan-wpa-", def->id, ".service", NULL);
        if (def->type == NETPLAN_DEF_TYPE_WIFI && def->has_match) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "ERROR: %s: networkd backend does not support wifi with match:, only by interface name\n", def->id);
            return FALSE;
        }

        g_debug("Creating wpa_supplicant config");
        if (!write_wpa_conf(def, rootdir, error))
            return FALSE;

        g_debug("Creating wpa_supplicant unit %s", slink);
        write_wpa_unit(def, rootdir);

        g_debug("Creating wpa_supplicant service enablement link %s", link);
        safe_mkdir_p_dir(link);

        if (symlink(slink, link) < 0 && errno != EEXIST) {
            // LCOV_EXCL_START
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "failed to create enablement symlink: %m\n");
            return FALSE;
            // LCOV_EXCL_STOP
        }

    }

    if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL)
        write_netdev_file(def, rootdir, path_base);
    if (!netplan_netdef_write_network_file(np_state, def, rootdir, path_base, has_been_written, error))
        return FALSE;
    SET_OPT_OUT_PTR(has_been_written, TRUE);
    return TRUE;
}

/**
 * Clean up all generated configurations in @rootdir from previous runs.
 */
void
netplan_networkd_cleanup(const char* rootdir)
{
    unlink_glob(rootdir, "/run/systemd/network/10-netplan-*");
    unlink_glob(rootdir, "/run/netplan/wpa-*.conf");
    unlink_glob(rootdir, "/run/systemd/system/systemd-networkd.service.wants/netplan-wpa-*.service");
    unlink_glob(rootdir, "/run/systemd/system/netplan-wpa-*.service");
    unlink_glob(rootdir, "/run/udev/rules.d/99-netplan-*");
    unlink_glob(rootdir, "/run/systemd/system/network.target.wants/netplan-regdom.service");
    unlink_glob(rootdir, "/run/systemd/system/netplan-regdom.service");
    /* Historically (up to v0.98) we had netplan-wpa@*.service files, in case of an
     * upgraded system, we need to make sure to clean those up. */
    unlink_glob(rootdir, "/run/systemd/system/systemd-networkd.service.wants/netplan-wpa@*.service");
}
