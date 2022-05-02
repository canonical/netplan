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

#pragma once

#include "parse.h"
#include <glib.h>
#include <yaml.h>
#include <uuid.h>

/* Quite a few types are part of our current ABI, and so were isolated
 * in order to make it easier to tell what's fair game and allow for ABI
 * compatibility checks using 'abidiff' (abigail-tools). */
#include "abi.h"

typedef enum {
    NETPLAN_ADDRGEN_DEFAULT,
    NETPLAN_ADDRGEN_EUI64,
    NETPLAN_ADDRGEN_STABLEPRIVACY,
    NETPLAN_ADDRGEN_MAX,
} NetplanAddrGenMode;

struct NetplanOptionalAddressType {
    char* name;
    NetplanOptionalAddressFlag flag;
};

// Not strictly speaking a type, but seems fair to keep it around.
extern struct NetplanOptionalAddressType NETPLAN_OPTIONAL_ADDRESS_TYPES[];

extern struct NetplanWifiWowlanType NETPLAN_WIFI_WOWLAN_TYPES[];

typedef struct missing_node {
    char* netdef_id;
    const yaml_node_t* node;
} NetplanMissingNode;

struct private_netdef_data {
    GHashTable* dirty_fields;
};

typedef enum {
    NETPLAN_WIFI_MODE_INFRASTRUCTURE,
    NETPLAN_WIFI_MODE_ADHOC,
    NETPLAN_WIFI_MODE_AP,
    NETPLAN_WIFI_MODE_OTHER,
    NETPLAN_WIFI_MODE_MAX_
} NetplanWifiMode;

typedef struct {
    char *endpoint;
    char *public_key;
    char *preshared_key;
    GArray *allowed_ips;
    guint keepalive;
} NetplanWireguardPeer;

typedef enum {
    NETPLAN_WIFI_BAND_DEFAULT,
    NETPLAN_WIFI_BAND_5,
    NETPLAN_WIFI_BAND_24
} NetplanWifiBand;

typedef struct {
    char* address;
    char* lifetime;
    char* label;
} NetplanAddressOptions;

typedef struct {
    NetplanWifiMode mode;
    char* ssid;
    NetplanWifiBand band;
    char* bssid;
    gboolean hidden;
    guint channel;

    NetplanAuthenticationSettings auth;
    gboolean has_auth;

    NetplanBackendSettings backend_settings;
} NetplanWifiAccessPoint;

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

    guint mtubytes;
    guint congestion_window;
    guint advertised_receive_window;
} NetplanIPRoute;

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
} NetplanIPRule;

struct netplan_state {
    /* Since both netdefs and netdefs_ordered store pointers to the same elements,
     * we consider that only netdefs_ordered is owner of this data. One should not
     * free() objects obtained from netdefs, and proper care should be taken to remove
     * any reference of an object in netdefs when destroying it from netdefs_ordered.
     */
    GHashTable *netdefs;
    GList *netdefs_ordered;
    NetplanBackend backend;
    NetplanOVSSettings ovs_settings;

    /* Hashset of the source files used to create this state. Owns its data (glib-allocated
     * char*) and is initialized with g_hash_table_new_full to avoid leaks. */
    GHashTable* sources;
};

struct netplan_parser {
    yaml_document_t doc;
    /* Netplan definitions that have already been processed.
     * Weak references to the nedefs */
    GHashTable* parsed_defs;
    /* Same definitions, stored in the order of processing.
     * Owning structure for the netdefs */
    GList* ordered;
    NetplanBackend global_backend;
    NetplanOVSSettings global_ovs_settings;

    /* Keep track of the files used as data source */
    GHashTable* sources;

    /* Data currently being processed */
    struct {
        /* Refs to objects allocated elsewhere */
        NetplanNetDefinition* netdef;
        NetplanAuthenticationSettings *auth;

        /* Owned refs, not yet referenced anywhere */
        NetplanWifiAccessPoint *access_point;
        NetplanWireguardPeer* wireguard_peer;
        NetplanAddressOptions* addr_options;
        NetplanIPRoute* route;
        NetplanIPRule* ip_rule;
        const char *filepath;

        /* Plain old data representing the backend for which we are
         * currently parsing. Not necessarily the same as the global
         * backend. */
        NetplanBackend backend;
    } current;

    /* List of "seen" ids not found in netdefs yet by the parser.
     * These are removed when it exists in this list and we reach the point of
     * creating a netdef for that id; so by the time we're done parsing the yaml
     * document it should be empty.
     *
     * Keys are not owned, but the values are. Should be created with NULL and g_free
     * destructors, respectively, so that the cleanup is automatic at destruction.
     */
    GHashTable* missing_id;

    /* Set of IDs in currently parsed YAML file, for being able to detect
     * "duplicate ID within one file" vs. allowing a drop-in to override/amend an
     * existing definition.
     *
     * Appears to be unused?
     * */
    GHashTable* ids_in_file;
    int missing_ids_found;

    /* Which fields have been nullified by a subsequent patch? */
    GHashTable* null_fields;
};

#define NETPLAN_ADVERTISED_RECEIVE_WINDOW_UNSPEC 0
#define NETPLAN_CONGESTION_WINDOW_UNSPEC 0
#define NETPLAN_MTU_UNSPEC 0
#define NETPLAN_METRIC_UNSPEC G_MAXUINT
#define NETPLAN_ROUTE_TABLE_UNSPEC 0
#define NETPLAN_IP_RULE_PRIO_UNSPEC G_MAXUINT
#define NETPLAN_IP_RULE_FW_MARK_UNSPEC 0
#define NETPLAN_IP_RULE_TOS_UNSPEC G_MAXUINT

void
reset_netdef(NetplanNetDefinition* netdef, NetplanDefType type, NetplanBackend renderer);

void
reset_ip_rule(NetplanIPRule* ip_rule);

void
reset_ovs_settings(NetplanOVSSettings *settings);

void
access_point_clear(NetplanWifiAccessPoint** ap, NetplanBackend backend);

void
wireguard_peer_clear(NetplanWireguardPeer** peer);

void
address_options_clear(NetplanAddressOptions** options);

void
ip_rule_clear(NetplanIPRule** rule);

void
route_clear(NetplanIPRoute** route);

gboolean
netplan_state_has_nondefault_globals(const NetplanState* np_state);
