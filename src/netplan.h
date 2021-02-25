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

#pragma once

#include "parse.h"

#define YAML_MAPPING_OPEN(event_ptr, emitter_ptr) \
{ \
    yaml_mapping_start_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_MAP_TAG, 1, YAML_ANY_MAPPING_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
}
#define YAML_MAPPING_CLOSE(event_ptr, emitter_ptr) \
{ \
    yaml_mapping_end_event_initialize(event_ptr); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
}
#define YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, scalar) \
{ \
    yaml_scalar_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_STR_TAG, (yaml_char_t *)scalar, strlen(scalar), 1, 0, YAML_PLAIN_SCALAR_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
}
/* Implicit plain and quoted tags, double quoted style */
#define YAML_SCALAR_QUOTED(event_ptr, emitter_ptr, scalar) \
{ \
    yaml_scalar_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_STR_TAG, (yaml_char_t *)scalar, strlen(scalar), 1, 1, YAML_DOUBLE_QUOTED_SCALAR_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
}
#define YAML_STRING(event_ptr, emitter_ptr, key, value_ptr) \
{ \
    if (value_ptr) { \
        YAML_SCALAR_PLAIN(event, emitter, key); \
        YAML_SCALAR_QUOTED(event, emitter, value_ptr); \
    } \
}
#define YAML_STRING_PLAIN(event_ptr, emitter_ptr, key, value_ptr) \
{ \
    if (value_ptr) { \
        YAML_SCALAR_PLAIN(event, emitter, key); \
        YAML_SCALAR_PLAIN(event, emitter, value_ptr); \
    } \
}
/* open YAML emitter, document, stream and initial mapping */
#define YAML_OUT_START(event_ptr, emitter_ptr, file) \
{ \
    yaml_emitter_initialize(emitter_ptr); \
    yaml_emitter_set_output_file(emitter_ptr, file); \
    yaml_stream_start_event_initialize(event_ptr, YAML_UTF8_ENCODING); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
    yaml_document_start_event_initialize(event_ptr, NULL, NULL, NULL, 1); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
    YAML_MAPPING_OPEN(event_ptr, emitter_ptr); \
}
/* close initial YAML mapping, document, stream and emitter */
#define YAML_OUT_STOP(event_ptr, emitter_ptr) \
{ \
    YAML_MAPPING_CLOSE(event_ptr, emitter_ptr); \
    yaml_document_end_event_initialize(event_ptr, 1); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
    yaml_stream_end_event_initialize(event_ptr); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
    yaml_emitter_delete(emitter_ptr); \
}

void write_netplan_conf(const NetplanNetDefinition* def, const char* rootdir);
