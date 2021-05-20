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
    yaml_mapping_start_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_MAP_TAG, 1, YAML_BLOCK_MAPPING_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
}
#define YAML_MAPPING_CLOSE(event_ptr, emitter_ptr) \
{ \
    yaml_mapping_end_event_initialize(event_ptr); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
}
#define YAML_SEQUENCE_OPEN(event_ptr, emitter_ptr) \
{ \
    yaml_sequence_start_event_initialize(event_ptr, NULL, (yaml_char_t *)YAML_SEQ_TAG, 1, YAML_BLOCK_SEQUENCE_STYLE); \
    if (!yaml_emitter_emit(emitter_ptr, event_ptr)) goto error; \
}
#define YAML_SEQUENCE_CLOSE(event_ptr, emitter_ptr) \
{ \
    yaml_sequence_end_event_initialize(event_ptr); \
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
        YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, key); \
        YAML_SCALAR_QUOTED(event_ptr, emitter_ptr, value_ptr); \
    } \
}
#define YAML_STRING_PLAIN(event_ptr, emitter_ptr, key, value_ptr) \
{ \
    if (value_ptr) { \
        YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, key); \
        YAML_SCALAR_PLAIN(event_ptr, emitter_ptr, value_ptr); \
    } \
}
#define YAML_UINT(event_ptr, emitter_ptr, key, value) \
{ \
    tmp = g_strdup_printf("%u", value); \
    YAML_STRING_PLAIN(event_ptr, emitter_ptr, key, tmp); \
    g_free(tmp); \
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

static const char* const netplan_def_type_to_str[NETPLAN_DEF_TYPE_MAX_] = {
    [NETPLAN_DEF_TYPE_NONE] = NULL,
    [NETPLAN_DEF_TYPE_ETHERNET] = "ethernets",
    [NETPLAN_DEF_TYPE_WIFI] = "wifis",
    [NETPLAN_DEF_TYPE_MODEM] = "modems",
    [NETPLAN_DEF_TYPE_BRIDGE] = "bridges",
    [NETPLAN_DEF_TYPE_BOND] = "bonds",
    [NETPLAN_DEF_TYPE_VLAN] = "vlans",
    [NETPLAN_DEF_TYPE_TUNNEL] = "tunnels",
    [NETPLAN_DEF_TYPE_PORT] = NULL,
    [NETPLAN_DEF_TYPE_NM] = "nm-devices",
};

static const char* const netplan_auth_key_management_type_to_str[NETPLAN_AUTH_KEY_MANAGEMENT_MAX] = {
    [NETPLAN_AUTH_KEY_MANAGEMENT_NONE] = "none",
    [NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK] = "psk",
    [NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP] = "eap",
    [NETPLAN_AUTH_KEY_MANAGEMENT_8021X] = "802.1x",
};

static const char* const netplan_auth_eap_method_to_str[NETPLAN_AUTH_EAP_METHOD_MAX] = {
    [NETPLAN_AUTH_EAP_NONE] = NULL,
    [NETPLAN_AUTH_EAP_TLS] = "tls",
    [NETPLAN_AUTH_EAP_PEAP] = "peap",
    [NETPLAN_AUTH_EAP_TTLS] = "ttls",
};

static const char* const netplan_tunnel_mode_to_str[NETPLAN_TUNNEL_MODE_MAX_] = {
    [NETPLAN_TUNNEL_MODE_UNKNOWN] = NULL,
    [NETPLAN_TUNNEL_MODE_IPIP] = "ipip",
    [NETPLAN_TUNNEL_MODE_GRE] = "gre",
    [NETPLAN_TUNNEL_MODE_SIT] = "sit",
    [NETPLAN_TUNNEL_MODE_ISATAP] = "isatap",
    [NETPLAN_TUNNEL_MODE_VTI] = "vti",
    [NETPLAN_TUNNEL_MODE_IP6IP6] = "ip6ip6",
    [NETPLAN_TUNNEL_MODE_IPIP6] = "ipip6",
    [NETPLAN_TUNNEL_MODE_IP6GRE] = "ip6gre",
    [NETPLAN_TUNNEL_MODE_VTI6] = "vti6",
    [NETPLAN_TUNNEL_MODE_GRETAP] = "gretap",
    [NETPLAN_TUNNEL_MODE_IP6GRETAP] = "ip6gretap",
    [NETPLAN_TUNNEL_MODE_WIREGUARD] = "wireguard",
};

static const char* const netplan_addr_gen_mode_to_str[NETPLAN_ADDRGEN_MAX] = {
    [NETPLAN_ADDRGEN_DEFAULT] = NULL,
    [NETPLAN_ADDRGEN_EUI64] = "eui64",
    [NETPLAN_ADDRGEN_STABLEPRIVACY] = "stable-privacy"
};

void write_netplan_conf(const NetplanNetDefinition* def, const char* rootdir);
