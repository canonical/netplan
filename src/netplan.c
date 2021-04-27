/*
 * Copyright (C) 2021 Canonical, Ltd.
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

#include <glib.h>
#include <yaml.h>

#include "netplan.h"
#include "parse.h"

static gboolean
write_match(yaml_event_t* event, yaml_emitter_t* emitter, const NetplanNetDefinition* def)
{
    YAML_SCALAR_PLAIN(event, emitter, "match");
    YAML_MAPPING_OPEN(event, emitter);
    YAML_STRING(event, emitter, "name", def->match.original_name);
    YAML_STRING(event, emitter, "macaddress", def->match.mac)
    YAML_STRING(event, emitter, "driver", def->match.driver)
    YAML_MAPPING_CLOSE(event, emitter);
    return TRUE;
error: return FALSE; // LCOV_EXCL_LINE
}

static gboolean
write_auth(yaml_event_t* event, yaml_emitter_t* emitter, NetplanAuthenticationSettings auth)
{
    YAML_SCALAR_PLAIN(event, emitter, "auth");
    YAML_MAPPING_OPEN(event, emitter);
    YAML_STRING(event, emitter, "key-management", netplan_auth_key_management_type_to_str[auth.key_management]);
    YAML_STRING(event, emitter, "method", netplan_auth_eap_method_to_str[auth.eap_method]);
    YAML_STRING(event, emitter, "anonymous-identity", auth.anonymous_identity);
    YAML_STRING(event, emitter, "identity", auth.identity);
    YAML_STRING(event, emitter, "ca-certificate", auth.ca_certificate);
    YAML_STRING(event, emitter, "client-certificate", auth.client_certificate);
    YAML_STRING(event, emitter, "client-key", auth.client_key);
    YAML_STRING(event, emitter, "client-key-password", auth.client_key_password);
    YAML_STRING(event, emitter, "phase2-auth", auth.phase2_auth);
    YAML_STRING(event, emitter, "password", auth.password);
    YAML_MAPPING_CLOSE(event, emitter);
    return TRUE;
error: return FALSE; // LCOV_EXCL_LINE
}

static gboolean
write_bond_params(yaml_event_t* event, yaml_emitter_t* emitter, const NetplanNetDefinition* def)
{
    if (def->bond_params.mode
        || def->bond_params.monitor_interval
        || def->bond_params.up_delay
        || def->bond_params.down_delay
        || def->bond_params.lacp_rate
        || def->bond_params.transmit_hash_policy
        || def->bond_params.selection_logic
        || def->bond_params.arp_validate
        || def->bond_params.arp_all_targets
        || def->bond_params.fail_over_mac_policy
        || def->bond_params.primary_reselect_policy
        || def->bond_params.learn_interval
        || def->bond_params.arp_interval
        || def->bond_params.primary_slave
        || def->bond_params.min_links
        || def->bond_params.all_slaves_active
        || def->bond_params.gratuitous_arp
        || def->bond_params.packets_per_slave
        || def->bond_params.resend_igmp
        || def->bond_params.arp_ip_targets) {
        YAML_SCALAR_PLAIN(event, emitter, "parameters");
        YAML_MAPPING_OPEN(event, emitter);
        YAML_STRING(event, emitter, "mode", def->bond_params.mode);
        YAML_STRING_PLAIN(event, emitter, "mii-monitor-interval", def->bond_params.monitor_interval);
        YAML_STRING_PLAIN(event, emitter, "up-delay", def->bond_params.up_delay);
        YAML_STRING_PLAIN(event, emitter, "down-delay", def->bond_params.down_delay);
        YAML_STRING_PLAIN(event, emitter, "lacp-rate", def->bond_params.lacp_rate);
        YAML_STRING(event, emitter, "transmit-hash-policy", def->bond_params.transmit_hash_policy);
        YAML_STRING(event, emitter, "ad-select", def->bond_params.selection_logic);
        YAML_STRING(event, emitter, "arp-validate", def->bond_params.arp_validate);
        YAML_STRING(event, emitter, "arp-all-targets", def->bond_params.arp_all_targets);
        YAML_STRING(event, emitter, "fail-over-mac-policy", def->bond_params.fail_over_mac_policy);
        YAML_STRING(event, emitter, "primary-reselect-policy", def->bond_params.primary_reselect_policy);
        YAML_STRING_PLAIN(event, emitter, "learn-packet-interval", def->bond_params.learn_interval);
        YAML_STRING_PLAIN(event, emitter, "arp-interval", def->bond_params.arp_interval);
        YAML_STRING(event, emitter, "primary", def->bond_params.primary_slave);
        if (def->bond_params.min_links)
            YAML_STRING_PLAIN(event, emitter, "min-links", g_strdup_printf("%u", def->bond_params.min_links)); //XXX: free the strdup'ed string
        if (def->bond_params.all_slaves_active)
            YAML_STRING_PLAIN(event, emitter, "all-slaves-active", "true");
        if (def->bond_params.gratuitous_arp)
            YAML_STRING_PLAIN(event, emitter, "gratuitous-arp", g_strdup_printf("%u", def->bond_params.gratuitous_arp)); //XXX: free the strdup'ed string
        if (def->bond_params.packets_per_slave)
            YAML_STRING_PLAIN(event, emitter, "packets-per-slave", g_strdup_printf("%u", def->bond_params.packets_per_slave)); //XXX: free the strdup'ed string
        if (def->bond_params.resend_igmp)
            YAML_STRING_PLAIN(event, emitter, "resend-igmp", g_strdup_printf("%u", def->bond_params.resend_igmp)); //XXX: free the strdup'ed string
        if (def->bond_params.arp_ip_targets) {
            YAML_SCALAR_PLAIN(event, emitter, "arp-ip-targets");
            YAML_SEQUENCE_OPEN(event, emitter);
            for (unsigned i = 0; i < def->bond_params.arp_ip_targets->len; ++i)
                YAML_SCALAR_PLAIN(event, emitter, g_array_index(def->bond_params.arp_ip_targets, char*, i));
            YAML_SEQUENCE_CLOSE(event, emitter);
        }
        YAML_MAPPING_CLOSE(event, emitter);
    }
    return TRUE;
error: return FALSE; // LCOV_EXCL_LINE
}

static gboolean
write_bridge_params(yaml_event_t* event, yaml_emitter_t* emitter, const NetplanNetDefinition* def, const GArray *interfaces)
{
    if (def->bridge_params.ageing_time
        || def->bridge_params.priority
        || def->bridge_params.port_priority
        || def->bridge_params.forward_delay
        || def->bridge_params.hello_time
        || def->bridge_params.max_age
        || def->bridge_params.path_cost
        || def->bridge_params.stp) {
        YAML_SCALAR_PLAIN(event, emitter, "parameters");
        YAML_MAPPING_OPEN(event, emitter);
        YAML_STRING_PLAIN(event, emitter, "ageing-time", def->bridge_params.ageing_time);
        YAML_STRING_PLAIN(event, emitter, "forward-delay", def->bridge_params.forward_delay);
        YAML_STRING_PLAIN(event, emitter, "hello-time", def->bridge_params.hello_time);
        YAML_STRING_PLAIN(event, emitter, "max-age", def->bridge_params.max_age);
        if (def->bridge_params.priority)
            YAML_STRING_PLAIN(event, emitter, "priority", g_strdup_printf("%u", def->bridge_params.priority)); //XXX: free the strdup'ed string
        if (def->bridge_params.stp)
            YAML_STRING_PLAIN(event, emitter, "stp", "true");

        YAML_SCALAR_PLAIN(event, emitter, "port-priority");
        YAML_MAPPING_OPEN(event, emitter);
        for (unsigned i = 0; i < interfaces->len; ++i) {
            NetplanNetDefinition *nd = g_array_index(interfaces, NetplanNetDefinition*, i);
            if (nd->bridge_params.port_priority) {
                YAML_STRING_PLAIN(event, emitter, nd->id, g_strdup_printf("%u", nd->bridge_params.port_priority)); //XXX: free the strdup'ed string
            }
        }
        YAML_MAPPING_CLOSE(event, emitter);

        YAML_SCALAR_PLAIN(event, emitter, "path-cost");
        YAML_MAPPING_OPEN(event, emitter);
        for (unsigned i = 0; i < interfaces->len; ++i) {
            NetplanNetDefinition *nd = g_array_index(interfaces, NetplanNetDefinition*, i);
            if (nd->bridge_params.path_cost) {
                YAML_STRING_PLAIN(event, emitter, nd->id, g_strdup_printf("%u", nd->bridge_params.path_cost)); //XXX: free the strdup'ed string
            }
        }
        YAML_MAPPING_CLOSE(event, emitter);

        YAML_MAPPING_CLOSE(event, emitter);
    }
    return TRUE;
error: return FALSE; // LCOV_EXCL_LINE
}

typedef struct {
    yaml_event_t* event;
    yaml_emitter_t* emitter;
} _passthrough_handler_data;

static void
_passthrough_handler(GQuark key_id, gpointer value, gpointer user_data)
{
    _passthrough_handler_data *d = user_data;
    const gchar* key = g_quark_to_string(key_id);
    YAML_SCALAR_PLAIN(d->event, d->emitter, key);
    YAML_SCALAR_QUOTED(d->event, d->emitter, value);
error: return; // LCOV_EXCL_LINE
}

static gboolean
write_backend_settings(yaml_event_t* event, yaml_emitter_t* emitter, NetplanBackendSettings s) {
    if (s.nm.uuid || s.nm.name || s.nm.passthrough) {
        YAML_SCALAR_PLAIN(event, emitter, "networkmanager");
        YAML_MAPPING_OPEN(event, emitter);
        if (s.nm.uuid) {
            YAML_SCALAR_PLAIN(event, emitter, "uuid");
            YAML_SCALAR_PLAIN(event, emitter, s.nm.uuid);
        }
        if (s.nm.name) {
            YAML_SCALAR_PLAIN(event, emitter, "name");
            YAML_SCALAR_QUOTED(event, emitter, s.nm.name);
        }
        if (s.nm.passthrough) {
            YAML_SCALAR_PLAIN(event, emitter, "passthrough");
            YAML_MAPPING_OPEN(event, emitter);
            _passthrough_handler_data d;
            d.event = event;
            d.emitter = emitter;
            g_datalist_foreach(&s.nm.passthrough, _passthrough_handler, &d);
            YAML_MAPPING_CLOSE(event, emitter);
        }
        YAML_MAPPING_CLOSE(event, emitter);
    }
    return TRUE;
error: return FALSE; // LCOV_EXCL_LINE
}

static gboolean
write_access_points(yaml_event_t* event, yaml_emitter_t* emitter, const NetplanNetDefinition* def)
{
    NetplanWifiAccessPoint* ap = NULL;
    GHashTableIter iter;
    gpointer key, value;
    YAML_SCALAR_PLAIN(event, emitter, "access-points");
    YAML_MAPPING_OPEN(event, emitter);
    g_hash_table_iter_init(&iter, def->access_points);
    while (g_hash_table_iter_next(&iter, &key, &value)) {
        ap = value;
        YAML_SCALAR_QUOTED(event, emitter, ap->ssid);
        YAML_MAPPING_OPEN(event, emitter);
        if (ap->hidden)
            YAML_STRING_PLAIN(event, emitter, "hidden", "true");
        YAML_STRING(event, emitter, "bssid", ap->bssid);
        if (ap->band == NETPLAN_WIFI_BAND_5) {
            YAML_STRING_PLAIN(event, emitter, "band", "5GHz");
        } else if (ap->band == NETPLAN_WIFI_BAND_24) {
            YAML_STRING_PLAIN(event, emitter, "band", "2.4GHz");
        }
        if (ap->channel)
            YAML_STRING_PLAIN(event, emitter, "channel", g_strdup_printf("%u", ap->channel)); // XXX: free strdup'ed string
        if (ap->has_auth)
            write_auth(event, emitter, ap->auth);
        YAML_SCALAR_PLAIN(event, emitter, "mode");
        if (ap->mode != NETPLAN_WIFI_MODE_OTHER) {
            YAML_SCALAR_PLAIN(event, emitter, netplan_wifi_mode_to_str[ap->mode]);
        } else {
            // LCOV_EXCL_START
            g_warning("netplan: serialize: %s (SSID %s), unsupported AP mode, falling back to 'infrastructure'", def->id, ap->ssid);
            YAML_SCALAR_PLAIN(event, emitter, "infrastructure"); //TODO: add YAML comment about unsupported mode
            // LCOV_EXCL_STOP
        }
        if (!write_backend_settings(event, emitter, ap->backend_settings)) goto error;
        YAML_MAPPING_CLOSE(event, emitter);
    }
    YAML_MAPPING_CLOSE(event, emitter);
    return TRUE;
error: return FALSE; // LCOV_EXCL_LINE
}

void
_serialize_yaml(yaml_event_t* event, yaml_emitter_t* emitter, const NetplanNetDefinition* def)
{
    gchar *tmp = NULL;
    GArray* tmp_arr = NULL;
    GHashTableIter iter;
    gpointer key, value;


    YAML_SCALAR_PLAIN(event, emitter, def->id);
    YAML_MAPPING_OPEN(event, emitter);
    if (def->backend == NETPLAN_BACKEND_NM) {
        YAML_STRING_PLAIN(event, emitter, "renderer", "NetworkManager");
    }

    if (def->type == NETPLAN_DEF_TYPE_NM)
        goto only_passthrough; //do not try to handle "unknown" connection types

    if (def->has_match)
        write_match(event, emitter, def);

    if (def->dhcp4) {
        YAML_STRING_PLAIN(event, emitter, "dhcp4", "true");
    }
    if (def->dhcp6) {
        YAML_STRING_PLAIN(event, emitter, "dhcp6", "true");
    }
    if (def->accept_ra == NETPLAN_RA_MODE_ENABLED) {
        YAML_STRING_PLAIN(event, emitter, "accept-ra", "true");
    }

    YAML_STRING(event, emitter, "macaddress", def->set_mac);
    YAML_STRING(event, emitter, "set-name", def->set_name);
    if (def->mtubytes) {
        tmp = g_strdup_printf("%u", def->mtubytes);
        YAML_STRING_PLAIN(event, emitter, "mtu", tmp);
        g_free(tmp);
    }
    if (def->emit_lldp)
        YAML_STRING_PLAIN(event, emitter, "emit-lldp", "true");

    if (def->has_auth)
        write_auth(event, emitter, def->auth);

    /* Search interfaces */
    switch (def->type) {
        case NETPLAN_DEF_TYPE_BRIDGE:
        case NETPLAN_DEF_TYPE_BOND:
            tmp_arr = g_array_new(FALSE, FALSE, sizeof(NetplanNetDefinition*));
            g_hash_table_iter_init(&iter, netdefs);
            while (g_hash_table_iter_next (&iter, &key, &value)) {
                NetplanNetDefinition *nd = (NetplanNetDefinition *) value;
                if (g_strcmp0(nd->bond, def->id) == 0 || g_strcmp0(nd->bridge, def->id) == 0)
                    g_array_append_val(tmp_arr, nd);
            }
            if (tmp_arr->len > 0) {
                YAML_SCALAR_PLAIN(event, emitter, "interfaces");
                YAML_SEQUENCE_OPEN(event, emitter);
                for (unsigned i = 0; i < tmp_arr->len; ++i) {
                    NetplanNetDefinition *nd = g_array_index(tmp_arr, NetplanNetDefinition*, i);
                    YAML_SCALAR_PLAIN(event, emitter, nd->id);
                }
                YAML_SEQUENCE_CLOSE(event, emitter);
            }
            write_bond_params(event, emitter, def);
            write_bridge_params(event, emitter, def, tmp_arr);
            g_array_free(tmp_arr, TRUE);
            break;
        default:
            break;
    }

    /* wake-on-lan */
    if (def->wake_on_lan)
        YAML_STRING_PLAIN(event, emitter, "wakeonlan", "true");

    if (def->wowlan) {
        YAML_SCALAR_PLAIN(event, emitter, "wakeonwlan");
        YAML_SEQUENCE_OPEN(event, emitter);
        /* XXX: make sure to extend if NetplanWifiWowlanFlag is extended */
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_DEFAULT)
            YAML_SCALAR_PLAIN(event, emitter, "default");
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_ANY)
            YAML_SCALAR_PLAIN(event, emitter, "any");
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_DISCONNECT)
            YAML_SCALAR_PLAIN(event, emitter, "disconnect");
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_MAGIC)
            YAML_SCALAR_PLAIN(event, emitter, "magic_pkt");
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_GTK_REKEY_FAILURE)
            YAML_SCALAR_PLAIN(event, emitter, "gtk_rekey_failure");
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_EAP_IDENTITY_REQ)
            YAML_SCALAR_PLAIN(event, emitter, "eap_identity_req");
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_4WAY_HANDSHAKE)
            YAML_SCALAR_PLAIN(event, emitter, "four_way_handshake");
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_RFKILL_RELEASE)
            YAML_SCALAR_PLAIN(event, emitter, "rfkill_release");
        if (def->wowlan & NETPLAN_WIFI_WOWLAN_TCP)
            YAML_SCALAR_PLAIN(event, emitter, "tcp");
        YAML_SEQUENCE_CLOSE(event, emitter);
    }

    /* some modem settings to auto-detect GSM vs CDMA connections */
    if (def->modem_params.auto_config)
        YAML_STRING_PLAIN(event, emitter, "auto-config", "true");
    YAML_STRING(event, emitter, "apn", def->modem_params.apn);
    YAML_STRING(event, emitter, "device-id", def->modem_params.device_id);
    YAML_STRING(event, emitter, "network-id", def->modem_params.network_id);
    YAML_STRING(event, emitter, "pin", def->modem_params.pin);
    YAML_STRING(event, emitter, "sim-id", def->modem_params.sim_id);
    YAML_STRING(event, emitter, "sim-operator-id", def->modem_params.sim_operator_id);
    YAML_STRING(event, emitter, "pin", def->modem_params.pin);
    YAML_STRING(event, emitter, "username", def->modem_params.username);
    YAML_STRING(event, emitter, "password", def->modem_params.password);
    YAML_STRING(event, emitter, "number", def->modem_params.number);

    if (def->type == NETPLAN_DEF_TYPE_WIFI)
        if (!write_access_points(event, emitter, def)) goto error;
