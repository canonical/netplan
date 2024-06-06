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
#include <net/if.h>
#include <sys/stat.h>

#include <glib.h>
#include <glib/gprintf.h>

#include "networkd.h"
#include "parse.h"
#include "names.h"
#include "util.h"
#include "util-internal.h"
#include "validation.h"

/**
 * Query sysfs for the MAC address (up to 20 bytes for infiniband) of @ifname
 * The caller owns the returned string and needs to free it.
 */
STATIC char*
_netplan_sysfs_get_mac_by_ifname(const char* ifname, const char* rootdir)
{
    g_autofree gchar* content = NULL;
    g_autofree gchar* sysfs_path = NULL;
    sysfs_path = g_build_path(G_DIR_SEPARATOR_S, rootdir ?: G_DIR_SEPARATOR_S,
                              "sys", "class", "net", ifname, "address", NULL);

    if (!g_file_get_contents (sysfs_path, &content, NULL, NULL)) {
        g_debug("%s: Cannot read file contents.", __FUNCTION__);
        return NULL;
    }

    // Trim whitespace & clone value
    return g_strdup(g_strstrip(content));
}

/**
 * Query sysfs for the driver used by @ifname
 * The caller owns the returned string and needs to free it.
 */
STATIC char*
_netplan_sysfs_get_driver_by_ifname(const char* ifname, const char* rootdir)
{
    g_autofree gchar* link = NULL;
    g_autofree gchar* sysfs_path = NULL;
    sysfs_path = g_build_path(G_DIR_SEPARATOR_S, rootdir ?: G_DIR_SEPARATOR_S,
                              "sys", "class", "net", ifname, "device", "driver", NULL);

    link = g_file_read_link(sysfs_path, NULL);
    if (!link) {
        g_debug("%s: Cannot read symlink of %s.", __FUNCTION__, sysfs_path);
        return NULL;
    }

    return g_path_get_basename(link);
}

STATIC void
_netplan_query_system_interfaces(GHashTable* tbl)
{
    g_assert(tbl);
    struct if_nameindex *if_nidxs, *intf;
    if_nidxs = if_nameindex();
    if (if_nidxs != NULL) {
        for (intf = if_nidxs; intf->if_index != 0 || intf->if_name != NULL; intf++)
            g_hash_table_add(tbl, g_strdup(intf->if_name));
        if_freenameindex(if_nidxs);
    }
}

/**
 * Enumerate all network interfaces (/sys/clas/net/...) and check
 * netplan_netdef_match_interface() to see if they match the current NetDef
 */
STATIC void
_netplan_enumerate_interfaces(const NetplanNetDefinition* def, GHashTable* ifaces, GHashTable* tbl, const char* carrier, const char* set_name, const char* rootdir)
{
    g_assert(ifaces);
    g_assert(tbl);

    GHashTableIter iter;
    gpointer key;
    g_hash_table_iter_init (&iter, ifaces);
    while (g_hash_table_iter_next (&iter, &key, NULL)) {
        const char* ifname = key;
        if (g_hash_table_contains(tbl, ifname)|| (set_name && g_hash_table_contains(tbl, set_name))) continue;
        g_autofree gchar* mac = _netplan_sysfs_get_mac_by_ifname(ifname, rootdir);
        g_autofree gchar* driver = _netplan_sysfs_get_driver_by_ifname(ifname, rootdir);
        if (netplan_netdef_match_interface(def, ifname, mac, driver))
            g_hash_table_replace(tbl, set_name ? g_strdup(set_name) : g_strdup(ifname), g_strdup(carrier));
    }
}

/**
 * Append WiFi frequencies to wpa_supplicant's freq_list=
 */
STATIC void
wifi_append_freq(__unused gpointer key, gpointer value, gpointer user_data)
{
    GString* s = user_data;
    g_string_append_printf(s, "%d ", GPOINTER_TO_INT(value));
}

/**
 * append wowlan_triggers= string for wpa_supplicant.conf
 */
STATIC gboolean
append_wifi_wowlan_flags(NetplanWifiWowlanFlag flag, GString* str, GError** error) {
    if (flag & NETPLAN_WIFI_WOWLAN_TYPES[0].flag || flag >= NETPLAN_WIFI_WOWLAN_TCP) {
        g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED, "ERROR: unsupported wowlan_triggers mask: 0x%x\n", flag);
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
STATIC void
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
    if (def->match.mac) {
        /* LP: #1804861 and LP: #1888726:
         * Using bond, bridge, and VLAN devices results in sharing MAC
         * addresses across interfaces.  Match by PermanentMACAddress to match
         * only the real phy interface and to continue to match it even after
         * its MAC address has been changed.
         */
        g_string_append_printf(s, "PermanentMACAddress=%s\n", def->match.mac);
    }
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
}

