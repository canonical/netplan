/*
 * Copyright (C) 2022 Canonical, Ltd.
 * Author: Lukas Märdian <slyon@ubuntu.com>
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

#pragma once
#include <glib.h>
#include <parse.h>
#include <uuid.h>

/* Those types are part of our ABI as they have been exposed in older versions */

typedef enum {
    NETPLAN_OPTIONAL_IPV4_LL = 1<<0,
    NETPLAN_OPTIONAL_IPV6_RA = 1<<1,
    NETPLAN_OPTIONAL_DHCP4   = 1<<2,
    NETPLAN_OPTIONAL_DHCP6   = 1<<3,
    NETPLAN_OPTIONAL_STATIC  = 1<<4,
} NetplanOptionalAddressFlag;

/* Fields below are valid for dhcp4 and dhcp6 unless otherwise noted. */
typedef struct dhcp_overrides {
    gboolean use_dns;
    gboolean use_ntp;
    gboolean send_hostname;
    gboolean use_hostname;
    gboolean use_mtu;
    gboolean use_routes;
    char* use_domains; /* netplan-feature: dhcp-use-domains */
    char* hostname;
    guint metric;
} NetplanDHCPOverrides;

typedef enum {
    NETPLAN_RA_MODE_KERNEL,
    NETPLAN_RA_MODE_ENABLED,
    NETPLAN_RA_MODE_DISABLED,
} NetplanRAMode;

typedef enum {
    NETPLAN_IB_MODE_KERNEL,
    NETPLAN_IB_MODE_DATAGRAM,
    NETPLAN_IB_MODE_CONNECTED,
} NetplanInfinibandMode;

typedef enum {
    NETPLAN_WIFI_WOWLAN_DEFAULT           = 1<<0,
    NETPLAN_WIFI_WOWLAN_ANY               = 1<<1,
    NETPLAN_WIFI_WOWLAN_DISCONNECT        = 1<<2,
    NETPLAN_WIFI_WOWLAN_MAGIC             = 1<<3,
    NETPLAN_WIFI_WOWLAN_GTK_REKEY_FAILURE = 1<<4,
    NETPLAN_WIFI_WOWLAN_EAP_IDENTITY_REQ  = 1<<5,
    NETPLAN_WIFI_WOWLAN_4WAY_HANDSHAKE    = 1<<6,
    NETPLAN_WIFI_WOWLAN_RFKILL_RELEASE    = 1<<7,
    NETPLAN_WIFI_WOWLAN_TCP               = 1<<8,
} NetplanWifiWowlanFlag;

struct NetplanWifiWowlanType {
    char* name;
    NetplanWifiWowlanFlag flag;
};

/* Tunnel mode enum; sync with NetworkManager's DBUS API */
/* TODO: figure out whether networkd's GRETAP and NM's ISATAP
 *       are the same thing.
 */
typedef enum {
    NETPLAN_TUNNEL_MODE_UNKNOWN     = 0,
    NETPLAN_TUNNEL_MODE_IPIP        = 1,
    NETPLAN_TUNNEL_MODE_GRE         = 2,
    NETPLAN_TUNNEL_MODE_SIT         = 3,
    NETPLAN_TUNNEL_MODE_ISATAP      = 4,  // NM only.
    NETPLAN_TUNNEL_MODE_VTI         = 5,
    NETPLAN_TUNNEL_MODE_IP6IP6      = 6,
    NETPLAN_TUNNEL_MODE_IPIP6       = 7,
    NETPLAN_TUNNEL_MODE_IP6GRE      = 8,
    NETPLAN_TUNNEL_MODE_VTI6        = 9,

    /* systemd-only, apparently? */
    NETPLAN_TUNNEL_MODE_GRETAP      = 101,
    NETPLAN_TUNNEL_MODE_IP6GRETAP   = 102,
    NETPLAN_TUNNEL_MODE_WIREGUARD   = 103,

    NETPLAN_TUNNEL_MODE_MAX_,
} NetplanTunnelMode;

