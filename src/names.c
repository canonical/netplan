/*
 * Copyright (C) 2021 Canonical, Ltd.
 * Author: Simon Chopin <simon.chopin@canonical.com>
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

#include "names.h"
#include "parse.h"

/* Non-static as we need it for ABI compatibility, see at the end of the file */
const char* const
netplan_backend_to_str[NETPLAN_BACKEND_MAX_] = {
    [NETPLAN_BACKEND_NONE] = "none",
    [NETPLAN_BACKEND_NETWORKD] = "networkd",
    [NETPLAN_BACKEND_NM] = "NetworkManager",
    [NETPLAN_BACKEND_OVS] = "OpenVSwitch",
};

static const char* const
netplan_wifi_mode_to_str[NETPLAN_WIFI_MODE_MAX_] = {
    [NETPLAN_WIFI_MODE_INFRASTRUCTURE] = "infrastructure",
    [NETPLAN_WIFI_MODE_ADHOC] = "adhoc",
    [NETPLAN_WIFI_MODE_AP] = "ap",
    [NETPLAN_WIFI_MODE_OTHER] = NULL,
};


static const char* const
netplan_def_type_to_str[NETPLAN_DEF_TYPE_MAX_] = {
    [NETPLAN_DEF_TYPE_NONE] = NULL,
    [NETPLAN_DEF_TYPE_ETHERNET] = "ethernets",
    [NETPLAN_DEF_TYPE_WIFI] = "wifis",
    [NETPLAN_DEF_TYPE_MODEM] = "modems",
    [NETPLAN_DEF_TYPE_BRIDGE] = "bridges",
    [NETPLAN_DEF_TYPE_BOND] = "bonds",
    [NETPLAN_DEF_TYPE_VLAN] = "vlans",
    [NETPLAN_DEF_TYPE_VRF] = "vrfs",
    [NETPLAN_DEF_TYPE_TUNNEL] = "tunnels",
    [NETPLAN_DEF_TYPE_PORT] = "_ovs-ports",
    [NETPLAN_DEF_TYPE_NM] = "nm-devices",
};

static const char* const
netplan_auth_key_management_type_to_str[NETPLAN_AUTH_KEY_MANAGEMENT_MAX] = {
    [NETPLAN_AUTH_KEY_MANAGEMENT_NONE] = "none",
    [NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK] = "psk",
    [NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP] = "eap",
    [NETPLAN_AUTH_KEY_MANAGEMENT_8021X] = "802.1x",
};

static const char* const
netplan_auth_eap_method_to_str[NETPLAN_AUTH_EAP_METHOD_MAX] = {
    [NETPLAN_AUTH_EAP_NONE] = NULL,
    [NETPLAN_AUTH_EAP_TLS] = "tls",
    [NETPLAN_AUTH_EAP_PEAP] = "peap",
    [NETPLAN_AUTH_EAP_TTLS] = "ttls",
};

static const char* const
netplan_tunnel_mode_to_str[NETPLAN_TUNNEL_MODE_MAX_] = {
    [NETPLAN_TUNNEL_MODE_UNKNOWN] = NULL,
    [NETPLAN_TUNNEL_MODE_IPIP] = "ipip",
    [NETPLAN_TUNNEL_MODE_GRE] = "gre",
    [NETPLAN_TUNNEL_MODE_SIT] = "sit",
    [NETPLAN_TUNNEL_MODE_ISATAP] = "isatap",
    [NETPLAN_TUNNEL_MODE_VTI] = "vti",
    [NETPLAN_TUNNEL_MODE_IP6IP6] = "ip6ip6",
    [NETPLAN_TUNNEL_MODE_IPIP6] = "ipip6",
    [NETPLAN_TUNNEL_MODE_IP6GRE] = "ip6gre",
    [NETPLAN_TUNNEL_MODE_VTI6] = "vti6",
    [NETPLAN_TUNNEL_MODE_GRETAP] = "gretap",
    [NETPLAN_TUNNEL_MODE_IP6GRETAP] = "ip6gretap",
    [NETPLAN_TUNNEL_MODE_WIREGUARD] = "wireguard",
};

static const char* const
netplan_addr_gen_mode_to_str[NETPLAN_ADDRGEN_MAX] = {
    [NETPLAN_ADDRGEN_DEFAULT] = NULL,
    [NETPLAN_ADDRGEN_EUI64] = "eui64",
    [NETPLAN_ADDRGEN_STABLEPRIVACY] = "stable-privacy"
};

static const char* const
netplan_infiniband_mode_to_str[NETPLAN_ADDRGEN_MAX] = {
    [NETPLAN_IB_MODE_KERNEL] = NULL,
    [NETPLAN_IB_MODE_DATAGRAM] = "datagram",
    [NETPLAN_IB_MODE_CONNECTED] = "connected"
};

#define NAME_FUNCTION(_radical, _type) const char *netplan_ ## _radical ## _name( _type val) \
{ \
    return (val < sizeof( netplan_ ## _radical ## _to_str )) ?  netplan_ ## _radical ## _to_str [val] : NULL; \
}

NAME_FUNCTION(backend, NetplanBackend);
NAME_FUNCTION(def_type, NetplanDefType);
NAME_FUNCTION(auth_key_management_type, NetplanAuthKeyManagementType);
NAME_FUNCTION(auth_eap_method, NetplanAuthEAPMethod);
NAME_FUNCTION(tunnel_mode, NetplanTunnelMode);
NAME_FUNCTION(addr_gen_mode, NetplanAddrGenMode);
NAME_FUNCTION(wifi_mode, NetplanWifiMode);
NAME_FUNCTION(infiniband_mode, NetplanInfinibandMode);

#define ENUM_FUNCTION(_radical, _type) _type netplan_ ## _radical ## _from_name(const char* val) \
{ \
    for (int i = 0; i < sizeof(netplan_ ## _radical ## _to_str); ++i) { \
        if (g_strcmp0(val, netplan_ ## _radical ## _to_str[i]) == 0) \
            return i; \
    } \
    return -1; \
}

ENUM_FUNCTION(def_type, NetplanDefType);

/* ABI compatibility definitions */

NETPLAN_ABI const char*
tunnel_mode_to_string(NetplanTunnelMode val) __attribute__ ((alias ("netplan_tunnel_mode_name")));

NETPLAN_ABI extern const char*
netplan_backend_to_name __attribute__((alias("netplan_backend_to_str")));