STATIC void
write_bridge_params_networkd(GString* s, const NetplanNetDefinition* def)
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

STATIC void
write_tunnel_params(GString* s, const NetplanNetDefinition* def)
{
    GString *params = NULL;

    params = g_string_sized_new(200);

    g_string_printf(params, "Independent=true\n");
    if (def->tunnel.mode == NETPLAN_TUNNEL_MODE_IPIP6 || def->tunnel.mode == NETPLAN_TUNNEL_MODE_IP6IP6)
        g_string_append_printf(params, "Mode=%s\n", netplan_tunnel_mode_name(def->tunnel.mode));
    if (def->tunnel.local_ip)
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

STATIC void
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

    if (def->wireguard_peers) {
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
}

STATIC void
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
        !(_is_macaddress_special_nd_option(def->set_mac) && def->backend == NETPLAN_BACKEND_NETWORKD) &&
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

    if (_is_macaddress_special_nd_option(def->set_mac) && def->backend == NETPLAN_BACKEND_NETWORKD) {
        if (!g_strcmp0(def->set_mac, "permanent")) {
            /* "permanent" is used for both NM and ND, but the actual setting value for ND is "persistent" */
            g_string_append_printf(s, "MACAddressPolicy=persistent\n");
        } else {
            g_string_append_printf(s, "MACAddressPolicy=%s\n", def->set_mac);
        }
    }

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
    _netplan_g_string_free_to_file(s, rootdir, path, ".link");
    umask(orig_umask);
}

STATIC gboolean
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

    _netplan_g_string_free_to_file(s, rootdir, path, NULL);
    _netplan_safe_mkdir_p_dir(link);
    if (symlink(path, link) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_set_error(error, NETPLAN_FILE_ERROR, errno, "failed to create enablement symlink: %m\n");
        return FALSE;
        // LCOV_EXCL_STOP
    }
    return TRUE;
}


STATIC gboolean
interval_has_suffix(const char* param) {
    gchar* endptr;

    g_ascii_strtoull(param, &endptr, 10);
    if (*endptr == '\0')
        return FALSE;

    return TRUE;
}

STATIC gboolean
ra_overrides_is_dirty(const NetplanRAOverrides* overrides) {
    if(overrides->use_dns != NETPLAN_TRISTATE_UNSET)
        return TRUE;
    if(overrides->use_domains != NETPLAN_USE_DOMAIN_MODE_UNSET)
        return TRUE;
    if(overrides->table != NETPLAN_ROUTE_TABLE_UNSPEC)
        return TRUE;

    return FALSE;
}


STATIC void
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
    if (def->bond_params.all_members_active)
        g_string_append_printf(params, "\nAllSlavesActive=%d", def->bond_params.all_members_active); /* wokeignore:rule=slave */
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
    if (def->bond_params.packets_per_member)
        g_string_append_printf(params, "\nPacketsPerSlave=%d", def->bond_params.packets_per_member); /* wokeignore:rule=slave */
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