typedef enum {
    NETPLAN_AUTH_KEY_MANAGEMENT_NONE,
    NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK,
    NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP,
    NETPLAN_AUTH_KEY_MANAGEMENT_8021X,
    NETPLAN_AUTH_KEY_MANAGEMENT_MAX,
} NetplanAuthKeyManagementType;

typedef enum {
    NETPLAN_AUTH_EAP_NONE,
    NETPLAN_AUTH_EAP_TLS,
    NETPLAN_AUTH_EAP_PEAP,
    NETPLAN_AUTH_EAP_TTLS,
    NETPLAN_AUTH_EAP_METHOD_MAX,
} NetplanAuthEAPMethod;

typedef struct authentication_settings {
    NetplanAuthKeyManagementType key_management;
    NetplanAuthEAPMethod eap_method;
    char* identity;
    char* anonymous_identity;
    char* password;
    char* ca_certificate;
    char* client_certificate;
    char* client_key;
    char* client_key_password;
    char* phase2_auth;  /* netplan-feature: auth-phase2 */
} NetplanAuthenticationSettings;

typedef struct ovs_controller {
    char* connection_mode;
    GArray* addresses;
} NetplanOVSController;

typedef struct ovs_settings {
    GHashTable* external_ids;
    GHashTable* other_config;
    char* lacp;
    char* fail_mode;
    gboolean mcast_snooping;
    GArray* protocols;
    gboolean rstp;
    NetplanOVSController controller;
    NetplanAuthenticationSettings ssl;
} NetplanOVSSettings;

typedef union {
    struct NetplanNMSettings {
        char *name;
        char *uuid;
        char *stable_id;
        char *device;
        GData* passthrough; /* See g_datalist* functions */
    } nm;
    struct NetplanNetworkdSettings {
        char *unit;
    } networkd;
} NetplanBackendSettings;

typedef enum
{
    /**
     * @brief Tristate enum type
     *
     * This type defines a boolean which can be unset, i.e.
     * this type has three states. The enum is ordered so
     * that
     *
     * UNSET -> -1
     * FALSE -> 0
     * TRUE  -> 1
     *
     * And the integer values can be used directly when
     * converting to string.
     */
    NETPLAN_TRISTATE_UNSET = -1, /* -1 */
    NETPLAN_TRISTATE_FALSE,      /*  0 */
    NETPLAN_TRISTATE_TRUE,       /*  1 */
} NetplanTristate;

/* Keep 'struct netplan_net_definition' in a separate header file, to allow for
 * abidiff to consider it "public API" (although it isn't) and notify us about
 * ABI compatibility issues. */
struct netplan_net_definition {
    NetplanDefType type;
    NetplanBackend backend;
    char* id;
    /* only necessary for NetworkManager connection UUIDs in some cases */
    uuid_t uuid;

    /* status options */
    gboolean optional;
    NetplanOptionalAddressFlag optional_addresses;
    gboolean critical;

    /* addresses */
    gboolean dhcp4;
    gboolean dhcp6;
    char* dhcp_identifier;
    NetplanDHCPOverrides dhcp4_overrides;
    NetplanDHCPOverrides dhcp6_overrides;
    NetplanRAMode accept_ra;
    GArray* ip4_addresses;
    GArray* ip6_addresses;
    GArray* address_options;
    gboolean ip6_privacy;
    guint ip6_addr_gen_mode;
    char* ip6_addr_gen_token;
    char* gateway4;
    char* gateway6;
    GArray* ip4_nameservers;
    GArray* ip6_nameservers;
    GArray* search_domains;
    GArray* routes;
    GArray* ip_rules;
    GArray* wireguard_peers;
    struct {
        gboolean ipv4;
        gboolean ipv6;
    } linklocal;

    /* master ID for slave devices */
    char* bridge;
    char* bond;

    /* peer ID for OVS patch ports */
    char* peer;

