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

#pragma once

#include <uuid.h>
#include <yaml.h>

/****************************************************
 * Parsed definitions
 ****************************************************/

typedef enum {
    ND_NONE,
    /* physical devices */
    ND_ETHERNET,
    ND_WIFI,
    /* virtual devices */
    ND_VIRTUAL,
    ND_BRIDGE = ND_VIRTUAL,
    ND_BOND,
    ND_VLAN,
} netdef_type;

typedef enum {
    BACKEND_NONE,
    BACKEND_NETWORKD,
    BACKEND_NM,
    _BACKEND_MAX,
} netdef_backend;

static const char* const netdef_backend_to_name[_BACKEND_MAX] = {
        [BACKEND_NONE] = "none",
        [BACKEND_NETWORKD] = "networkd",
        [BACKEND_NM] = "NetworkManager",
};

typedef enum {
    ACCEPT_RA_KERNEL,
    ACCEPT_RA_ENABLED,
    ACCEPT_RA_DISABLED,
} ra_mode;

typedef struct missing_node {
    char* netdef_id;
    const yaml_node_t* node;
} missing_node;

/**
 * Represent a configuration stanza
 */
typedef struct net_definition {
    netdef_type type;
    netdef_backend backend;
    char* id;
    /* only necessary for NetworkManager connection UUIDs in some cases */
    uuid_t uuid;

    /* status options */
    gboolean optional;
    gboolean critical;

    /* addresses */
    gboolean dhcp4;
    gboolean dhcp6;
    char* dhcp_identifier;
    ra_mode accept_ra;
    GArray* ip4_addresses;
    GArray* ip6_addresses;
    char* gateway4;
    char* gateway6;
    GArray* ip4_nameservers;
    GArray* ip6_nameservers;
    GArray* search_domains;
    GArray* routes;
    GArray* ip_rules;

    /* master ID for slave devices */
    char* bridge;
    char* bond;

    /* vlan */
    guint vlan_id;
    struct net_definition* vlan_link;
    gboolean has_vlans;

    /* Configured custom MAC address */
    char* set_mac;

    /* interface mtu */
    guint mtubytes;

    /* these properties are only valid for physical interfaces (type < ND_VIRTUAL) */
    char* set_name;
    struct {
        char* driver;
        char* mac;
        char* original_name;
    } match;
    gboolean has_match;
    gboolean wake_on_lan;

    /* these properties are only valid for ND_WIFI */
    GHashTable* access_points; /* SSID → wifi_access_point* */

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
        guint gratuitious_arp;
        /* TODO: unsolicited_na */
        guint packets_per_slave;
        char* primary_reselect_policy;
        guint resend_igmp;
        char* learn_interval;
        char* primary_slave;
    } bond_params;

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

} net_definition;

typedef enum {
    WIFI_MODE_INFRASTRUCTURE,
    WIFI_MODE_ADHOC,
    WIFI_MODE_AP
} wifi_mode;

typedef struct {
    wifi_mode mode;
    char* ssid;
    char* password;
} wifi_access_point;

#define METRIC_UNSPEC G_MAXUINT
#define ROUTE_TABLE_UNSPEC 0
#define IP_RULE_PRIO_UNSPEC G_MAXUINT
#define IP_RULE_FW_MARK_UNSPEC 0
#define IP_RULE_TOS_UNSPEC G_MAXUINT

typedef struct {
    guint family;
    char* type;
    char* scope;
    guint table;

    char* from;
    char* to;
    char* via;

    gboolean onlink;

    /* valid metrics are valid positive integers.
     * invalid metrics are represented by METRIC_UNSPEC */
    guint metric;
} ip_route;

typedef struct {
    guint family;

    char* from;
    char* to;

    /* table: Valid values are 1 <= x <= 4294967295) */
    guint table;
    guint priority;
    /* fwmark: Valid values are 1 <= x <= 4294967295) */
    guint fwmark;
    /* type-of-service: between 0 and 255 */
    guint tos;
} ip_rule;

/* Written/updated by parse_yaml(): char* id →  net_definition */
extern GHashTable* netdefs;

/****************************************************
 * Functions
 ****************************************************/

gboolean parse_yaml(const char* filename, GError** error);
gboolean finish_parse(GError** error);
netdef_backend get_global_backend();
