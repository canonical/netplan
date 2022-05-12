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

/* This module contains functions to deal with the Netplan objects,
 * notably, accessors and destructors. Note that types specific to parsing
 * are implemented separately.
 */

#include <glib.h>
#include "types.h"
#include "util-internal.h"

#define FREE_AND_NULLIFY(ptr) { g_free(ptr); ptr = NULL; }

/* Helper function to free a GArray after applying a destructor to its
 * elements. Note that in the most trivial case (g_free) we should probably
 * have used a GPtrArray directly... */
static void
free_garray_with_destructor(GArray** array, void (destructor)(void *))
{
    if (*array) {
        for (size_t i = 0; i < (*array)->len; ++i) {
            void* ptr = g_array_index(*array, char*, i);
            destructor(ptr);
        }
        g_array_free(*array, TRUE);
        *array = NULL;
    }
}

/* Helper function to free a GHashTable after applying a simple destructor to its
 * elements. */
static void
free_hashtable_with_destructor(GHashTable** hash, void (destructor)(void *)) {
    if (*hash) {
        GHashTableIter iter;
        gpointer key, value;
        g_hash_table_iter_init(&iter, *hash);
        while (g_hash_table_iter_next(&iter, &key, &value))
            destructor(value);
        g_hash_table_destroy(*hash);
        *hash = NULL;
    }
}

static void
free_address_options(void* ptr)
{
    NetplanAddressOptions* opts = ptr;
    g_free(opts->address);
    g_free(opts->label);
    g_free(opts->lifetime);
    g_free(opts);
}

static void
free_route(void* ptr)
{
    NetplanIPRoute* route = ptr;
    g_free(route->scope);
    g_free(route->type);
    g_free(route->to);
    g_free(route->from);
    g_free(route->via);
    g_free(route);
}

static void
free_ip_rules(void* ptr)
{
    NetplanIPRule* rule = ptr;
    g_free(rule->to);
    g_free(rule->from);
    g_free(rule);
}

static void
free_wireguard_peer(void* ptr)
{
    NetplanWireguardPeer* wg = ptr;
    g_free(wg->endpoint);
    g_free(wg->preshared_key);
    g_free(wg->public_key);
    free_garray_with_destructor(&wg->allowed_ips, g_free);
    g_free(wg);
}

static void
reset_auth_settings(NetplanAuthenticationSettings* auth)
{
    FREE_AND_NULLIFY(auth->identity);
    FREE_AND_NULLIFY(auth->anonymous_identity);
    FREE_AND_NULLIFY(auth->password);
    FREE_AND_NULLIFY(auth->ca_certificate);
    FREE_AND_NULLIFY(auth->client_certificate);
    FREE_AND_NULLIFY(auth->client_key);
    FREE_AND_NULLIFY(auth->client_key_password);
    FREE_AND_NULLIFY(auth->phase2_auth);
    auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_NONE;
    auth->eap_method = NETPLAN_AUTH_EAP_NONE;
}

void
reset_ovs_settings(NetplanOVSSettings* settings)
{
    settings->mcast_snooping = FALSE;
    settings->rstp = FALSE;

    free_hashtable_with_destructor(&settings->external_ids, g_free);
    free_hashtable_with_destructor(&settings->other_config, g_free);

    FREE_AND_NULLIFY(settings->lacp);
    FREE_AND_NULLIFY(settings->fail_mode);

    free_garray_with_destructor(&settings->protocols, g_free);
    reset_auth_settings(&settings->ssl);

    free_garray_with_destructor(&settings->controller.addresses, g_free);
    FREE_AND_NULLIFY(settings->controller.connection_mode);
}

static void
reset_dhcp_overrides(NetplanDHCPOverrides* overrides)
{
    overrides->use_dns = TRUE;
    FREE_AND_NULLIFY(overrides->use_domains);
    overrides->use_ntp = TRUE;
    overrides->send_hostname = TRUE;
    overrides->use_hostname = TRUE;
    overrides->use_mtu = TRUE;
    overrides->use_routes = TRUE;
    FREE_AND_NULLIFY(overrides->hostname);
    overrides->metric = NETPLAN_METRIC_UNSPEC;
}

void
reset_ip_rule(NetplanIPRule* ip_rule)
{
    ip_rule->family = G_MAXUINT; /* 0 is a valid family ID */
    ip_rule->priority = NETPLAN_IP_RULE_PRIO_UNSPEC;
    ip_rule->table = NETPLAN_ROUTE_TABLE_UNSPEC;
    ip_rule->tos = NETPLAN_IP_RULE_TOS_UNSPEC;
    ip_rule->fwmark = NETPLAN_IP_RULE_FW_MARK_UNSPEC;
}