    /* vlan */
    guint vlan_id;
    NetplanNetDefinition* vlan_link;
    gboolean has_vlans;

    /* Configured custom MAC address */
    char* set_mac;

    /* interface mtu */
    guint mtubytes;
    /* ipv6 mtu */
    /* netplan-feature: ipv6-mtu */
    guint ipv6_mtubytes;

    /* these properties are only valid for physical interfaces (type < ND_VIRTUAL) */
    char* set_name;
    struct {
        /* A glob (or tab-separated list of globs) to match a specific driver */
        char* driver;
        char* mac;
        char* original_name;
    } match;
    gboolean has_match;
    gboolean wake_on_lan;
    NetplanWifiWowlanFlag wowlan;
    gboolean emit_lldp;

    /* these properties are only valid for NETPLAN_DEF_TYPE_WIFI */
    GHashTable* access_points; /* SSID → NetplanWifiAccessPoint* */

    struct {
        char* mode;
        char* lacp_rate;
        char* monitor_interval;
        guint min_links;
        char* transmit_hash_policy;
        char* selection_logic;
        gboolean all_slaves_active;
        char* arp_interval;
        GArray* arp_ip_targets;
        char* arp_validate;
        char* arp_all_targets;
        char* up_delay;
        char* down_delay;
        char* fail_over_mac_policy;
        guint gratuitous_arp;
        /* TODO: unsolicited_na */
        guint packets_per_slave;
        char* primary_reselect_policy;
        guint resend_igmp;
        char* learn_interval;
        char* primary_slave;
    } bond_params;

    /* netplan-feature: modems */
    struct {
        char* apn;
        gboolean auto_config;
        char* device_id;
        char* network_id;
        char* number;
        char* password;
        char* pin;
        char* sim_id;
        char* sim_operator_id;
        char* username;
    } modem_params;

    struct {
        char* ageing_time;
        guint priority;
        guint port_priority;
        char* forward_delay;
        char* hello_time;
        char* max_age;
        guint path_cost;
        gboolean stp;
    } bridge_params;
    gboolean custom_bridging;

    struct {
        NetplanTunnelMode mode;
        char *local_ip;
        char *remote_ip;
        char *input_key;
        char *output_key;
        char *private_key; /* used for wireguard */
        guint fwmark;
        guint port;
    } tunnel;

    NetplanAuthenticationSettings auth;
    gboolean has_auth;

    /* these properties are only valid for SR-IOV NICs */
    /* netplan-feature: sriov */
    struct netplan_net_definition* sriov_link;
    gboolean sriov_vlan_filter;
    guint sriov_explicit_vf_count;

    /* these properties are only valid for OpenVSwitch */
    /* netplan-feature: openvswitch */
    NetplanOVSSettings ovs_settings;

    NetplanBackendSettings backend_settings;

    char* filepath;
    /* it cannot be in the tunnel struct: https://github.com/canonical/netplan/pull/206 */
    guint tunnel_ttl;

    /* netplan-feature: activation-mode */
    char* activation_mode;

    /* configure without carrier */
    gboolean ignore_carrier;

    /* offload options */
    NetplanTristate receive_checksum_offload;
    NetplanTristate transmit_checksum_offload;
    NetplanTristate tcp_segmentation_offload;
    NetplanTristate tcp6_segmentation_offload;
    NetplanTristate generic_segmentation_offload;
    NetplanTristate generic_receive_offload;
    NetplanTristate large_receive_offload;

    struct private_netdef_data* _private;

    /* netplan-feature: eswitch-mode */
    char* embedded_switch_mode;
    gboolean sriov_delay_virtual_functions_rebind;

    /* netplan-feature: infiniband */
    NetplanInfinibandMode ib_mode; /* IPoIB */

    /* netplan-feature: regdom */
    char* regulatory_domain;

    /* vrf */
    /* netplan-feature: vrf */
    NetplanNetDefinition* vrf_link;
    guint vrf_table;
};
