/*
 * Copyright (C) 2018,2019,2020 Cumulus Networks Inc.
 * Author: Julien Fortin <julien@cumulusnetworks.com>
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

#include <time.h>
#include <unistd.h>
#include <glib.h>
#include <glib/gprintf.h>

#include "util.h"
#include "ifupdown2.h"

static GList* stanza_list = NULL;
static GHashTable* _masters_slaves = NULL;
static const char* ENI = "/etc/network/interfaces";

const char* get_ifupdown2_eni_path(const char* rootdir)
{
    return g_strjoin(NULL, rootdir ?: "", ENI, NULL);
}

static void prepare_ifupdown2_conf_init_stanza(NetplanNetDefinition* def, GString* s)
{
    gboolean dhcp = FALSE;

    if (def->dhcp4) {
        g_string_append_printf(s, "auto %s\niface %s inet dhcp\n", def->id, def->id);
        dhcp = TRUE;
    }

    if (def->dhcp6) {
        g_string_append_printf(s, "auto %s\niface %s inet6 dhcp\n", def->id, def->id);
        dhcp = TRUE;
    }

    if (dhcp == FALSE) {
        if (!strcmp(def->id, "lo"))
            g_string_append_printf(s, "auto %s\niface %s inet loopback\n", def->id, def->id);
        else
            g_string_append_printf(s, "auto %s\niface %s\n", def->id, def->id);
    }
}

static void prepare_ifupdown2_conf_addresses(NetplanNetDefinition* def, GString* s)
{
    if (def->ip4_addresses)
        for (unsigned i = 0; i < def->ip4_addresses->len; ++i)
            g_string_append_printf(s, "\taddress %s\n", g_array_index(def->ip4_addresses, char*, i));
    if (def->ip6_addresses)
        for (unsigned i = 0; i < def->ip6_addresses->len; ++i)
            g_string_append_printf(s, "\taddress %s\n", g_array_index(def->ip6_addresses, char*, i));

    if (def->gateway4)
        g_string_append_printf(s, "\tgateway %s\n", def->gateway4);

    if (def->gateway6)
        g_string_append_printf(s, "\tgateway %s\n", def->gateway6);

    if (def->set_mac)
        g_string_append_printf(s, "\thwaddress %s\n", def->set_mac);

    if (def->mtubytes)
        g_string_append_printf(s, "\tmtu %u\n", def->mtubytes);
}

static void prepare_ifupdown2_conf_bridge(NetplanNetDefinition* def, GString* s)
{
    GList* slaves_list = g_hash_table_lookup(_masters_slaves, (char*) def->id);

    g_string_append_printf(s, "\tbridge-ports");
    if (slaves_list) {
        for (; slaves_list; slaves_list = slaves_list->next) {
            g_string_append_printf(s, " %s", (char*) slaves_list->data);
        }
        g_string_append_printf(s, "\n");
    } else
        g_string_append_printf(s, " None\n");

    if (def->bridge_params.ageing_time)
        g_string_append_printf(s, "\tbridge-ageing %s\n", def->bridge_params.ageing_time);

    if (def->bridge_params.priority)
        g_string_append_printf(s, "\tbridge-bridgeprio %d\n", def->bridge_params.priority);

    if (def->bridge_params.port_priority)
        g_string_append_printf(s, "\tbridge-portprios %d\n", def->bridge_params.port_priority);

    if (def->bridge_params.forward_delay)
        g_string_append_printf(s, "\tbridge-fd %s\n", def->bridge_params.forward_delay);

    if (def->bridge_params.hello_time)
        g_string_append_printf(s, "\tbridge-hello %s\n", def->bridge_params.hello_time);

    if (def->bridge_params.max_age)
        g_string_append_printf(s, "\tbridge-maxage %s\n", def->bridge_params.max_age);

    if (def->bridge_params.path_cost)
        g_string_append_printf(s, "\tbridge-pathcosts %d\n", def->bridge_params.path_cost);

    if (def->bridge_params.stp)
        g_string_append_printf(s, "\tbridge-stp yes\n");
}

static void prepare_ifupdown2_conf_tunnel(NetplanNetDefinition* def, GString* s)
{
    g_string_append_printf(s, "\ttunnel-mode %s\n", netplan_tunnel_mode_table[def->tunnel.mode]);

    if (def->tunnel.local_ip)
        g_string_append_printf(s, "\ttunnel-local %s\n", def->tunnel.local_ip);

    if (def->tunnel.remote_ip)
        g_string_append_printf(s, "\ttunnel-endpoint %s\n", def->tunnel.remote_ip);
}

static void prepare_ifupdown2_conf_vlan(NetplanNetDefinition* def, GString* s)
{
    g_string_append_printf(s, "\tvlan-id %u\n", def->vlan_id);

    if (def->vlan_link)
        g_string_append_printf(s, "\tvlan-raw-device %s\n", def->vlan_link->id);
}

static void prepare_ifupdown2_conf_bond(NetplanNetDefinition* def, GString* s)
{
    GList* slaves_list = g_hash_table_lookup(_masters_slaves, (char*) def->id);

    g_string_append_printf(s, "\tbond-slaves");
    if (slaves_list) {
        for (; slaves_list; slaves_list = slaves_list->next) {
            g_string_append_printf(s, " %s", (char*) slaves_list->data);
        }
        g_string_append_printf(s, "\n");
    } else
        g_string_append_printf(s, " None\n");

    if (def->bond_params.mode)
        g_string_append_printf(s, "\tbond-mode %s\n", def->bond_params.mode);

    if (def->bond_params.lacp_rate)
        g_string_append_printf(s, "\tbond-lacp-rate %s\n", def->bond_params.lacp_rate);

    if (def->bond_params.monitor_interval)
        g_string_append_printf(s, "\tbond-miimon %s\n", def->bond_params.monitor_interval);

    if (def->bond_params.min_links)
        g_string_append_printf(s, "\tbond-min-links %d\n", def->bond_params.min_links);

    if (def->bond_params.transmit_hash_policy)
        g_string_append_printf(s, "\tbond-xmit-hash-policy %s\n", def->bond_params.transmit_hash_policy);

    if (def->bond_params.up_delay)
        g_string_append_printf(s, "\tbond-updelay %s\n", def->bond_params.up_delay);

    if (def->bond_params.down_delay)
        g_string_append_printf(s, "\tbond-downdelay %s\n", def->bond_params.down_delay);

    if (def->bond_params.gratuitous_arp)
        g_string_append_printf(s, "\tbond-num-grat-arp %d\n", def->bond_params.gratuitous_arp);

    if (def->bond_params.primary_reselect_policy)
        g_string_append_printf(s, "\tbond-primary-reselect %s\n", def->bond_params.primary_reselect_policy);

    if (def->bond_params.primary_slave)
        g_string_append_printf(s, "\tbond-primary %s\n", def->bond_params.primary_slave);
}

void prepare_ifupdown2_conf(NetplanNetDefinition* def, const char* rootdir)
{
    if (def->backend != NETPLAN_BACKEND_IFUPDOWN2) {
        g_debug("ifupdown2: definition %s is not for us (backend %i)", def->id, def->backend);
        return;
    }

    GString* s = g_string_new(NULL);

    if (!_masters_slaves)
        _masters_slaves = g_hash_table_new(g_str_hash, g_str_equal);

    char* master = NULL;

    if (def->bond)
        master = def->bond;
    else if (def->bridge)
        master = def->bridge;

    if (master) {
        // we need to save this slave (def->id) in the masters_slaves hashtable
        g_hash_table_insert(_masters_slaves, master, g_list_append(g_hash_table_lookup(_masters_slaves, master), def->id));
    }

    // Init stanza (auto, iface etc...)
    prepare_ifupdown2_conf_init_stanza(def, s);

    // Handle address configuration
    prepare_ifupdown2_conf_addresses(def, s);

    // Handle virtual device configuration
    if (def->type >= NETPLAN_DEF_TYPE_VIRTUAL) {
        switch (def->type) {
            case NETPLAN_DEF_TYPE_BRIDGE:
                prepare_ifupdown2_conf_bridge(def, s);
                break;

            case NETPLAN_DEF_TYPE_BOND:
                prepare_ifupdown2_conf_bond(def, s);
                break;

            case NETPLAN_DEF_TYPE_VLAN:
                prepare_ifupdown2_conf_vlan(def, s);
                break;

            case NETPLAN_DEF_TYPE_TUNNEL:
                prepare_ifupdown2_conf_tunnel(def, s);
                break;

            default:
                g_debug("%s: ifupdown2 does not support setting NetplanDefType %d.", def->id, def->type);
        }
    }
    stanza_list = g_list_append(stanza_list, s);
}

static char* get_time()
{
    time_t current_time = time(NULL);

    if (current_time == ((time_t) - 1))
        return NULL;

    return ctime(&current_time);
}

void write_ifupdown2_conf(const char* rootdir)
{
    GString* content = g_string_new("# This file has been auto-generated by netplan's ifupdown2 backend\n");
    g_string_append_printf(content, "# Backend version: 0.1.0\n");
    g_string_append_printf(content, "# Date: %s", get_time()); // ctime already adds a \n

    GList* tmp = stanza_list;
    for (; tmp != NULL; tmp = tmp->next) {
        char* stanza = g_string_free(tmp->data, FALSE);

        if (stanza)
            g_string_append_printf(content, "\n%s", stanza);

        free(stanza);
    }

    g_string_free_to_file(content, rootdir, ENI, NULL);
    stanza_list = NULL;
}

void cleanup_ifupdown2_conf(const char* rootdir)
{
    unlink(get_ifupdown2_eni_path(rootdir));
    g_list_free(stanza_list);
    stanza_list = NULL;
}