STATIC void
write_vxlan_parameters(const NetplanNetDefinition* def, GString* s)
{
    g_assert(def->vxlan);
    GString* params = NULL;

    params = g_string_sized_new(200);

    if (def->tunnel.remote_ip) {
        if (is_multicast_address(def->tunnel.remote_ip))
            g_string_append_printf(params, "\nGroup=%s", def->tunnel.remote_ip);
        else
            g_string_append_printf(params, "\nRemote=%s", def->tunnel.remote_ip);
    }
    if (def->tunnel.local_ip)
        g_string_append_printf(params, "\nLocal=%s", def->tunnel.local_ip);
    if (def->vxlan->tos)
        g_string_append_printf(params, "\nTOS=%d", def->vxlan->tos);
    if (def->tunnel_ttl)
        g_string_append_printf(params, "\nTTL=%d", def->tunnel_ttl);
    if (def->vxlan->mac_learning != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(params, "\nMacLearning=%s", def->vxlan->mac_learning ? "true" : "false");
    if (def->vxlan->ageing)
        g_string_append_printf(params, "\nFDBAgeingSec=%d", def->vxlan->ageing);
    if (def->vxlan->limit)
        g_string_append_printf(params, "\nMaximumFDBEntries=%d", def->vxlan->limit);
    if (def->vxlan->arp_proxy != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(params, "\nReduceARPProxy=%s", def->vxlan->arp_proxy ? "true" : "false");
    if (def->vxlan->notifications) {
        if (def->vxlan->notifications & NETPLAN_VXLAN_NOTIFICATION_L2_MISS)
            g_string_append(params, "\nL2MissNotification=true");
        if (def->vxlan->notifications & NETPLAN_VXLAN_NOTIFICATION_L3_MISS)
            g_string_append(params, "\nL3MissNotification=true");
    }
    if (def->vxlan->short_circuit != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(params, "\nRouteShortCircuit=%s", def->vxlan->short_circuit ? "true" : "false");
    if (def->vxlan->checksums) {
        if (def->vxlan->checksums & NETPLAN_VXLAN_CHECKSUM_UDP)
            g_string_append(params, "\nUDPChecksum=true");
        if (def->vxlan->checksums & NETPLAN_VXLAN_CHECKSUM_ZERO_UDP6_TX)
            g_string_append(params, "\nUDP6ZeroChecksumTx=true");
        if (def->vxlan->checksums & NETPLAN_VXLAN_CHECKSUM_ZERO_UDP6_RX)
            g_string_append(params, "\nUDP6ZeroChecksumRx=true");
        if (def->vxlan->checksums & NETPLAN_VXLAN_CHECKSUM_REMOTE_TX)
            g_string_append(params, "\nRemoteChecksumTx=true");
        if (def->vxlan->checksums & NETPLAN_VXLAN_CHECKSUM_REMOTE_RX)
            g_string_append(params, "\nRemoteChecksumRx=true");
    }
    if (def->vxlan->extensions) {
        if (def->vxlan->extensions & NETPLAN_VXLAN_EXTENSION_GROUP_POLICY)
            g_string_append(params, "\nGroupPolicyExtension=true");
        if (def->vxlan->extensions & NETPLAN_VXLAN_EXTENSION_GENERIC_PROTOCOL)
            g_string_append(params, "\nGenericProtocolExtension=true");
    }
    if (def->tunnel.port)
        g_string_append_printf(params, "\nDestinationPort=%d", def->tunnel.port);
    if (def->vxlan->source_port_min && def->vxlan->source_port_max)
        g_string_append_printf(params, "\nPortRange=%u-%u",
                               def->vxlan->source_port_min,
                               def->vxlan->source_port_max);
    if (def->vxlan->flow_label != G_MAXUINT)
        g_string_append_printf(params, "\nFlowLabel=%d", def->vxlan->flow_label);
    if (def->vxlan->do_not_fragment != NETPLAN_TRISTATE_UNSET)
        g_string_append_printf(params, "\nIPDoNotFragment=%s", def->vxlan->do_not_fragment ? "true" : "false");
    if (!def->vxlan->link)
        g_string_append(params, "\nIndependent=true");

    if (params->len)
        g_string_append_printf(s, "%s\n", params->str);

    g_string_free(params, TRUE);
}

STATIC void
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

    if (def->set_mac && _is_valid_macaddress(def->set_mac))
        g_string_append_printf(s, "MACAddress=%s\n", def->set_mac);
    if (def->mtubytes)
        g_string_append_printf(s, "MTUBytes=%u\n", def->mtubytes);

    switch (def->type) {
        case NETPLAN_DEF_TYPE_BRIDGE:
            g_string_append(s, "Kind=bridge\n");
            write_bridge_params_networkd(s, def);
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

        case NETPLAN_DEF_TYPE_DUMMY:                        /* wokeignore:rule=dummy */
            g_string_append_printf(s, "Kind=dummy\n");      /* wokeignore:rule=dummy */
            break;

        case NETPLAN_DEF_TYPE_VETH:
            /*
             * Only one .netdev file is required to create the veth pair.
             * To select what netdef we are going to use, we sort both names, get the first one,
             * and, if the selected name is the name of the netdef being written, we generate
             * the .netdev file. Otherwise we skip the netdef.
             */
            g_string_append_printf(s, "Kind=veth\n");
            if (def->veth_peer_link) {
                gchar* first = g_strcmp0(def->id, def->veth_peer_link->id) < 0 ? def->id : def->veth_peer_link->id;
                if (first != def->id) {
                    g_string_free(s, TRUE);
                    return;
                }
                g_string_append_printf(s, "\n[Peer]\nName=%s\n", def->veth_peer_link->id);
            }
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

                case NETPLAN_TUNNEL_MODE_VXLAN:
                    g_string_append_printf(s, "Kind=vxlan\n\n[VXLAN]\nVNI=%u", def->vxlan->vni);
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
            else if (def->tunnel.mode == NETPLAN_TUNNEL_MODE_VXLAN)
                write_vxlan_parameters(def, s);
            else
                write_tunnel_params(s, def);
            break;

        default: g_assert_not_reached(); // LCOV_EXCL_LINE
    }

    /* these do not contain secrets and need to be readable by
     * systemd-networkd - LP: #1736965 */
    orig_umask = umask(022);
    _netplan_g_string_free_to_file(s, rootdir, path, ".netdev");
    umask(orig_umask);
}

STATIC void
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
        g_string_append_printf(s, "Metric=%u\n", r->metric);
    if (r->table != NETPLAN_ROUTE_TABLE_UNSPEC)
        g_string_append_printf(s, "Table=%d\n", r->table);
    if (r->mtubytes != NETPLAN_MTU_UNSPEC)
        g_string_append_printf(s, "MTUBytes=%u\n", r->mtubytes);
    if (r->congestion_window != NETPLAN_CONGESTION_WINDOW_UNSPEC)
        g_string_append_printf(s, "InitialCongestionWindow=%u\n", r->congestion_window);
    if (r->advertised_receive_window != NETPLAN_ADVERTISED_RECEIVE_WINDOW_UNSPEC)
        g_string_append_printf(s, "InitialAdvertisedReceiveWindow=%u\n", r->advertised_receive_window);
}

STATIC void
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

STATIC void
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

STATIC gboolean
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
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "use-dns");
            return FALSE;
        }
        if (g_strcmp0(def->dhcp4_overrides.use_domains, def->dhcp6_overrides.use_domains) != 0){
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "use-domains");
            return FALSE;
        }
        if (def->dhcp4_overrides.use_ntp != def->dhcp6_overrides.use_ntp) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "use-ntp");
            return FALSE;
        }
        if (def->dhcp4_overrides.send_hostname != def->dhcp6_overrides.send_hostname) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "send-hostname");
            return FALSE;
        }
        if (def->dhcp4_overrides.use_hostname != def->dhcp6_overrides.use_hostname) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "use-hostname");
            return FALSE;
        }
        if (def->dhcp4_overrides.use_mtu != def->dhcp6_overrides.use_mtu) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "use-mtu");
            return FALSE;
        }
        if (g_strcmp0(def->dhcp4_overrides.hostname, def->dhcp6_overrides.hostname) != 0) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "hostname");
            return FALSE;
        }
        if (def->dhcp4_overrides.metric != def->dhcp6_overrides.metric) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "route-metric");
            return FALSE;
        }
        if (def->dhcp4_overrides.use_routes != def->dhcp6_overrides.use_routes) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, DHCP_OVERRIDES_ERROR, def->id, "use-routes");
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
_netplan_netdef_write_network_file(
        const NetplanState* np_state,
        const NetplanNetDefinition* def,
        const char *rootdir,
        const char* path,
        gboolean* has_been_written,
        GError** error)
{
    g_autoptr(GString) network = NULL;
    g_autoptr(GString) link = NULL;
    GString* s = NULL;
    mode_t orig_umask;

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
    }

    if (def->optional_addresses) {
        for (unsigned i = 0; NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name != NULL; ++i) {
            if (def->optional_addresses & NETPLAN_OPTIONAL_ADDRESS_TYPES[i].flag) {
            g_string_append_printf(link, "OptionalAddresses=%s\n", NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name);
            }
        }
    }

    if (def->mtubytes)
        g_string_append_printf(link, "MTUBytes=%u\n", def->mtubytes);
    if (def->set_mac && _is_valid_macaddress(def->set_mac))
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
        g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED, "ERROR: %s: ipv6-address-generation mode is not supported by networkd\n", def->id);
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

    if (def->critical)
        g_string_append_printf(network, "KeepConfiguration=true\n");

    if (def->bridge && def->backend != NETPLAN_BACKEND_OVS) {
        g_string_append_printf(network, "Bridge=%s\n", def->bridge);

        if (   def->bridge_params.path_cost
            || def->bridge_params.port_priority
            || def->bridge_hairpin != NETPLAN_TRISTATE_UNSET
            || def->bridge_learning != NETPLAN_TRISTATE_UNSET
            || def->bridge_neigh_suppress != NETPLAN_TRISTATE_UNSET)
            g_string_append_printf(network, "\n[Bridge]\n");
        if (def->bridge_params.path_cost)
            g_string_append_printf(network, "Cost=%u\n", def->bridge_params.path_cost);
        if (def->bridge_params.port_priority)
            g_string_append_printf(network, "Priority=%u\n", def->bridge_params.port_priority);
        if (def->bridge_hairpin != NETPLAN_TRISTATE_UNSET)
            g_string_append_printf(network, "HairPin=%s\n", def->bridge_hairpin ? "true" : "false");
        if (def->bridge_learning != NETPLAN_TRISTATE_UNSET)
            g_string_append_printf(network, "Learning=%s\n", def->bridge_learning ? "true" : "false");
        if (def->bridge_neigh_suppress != NETPLAN_TRISTATE_UNSET)
            g_string_append_printf(network, "NeighborSuppression=%s\n", def->bridge_neigh_suppress ? "true" : "false");

    }
    if (def->bond && def->backend != NETPLAN_BACKEND_OVS) {
        g_string_append_printf(network, "Bond=%s\n", def->bond);

        if (def->bond_params.primary_member)
            g_string_append_printf(network, "PrimarySlave=true\n"); /* wokeignore:rule=slave */
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

    /* VXLAN options */
    if (def->has_vxlans) {
        /* iterate over all netdefs to find VXLANs attached to us */
        GList *l = np_state->netdefs_ordered;
        const NetplanNetDefinition* nd;
        for (; l != NULL; l = l->next) {
            nd = l->data;
            if (nd->vxlan && nd->vxlan->link == def &&
                nd->type == NETPLAN_DEF_TYPE_TUNNEL &&
                nd->tunnel.mode == NETPLAN_TUNNEL_MODE_VXLAN)
                g_string_append_printf(network, "VXLAN=%s\n", nd->id);
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

    if (def->address_options) {
        for (unsigned i = 0; i < def->address_options->len; ++i) {
            NetplanAddressOptions* opts = g_array_index(def->address_options, NetplanAddressOptions*, i);
            write_addr_option(opts, network);
        }
    }

    if (def->dhcp4 || def->dhcp6) {
        /* NetworkManager compatible route metrics */
        g_string_append(network, "\n[DHCP]\n");
    }

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

    /* ra-overrides */
    if (ra_overrides_is_dirty(&def->ra_overrides)) {
        g_string_append(network, "\n[IPv6AcceptRA]\n");

        if (def->ra_overrides.use_dns != NETPLAN_TRISTATE_UNSET) {
            g_string_append_printf(network, "UseDNS=%s\n", def->ra_overrides.use_dns ? "true" : "false");
        }
        if (def->ra_overrides.use_domains == NETPLAN_USE_DOMAIN_MODE_FALSE) {
            g_string_append_printf(network, "UseDomains=%s\n", "false");
        } else if (def->ra_overrides.use_domains == NETPLAN_USE_DOMAIN_MODE_TRUE) {
            g_string_append_printf(network, "UseDomains=%s\n", "true");
        } else if (def->ra_overrides.use_domains == NETPLAN_USE_DOMAIN_MODE_ROUTE) {
            g_string_append_printf(network, "UseDomains=%s\n", "route");
        }
        if (def->ra_overrides.table != NETPLAN_ROUTE_TABLE_UNSPEC) {
            g_string_append_printf(network, "RouteTable=%d\n", def->ra_overrides.table);
        }
    }

    if (network->len > 0 || link->len > 0) {
        s = g_string_sized_new(200);
        append_match_section(def, s, TRUE);

        if (link->len > 0)
            g_string_append_printf(s, "\n[Link]\n%s", link->str);
        if (network->len > 0)
            g_string_append_printf(s, "\n[Network]\n%s", network->str);

        /* these do not contain secrets and need to be readable by
         * systemd-networkd - LP: #1736965 */
        orig_umask = umask(022);
        _netplan_g_string_free_to_file(s, rootdir, path, ".network");
        umask(orig_umask);
    }

    SET_OPT_OUT_PTR(has_been_written, TRUE);
    return TRUE;
}

STATIC void
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
    _netplan_g_string_free_to_file(s, rootdir, path, NULL);
    umask(orig_umask);
}

STATIC gboolean
append_wpa_auth_conf(GString* s, const NetplanAuthenticationSettings* auth, const char* id, GError** error)
{
    switch (auth->key_management) {
        case NETPLAN_AUTH_KEY_MANAGEMENT_NONE:
            g_string_append(s, "  key_mgmt=NONE\n");
            break;

        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK:
            if (auth->pmf_mode == NETPLAN_AUTH_PMF_MODE_OPTIONAL)
                /* Case where the user only provided the password.
                 * We enable support for WPA2 and WPA3 personal.
                 */
                g_string_append(s, "  key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE\n");
            else
                g_string_append(s, "  key_mgmt=WPA-PSK\n");
            break;

        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP:
            g_string_append(s, "  key_mgmt=WPA-EAP\n");
            break;

        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAPSHA256:
            g_string_append(s, "  key_mgmt=WPA-EAP WPA-EAP-SHA256\n");
            break;

        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAPSUITE_B_192:
            g_string_append(s, "  key_mgmt=WPA-EAP-SUITE-B-192\n");
            break;

        case NETPLAN_AUTH_KEY_MANAGEMENT_WPA_SAE:
            g_string_append(s, "  key_mgmt=SAE\n");
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

        case NETPLAN_AUTH_EAP_LEAP:
            g_string_append(s, "  eap=LEAP\n");
            break;

        case NETPLAN_AUTH_EAP_PWD:
            g_string_append(s, "  eap=PWD\n");
            break;

        default: break; // LCOV_EXCL_LINE
    }

    switch (auth->pmf_mode) {
        case NETPLAN_AUTH_PMF_MODE_NONE:
        case NETPLAN_AUTH_PMF_MODE_DISABLED:
            break;

        case NETPLAN_AUTH_PMF_MODE_OPTIONAL:
            g_string_append(s, "  ieee80211w=1\n");
            break;

        case NETPLAN_AUTH_PMF_MODE_REQUIRED:
            g_string_append(s, "  ieee80211w=2\n");
            break;
    }

    if (auth->identity) {
        g_string_append_printf(s, "  identity=\"%s\"\n", auth->identity);
    }
    if (auth->anonymous_identity) {
        g_string_append_printf(s, "  anonymous_identity=\"%s\"\n", auth->anonymous_identity);
    }

    char* psk = NULL;
    if (auth->psk)
        psk = auth->psk;
    else if (auth->password && _is_auth_key_management_psk(auth))
        psk = auth->password;

    if (psk) {
        size_t len = strlen(psk);
        if (len == 64) {
            /* must be a hex-digit key representation */
            for (unsigned i = 0; i < 64; ++i)
                if (!isxdigit(psk[i])) {
                    g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED, "ERROR: %s: PSK length of 64 is only supported for hex-digit representation\n", id);
                    return FALSE;
                }
            /* this is required to be unquoted */
            g_string_append_printf(s, "  psk=%s\n", psk);
        } else if (len < 8 || len > 63) {
            /* per wpa_supplicant spec, passphrase needs to be between 8 and 63 characters */
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, "ERROR: %s: ASCII passphrase must be between 8 and 63 characters (inclusive)\n", id);
            return FALSE;
        } else {
            g_string_append_printf(s, "  psk=\"%s\"\n", psk);
        }
    }

    if (auth->password
        && (!_is_auth_key_management_psk(auth) || auth->eap_method != NETPLAN_AUTH_EAP_NONE)) {
        if (strncmp(auth->password, "hash:", 5) == 0) {
            g_string_append_printf(s, "  password=%s\n", auth->password);
        } else {
            g_string_append_printf(s, "  password=\"%s\"\n", auth->password);
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
STATIC void
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
    _netplan_g_string_free_to_file(s, rootdir, path, NULL);
    umask(orig_umask);
}

STATIC gboolean
write_wpa_conf(const NetplanNetDefinition* def, const char* rootdir, GError** error)
{
    GHashTableIter iter;
    GString* s = g_string_new("ctrl_interface=/run/wpa_supplicant\n\n");
    g_autofree char* path = g_strjoin(NULL, "run/netplan/wpa-", def->id, ".conf", NULL);
    mode_t orig_umask;

    g_debug("%s: Creating wpa_supplicant configuration file %s", def->id, path);
    if (def->type == NETPLAN_DEF_TYPE_WIFI) {
        if (!def->access_points) {
            g_string_free(s, TRUE);
            return FALSE;
        }
        if (def->wowlan && def->wowlan > NETPLAN_WIFI_WOWLAN_DEFAULT) {
            g_string_append(s, "wowlan_triggers=");
            if (!append_wifi_wowlan_flags(def->wowlan, s, error)) {
                g_string_free(s, TRUE);
                return FALSE;
            }
        }
        /* available as of wpa_supplicant version 0.6.7 */
        if (def->regulatory_domain) {
            g_string_append_printf(s, "country=%s\n", def->regulatory_domain);
        }
        NetplanWifiAccessPoint* ap;
        g_hash_table_iter_init(&iter, def->access_points);
        while (g_hash_table_iter_next(&iter, NULL, (gpointer) &ap)) {
            gchar* freq_config_str = ap->mode == NETPLAN_WIFI_MODE_ADHOC ? "frequency" : "freq_list";

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
                    g_string_append_printf(s, "  %s=%d\n", freq_config_str, wifi_get_freq24(ap->channel));
                } else if (ap->mode != NETPLAN_WIFI_MODE_ADHOC) {
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
                    g_string_append_printf(s, "  %s=%d\n", freq_config_str, wifi_get_freq5(ap->channel));
                } else if (ap->mode != NETPLAN_WIFI_MODE_ADHOC) {
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
                    g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED, "ERROR: %s: %s: networkd does not support this wifi mode\n", def->id, ap->ssid);
                    g_string_free(s, TRUE);
                    return FALSE;
            }

            /* wifi auth trumps netdef auth */
            if (ap->has_auth) {
                if (!append_wpa_auth_conf(s, &ap->auth, ap->ssid, error)) {
                    g_string_free(s, TRUE);
                    return FALSE;
                }
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
        if (!append_wpa_auth_conf(s, &def->auth, def->id, error)) {
            g_string_free(s, TRUE);
            return FALSE;
        }
        g_string_append(s, "}\n");
    }

    /* use tight permissions as this contains secrets */
    orig_umask = umask(077);
    _netplan_g_string_free_to_file(s, rootdir, path, NULL);
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
gboolean
_netplan_netdef_write_networkd(
        const NetplanState* np_state,
        const NetplanNetDefinition* def,
        const char *rootdir,
        gboolean* has_been_written,
        GError** error)
{
    /* TODO: make use of netplan_netdef_get_output_filename() */
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
        g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED, "ERROR: %s: networkd backend does not support GSM/CDMA modem configuration\n", def->id);
        return FALSE;
    }

    if (def->type == NETPLAN_DEF_TYPE_WIFI || def->has_auth) {
        g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/systemd-networkd.service.wants/netplan-wpa-", def->id, ".service", NULL);
        g_autofree char* slink = g_strjoin(NULL, "/run/systemd/system/netplan-wpa-", def->id, ".service", NULL);
        if (def->type == NETPLAN_DEF_TYPE_WIFI && def->has_match) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED, "ERROR: %s: networkd backend does not support wifi with match:, only by interface name\n", def->id);
            return FALSE;
        }

        g_debug("Creating wpa_supplicant config");
        if (!write_wpa_conf(def, rootdir, error))
            return FALSE;

        g_debug("Creating wpa_supplicant unit %s", slink);
        write_wpa_unit(def, rootdir);

        g_debug("Creating wpa_supplicant service enablement link %s", link);
        _netplan_safe_mkdir_p_dir(link);

        if (symlink(slink, link) < 0 && errno != EEXIST) {
            // LCOV_EXCL_START
            g_set_error(error, NETPLAN_FILE_ERROR, errno, "failed to create enablement symlink: %m\n");
            return FALSE;
            // LCOV_EXCL_STOP
        }

    }

    if (def->set_mac &&
        !_is_valid_macaddress(def->set_mac) &&
        !_is_macaddress_special_nd_option(def->set_mac)) {
        g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED,
                    "ERROR: %s: networkd backend does not support the MAC address option '%s'\n",
                    def->id, def->set_mac);
        return FALSE;
    }

    if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL)
        write_netdev_file(def, rootdir, path_base);
    if (!_netplan_netdef_write_network_file(np_state, def, rootdir, path_base, has_been_written, error))
        return FALSE;
    SET_OPT_OUT_PTR(has_been_written, TRUE);
    return TRUE;
}