/* Reset a backend settings object. The caller needs to specify the actual backend as it is not
 * contained within the object itself! */
static void
reset_backend_settings(NetplanBackendSettings* settings, NetplanBackend backend)
{
    switch (backend) {
        case NETPLAN_BACKEND_NETWORKD:
            FREE_AND_NULLIFY(settings->networkd.unit);
            break;
        case NETPLAN_BACKEND_NM:
            FREE_AND_NULLIFY(settings->nm.name);
            FREE_AND_NULLIFY(settings->nm.uuid);
            FREE_AND_NULLIFY(settings->nm.stable_id);
            FREE_AND_NULLIFY(settings->nm.device);
            g_datalist_clear(&settings->nm.passthrough);
            break;
        default:
            break;
    }
}

static void
reset_private_netdef_data(struct private_netdef_data* data) {
    if (!data)
        return;
    if (data->dirty_fields)
        g_hash_table_destroy(data->dirty_fields);
    data->dirty_fields = NULL;
}

/* Free a heap-allocated NetplanWifiAccessPoint object.
 * Signature made to match the g_hash_table_foreach function.
 * @key: ignored
 * @value: pointer to a heap-allocated NetlpanWifiAccessPoint object
 * @data: pointer to a NetplanBackend value representing the renderer context in which
 *        to interpret the processed object, especially regarding the backend settings
 */
static void
free_access_point(void* key, void* value, void* data)
{
    NetplanWifiAccessPoint* ap = value;
    g_free(ap->ssid);
    g_free(ap->bssid);
    reset_auth_settings(&ap->auth);
    reset_backend_settings(&ap->backend_settings, *((NetplanBackend *)data));
    g_free(ap);
}

