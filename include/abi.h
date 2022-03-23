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

#include "../src/types.h"

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

    char* filename;
    /* it cannot be in the tunnel struct: https://github.com/canonical/netplan/pull/206 */
    guint tunnel_ttl;

    /* netplan-feature: activation-mode */
    char* activation_mode;

    /* configure without carrier */
    gboolean ignore_carrier;

    /* offload options */
    gboolean receive_checksum_offload;
    gboolean transmit_checksum_offload;
    gboolean tcp_segmentation_offload;
    gboolean tcp6_segmentation_offload;
    gboolean generic_segmentation_offload;
    gboolean generic_receive_offload;
    gboolean large_receive_offload;

    struct private_netdef_data* _private;

    /* netplan-feature: eswitch-mode */
    char* embedded_switch_mode;
    gboolean sriov_delay_virtual_functions_rebind;
};
