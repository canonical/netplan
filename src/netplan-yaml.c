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

#include "netplan-yaml.h"
#include "parse.h"

/**
 * TODO: docs
 */
//XXX: gchar*
gboolean
render_netdef(NetplanNetDefinition nd, const char* yaml_path)
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

    // TODO: match?
    if (def->type == NETPLAN_DEF_TYPE_WIFI) {
        // TODO: wifi?
        // TODO: ap backend settings?
    }
    // TODO: backend settings?

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

gboolean
_render_netdef(const char* in_path, const char* out_path)
{
    //TODO: parse in_path
    return render_netdef(..., out_path);
}