/* Reset a given network definition to its initial state, releasing any owned data */
void
reset_netdef(NetplanNetDefinition* netdef, NetplanDefType new_type, NetplanBackend new_backend) {
    /* Needed for some cleanups down the line */
    NetplanBackend backend = netdef->backend;

    netdef->type = new_type;
    netdef->backend = new_backend;
    FREE_AND_NULLIFY(netdef->id);
    memset(netdef->uuid, 0, sizeof(netdef->uuid));

    netdef->optional = FALSE;
    netdef->optional_addresses = 0;
    netdef->critical = FALSE;

    netdef->dhcp4 = FALSE;
    netdef->dhcp6 = FALSE;

    FREE_AND_NULLIFY(netdef->dhcp_identifier);

    reset_dhcp_overrides(&netdef->dhcp4_overrides);
    reset_dhcp_overrides(&netdef->dhcp6_overrides);
    netdef->accept_ra = NETPLAN_RA_MODE_KERNEL;

    free_garray_with_destructor(&netdef->ip4_addresses, g_free);
    free_garray_with_destructor(&netdef->ip6_addresses, g_free);
    free_garray_with_destructor(&netdef->address_options, free_address_options);

    netdef->ip6_privacy = FALSE;
    netdef->ip6_addr_gen_mode = NETPLAN_ADDRGEN_DEFAULT;
    FREE_AND_NULLIFY(netdef->ip6_addr_gen_token);

    FREE_AND_NULLIFY(netdef->gateway4);
    FREE_AND_NULLIFY(netdef->gateway6);
    free_garray_with_destructor(&netdef->ip4_nameservers, g_free);
    free_garray_with_destructor(&netdef->ip6_nameservers, g_free);
    free_garray_with_destructor(&netdef->search_domains, g_free);
    free_garray_with_destructor(&netdef->routes, free_route);
    free_garray_with_destructor(&netdef->ip_rules, free_ip_rules);
    free_garray_with_destructor(&netdef->wireguard_peers, free_wireguard_peer);

    netdef->linklocal.ipv4 = FALSE;
    netdef->linklocal.ipv6 = TRUE;

    FREE_AND_NULLIFY(netdef->bridge);
    FREE_AND_NULLIFY(netdef->bond);

    FREE_AND_NULLIFY(netdef->peer);

    netdef->vlan_id = G_MAXUINT; /* 0 is a valid ID */
    netdef->vlan_link = NULL;
    netdef->has_vlans = FALSE;

    FREE_AND_NULLIFY(netdef->set_mac);
    netdef->mtubytes = 0;
    netdef->ipv6_mtubytes = 0;

    FREE_AND_NULLIFY(netdef->set_name);
    FREE_AND_NULLIFY(netdef->match.driver);
    FREE_AND_NULLIFY(netdef->match.mac);
    FREE_AND_NULLIFY(netdef->match.original_name);
    netdef->has_match = FALSE;
    netdef->wake_on_lan = FALSE;
    netdef->wowlan = 0;
    netdef->emit_lldp = FALSE;

    if (netdef->access_points) {
        g_hash_table_foreach(netdef->access_points, free_access_point, &backend);
        g_hash_table_destroy(netdef->access_points);
        netdef->access_points = NULL;
    }

    FREE_AND_NULLIFY(netdef->bond_params.mode);
    FREE_AND_NULLIFY(netdef->bond_params.lacp_rate);
    FREE_AND_NULLIFY(netdef->bond_params.monitor_interval);
    FREE_AND_NULLIFY(netdef->bond_params.transmit_hash_policy);
    FREE_AND_NULLIFY(netdef->bond_params.selection_logic);
    FREE_AND_NULLIFY(netdef->bond_params.arp_interval);
    free_garray_with_destructor(&netdef->bond_params.arp_ip_targets, g_free);
    FREE_AND_NULLIFY(netdef->bond_params.arp_validate);
    FREE_AND_NULLIFY(netdef->bond_params.arp_all_targets);
    FREE_AND_NULLIFY(netdef->bond_params.up_delay);
    FREE_AND_NULLIFY(netdef->bond_params.down_delay);
    FREE_AND_NULLIFY(netdef->bond_params.fail_over_mac_policy);
    FREE_AND_NULLIFY(netdef->bond_params.primary_reselect_policy);
    FREE_AND_NULLIFY(netdef->bond_params.learn_interval);
    FREE_AND_NULLIFY(netdef->bond_params.primary_slave);
    memset(&netdef->bond_params, 0, sizeof(netdef->bond_params));

    FREE_AND_NULLIFY(netdef->modem_params.apn);
    FREE_AND_NULLIFY(netdef->modem_params.device_id);
    FREE_AND_NULLIFY(netdef->modem_params.network_id);
    FREE_AND_NULLIFY(netdef->modem_params.number);
    FREE_AND_NULLIFY(netdef->modem_params.password);
    FREE_AND_NULLIFY(netdef->modem_params.pin);
    FREE_AND_NULLIFY(netdef->modem_params.sim_id);
    FREE_AND_NULLIFY(netdef->modem_params.sim_operator_id);
    FREE_AND_NULLIFY(netdef->modem_params.username);
    memset(&netdef->modem_params, 0, sizeof(netdef->modem_params));

    FREE_AND_NULLIFY(netdef->bridge_params.ageing_time);
    FREE_AND_NULLIFY(netdef->bridge_params.forward_delay);
    FREE_AND_NULLIFY(netdef->bridge_params.hello_time);
    FREE_AND_NULLIFY(netdef->bridge_params.max_age);
    memset(&netdef->bridge_params, 0, sizeof(netdef->bridge_params));
    netdef->custom_bridging = FALSE;

    FREE_AND_NULLIFY(netdef->tunnel.local_ip);
    FREE_AND_NULLIFY(netdef->tunnel.remote_ip);
    FREE_AND_NULLIFY(netdef->tunnel.input_key);
    FREE_AND_NULLIFY(netdef->tunnel.output_key);
    FREE_AND_NULLIFY(netdef->tunnel.private_key);
    memset(&netdef->tunnel, 0, sizeof(netdef->tunnel));
    netdef->tunnel.mode = NETPLAN_TUNNEL_MODE_UNKNOWN;

    reset_auth_settings(&netdef->auth);
    netdef->has_auth = FALSE;

    netdef->sriov_link = NULL;
    netdef->sriov_vlan_filter = FALSE;
    netdef->sriov_explicit_vf_count = G_MAXUINT; /* 0 is a valid number of VFs */

    reset_ovs_settings(&netdef->ovs_settings);
    reset_backend_settings(&netdef->backend_settings, backend);

    FREE_AND_NULLIFY(netdef->filepath);
    netdef->tunnel_ttl = 0;
    FREE_AND_NULLIFY(netdef->activation_mode);
    netdef->ignore_carrier = FALSE;

    netdef->receive_checksum_offload = FALSE;
    netdef->transmit_checksum_offload = FALSE;
    netdef->tcp_segmentation_offload = FALSE;
    netdef->tcp6_segmentation_offload = FALSE;
    netdef->generic_segmentation_offload = FALSE;
    netdef->generic_receive_offload = FALSE;
    netdef->large_receive_offload = FALSE;

    reset_private_netdef_data(netdef->_private);
    FREE_AND_NULLIFY(netdef->_private);

    netdef->receive_checksum_offload = NETPLAN_TRISTATE_UNSET;
    netdef->transmit_checksum_offload = NETPLAN_TRISTATE_UNSET;
    netdef->tcp_segmentation_offload = NETPLAN_TRISTATE_UNSET;
    netdef->tcp6_segmentation_offload = NETPLAN_TRISTATE_UNSET;
    netdef->generic_segmentation_offload = NETPLAN_TRISTATE_UNSET;
    netdef->generic_receive_offload = NETPLAN_TRISTATE_UNSET;
    netdef->large_receive_offload = NETPLAN_TRISTATE_UNSET;
}