gboolean
_netplan_networkd_write_wait_online(const NetplanState* np_state, const char* rootdir)
{
    // Set of all current network interfaces, potentially non yet renamed
    GHashTable* system_interfaces = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    _netplan_query_system_interfaces(system_interfaces);

    // Hash set of non-optional interfaces to wait for
    GHashTable* non_optional_interfaces = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_free);
    NetplanStateIterator iter;
    netplan_state_iterator_init(np_state, &iter);
    while (netplan_state_iterator_has_next(&iter)) {
        NetplanNetDefinition* def = netplan_state_iterator_next(&iter);
        if (def->backend != NETPLAN_BACKEND_NETWORKD)
            continue;

        /* When activation-mode is used we default to being optional.
         * Otherwise, systemd might wait indefinitely for the interface to
         * come online.
         */
        if (!(def->optional || def->activation_mode)) {
            // Check if we have any IP configuration
            // bond and bridge members will never ask for link-local addresses (see above)
            struct address_iter* addr_iter = _netplan_netdef_new_address_iter(def);
            gboolean routable =   _netplan_address_iter_next(addr_iter) != NULL
                               || netplan_netdef_get_dhcp4(def)
                               || netplan_netdef_get_dhcp6(def);
            gboolean degraded =   (   netplan_netdef_get_link_local_ipv4(def)
                                   && !(netplan_netdef_get_bond_link(def) || netplan_netdef_get_bridge_link(def)))
                               || (   netplan_netdef_get_link_local_ipv6(def)
                                   && !(netplan_netdef_get_bond_link(def) || netplan_netdef_get_bridge_link(def)));
            gboolean any_ips = routable || degraded;
            _netplan_address_iter_free(addr_iter);

            // no matching => single physical interface, ignoring non-existing interfaces
            // OR: virtual interfaces, those will be created later on and cannot have a matching condition
            gboolean physical_no_match_or_virtual = FALSE
                || (!netplan_netdef_has_match(def) && g_hash_table_contains(system_interfaces, def->id))
                || (netplan_netdef_get_type(def) >= NETPLAN_DEF_TYPE_VIRTUAL);
            if (physical_no_match_or_virtual) {
                g_hash_table_replace(non_optional_interfaces, g_strdup(def->id), any_ips ? g_strdup("degraded") : g_strdup("carrier"));
            } else if (def->set_name) { // matching on a single interface, to be renamed
                 _netplan_enumerate_interfaces(def, system_interfaces, non_optional_interfaces, any_ips ? "degraded" : "carrier", def->set_name, rootdir);
            } else { // matching on potentially multiple interfaces
                // XXX: we shouldn't run this enumeration for every NetDef...
                _netplan_enumerate_interfaces(def, system_interfaces, non_optional_interfaces, any_ips ? "degraded" : "carrier", NULL, rootdir);
            }
        }
    }
    g_hash_table_destroy(system_interfaces);

    // create run/systemd/system/systemd-networkd-wait-online.service.d/
    const char* override = "/run/systemd/system/systemd-networkd-wait-online.service.d/10-netplan.conf";
    // The "ConditionPathIsSymbolicLink" is Netplan's s-n-wait-online enablement symlink,
    // as we want to run -wait-online only if enabled by Netplan.
    GString* content = g_string_new("[Unit]\n"
        "ConditionPathIsSymbolicLink=/run/systemd/generator/network-online.target.wants/systemd-networkd-wait-online.service\n");
    if (g_hash_table_size(non_optional_interfaces) == 0) {
        _netplan_g_string_free_to_file(content, rootdir, override, NULL);
        g_hash_table_destroy(non_optional_interfaces);
        return FALSE;
    }

    // We have non-optional interface, so let's wait for those explicitly
    GHashTableIter idx;
    gpointer key, value;
    g_string_append(content, "\n[Service]\nExecStart=\n"
                                "ExecStart=/lib/systemd/systemd-networkd-wait-online");
    g_hash_table_iter_init (&idx, non_optional_interfaces);
    while (g_hash_table_iter_next (&idx, &key, &value)) {
        const char* ifname = key;
        const char* min_oper_state = value;
        g_string_append_printf(content, " -i %s", ifname);
        // XXX: We should be checking IFF_LOOPBACK instead of interface name.
        //      But don't have access to the flags here.
        if (!g_strcmp0(ifname, "lo"))
            g_string_append(content, ":carrier"); // "carrier" as min-oper state for loopback
        else if (min_oper_state)
            g_string_append_printf(content, ":%s", min_oper_state);
    }
    g_string_append(content, "\n");

    _netplan_g_string_free_to_file(content, rootdir, override, NULL);
    g_hash_table_destroy(non_optional_interfaces);
    return TRUE;
}

/**
 * Clean up all generated configurations in @rootdir from previous runs.
 */
void
_netplan_networkd_cleanup(const char* rootdir)
{
    _netplan_unlink_glob(rootdir, "/run/systemd/network/10-netplan-*");
    _netplan_unlink_glob(rootdir, "/run/netplan/wpa-*.conf");
    _netplan_unlink_glob(rootdir, "/run/systemd/system/systemd-networkd.service.wants/netplan-wpa-*.service");
    _netplan_unlink_glob(rootdir, "/run/systemd/system/netplan-wpa-*.service");
    _netplan_unlink_glob(rootdir, "/run/udev/rules.d/99-netplan-*");
    _netplan_unlink_glob(rootdir, "/run/systemd/system/network.target.wants/netplan-regdom.service");
    _netplan_unlink_glob(rootdir, "/run/systemd/system/netplan-regdom.service");
    _netplan_unlink_glob(rootdir, "/run/systemd/system/systemd-networkd-wait-online.service.d/10-netplan*.conf");
}