only_passthrough:
    if (!write_backend_settings(event, emitter, def->backend_settings)) goto error;

    /* Close remaining mappings */
    YAML_MAPPING_CLOSE(event, emitter);

    return;

error:
    //TODO: handle error cases
    g_warning("=== YAML err: %s\n", emitter->problem);
    return;
}

/**
 * Generate the Netplan YAML configuration for the selected netdef
 * @def: NetplanNetDefinition (as pointer), the data to be serialized
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
void
write_netplan_conf(const NetplanNetDefinition* def, const char* rootdir)
{
    g_autofree gchar *filename = NULL;
    g_autofree gchar *path = NULL;

    /* NetworkManager produces one file per connection profile
    * It's 90-* to be higher priority than the default 70-netplan-set.yaml */
    if (def->backend_settings.nm.uuid)
        filename = g_strconcat("90-NM-", def->backend_settings.nm.uuid, ".yaml", NULL);
    else
        filename = g_strconcat("10-netplan-", def->id, ".yaml", NULL);
    path = g_build_path(G_DIR_SEPARATOR_S, rootdir ?: G_DIR_SEPARATOR_S, "etc", "netplan", filename, NULL);

    /* Start rendering YAML output */
    yaml_emitter_t emitter_data;
    yaml_event_t event_data;
    yaml_emitter_t* emitter = &emitter_data;
    yaml_event_t* event = &event_data;
    FILE *output = fopen(path, "wb");

    YAML_OUT_START(event, emitter, output);
    /* build the netplan boilerplate YAML structure */
    YAML_SCALAR_PLAIN(event, emitter, "network");
    YAML_MAPPING_OPEN(event, emitter);
    YAML_STRING_PLAIN(event, emitter, "version", "2");
    if (netplan_get_global_backend() == NETPLAN_BACKEND_NM) {
        YAML_STRING(event, emitter, "renderer", "NetworkManager");
    } else if (netplan_get_global_backend() == NETPLAN_BACKEND_NETWORKD) {
        YAML_STRING(event, emitter, "renderer", "networkd");
    }

    if (netplan_def_type_to_str[def->type])
        YAML_SCALAR_PLAIN(event, emitter, netplan_def_type_to_str[def->type]);
    YAML_MAPPING_OPEN(event, emitter);

    _serialize_yaml(event, emitter, def);



    /* Close remaining mappings */
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);

    /* Tear down the YAML emitter */
    YAML_OUT_STOP(event, emitter);
    fclose(output);
    return;

    // LCOV_EXCL_START
