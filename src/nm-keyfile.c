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

#include "nm-keyfile.h"
#include "parse.h"

static const NetplanDefType
type_from_str(const char* type_str)
{
    if (!g_strcmp0(type_str, "ethernet") || !g_strcmp0(type_str, "802-3-ethernet"))
        return NETPLAN_DEF_TYPE_ETHERNET;

    /* Full fallback/passthrough mode */
    return NETPLAN_DEF_TYPE_OTHER;
}

/**
 * Render keyfile data to YAML
 */
gboolean
netplan_render_yaml_from_nm_keyfile(GKeyFile* kf, const char* rootdir)
{
    g_autofree gchar *id = NULL;
    g_autofree gchar *uuid = NULL;
    g_autofree gchar *filename = NULL;
    g_autofree gchar *yaml_path = NULL;
    g_autofree gchar *type = NULL;
    uuid = g_key_file_get_string(kf, "connection", "uuid", NULL);
    if (!uuid)
        return FALSE;
    type = g_key_file_get_string(kf, "connection", "type", NULL);
    if (!type)
        return FALSE;
    filename = g_strconcat("90-NM-", uuid, ".yaml", NULL);
    yaml_path = g_strjoin("/", rootdir? rootdir : "", "etc", "netplan", filename, NULL);

    /* YAML emitter */
    yaml_emitter_t emitter;
    yaml_event_t event;
    yaml_emitter_initialize(&emitter);

    /* set the output file */
    FILE *output = fopen(yaml_path, "wb");
    yaml_emitter_set_output_file(&emitter, output);

    /* start STREAM and DOCUMENT events */
    yaml_stream_start_event_initialize(&event, YAML_UTF8_ENCODING);
    if (!yaml_emitter_emit(&emitter, &event)) goto error;

    yaml_document_start_event_initialize(&event, NULL, NULL, NULL, 1);
    if (!yaml_emitter_emit(&emitter, &event)) goto error;

    /* build the YAML structure (mappings & scalars) */
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "network");
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "version");
    YAML_SCALAR_PLAIN(event, emitter, "2");
    switch (type_from_str(type)) {
        case NETPLAN_DEF_TYPE_ETHERNET:
            YAML_SCALAR_PLAIN(event, emitter, "ethernets");
            break;
        default:
            YAML_SCALAR_PLAIN(event, emitter, "others"); /* full NM/keyfile fallback mode */
            break;
    }
    YAML_MAPPING_OPEN(event, emitter);

    /* Define the connection profile */
    id = g_strconcat("NM-", uuid, NULL);
    YAML_SCALAR_PLAIN(event, emitter, id);
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "renderer");
    YAML_SCALAR_PLAIN(event, emitter, "NetworkManager");
    YAML_SCALAR_PLAIN(event, emitter, "networkmanager"); /* Backend specific configuration */
    YAML_MAPPING_OPEN(event, emitter);
    YAML_SCALAR_PLAIN(event, emitter, "uuid");
    YAML_SCALAR_PLAIN(event, emitter, uuid);
    YAML_SCALAR_PLAIN(event, emitter, "passthrough");
    YAML_MAPPING_OPEN(event, emitter);

    /* Define the fallback keyfile settings */
    /* ===== KEYFILE READER START ==== */
    gchar *group_key = NULL;
    gchar *value = NULL;
    gsize klen = 0;
    gsize glen = 0;
    gchar **groups = g_key_file_get_groups(kf, &glen);
    for(unsigned i = 0; i < glen; ++i) {
        klen = 0;
        gchar **keys = g_key_file_get_keys(kf, groups[i], &klen, NULL); //TODO: error handling
        for(unsigned j = 0; j < klen; ++j) {
            group_key = g_strconcat(groups[i], ".", keys[j], NULL);
            value = g_key_file_get_string(kf, groups[i], keys[j], NULL); //TODO: error handling

            // TODO: error handling (freeing the variables)
            YAML_SCALAR_PLAIN(event, emitter, group_key);
            YAML_SCALAR_QUOTED(event, emitter, value);

            g_free(group_key);
            g_free(value);
        }
        g_strfreev(keys);
    }
    g_strfreev(groups);
    /* ===== KEYFILE READER END ==== */

    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);
    YAML_MAPPING_CLOSE(event, emitter);

    /* close DOCUMENT, STREAM and FILE */
    yaml_document_end_event_initialize(&event, 1);
    if (!yaml_emitter_emit(&emitter, &event)) goto error;

    yaml_stream_end_event_initialize(&event);
    if (!yaml_emitter_emit(&emitter, &event)) goto error;

    yaml_emitter_delete(&emitter);
    fclose(output);
    return TRUE;

    // LCOV_EXCL_START
error:
    // TODO: free some more variables
    yaml_emitter_delete(&emitter);
    return FALSE;
    // LCOV_EXCL_STOP

}

/* For testing only */
gboolean
_netplan_render_yaml_from_nm_keyfile_str(const char* keyfile_str, const char* rootdir)
{
    /* Pass through the test-data (keyfile string) during testing,
     * until we cann pass the real GKeyFile data from Python */
    g_autoptr(GKeyFile) kf = g_key_file_new();
    g_key_file_load_from_data(kf, keyfile_str, -1, 0, NULL);
    return netplan_render_yaml_from_nm_keyfile(kf, rootdir);
}