static void
clear_netdef_from_list(void *def)
{
    reset_netdef((NetplanNetDefinition *)def, NETPLAN_DEF_TYPE_NONE, NETPLAN_BACKEND_NONE);
    g_free(def);
}

NetplanState*
netplan_state_new()
{
    NetplanState* np_state = g_new0(NetplanState, 1);
    netplan_state_reset(np_state);
    return np_state;
}

void
netplan_state_clear(NetplanState** np_state_p)
{
    g_assert(np_state_p);
    NetplanState* np_state = *np_state_p;
    *np_state_p = NULL;
    netplan_state_reset(np_state);
    g_free(np_state);
}

void
netplan_state_reset(NetplanState* np_state)
{
    g_assert(np_state != NULL);

    /* As stated in the netplan_state definition, netdefs_ordered is the collection
     * owning the allocated definitions, whereas netdefs only has "weak" pointers.
     * As such, we can destroy it without having to worry about freeing memory.
     */
    if(np_state->netdefs) {
        g_hash_table_destroy(np_state->netdefs);
        np_state->netdefs = NULL;
    }

    /* Here on the contrary we have to release the memory */
    if(np_state->netdefs_ordered) {
        g_clear_list(&np_state->netdefs_ordered, clear_netdef_from_list);
        np_state->netdefs_ordered = NULL;
    }

    np_state->backend = NETPLAN_BACKEND_NONE;
    reset_ovs_settings(&np_state->ovs_settings);

    if (np_state->sources) {
        /* Properly configured at creation to clean up after itself. */
        g_hash_table_destroy(np_state->sources);
        np_state->sources = NULL;
    }
}

NetplanBackend
netplan_state_get_backend(const NetplanState* np_state)
{
    g_assert(np_state);
    return np_state->backend;
}

guint
netplan_state_get_netdefs_size(const NetplanState* np_state)
{
    g_assert(np_state);
    return np_state->netdefs ? g_hash_table_size(np_state->netdefs) : 0;
}

void
access_point_clear(NetplanWifiAccessPoint** ap, NetplanBackend backend)
{
    NetplanWifiAccessPoint* obj = *ap;
    if (!obj)
        return;
    *ap = NULL;
    free_access_point(NULL, obj, &backend);
}

#define CLEAR_FROM_FREE(free_fn, clear_fn, type) void clear_fn(type** dest) \
{ \
    type* obj; \
    if (!dest || !(*dest)) return; \
    obj = *dest; \
    *dest = NULL; \
    free_fn(obj);\
}

CLEAR_FROM_FREE(free_wireguard_peer, wireguard_peer_clear, NetplanWireguardPeer);
CLEAR_FROM_FREE(free_ip_rules, ip_rule_clear, NetplanIPRule);
CLEAR_FROM_FREE(free_route, route_clear, NetplanIPRoute);
CLEAR_FROM_FREE(free_address_options, address_options_clear, NetplanAddressOptions);

NetplanNetDefinition*
netplan_state_get_netdef(const NetplanState* np_state, const char* id)
{
    g_assert(np_state);
    if (!np_state->netdefs)
        return NULL;
    return g_hash_table_lookup(np_state->netdefs, id);
}

NETPLAN_PUBLIC ssize_t
netplan_netdef_get_filepath(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buf_size)
{
    g_assert(netdef);
    return netplan_copy_string(netdef->filepath, out_buffer, out_buf_size);
}

NETPLAN_INTERNAL const char*
netplan_netdef_get_id(const NetplanNetDefinition* netdef)
{
    g_assert(netdef);
    return netdef->id;
}

NETPLAN_INTERNAL const char*
_netplan_netdef_id(NetplanNetDefinition* netdef) __attribute__((alias("netplan_netdef_get_id")));

gboolean
netplan_state_has_nondefault_globals(const NetplanState* np_state)
{
        return (np_state->backend != NETPLAN_BACKEND_NONE)
                || has_openvswitch(&np_state->ovs_settings, NETPLAN_BACKEND_NONE, NULL);
}

NETPLAN_INTERNAL const char*
netplan_netdef_get_embedded_switch_mode(const NetplanNetDefinition* netdef)
{
    g_assert(netdef);
    return netdef->embedded_switch_mode;
}

NETPLAN_INTERNAL gboolean
netplan_netdef_get_delay_virtual_functions_rebind(const NetplanNetDefinition* netdef)
{
    g_assert(netdef);
    return netdef->sriov_delay_virtual_functions_rebind;
}
