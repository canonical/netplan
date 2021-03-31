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
        if (ap->has_auth)
            write_auth(event, emitter, ap->auth);
        if (ap->hidden) {
            YAML_SCALAR_PLAIN(event, emitter, "hidden");
            YAML_SCALAR_PLAIN(event, emitter, "true");
        }
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
    gchar *tmp = NULL;

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
    YAML_SCALAR_PLAIN(event, emitter, netplan_def_type_to_str[def->type]);
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, def->id);
    YAML_MAPPING_OPEN(event, emitter);
    YAML_STRING_PLAIN(event, emitter, "renderer", netplan_backend_to_name[def->backend])

    if (def->type == NETPLAN_DEF_TYPE_NM)
        goto only_passthrough; //do not try to handle "unknown" connection types

    if (def->has_match)
        write_match(event, emitter, def);

    if (def->dhcp4) {
        YAML_STRING_PLAIN(event, emitter, "dhcp4", "true");
    } else {
        YAML_STRING_PLAIN(event, emitter, "dhcp4", "false");
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

    /* wake-on-lan */
    if (def->wake_on_lan)
        YAML_STRING_PLAIN(event, emitter, "wakeonlan", "true");

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
