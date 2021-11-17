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

#include <yaml.h>

#define YAML_MAPPING_OPEN(event_ptr, emitter_ptr) \
{ \
    yaml_mapping_start_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_MAP_TAG, 1, YAML_BLOCK_MAPPING_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
}
#define YAML_MAPPING_CLOSE(event_ptr, emitter_ptr) \
{ \
    yaml_mapping_end_event_initialize(event_ptr); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
}
#define YAML_SEQUENCE_OPEN(event_ptr, emitter_ptr) \
{ \
    yaml_sequence_start_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_SEQ_TAG, 1, YAML_BLOCK_SEQUENCE_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
}
#define YAML_SEQUENCE_CLOSE(event_ptr, emitter_ptr) \
{ \
    yaml_sequence_end_event_initialize(event_ptr); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
}
#define YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, scalar) \
{ \
    yaml_scalar_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_STR_TAG, (yaml_char_t *)scalar, strlen(scalar), 1, 0, YAML_PLAIN_SCALAR_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
}

#define YAML_NULL_PLAIN(event_ptr, emitter_ptr) \
    yaml_scalar_event_initialize(event_ptr, NULL, (yaml_char_t*)YAML_NULL_TAG, (yaml_char_t*)"null", strlen("null"), 1, 0, YAML_PLAIN_SCALAR_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \

/* Implicit plain and quoted tags, double quoted style */
#define YAML_SCALAR_QUOTED(event_ptr, emitter_ptr, scalar) \
{ \
    yaml_scalar_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_STR_TAG, (yaml_char_t *)scalar, strlen(scalar), 1, 1, YAML_DOUBLE_QUOTED_SCALAR_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
}
#define YAML_NONNULL_STRING(event_ptr, emitter_ptr, key, value_ptr) \
{ \
    if (value_ptr) { \
        YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, key); \
        YAML_SCALAR_QUOTED(event_ptr, emitter_ptr, value_ptr); \
    } \
}
#define YAML_NONNULL_STRING_PLAIN(event_ptr, emitter_ptr, key, value_ptr) \
{ \
    if (value_ptr) { \
        YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, key); \
        YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, value_ptr); \
    } \
}
#define _YAML_UINT(event_ptr, emitter_ptr, key, value) \
{ \
    tmp = g_strdup_printf("%u", value); \
    YAML_NONNULL_STRING_PLAIN(event_ptr, emitter_ptr, key, tmp); \
    g_free(tmp); \
}

#define YAML_NULL(event_ptr, emitter_ptr, key) \
    YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, key); \
    YAML_NULL_PLAIN(event_ptr, emitter_ptr); \

/* open YAML emitter, document, stream and initial mapping */
#define YAML_OUT_START(event_ptr, emitter_ptr, file) \
{ \
    yaml_emitter_initialize(emitter_ptr); \
    yaml_emitter_set_output_file(emitter_ptr, file); \
    yaml_stream_start_event_initialize(event_ptr, YAML_UTF8_ENCODING); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
    yaml_document_start_event_initialize(event_ptr, NULL, NULL, NULL, 1); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
    YAML_MAPPING_OPEN(event_ptr, emitter_ptr); \
}
/* close initial YAML mapping, document, stream and emitter */
#define YAML_OUT_STOP(event_ptr, emitter_ptr) \
{ \
    YAML_MAPPING_CLOSE(event_ptr, emitter_ptr); \
    yaml_document_end_event_initialize(event_ptr, 1); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
    yaml_stream_end_event_initialize(event_ptr); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto err_path; \
    yaml_emitter_delete(emitter_ptr); \
}
