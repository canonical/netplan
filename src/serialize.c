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

#include "serialize.h"
#include "parse.h"

static gboolean
write_match(yaml_event_t* event, yaml_emitter_t* emitter, NetplanNetDefinition* nd)
{
    if (nd->type < NETPLAN_DEF_TYPE_VIRTUAL) {
        YAML_SCALAR_PLAIN(event, emitter, "match");
        YAML_MAPPING_OPEN(event, emitter);
        if (nd->match.original_name) {
            YAML_SCALAR_PLAIN(event, emitter, "name");
            YAML_SCALAR_QUOTED(event, emitter, nd->match.original_name);
        }
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
write_access_points(yaml_event_t* event, yaml_emitter_t* emitter, NetplanNetDefinition* nd)
{
    NetplanWifiAccessPoint* ap = NULL;
    GHashTableIter iter;
    gpointer key, value;
    YAML_SCALAR_PLAIN(event, emitter, "access-points"); //FIXME: loop for each AP
    YAML_MAPPING_OPEN(event, emitter);
    g_hash_table_iter_init(&iter, nd->access_points);
    while (g_hash_table_iter_next(&iter, &key, &value)) {
        ap = value;
        YAML_SCALAR_QUOTED(event, emitter, ap->ssid);
        YAML_MAPPING_OPEN(event, emitter);
        if (ap->hidden) {
            YAML_SCALAR_PLAIN(event, emitter, "hidden");
            YAML_SCALAR_PLAIN(event, emitter, "true");
        }
        YAML_SCALAR_PLAIN(event, emitter, "mode");
        if (ap->mode != NETPLAN_WIFI_MODE_OTHER) {
            YAML_SCALAR_PLAIN(event, emitter, netplan_wifi_mode_to_str[ap->mode]);
        } else {
            // LCOV_EXCL_START
            g_warning("netplan: serialize: %s (SSID %s), unsupported AP mode, falling back to 'infrastructure'", nd->id, ap->ssid);
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
 * Takes a single NetplanNetDefinition structure and writes it to a YAML file.
 * @nd: NetplanNetDefinition (as pointer), the data to be serialized
 * @yaml_path: string, the full path of the file to be written
 */
gboolean
netplan_render_netdef(NetplanNetDefinition* nd, const char* yaml_path)
{
    /* Start rendering YAML output */
    yaml_emitter_t emitter_data;
    yaml_event_t event_data;
    yaml_emitter_t* emitter = &emitter_data;
    yaml_event_t* event = &event_data;
    FILE *output = fopen(yaml_path, "wb");

    YAML_OUT_START(event, emitter, output);
    /* build the netplan boilerplate YAML structure */
    YAML_SCALAR_PLAIN(event, emitter, "network");
    YAML_MAPPING_OPEN(event, emitter);
    // TODO: global backend/renderer
    YAML_SCALAR_PLAIN(event, emitter, "version");
    YAML_SCALAR_PLAIN(event, emitter, "2");
    YAML_SCALAR_PLAIN(event, emitter, netplan_def_type_to_str[nd->type]);
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, nd->id);
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "renderer");
    YAML_SCALAR_PLAIN(event, emitter, netplan_backend_to_name[nd->backend]);

    if (nd->has_match)
        write_match(event, emitter, nd);

    /* wake-on-lan */
    if (nd->wake_on_lan)
        YAML_STRING_PLAIN(event, emitter, "wakeonlan", "true");

    if (nd->type == NETPLAN_DEF_TYPE_WIFI)
        if (!write_access_points(event, emitter, nd)) goto error;
    if (!write_backend_settings(event, emitter, nd->backend_settings)) goto error;

    /* Close remaining mappings */
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);

    /* Tear down the YAML emitter */
    YAML_OUT_STOP(event, emitter);
    fclose(output);
    return TRUE;

    // LCOV_EXCL_START
error:
    yaml_emitter_delete(emitter);
    fclose(output);
    return FALSE;
    // LCOV_EXCL_STOP
}

/**
 * Helper function for testing only
 */
gboolean
_netplan_render_netdef(const char* netdef_id, const char* read_path, const char* write_path)
{
    gboolean ret = FALSE;
    GHashTable* ht = NULL;
    NetplanNetDefinition* nd = NULL;
    netplan_parse_yaml(read_path, NULL);
    ht = netplan_finish_parse(NULL);
    nd = g_hash_table_lookup(ht, netdef_id);
    ret = netplan_render_netdef(nd, write_path);
    netplan_clear_netdefs();
    return ret;
}