error:
    yaml_emitter_delete(emitter);
    fclose(output);
    // LCOV_EXCL_STOP
}

/* XXX: implement the following functions, once needed:
void write_netplan_conf_finish(const char* rootdir)
void cleanup_netplan_conf(const char* rootdir)
*/

/**
 * Helper function for testing only
 */
void
_write_netplan_conf(const char* netdef_id, const char* rootdir)
{
    GHashTable* ht = NULL;
    const NetplanNetDefinition* def = NULL;
    ht = netplan_finish_parse(NULL);
    def = g_hash_table_lookup(ht, netdef_id);
    write_netplan_conf(def, rootdir);
}

gboolean
contains_netdef_type(gpointer key, gpointer value, gpointer user_data)
{
    NetplanNetDefinition *nd = value;
    NetplanDefType *type = user_data;
    return nd->type == *type;
}

void
_write_netplan_conf_full(const char* file_hint, const char* rootdir)
{
    g_autofree gchar *filename = NULL;
    g_autofree gchar *path = NULL;
    GHashTableIter iter;
    gpointer key, value;

    if (netdefs && g_hash_table_size(netdefs) > 0) {
        path = g_build_path(G_DIR_SEPARATOR_S, rootdir ?: G_DIR_SEPARATOR_S, "etc", "netplan", file_hint, NULL);

        /* Start rendering YAML output */
        yaml_emitter_t emitter_data;
        yaml_event_t event_data;
        yaml_emitter_t* emitter = &emitter_data;
        yaml_event_t* event = &event_data;
        FILE *output = fopen(path, "wb");

        YAML_OUT_START(event, emitter, output);
        /* build the netplan boilerplate YAML structure */
        YAML_SCALAR_PLAIN(event, emitter, "network");
        YAML_MAPPING_OPEN(event, emitter);
        YAML_STRING_PLAIN(event, emitter, "version", "2");
        if (netplan_get_global_backend() == NETPLAN_BACKEND_NM) {
            YAML_STRING_PLAIN(event, emitter, "renderer", "NetworkManager");
        } else if (netplan_get_global_backend() == NETPLAN_BACKEND_NETWORKD) {
            YAML_STRING_PLAIN(event, emitter, "renderer", "networkd");
        }



        /* Go through the netdefs type-by-type */
        for (unsigned i = 0; i < NETPLAN_DEF_TYPE_MAX_; ++i) {
            /* Per-netdef config */
            if (netplan_def_type_to_str[i] && g_hash_table_find(netdefs, contains_netdef_type, &i)) {
                YAML_SCALAR_PLAIN(event, emitter, netplan_def_type_to_str[i]);
                YAML_MAPPING_OPEN(event, emitter);
                g_hash_table_iter_init(&iter, netdefs);
                while (g_hash_table_iter_next (&iter, &key, &value)) {
                    NetplanNetDefinition *def = (NetplanNetDefinition *) value;
                    if (def->type == i)
                        _serialize_yaml(event, emitter, def);
                }
                YAML_MAPPING_CLOSE(event, emitter);
            }
        }





        /* Close remaining mappings */
        YAML_MAPPING_CLOSE(event, emitter);

        /* Tear down the YAML emitter */
        YAML_OUT_STOP(event, emitter);
        fclose(output);
        return;

        // LCOV_EXCL_START
error:
        g_warning("YAML error: %s", emitter->problem);
        yaml_emitter_delete(emitter);
        fclose(output);
        // LCOV_EXCL_STOP


    } else {
        //TODO
        g_debug("No data/netdefs to serialize into YAML.");
    }
}