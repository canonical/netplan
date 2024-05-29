/*
 * Copyright (C) 2016-2023 Canonical, Ltd.
 * Author: Martin Pitt <martin.pitt@ubuntu.com>
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

#include <stdarg.h>
#include <errno.h>
#include <regex.h>
#include <arpa/inet.h>

#include <glib.h>
#include <glib/gstdio.h>
#include <gio/gio.h>

#include <sys/stat.h>
#include <yaml.h>

#include "parse.h"
#include "names.h"
#include "util-internal.h"
#include "error.h"
#include "validation.h"

#define NETPLAN_VERSION_MIN    2
#define NETPLAN_VERSION_MAX    3

/* convenience macro to put the offset of a NetplanNetDefinition field into "void* data" */
#define access_point_offset(field) GUINT_TO_POINTER(offsetof(NetplanWifiAccessPoint, field))
#define addr_option_offset(field) GUINT_TO_POINTER(offsetof(NetplanAddressOptions, field))
#define auth_offset(field) GUINT_TO_POINTER(offsetof(NetplanAuthenticationSettings, field))
#define ip_rule_offset(field) GUINT_TO_POINTER(offsetof(NetplanIPRule, field))
#define netdef_offset(field) GUINT_TO_POINTER(offsetof(NetplanNetDefinition, field))
#define ovs_settings_offset(field) GUINT_TO_POINTER(offsetof(NetplanOVSSettings, field))
#define route_offset(field) GUINT_TO_POINTER(offsetof(NetplanIPRoute, field))
#define wireguard_peer_offset(field) GUINT_TO_POINTER(offsetof(NetplanWireguardPeer, field))
#define vxlan_offset(field) GUINT_TO_POINTER(offsetof(NetplanVxlan, field))

/* convenience macro to avoid strdup'ing a string into a field if it's already set. */
#define set_str_if_null(dst, src) { if (dst == NULL) {\
    dst = g_strdup(src); \
} }

/*
 * We use g_strescape to escape control characters from the input.
 * Besides control characters, g_strescape will also escape double quotes and backslashes.
 * Quotes are escaped at configuration generation time as needed, as they might be part of passwords for example.
 * Escaping backslashes in the parser affects "netplan set" as it will always escape \'s from
 * the input and update YAMLs with all the \'s escaped again.
*/
static char* STRESCAPE_EXCEPTIONS = "\"\\";

STATIC gboolean
insert_kv_into_hash(void *key, void *value, void *hash);

/**
 * Load YAML file into a yaml_document_t.
 *
 * @input_fd: the file descriptor pointing to the YAML source file
 * @doc: the output document structure
 *
 * Returns: TRUE on success, FALSE if the document is malformed; @error gets set then.
 */
STATIC gboolean
load_yaml_from_fd(int input_fd, yaml_document_t* doc, GError** error)
{
    int in_dup = -1;
    FILE* fyaml = NULL;
    yaml_parser_t parser;
    gboolean ret = TRUE;

    in_dup = dup(input_fd);
    if (in_dup < 0)
        goto file_error; // LCOV_EXCL_LINE

    fyaml = fdopen(in_dup, "r");
    if (!fyaml)
        goto file_error; // LCOV_EXCL_LINE

    yaml_parser_initialize(&parser);
    yaml_parser_set_input_file(&parser, fyaml);
    if (!yaml_parser_load(&parser, doc)) {
        ret = parser_error(&parser, NULL, error);
    }

    yaml_parser_delete(&parser);
    fclose(fyaml);
    return ret;

    // LCOV_EXCL_START
file_error:
    g_set_error(error, NETPLAN_FILE_ERROR, errno, "Error when opening FD %d: %m", input_fd);
    if (in_dup >= 0)
        close(in_dup);
    return FALSE;
    // LCOV_EXCL_STOP
}

/**
 * Load YAML file name into a yaml_document_t.
 *
 * @yaml: file path to the YAML source file
 * @doc: the output document structure
 *
 * Returns: TRUE on success, FALSE if the document is malformed; @error gets set then.
 */
STATIC gboolean
load_yaml(const char* yaml, yaml_document_t* doc, GError** error)
{
    FILE* fyaml = NULL;
    yaml_parser_t parser;
    gboolean ret = TRUE;

    fyaml = g_fopen(yaml, "r");
    if (!fyaml) { // LCOV_EXCL_START
        g_set_error(error, NETPLAN_FILE_ERROR, errno, "Cannot open %s: %m", yaml);
        return FALSE;
    } // LCOV_EXCL_STOP

    yaml_parser_initialize(&parser);
    yaml_parser_set_input_file(&parser, fyaml);
    if (!yaml_parser_load(&parser, doc)) {
        ret = parser_error(&parser, yaml, error);
    }

    yaml_parser_delete(&parser);
    fclose(fyaml);
    return ret;
}

#define YAML_VARIABLE_NODE  YAML_NO_NODE

/**
 * Raise a GError about a type mismatch and return FALSE.
 */
STATIC gboolean
assert_type_fn(const NetplanParser* npp, yaml_node_t* node, yaml_node_type_t expected_type, GError** error)
{
    if (node->type == expected_type)
        return TRUE;

    switch (expected_type) {
        case YAML_VARIABLE_NODE:
            /* Special case, defer coherence checking to the next handlers */
            return TRUE;
            break;
        case YAML_SCALAR_NODE:
            yaml_error(npp, node, error, "expected scalar");
            break;
        case YAML_SEQUENCE_NODE:
            yaml_error(npp, node, error, "expected sequence");
            break;
        case YAML_MAPPING_NODE:
            yaml_error(npp, node, error, "expected mapping (check indentation)");
            break;

        // LCOV_EXCL_START
        default:
            g_assert_not_reached();
        // LCOV_EXCL_STOP
    }
    return FALSE;
}

#define assert_type(ctx,n,t) { if (!assert_type_fn(ctx,n,t,error)) return FALSE; }

static inline const char*
scalar(const yaml_node_t* node)
{
    return (const char*) node->data.scalar.value;
}

STATIC void
add_missing_node(NetplanParser *npp, const yaml_node_t* node)
{
    NetplanMissingNode* missing;

    /* Let's capture the current netdef we were playing with along with the
     * actual yaml_node_t that errors (that is an identifier not previously
     * seen by the compiler). We can use it later to write an sensible error
     * message and point the user in the right direction. */
    missing = g_new0(NetplanMissingNode, 1);
    missing->netdef_id = npp->current.netdef->id;
    missing->node = node;

    g_debug("recording missing yaml_node_t %s", scalar(node));
    g_hash_table_insert(npp->missing_id, (gpointer)scalar(node), missing);
}

/**
 * Check that node contains a valid ID/interface name. Raise GError if not.
 */
STATIC gboolean
assert_valid_id(const NetplanParser* npp, yaml_node_t* node, GError** error)
{
    static regex_t re;
    static gboolean re_inited = FALSE;

    assert_type(npp, node, YAML_SCALAR_NODE);

    if (!re_inited) {
        g_assert(regcomp(&re, "^[[:alnum:][:punct:]]+$", REG_EXTENDED|REG_NOSUB) == 0);
        re_inited = TRUE;
    }

    if (regexec(&re, scalar(node), 0, NULL, 0) != 0)
        return yaml_error(npp, node, error, "Invalid name '%s'", scalar(node));
    return TRUE;
}

NetplanNetDefinition*
netplan_netdef_new(NetplanParser *npp, const char* id, NetplanDefType type, NetplanBackend backend)
{
    /* create new network definition */
    NetplanNetDefinition *netdef = g_new0(NetplanNetDefinition, 1);
    reset_netdef(netdef, type, backend);
    netdef->id = g_strdup(id);

    if (!npp->parsed_defs)
        npp->parsed_defs = g_hash_table_new(g_str_hash, g_str_equal);
    g_hash_table_insert(npp->parsed_defs, netdef->id, netdef);
    npp->ordered = g_list_append(npp->ordered, netdef);
    return netdef;
}

/****************************************************
 * Data types and functions for interpreting YAML nodes
 ****************************************************/

typedef gboolean (*node_handler) (NetplanParser* npp, yaml_node_t* node, const void* data, GError** error);

typedef gboolean (*custom_map_handler) (NetplanParser* npp, yaml_node_t* node, const char *prefix, const void* data, GError** error);

typedef struct mapping_entry_handler_s {
    /* mapping key (must be scalar) */
    const char* key;
    /* expected type  of the mapped value */
    yaml_node_type_t type;
    union {
        node_handler generic;
        custom_map_handler variable;
        struct {
            const struct mapping_entry_handler_s* handlers;
            custom_map_handler custom;
        } map;
    };

    /* user_data */
    const void* data;
} mapping_entry_handler;

/**
 * Return the #mapping_entry_handler that matches @key, or NULL if not found.
 */
STATIC const mapping_entry_handler*
get_handler(const mapping_entry_handler* handlers, const char* key)
{
    for (unsigned i = 0; handlers[i].key != NULL; ++i) {
        if (g_strcmp0(handlers[i].key, key) == 0)
            return &handlers[i];
    }
    return NULL;
}

/**
 * Call handlers for all entries in a YAML mapping.
 * @doc: The yaml_document_t
 * @node: The yaml_node_t to process, must be a #YAML_MAPPING_NODE
 * @handlers: Array of mapping_entry_handler with allowed keys
 * @error: Gets set on data type errors or unknown keys
 *
 * Returns: TRUE on success, FALSE on error (@error gets set then).
 */
STATIC gboolean
process_mapping(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, const mapping_entry_handler* handlers, GList** out_values, GError** error)
{
    yaml_node_pair_t* entry;

    assert_type(npp, node, YAML_MAPPING_NODE);

    for (entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        const mapping_entry_handler* h;
        gboolean res = TRUE;
        g_autofree char* full_key = NULL;

        g_assert(error == NULL || *error == NULL);

        key = yaml_document_get_node(&npp->doc, entry->key);
        value = yaml_document_get_node(&npp->doc, entry->value);
        assert_type(npp, key, YAML_SCALAR_NODE);
        if (npp->null_fields && key_prefix) {
            full_key = g_strdup_printf("%s\t%s", key_prefix, scalar(key));
            if (g_hash_table_contains(npp->null_fields, full_key))
                continue;
        }
        h = get_handler(handlers, scalar(key));
        if (!h)
            return yaml_error(npp, key, error, "unknown key '%s'", scalar(key));
        assert_type(npp, value, h->type);
        if (out_values)
            *out_values = g_list_prepend(*out_values, g_strdup(scalar(key)));
        if (h->type == YAML_MAPPING_NODE) {
            if (h->map.custom)
                res = h->map.custom(npp, value, full_key, h->data, error);
            else
                res = process_mapping(npp, value, full_key, h->map.handlers, NULL, error);
        } else if (h->type == YAML_NO_NODE) {
            res = h->variable(npp, value, full_key, h->data, error);
        } else {
            res = h->generic(npp, value, h->data, error);
        }
        if (!res)
            return FALSE;
    }

    return TRUE;
}

/*************************************************************
 * Generic helper functions to extract data from scalar nodes.
 *************************************************************/

/**
 * Handler for setting a guint field from a scalar node, inside a given struct
 * @entryptr: pointer to the begining of the to-be-modified data structure
 * @data: offset into entryptr struct where the guint field to write is located
 */
STATIC gboolean
handle_generic_guint(NetplanParser* npp, yaml_node_t* node, const void* entryptr, const void* data, GError** error)
{
    g_assert(entryptr);
    guint offset = GPOINTER_TO_UINT(data);
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT)
        return yaml_error(npp, node, error, "invalid unsigned int value '%s'", scalar(node));

    mark_data_as_dirty(npp, entryptr + offset);
    *((guint*) ((void*) entryptr + offset)) = (guint) v;
    return TRUE;
}

/**
 * Handler for setting a string field from a scalar node, inside a given struct
 * @entryptr: pointer to the beginning of the to-be-modified data structure
 * @data: offset into entryptr struct where the const char* field to write is
 *        located
 */
STATIC gboolean
handle_generic_str(NetplanParser* npp, yaml_node_t* node, void* entryptr, const void* data, __unused GError** error)
{
    g_assert(entryptr);
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) entryptr + offset);
    g_free(*dest);
    *dest = g_strescape(scalar(node), STRESCAPE_EXCEPTIONS);
    mark_data_as_dirty(npp, dest);
    return TRUE;
}

STATIC gboolean
handle_special_macaddress_option(NetplanParser* npp, yaml_node_t* node, void* entryptr, const void* data, GError** error)
{
    g_assert(entryptr);
    g_assert(node->type == YAML_SCALAR_NODE);

    if (!_is_macaddress_special_nm_option(scalar(node)) &&
        !_is_macaddress_special_nd_option(scalar(node)))
        return FALSE;

    return handle_generic_str(npp, node, entryptr, data, error);
}

/*
 * Handler for setting a MAC address field from a scalar node, inside a given struct
 * @entryptr: pointer to the beginning of the to-be-modified data structure
 * @data: offset into entryptr struct where the const char* field to write is
 *        located
 */
STATIC gboolean
handle_generic_mac(NetplanParser* npp, yaml_node_t* node, void* entryptr, const void* data, GError** error)
{
    g_assert(entryptr);
    g_assert(node->type == YAML_SCALAR_NODE);

    if (!_is_valid_macaddress(scalar(node)))
        return yaml_error(npp, node, error, "Invalid MAC address '%s', must be XX:XX:XX:XX:XX:XX or XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX", scalar(node));

    return handle_generic_str(npp, node, entryptr, data, error);
}

/*
 * Handler for setting a boolean field from a scalar node, inside a given struct
 * @entryptr: pointer to the beginning of the to-be-modified data structure
 * @data: offset into entryptr struct where the boolean field to write is located
 */
STATIC gboolean
handle_generic_bool(NetplanParser* npp, yaml_node_t* node, void* entryptr, const void* data, GError** error)
{
    g_assert(entryptr);
    guint offset = GPOINTER_TO_UINT(data);
    gboolean v;
    gboolean* dest = ((void*) entryptr + offset);

    if (g_ascii_strcasecmp(scalar(node), "true") == 0 ||
        g_ascii_strcasecmp(scalar(node), "on") == 0 ||
        g_ascii_strcasecmp(scalar(node), "yes") == 0 ||
        g_ascii_strcasecmp(scalar(node), "y") == 0)
        v = TRUE;
    else if (g_ascii_strcasecmp(scalar(node), "false") == 0 ||
        g_ascii_strcasecmp(scalar(node), "off") == 0 ||
        g_ascii_strcasecmp(scalar(node), "no") == 0 ||
        g_ascii_strcasecmp(scalar(node), "n") == 0)
        v = FALSE;
    else
        return yaml_error(npp, node, error, "invalid boolean value '%s'", scalar(node));

    *dest = v;
    mark_data_as_dirty(npp, dest);
    return TRUE;
}

/*
 * Handler for setting a HashTable field from a mapping node, inside a given struct
 * @entryptr: pointer to the beginning of the to-be-modified data structure
 * @data: offset into entryptr struct where the boolean field to write is located
 */
STATIC gboolean
handle_generic_tristate(NetplanParser* npp, yaml_node_t* node, void* entryptr, const void* data, GError** error)
{
    g_assert(entryptr);
    NetplanTristate v;
    guint offset = GPOINTER_TO_UINT(data);
    NetplanTristate* dest = ((void*) entryptr + offset);

    if (g_ascii_strcasecmp(scalar(node), "true") == 0 ||
        g_ascii_strcasecmp(scalar(node), "on") == 0 ||
        g_ascii_strcasecmp(scalar(node), "yes") == 0 ||
        g_ascii_strcasecmp(scalar(node), "y") == 0)
        v = NETPLAN_TRISTATE_TRUE;
    else if (g_ascii_strcasecmp(scalar(node), "false") == 0 ||
        g_ascii_strcasecmp(scalar(node), "off") == 0 ||
        g_ascii_strcasecmp(scalar(node), "no") == 0 ||
        g_ascii_strcasecmp(scalar(node), "n") == 0)
        v = NETPLAN_TRISTATE_FALSE;
    else
        return yaml_error(npp, node, error, "invalid boolean value '%s'", scalar(node));

    *dest = v;
    mark_data_as_dirty(npp, dest);
    return TRUE;
}

/*
 * Handler for setting a HashTable field from a mapping node, inside a given struct
 * @entryptr: pointer to the beginning of the to-be-modified data structure
 * @data: offset into entryptr struct where the boolean field to write is located
*/
STATIC gboolean
handle_generic_map(NetplanParser *npp, yaml_node_t* node, const char* key_prefix, void* entryptr, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    GHashTable** map = (GHashTable**) ((void*) entryptr + offset);
    if (!*map)
        *map = g_hash_table_new(g_str_hash, g_str_equal);

    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;

        key = yaml_document_get_node(&npp->doc, entry->key);
        value = yaml_document_get_node(&npp->doc, entry->value);

        assert_type(npp, key, YAML_SCALAR_NODE);
        assert_type(npp, value, YAML_SCALAR_NODE);

        g_autofree char* escaped_key = g_strescape(scalar(key), STRESCAPE_EXCEPTIONS);
        g_autofree char* escaped_value = g_strescape(scalar(value), STRESCAPE_EXCEPTIONS);

        if (key_prefix && npp->null_fields) {
            g_autofree char* full_key = NULL;
            full_key = g_strdup_printf("%s\t%s", key_prefix, escaped_key);
            if (g_hash_table_contains(npp->null_fields, full_key))
                continue;
        }

        char* stored_value = NULL;
        if (g_hash_table_lookup_extended(*map, escaped_key, NULL, (void**)&stored_value)) {
            /* We can safely skip this if it is the exact key/value match
             * (probably caused by multi-pass processing) */
            if (g_strcmp0(stored_value, escaped_value) == 0)
                continue;
            return yaml_error(npp, node, error, "duplicate map entry '%s'", escaped_key);
        } else
            g_hash_table_insert(*map, g_strdup(escaped_key), g_strdup(escaped_value));
    }
    mark_data_as_dirty(npp, map);

    return TRUE;
}

/*
 * Handler for setting a DataList field from a mapping node, inside a given struct
 * @entryptr: pointer to the beginning of the to-be-modified data structure
 * @data: offset into entryptr struct where the boolean field to write is located
*/
STATIC gboolean
handle_generic_datalist(NetplanParser *npp, yaml_node_t* node, const char* key_prefix, void* entryptr, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    GData** list = (GData**) ((void*) entryptr + offset);
    if (!*list)
        g_datalist_init(list);

    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        g_autofree char* full_key = NULL;
        g_autofree char* escaped_key = NULL;
        g_autofree char* escaped_value = NULL;

        key = yaml_document_get_node(&npp->doc, entry->key);
        value = yaml_document_get_node(&npp->doc, entry->value);

        assert_type(npp, key, YAML_SCALAR_NODE);
        assert_type(npp, value, YAML_SCALAR_NODE);

        escaped_key = g_strescape(scalar(key), STRESCAPE_EXCEPTIONS);
        escaped_value = g_strescape(scalar(value), STRESCAPE_EXCEPTIONS);

        if (npp->null_fields && key_prefix) {
            full_key = g_strdup_printf("%s\t%s", key_prefix, escaped_key);
            if (g_hash_table_contains(npp->null_fields, full_key))
                continue;
        }

        g_datalist_id_set_data_full(list, g_quark_from_string(escaped_key),
                                    g_strdup(escaped_value), g_free);
    }
    mark_data_as_dirty(npp, list);

    return TRUE;
}


/**
 * Generic handler for setting a npp->current.netdef string field from a scalar node
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
STATIC gboolean
handle_netdef_str(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_str(npp, node, npp->current.netdef, data, error);
}

/**
 * Generic handler for setting a npp->current.netdef ID/iface name field from a scalar node
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
STATIC gboolean
handle_netdef_id(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (!assert_valid_id(npp, node, error))
        return FALSE;
    return handle_netdef_str(npp, node, data, error);
}

STATIC gboolean
handle_embedded_switch_mode(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (g_strcmp0(scalar(node), "switchdev") != 0 && g_strcmp0(scalar(node), "legacy") != 0)
        return yaml_error(npp, node, error, "Value of 'embedded-switch-mode' needs to be 'switchdev' or 'legacy'");

    return handle_netdef_str(npp, node, data, error);
}

STATIC gboolean
handle_ib_mode(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    if (g_strcmp0(scalar(node), "datagram") == 0)
        npp->current.netdef->ib_mode = NETPLAN_IB_MODE_DATAGRAM;
    else if (g_strcmp0(scalar(node), "connected") == 0)
        npp->current.netdef->ib_mode = NETPLAN_IB_MODE_CONNECTED;
    else
        return yaml_error(npp, node, error, "Value of 'infiniband-mode' needs to be 'datagram' or 'connected'");
    return TRUE;
}

/**
 * Generic handler for setting a npp->current.netdef ID/iface name field referring to an
 * existing ID from a scalar node. This handler also includes a special case
 * handler for OVS VLANs, switching the backend implicitly to OVS for such
 * interfaces
 * @data: offset into NetplanNetDefinition where the NetplanNetDefinition* field to write is
 *        located
 */
STATIC gboolean
handle_netdef_id_ref(NetplanParser* npp, yaml_node_t* node, const void* data, __unused GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    NetplanNetDefinition* ref = NULL;
    NetplanNetDefinition** dest = (void*) npp->current.netdef + offset;

    ref = g_hash_table_lookup(npp->parsed_defs, scalar(node));
    if (!ref) {
        add_missing_node(npp, node);
    } else {
        NetplanNetDefinition* netdef = npp->current.netdef;
        *dest = ref;

        if (netdef->type == NETPLAN_DEF_TYPE_VLAN && ref->backend == NETPLAN_BACKEND_OVS) {
            g_debug("%s: VLAN defined for Open vSwitch interface, choosing OVS backend", netdef->id);
            netdef->backend = NETPLAN_BACKEND_OVS;
        }
    }
    mark_data_as_dirty(npp, dest);
    return TRUE;
}

/**
 * Handler for setting a npp->current.netdef ID/iface name field referring to an
 * existing ID from a scalar node.
 * @data: offset into NetplanVxlan where the NetplanNetDefinition* field to
 *        write is located
 */
STATIC gboolean
handle_vxlan_id_ref(NetplanParser* npp, yaml_node_t* node, const void* data, __unused GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    NetplanNetDefinition* ref = NULL;
    NetplanNetDefinition** dest = (void*) npp->current.vxlan + offset;

    ref = g_hash_table_lookup(npp->parsed_defs, scalar(node));
    if (!ref)
        add_missing_node(npp, node);
    else
        *dest = ref;
    mark_data_as_dirty(npp, dest);
    return TRUE;
}



/**
 * Generic handler for setting a npp->current.netdef match MAC address field from a scalar node
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
STATIC gboolean
handle_netdef_match_mac(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_mac(npp, node, npp->current.netdef, data, error);
}

/**
 * Generic handler for setting a npp->current.netdef MAC address field from a scalar node
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
STATIC gboolean
handle_netdef_set_mac(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    int res = handle_generic_mac(npp, node, npp->current.netdef, data, NULL);

    /* If the generic MAC parsing fails, we check to see if the value is one of the special values */
    if (!res) {
        if (!handle_special_macaddress_option(npp, node, npp->current.netdef, data, NULL)) {
            return yaml_error(npp, node, error,
                              "Invalid MAC address '%s', must be XX:XX:XX:XX:XX:XX, XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX:XX"
                              " or one of 'permanent', 'random', 'stable', 'preserve'.",
                              scalar(node));
        }
    }

    return TRUE;
}

/**
 * Generic handler for setting a npp->current.netdef gboolean field from a scalar node
 * @data: offset into NetplanNetDefinition where the gboolean field to write is located
 */
STATIC gboolean
handle_netdef_bool(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_bool(npp, node, npp->current.netdef, data, error);
}

/**
 * Generic handler for tri-state settings that can be "UNSET", "TRUE", or "FALSE".
 * @data: offset into NetplanNetDefinition where the guint field to write is located
 */
STATIC gboolean
handle_netdef_tristate(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_tristate(npp, node, npp->current.netdef, data, error);
}

/**
 * Generic handler for setting a npp->current.netdef guint field from a scalar node
 * @data: offset into NetplanNetDefinition where the guint field to write is located
 */
STATIC gboolean
handle_netdef_guint(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_guint(npp, node, npp->current.netdef, data, error);
}

STATIC gboolean
handle_netdef_ip4(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) npp->current.netdef + offset);
    g_autofree char* addr = NULL;
    char* prefix_len;

    /* these addresses can't have /prefix_len */
    addr = g_strdup(scalar(node));
    prefix_len = strrchr(addr, '/');

    /* FIXME: stop excluding this from coverage; refactor address handling instead */
    // LCOV_EXCL_START
    if (prefix_len)
        return yaml_error(npp, node, error,
                          "invalid address: a single IPv4 address (without /prefixlength) is required");

    /* is it an IPv4 address? */
    if (!is_ip4_address(addr))
        return yaml_error(npp, node, error,
                          "invalid IPv4 address: %s", scalar(node));
    // LCOV_EXCL_STOP

    g_free(*dest);
    *dest = g_strdup(scalar(node));
    mark_data_as_dirty(npp, dest);

    return TRUE;
}

STATIC gboolean
handle_netdef_ip6(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) npp->current.netdef + offset);
    g_autofree char* addr = NULL;
    char* prefix_len;

    /* these addresses can't have /prefix_len */
    addr = g_strdup(scalar(node));
    prefix_len = strrchr(addr, '/');

    /* FIXME: stop excluding this from coverage; refactor address handling instead */
    // LCOV_EXCL_START
    if (prefix_len)
        return yaml_error(npp, node, error,
                          "invalid address: a single IPv6 address (without /prefixlength) is required");

    /* is it an IPv6 address? */
    if (!is_ip6_address(addr))
        return yaml_error(npp, node, error,
                          "invalid IPv6 address: %s", scalar(node));
    // LCOV_EXCL_STOP

    g_free(*dest);
    *dest = g_strdup(scalar(node));
    mark_data_as_dirty(npp, dest);

    return TRUE;
}

STATIC gboolean
handle_netdef_addrgen(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    g_assert(npp->current.netdef);
    if (strcmp(scalar(node), "eui64") == 0)
        npp->current.netdef->ip6_addr_gen_mode = NETPLAN_ADDRGEN_EUI64;
    else if (strcmp(scalar(node), "stable-privacy") == 0)
        npp->current.netdef->ip6_addr_gen_mode = NETPLAN_ADDRGEN_STABLEPRIVACY;
    else
        return yaml_error(npp, node, error, "unknown ipv6-address-generation '%s'", scalar(node));
    return TRUE;
}

STATIC gboolean
handle_netdef_addrtok(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.netdef);
    gboolean ret = handle_netdef_str(npp, node, data, error);
    if (!is_ip6_address(npp->current.netdef->ip6_addr_gen_token))
        return yaml_error(npp, node, error, "invalid ipv6-address-token '%s'", scalar(node));
    return ret;
}

STATIC gboolean
handle_netdef_map(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, const void* data, GError** error)
{
    g_assert(npp->current.netdef);
    return handle_generic_map(npp, node, key_prefix, npp->current.netdef, data, error);
}

STATIC gboolean
handle_netdef_backend_settings_str(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    npp->current.netdef->has_backend_settings_nm = TRUE;
    return handle_generic_str(npp, node, npp->current.netdef, data, error);
}

/**
 * Generic handler for setting a npp->current.netdef use-domains field from a scalar node
 * @data: offset into NetplanNetDefinition where the use-domains field to write is located
 */
STATIC gboolean
handle_netdef_use_domains(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    NetplanUseDomainMode v;
    guint offset = GPOINTER_TO_UINT(data);
    NetplanUseDomainMode* dest = ((void*) npp->current.netdef + offset);

    gboolean ret = handle_generic_bool(npp, node, npp->current.netdef, data, NULL);

    if (ret) {
        if (*dest) {
            v = NETPLAN_USE_DOMAIN_MODE_TRUE;
        } else {
            v = NETPLAN_USE_DOMAIN_MODE_FALSE;
        }
    } else if (g_ascii_strcasecmp(scalar(node), "route") == 0) {
        v = NETPLAN_USE_DOMAIN_MODE_ROUTE;
    } else {
        return yaml_error(npp, node, error,
                          "Invalid use-domains options '%s', must be a boolean, or the special value 'route'.",
                          scalar(node));
    }

    *dest = v;
    mark_data_as_dirty(npp, dest);
    return TRUE;
}

/*
 * Check if the passthrough key format is incorrect and remove it from the list.
 * user_data is expected to contain a pointer to the GData list.
 */
STATIC void
validate_kf_group_key(GQuark key_id, __unused gpointer value, gpointer user_data)
{
    GArray* bad_keys = user_data;
    const gchar* key = g_quark_to_string(key_id);
    gchar** group_key = g_strsplit(key, ".", -1);
    if (g_strv_length(group_key) < 2) {
        g_warning("NetworkManager: passthrough key '%s' format is invalid, should be 'group.key'.", key);
        g_array_append_val(bad_keys, key_id);
    }
    g_strfreev(group_key);
}

STATIC gboolean
handle_netdef_passthrough_datalist(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, const void* data, GError** error)
{
    g_assert(npp->current.netdef);
    gboolean ret = handle_generic_datalist(npp, node, key_prefix, npp->current.netdef, data, error);

    GData** list = &npp->current.netdef->backend_settings.passthrough;
    GArray* bad_keys = g_array_new(FALSE, FALSE, sizeof(GQuark));

    /* Validate and remove passthrough keys that are not in the
     * expected format (group.key)
     */
    g_datalist_foreach(list, validate_kf_group_key, bad_keys);

    for (unsigned int i = 0; i < bad_keys->len; i++) {
        GQuark bad_quark = g_array_index(bad_keys, GQuark, i);
        g_datalist_id_remove_data(list, bad_quark);
    }

    g_array_free(bad_keys, TRUE);

    if (*list == NULL) {
        g_datalist_clear(list);
    }

    npp->current.netdef->has_backend_settings_nm = TRUE;

    return ret;
}

STATIC gboolean
handle_veth_peer(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    NetplanNetDefinition* netdef = npp->current.netdef;

    if (!g_strcmp0(netdef->id, scalar(node)))
        return yaml_error(npp, node, error, "%s: virtual-ethernet peer cannot be itself", netdef->id);

    NetplanNetDefinition* link = g_hash_table_lookup(npp->parsed_defs, scalar(node));
    if (link) {
        if (link->type != NETPLAN_DEF_TYPE_VETH && link->type != NETPLAN_DEF_TYPE_NM_PLACEHOLDER_)
            return yaml_error(npp, node, error, "%s: virtual-ethernet peer '%s' is not a virtual-ethernet interface", netdef->id, link->id);

        if (link->veth_peer_link && link->veth_peer_link != netdef)
            return yaml_error(npp, node, error, "%s: virtual-ethernet peer '%s' is another virtual-ethernet's (%s) peer already",
                              netdef->id, link->id, link->veth_peer_link->id);

        netdef->veth_peer_link = link;
        link->veth_peer_link = netdef;

        return TRUE;
    }

    add_missing_node(npp, node);

    return TRUE;
}


/****************************************************
 * Grammar and handlers for network config "match" entry
 ****************************************************/

STATIC gboolean
handle_match_driver(NetplanParser* npp, yaml_node_t* node, __unused const char* key_prefix, __unused const void* _, GError** error)
{
    gboolean ret = FALSE;
    yaml_node_t *elem = NULL;
    g_autoptr(GString) sequence = NULL;

    /* We overload the 'driver' setting for matches; such that it can either be a
     * single scalar specifying a single driver glob/match, or a sequence of many
     * globs any of which must match. */
    if (node->type == YAML_SCALAR_NODE) {
        if (g_strrstr(scalar(node), " "))
            return yaml_error(npp, node, error, "A 'driver' glob cannot contain whitespace");
        ret = handle_netdef_str(npp, node, netdef_offset(match.driver), error);
    } else if (node->type == YAML_SEQUENCE_NODE) {
        for (yaml_node_item_t *iter = node->data.sequence.items.start; iter < node->data.sequence.items.top; iter++) {
            elem = yaml_document_get_node(&npp->doc, *iter);
            assert_type(npp, elem, YAML_SCALAR_NODE);
            g_autofree char* escaped_elem = g_strescape(scalar(elem), STRESCAPE_EXCEPTIONS);
            if (g_strrstr(escaped_elem, " "))
                return yaml_error(npp, node, error, "A 'driver' glob cannot contain whitespace");

            if (!sequence)
                sequence = g_string_new(escaped_elem);
            else
                g_string_append_printf(sequence, "\t%s", escaped_elem); /* tab separated */
        }

        if (!sequence)
            return yaml_error(npp, node, error, "invalid sequence for 'driver'");

        npp->current.netdef->match.driver = g_strdup(sequence->str);
        ret = TRUE;
    } else
        return yaml_error(npp, node, error, "invalid type for 'driver': must be a scalar or a sequence of scalars");

    return ret;
}

STATIC const mapping_entry_handler match_handlers[] = {
    {"driver", YAML_NO_NODE, {.variable=handle_match_driver}, NULL},
    {"macaddress", YAML_SCALAR_NODE, {.generic=handle_netdef_match_mac}, netdef_offset(match.mac)},
    {"name", YAML_SCALAR_NODE, {.generic=handle_netdef_id}, netdef_offset(match.original_name)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network config "auth" entry
 ****************************************************/

STATIC gboolean
handle_auth_str(NetplanParser* npp, yaml_node_t* node, const void* data, __unused GError** error)
{
    g_assert(npp->current.auth);
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) npp->current.auth + offset);
    g_free(*dest);
    *dest = g_strescape(scalar(node), STRESCAPE_EXCEPTIONS);
    mark_data_as_dirty(npp, dest);
    return TRUE;
}

STATIC gboolean
handle_auth_key_management(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    NetplanAuthenticationSettings* auth = npp->current.auth;
    g_assert(auth);
    if (strcmp(scalar(node), "none") == 0)
        auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_NONE;
    else if (strcmp(scalar(node), "psk") == 0)
        auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK;
    else if (strcmp(scalar(node), "eap") == 0)
        auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP;
    else if (strcmp(scalar(node), "eap-sha256") == 0) {
        /* WPA-EAP-SHA256 is commonly used with Protected Management Frames
         * so let's set it as optional
         */
        auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAPSHA256;
        auth->pmf_mode = NETPLAN_AUTH_PMF_MODE_OPTIONAL;
    }
    else if (strcmp(scalar(node), "eap-suite-b-192") == 0) {
        /* Settings for WPA3-Enterprise for sensitive enterprise environments.
         * Protected Management Frames (ieee80211w) is mandatory.
         */
        auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAPSUITE_B_192;
        auth->pmf_mode = NETPLAN_AUTH_PMF_MODE_REQUIRED;
    }
    else if (strcmp(scalar(node), "sae") == 0) {
        /* SAE is used by WPA3 and Protected Management Frames
         * (ieee80211w) is mandatory.
         */
        auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_SAE;
        auth->pmf_mode = NETPLAN_AUTH_PMF_MODE_REQUIRED;
    }
    else if (strcmp(scalar(node), "802.1x") == 0)
        auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_8021X;
    else
        return yaml_error(npp, node, error, "unknown key management type '%s'", scalar(node));
    return TRUE;
}

STATIC gboolean
handle_auth_method(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    NetplanAuthenticationSettings* auth = npp->current.auth;
    g_assert(auth);
    if (strcmp(scalar(node), "tls") == 0)
        auth->eap_method = NETPLAN_AUTH_EAP_TLS;
    else if (strcmp(scalar(node), "peap") == 0)
        auth->eap_method = NETPLAN_AUTH_EAP_PEAP;
    else if (strcmp(scalar(node), "ttls") == 0)
        auth->eap_method = NETPLAN_AUTH_EAP_TTLS;
    else if (strcmp(scalar(node), "leap") == 0)
        auth->eap_method = NETPLAN_AUTH_EAP_LEAP;
    else if (strcmp(scalar(node), "pwd") == 0)
        auth->eap_method = NETPLAN_AUTH_EAP_PWD;
    else
        return yaml_error(npp, node, error, "unknown EAP method '%s'", scalar(node));
    return TRUE;
}

STATIC const mapping_entry_handler auth_handlers[] = {
    {"key-management", YAML_SCALAR_NODE, {.generic=handle_auth_key_management}, NULL},
    {"method", YAML_SCALAR_NODE, {.generic=handle_auth_method}, NULL},
    {"identity", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(identity)},
    {"anonymous-identity", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(anonymous_identity)},
    {"password", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(password)},
    {"ca-certificate", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(ca_certificate)},
    {"client-certificate", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(client_certificate)},
    {"client-key", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(client_key)},
    {"client-key-password", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(client_key_password)},
    {"phase2-auth", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(phase2_auth)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network device definition
 ****************************************************/

NetplanBackend
get_default_backend_for_type(NetplanBackend global_backend, __unused NetplanDefType type)
{
    if (global_backend != NETPLAN_BACKEND_NONE)
        return global_backend;

    /* networkd can handle all device types at the moment, so nothing
     * type-specific */
    return NETPLAN_BACKEND_NETWORKD;
}

STATIC gboolean
handle_ap_backend_settings_str(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    npp->current.netdef->has_backend_settings_nm = TRUE;
    return handle_generic_str(npp, node, npp->current.access_point, data, error);
}

STATIC gboolean
handle_access_point_datalist(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, const void* data, GError** error)
{
    g_assert(npp->current.access_point);
    gboolean ret = handle_generic_datalist(npp, node, key_prefix, npp->current.access_point, data, error);

    GData** list = &npp->current.access_point->backend_settings.passthrough;
    GArray* bad_keys = g_array_new(FALSE, FALSE, sizeof(GQuark));

    /* Validate and remove passthrough keys that are not in the
     * expected format (group.key)
     */
    g_datalist_foreach(list, validate_kf_group_key, bad_keys);

    for (unsigned int i = 0; i < bad_keys->len; i++) {
        GQuark bad_quark = g_array_index(bad_keys, GQuark, i);
        g_datalist_id_remove_data(list, bad_quark);
    }

    g_array_free(bad_keys, TRUE);

    if (*list == NULL) {
        g_datalist_clear(list);
    }

    npp->current.netdef->has_backend_settings_nm = TRUE;

    return ret;
}

STATIC gboolean
handle_access_point_guint(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_guint(npp, node, npp->current.access_point, data, error);
}

STATIC gboolean
handle_access_point_mac(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_mac(npp, node, npp->current.access_point, data, error);
}

STATIC gboolean
handle_access_point_bool(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_bool(npp, node, npp->current.access_point, data, error);
}

STATIC gboolean
handle_access_point_password(NetplanParser* npp, yaml_node_t* node, __unused const void* _, __unused GError** error)
{
    NetplanWifiAccessPoint *access_point = npp->current.access_point;
    g_assert(access_point);
    /* shortcut for WPA-PSK */
    access_point->has_auth = TRUE;
    if (access_point->auth.key_management == NETPLAN_AUTH_KEY_MANAGEMENT_NONE)
        access_point->auth.key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK;

    access_point->auth.pmf_mode = NETPLAN_AUTH_PMF_MODE_OPTIONAL;
    g_free(access_point->auth.psk);
    access_point->auth.psk = g_strescape(scalar(node), STRESCAPE_EXCEPTIONS);
    return TRUE;
}

STATIC gboolean
handle_access_point_auth(NetplanParser* npp, yaml_node_t* node, __unused const char* key_prefix, __unused const void* _, GError** error)
{
    NetplanWifiAccessPoint *access_point = npp->current.access_point;
    gboolean ret;

    g_assert(access_point);
    access_point->has_auth = TRUE;

    npp->current.auth = &access_point->auth;
    ret = process_mapping(npp, node, NULL, auth_handlers, NULL, error);
    npp->current.auth = NULL;

    return ret;
}

STATIC gboolean
handle_access_point_mode(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    NetplanWifiAccessPoint *access_point = npp->current.access_point;
    g_assert(access_point);
    if (strcmp(scalar(node), "infrastructure") == 0)
        access_point->mode = NETPLAN_WIFI_MODE_INFRASTRUCTURE;
    else if (strcmp(scalar(node), "adhoc") == 0)
        access_point->mode = NETPLAN_WIFI_MODE_ADHOC;
    else if (strcmp(scalar(node), "ap") == 0)
        access_point->mode = NETPLAN_WIFI_MODE_AP;
    else
        return yaml_error(npp, node, error, "unknown wifi mode '%s'", scalar(node));
    return TRUE;
}

STATIC gboolean
handle_access_point_band(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    NetplanWifiAccessPoint *access_point = npp->current.access_point;
    g_assert(access_point);
    if (strcmp(scalar(node), "5GHz") == 0 || strcmp(scalar(node), "5G") == 0)
        access_point->band = NETPLAN_WIFI_BAND_5;
    else if (strcmp(scalar(node), "2.4GHz") == 0 || strcmp(scalar(node), "2.4G") == 0)
        access_point->band = NETPLAN_WIFI_BAND_24;
    else
        return yaml_error(npp, node, error, "unknown wifi band '%s'", scalar(node));
    return TRUE;
}

STATIC gboolean
handle_tunnel_key_flags(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        gboolean found = FALSE;
        assert_type(npp, entry, YAML_SCALAR_NODE);

        for (int i = 1; i < NETPLAN_KEY_FLAG_MAX_; i <<= 1) {
            if (!g_ascii_strcasecmp(scalar(entry), netplan_key_flags_name(i))) {
                npp->current.netdef->tunnel_private_key_flags |= i;
                found = TRUE;
            }
        }

        if (!found)
            return yaml_error(npp, node, error,
                              "Key flag '%s' is not supported. Valid values are \"agent-owned\", \"not-saved\" and \"not-required\"",
                              scalar(entry));
    }
    return TRUE;
}

/* Keep in sync with ap_nm_backend_settings_handlers */
static const mapping_entry_handler nm_backend_settings_handlers[] = {
    {"name", YAML_SCALAR_NODE, {.generic=handle_netdef_backend_settings_str}, netdef_offset(backend_settings.name)},
    {"uuid", YAML_SCALAR_NODE, {.generic=handle_netdef_backend_settings_str}, netdef_offset(backend_settings.uuid)},
    {"stable-id", YAML_SCALAR_NODE, {.generic=handle_netdef_backend_settings_str}, netdef_offset(backend_settings.stable_id)},
    {"device", YAML_SCALAR_NODE, {.generic=handle_netdef_backend_settings_str}, netdef_offset(backend_settings.device)},
    /* Fallback mode, to support all NM settings of the NetworkManager netplan backend */
    {"passthrough", YAML_MAPPING_NODE, {.map={.custom=handle_netdef_passthrough_datalist}}, netdef_offset(backend_settings.passthrough)},
    {NULL}
};

/* Keep in sync with nm_backend_settings_handlers */
static const mapping_entry_handler ap_nm_backend_settings_handlers[] = {
    {"name", YAML_SCALAR_NODE, {.generic=handle_ap_backend_settings_str}, access_point_offset(backend_settings.name)},
    {"uuid", YAML_SCALAR_NODE, {.generic=handle_ap_backend_settings_str}, access_point_offset(backend_settings.uuid)},
    {"stable-id", YAML_SCALAR_NODE, {.generic=handle_ap_backend_settings_str}, access_point_offset(backend_settings.stable_id)},
    {"device", YAML_SCALAR_NODE, {.generic=handle_ap_backend_settings_str}, access_point_offset(backend_settings.device)},
    /* Fallback mode, to support all NM settings of the NetworkManager netplan backend */
    {"passthrough", YAML_MAPPING_NODE, {.map={.custom=handle_access_point_datalist}}, access_point_offset(backend_settings.passthrough)},
    {NULL}
};


static const mapping_entry_handler wifi_access_point_handlers[] = {
    {"band", YAML_SCALAR_NODE, {.generic=handle_access_point_band}, NULL},
    {"bssid", YAML_SCALAR_NODE, {.generic=handle_access_point_mac}, access_point_offset(bssid)},
    {"hidden", YAML_SCALAR_NODE, {.generic=handle_access_point_bool}, access_point_offset(hidden)},
    {"channel", YAML_SCALAR_NODE, {.generic=handle_access_point_guint}, access_point_offset(channel)},
    {"mode", YAML_SCALAR_NODE, {.generic=handle_access_point_mode}, NULL},
    {"password", YAML_SCALAR_NODE, {.generic=handle_access_point_password}, NULL},
    {"auth", YAML_MAPPING_NODE, {.map={.custom=handle_access_point_auth}}, NULL},
    {"networkmanager", YAML_MAPPING_NODE, {.map={.handlers=ap_nm_backend_settings_handlers}}, NULL},
    {NULL}
};

/**
 * Parse scalar node's string into a netdef_backend.
 */
STATIC gboolean
parse_renderer(NetplanParser* npp, yaml_node_t* node, NetplanBackend* backend, GError** error)
{
    if (strcmp(scalar(node), "networkd") == 0)
        *backend = NETPLAN_BACKEND_NETWORKD;
    else if (strcmp(scalar(node), "NetworkManager") == 0)
        *backend = NETPLAN_BACKEND_NM;
    else
        return yaml_error(npp, node, error, "unknown renderer '%s'", scalar(node));
    mark_data_as_dirty(npp, backend);
    return TRUE;
}

STATIC gboolean
handle_netdef_renderer(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    if (npp->current.netdef->type == NETPLAN_DEF_TYPE_VLAN) {
        if (strcmp(scalar(node), "sriov") == 0) {
            npp->current.netdef->sriov_vlan_filter = TRUE;
            return TRUE;
        }
    }

    return parse_renderer(npp, node, &npp->current.netdef->backend, error);
}

STATIC gboolean
handle_accept_ra(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    gboolean ret = handle_generic_bool(npp, node, npp->current.netdef, data, error);
    if (npp->current.netdef->accept_ra)
        npp->current.netdef->accept_ra = NETPLAN_RA_MODE_ENABLED;
    else
        npp->current.netdef->accept_ra = NETPLAN_RA_MODE_DISABLED;
    return ret;
}

STATIC gboolean
handle_activation_mode(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (g_strcmp0(scalar(node), "manual") && g_strcmp0(scalar(node), "off"))
        return yaml_error(npp, node, error, "Value of 'activation-mode' needs to be 'manual' or 'off'");

    return handle_netdef_str(npp, node, data, error);
}

STATIC gboolean
handle_match(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* _, GError** error)
{
    npp->current.netdef->has_match = TRUE;
    return process_mapping(npp, node, key_prefix, match_handlers, NULL, error);
}

struct NetplanWifiWowlanType
NETPLAN_WIFI_WOWLAN_TYPES[] = {
    {"default",            NETPLAN_WIFI_WOWLAN_DEFAULT},
    {"any",                NETPLAN_WIFI_WOWLAN_ANY},
    {"disconnect",         NETPLAN_WIFI_WOWLAN_DISCONNECT},
    {"magic_pkt",          NETPLAN_WIFI_WOWLAN_MAGIC},
    {"gtk_rekey_failure",  NETPLAN_WIFI_WOWLAN_GTK_REKEY_FAILURE},
    {"eap_identity_req",   NETPLAN_WIFI_WOWLAN_EAP_IDENTITY_REQ},
    {"four_way_handshake", NETPLAN_WIFI_WOWLAN_4WAY_HANDSHAKE},
    {"rfkill_release",     NETPLAN_WIFI_WOWLAN_RFKILL_RELEASE},
    {"tcp",                NETPLAN_WIFI_WOWLAN_TCP},
    {NULL},
};

STATIC gboolean
handle_wowlan(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        assert_type(npp, entry, YAML_SCALAR_NODE);
        int found = FALSE;

        for (unsigned i = 0; NETPLAN_WIFI_WOWLAN_TYPES[i].name != NULL; ++i) {
            if (g_ascii_strcasecmp(scalar(entry), NETPLAN_WIFI_WOWLAN_TYPES[i].name) == 0) {
                npp->current.netdef->wowlan |= NETPLAN_WIFI_WOWLAN_TYPES[i].flag;
                found = TRUE;
                break;
            }
        }
        if (!found)
            return yaml_error(npp, node, error, "invalid value for wakeonwlan: '%s'", scalar(entry));
    }
    if (npp->current.netdef->wowlan > NETPLAN_WIFI_WOWLAN_DEFAULT && npp->current.netdef->wowlan & NETPLAN_WIFI_WOWLAN_TYPES[0].flag)
        return yaml_error(npp, node, error, "'default' is an exclusive flag for wakeonwlan");
    return TRUE;
}

STATIC gboolean
handle_auth(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* _, GError** error)
{
    gboolean ret;

    npp->current.netdef->has_auth = TRUE;

    npp->current.auth = &npp->current.netdef->auth;
    ret = process_mapping(npp, node, key_prefix, auth_handlers, NULL, error);
    mark_data_as_dirty(npp, &npp->current.netdef->auth);
    npp->current.auth = NULL;

    return ret;
}

STATIC gboolean
handle_address_option_lifetime(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (g_ascii_strcasecmp(scalar(node), "0") != 0 &&
        g_ascii_strcasecmp(scalar(node), "forever") != 0) {
        return yaml_error(npp, node, error, "invalid lifetime value '%s'", scalar(node));
    }
    return handle_generic_str(npp, node, npp->current.addr_options, data, error);
}

STATIC gboolean
handle_address_option_label(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_generic_str(npp, node, npp->current.addr_options, data, error);
}

const mapping_entry_handler address_option_handlers[] = {
    {"lifetime", YAML_SCALAR_NODE, {.generic=handle_address_option_lifetime}, addr_option_offset(lifetime)},
    {"label", YAML_SCALAR_NODE, {.generic=handle_address_option_label}, addr_option_offset(label)},
    {NULL}
};

/*
 * Handler for setting an array of IP addresses from a sequence node, inside a given struct
 * @entryptr: pointer to the beginning of the do-be-modified data structure
 * @data: offset into entryptr struct where the array to write is located
 */
STATIC gboolean
handle_generic_addresses(NetplanParser* npp, yaml_node_t* node, gboolean check_zero_prefix, GArray** ip4, GArray** ip6, GError** error)
{
    g_assert(ip4);
    g_assert(ip6);
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        g_autofree char* addr = NULL;
        char* prefix_len;
        guint64 prefix_len_num;
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        yaml_node_t *key = NULL;
        yaml_node_t *value = NULL;

        if (entry->type != YAML_SCALAR_NODE && entry->type != YAML_MAPPING_NODE) {
            return yaml_error(npp, entry, error, "expected either scalar or mapping (check indentation)");
        }

        if (entry->type == YAML_MAPPING_NODE) {
            key = yaml_document_get_node(&npp->doc, entry->data.mapping.pairs.start->key);
            value = yaml_document_get_node(&npp->doc, entry->data.mapping.pairs.start->value);
            entry = key;
        }
        assert_type(npp, entry, YAML_SCALAR_NODE);

        /* split off /prefix_len */
        addr = g_strdup(scalar(entry));
        prefix_len = strrchr(addr, '/');
        if (!prefix_len)
            return yaml_error(npp, node, error, "address '%s' is missing /prefixlength", scalar(entry));
        *prefix_len = '\0';
        prefix_len++; /* skip former '/' into first char of prefix */
        prefix_len_num = g_ascii_strtoull(prefix_len, NULL, 10);

        if (value) {
            if (!is_ip4_address(addr) && !is_ip6_address(addr))
                return yaml_error(npp, node, error, "malformed address '%s', must be X.X.X.X/NN or X:X:X:X:X:X:X:X/NN", scalar(entry));

            if (!npp->current.netdef->address_options)
                npp->current.netdef->address_options = g_array_new(FALSE, FALSE, sizeof(NetplanAddressOptions*));

            for (unsigned i = 0; i < npp->current.netdef->address_options->len; ++i) {
                NetplanAddressOptions* opts = g_array_index(npp->current.netdef->address_options, NetplanAddressOptions*, i);
                /* check for multi-pass parsing, return early if options for this address already exist */
                if (!g_strcmp0(scalar(key), opts->address))
                    return TRUE;
            }

            npp->current.addr_options = g_new0(NetplanAddressOptions, 1);
            npp->current.addr_options->address = g_strdup(scalar(key));

            if (!process_mapping(npp, value, NULL, address_option_handlers, NULL, error))
                return FALSE;

            g_array_append_val(npp->current.netdef->address_options, npp->current.addr_options);
            mark_data_as_dirty(npp, &npp->current.netdef->address_options);
            npp->current.addr_options = NULL;

            continue;
        }

        /* is it an IPv4 address? */
        if (is_ip4_address(addr)) {
            if ((check_zero_prefix && prefix_len_num == 0) || prefix_len_num > 32)
                return yaml_error(npp, node, error, "invalid prefix length in address '%s'", scalar(entry));

            if (!*ip4)
                *ip4 = g_array_new(FALSE, FALSE, sizeof(char*));

            /* Do not append the same IP (on multiple passes), if it is already contained */
            for (unsigned i = 0; i < (*ip4)->len; ++i)
                if (!g_strcmp0(scalar(entry), g_array_index(*ip4, char*, i)))
                    goto skip_ip4;
            char* s = g_strdup(scalar(entry));
            g_array_append_val(*ip4, s);
            mark_data_as_dirty(npp, ip4);
skip_ip4:
            continue;
        }

        /* is it an IPv6 address? */
        if (is_ip6_address(addr)) {
            if ((check_zero_prefix && prefix_len_num == 0) || prefix_len_num > 128)
                return yaml_error(npp, node, error, "invalid prefix length in address '%s'", scalar(entry));
            if (!*ip6)
                *ip6 = g_array_new(FALSE, FALSE, sizeof(char*));

            /* Do not append the same IP (on multiple passes), if it is already contained */
            for (unsigned i = 0; i < (*ip6)->len; ++i)
                if (!g_strcmp0(scalar(entry), g_array_index(*ip6, char*, i)))
                    goto skip_ip6;
            char* s = g_strdup(scalar(entry));
            g_array_append_val(*ip6, s);
            mark_data_as_dirty(npp, ip6);
skip_ip6:
            continue;
        }

        return yaml_error(npp, node, error, "malformed address '%s', must be X.X.X.X/NN or X:X:X:X:X:X:X:X/NN", scalar(entry));
    }

    return TRUE;
}

STATIC gboolean
handle_addresses(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    return handle_generic_addresses(npp, node, TRUE, &(npp->current.netdef->ip4_addresses), &(npp->current.netdef->ip6_addresses), error);
}

STATIC gboolean
handle_gateway4(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    if (!is_ip4_address(scalar(node)))
        return yaml_error(npp, node, error, "invalid IPv4 address '%s'", scalar(node));
    if (npp->current.netdef->gateway4) {
        g_free(npp->current.netdef->gateway4);
        npp->current.netdef->gateway4 = NULL;
    }
    set_str_if_null(npp->current.netdef->gateway4, scalar(node));
    mark_data_as_dirty(npp, &npp->current.netdef->gateway4);
    g_warning("`gateway4` has been deprecated, use default routes instead.\n"
              "See the 'Default routes' section of the documentation for more details.");
    return TRUE;
}

STATIC gboolean
handle_gateway6(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    if (!is_ip6_address(scalar(node)))
        return yaml_error(npp, node, error, "invalid IPv6 address '%s'", scalar(node));
    if (npp->current.netdef->gateway6) {
        g_free(npp->current.netdef->gateway6);
        npp->current.netdef->gateway6 = NULL;
    }
    set_str_if_null(npp->current.netdef->gateway6, scalar(node));
    mark_data_as_dirty(npp, &npp->current.netdef->gateway6);
    g_warning("`gateway6` has been deprecated, use default routes instead.\n"
              "See the 'Default routes' section of the documentation for more details.");
    return TRUE;
}

STATIC gboolean
handle_wifi_access_points(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* data, GError** error)
{
    GHashTable* access_points = g_hash_table_new(g_str_hash, g_str_equal);

    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        NetplanWifiAccessPoint *access_point = NULL;
        g_autofree char* full_key = NULL;
        g_autofree char* escaped_key = NULL;
        yaml_node_t* key, *value;
        const gchar* ssid;

        key = yaml_document_get_node(&npp->doc, entry->key);
        assert_type(npp, key, YAML_SCALAR_NODE);
        value = yaml_document_get_node(&npp->doc, entry->value);
        assert_type(npp, value, YAML_MAPPING_NODE);

        escaped_key = g_strescape(scalar(key), STRESCAPE_EXCEPTIONS);

        if (key_prefix && npp->null_fields) {
            full_key = g_strdup_printf("%s\t%s", key_prefix, escaped_key);
            if (g_hash_table_contains(npp->null_fields, full_key))
                continue;
        }

        ssid = escaped_key;

        /*
         * Delete the access-point if it already exists in the netdef and let the new
         * one be added. It has the side effect of reprocessing APs if the parser requires a
         * second pass.
         *
         * TODO: implement support for merging AP settings if they were previously defined
         */
        if (npp->current.netdef->access_points && g_hash_table_contains(npp->current.netdef->access_points, ssid)) {
            NetplanWifiAccessPoint *ap = g_hash_table_lookup(npp->current.netdef->access_points, ssid);
            g_hash_table_remove(npp->current.netdef->access_points, ssid);
            free_access_point(NULL, ap, NULL);
        }

        /* Check if the SSID was already defined in the same netdef in this YAML file we are parsing */
        if (g_hash_table_contains(access_points, ssid)) {
            g_hash_table_foreach(access_points, free_access_point, NULL);
            g_hash_table_destroy(access_points);
            return yaml_error(npp, key, error, "%s: Duplicate access point SSID '%s'", npp->current.netdef->id, ssid);
        }

        g_assert(access_point == NULL);
        access_point = g_new0(NetplanWifiAccessPoint, 1);
        access_point->ssid = g_strdup(ssid);
        g_debug("%s: adding wifi AP '%s'", npp->current.netdef->id, access_point->ssid);

        npp->current.access_point = access_point;
        if (!process_mapping(npp, value, full_key, wifi_access_point_handlers, NULL, error)) {
            access_point_clear(&npp->current.access_point, npp->current.backend);
            g_hash_table_foreach(access_points, free_access_point, NULL);
            g_hash_table_destroy(access_points);
            return FALSE;
        }

        g_hash_table_insert(access_points, access_point->ssid, access_point);
        npp->current.access_point = NULL;
    }

    if (g_hash_table_size(access_points) > 0) {
        if (!npp->current.netdef->access_points)
            npp->current.netdef->access_points = g_hash_table_new(g_str_hash, g_str_equal);
        g_hash_table_foreach_steal(access_points, insert_kv_into_hash, npp->current.netdef->access_points);
        mark_data_as_dirty(npp, &npp->current.netdef->access_points);
    }
    g_hash_table_destroy(access_points);
    return TRUE;
}

/**
 * Handler for bridge "interfaces:" list. We don't store that list in npp->current.netdef,
 * but set npp->current.netdef's ID in all listed interfaces' "bond" or "bridge" field.
 * @data: ignored
 */
STATIC gboolean
handle_bridge_interfaces(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    /* all entries must refer to already defined IDs */
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        NetplanNetDefinition *component;

        assert_type(npp, entry, YAML_SCALAR_NODE);
        component = g_hash_table_lookup(npp->parsed_defs, scalar(entry));
        if (!component) {
            add_missing_node(npp, entry);
        } else {
            if (component->bridge && g_strcmp0(component->bridge, npp->current.netdef->id) != 0)
                return yaml_error(npp, node, error, "%s: interface '%s' is already assigned to bridge %s",
                                  npp->current.netdef->id, scalar(entry), component->bridge);
            if (component->bond)
                return yaml_error(npp, node, error, "%s: interface '%s' is already assigned to bond %s",
                                  npp->current.netdef->id, scalar(entry), component->bond);
            set_str_if_null(component->bridge, npp->current.netdef->id);
            component->bridge_link = npp->current.netdef;
            if (component->backend == NETPLAN_BACKEND_OVS) {
                g_debug("%s: Bridge contains Open vSwitch interface, choosing OVS backend", npp->current.netdef->id);
                npp->current.netdef->backend = NETPLAN_BACKEND_OVS;
            }
        }
    }

    return TRUE;
}

/**
 * Handler for bond "mode" types.
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
STATIC gboolean
handle_bond_mode(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (!(strcmp(scalar(node), "balance-rr") == 0 ||
        strcmp(scalar(node), "active-backup") == 0 ||
        strcmp(scalar(node), "balance-xor") == 0 ||
        strcmp(scalar(node), "broadcast") == 0 ||
        strcmp(scalar(node), "802.3ad") == 0 ||
        strcmp(scalar(node), "balance-tlb") == 0 ||
        strcmp(scalar(node), "balance-alb") == 0 ||
        strcmp(scalar(node), "balance-tcp") == 0 || // only supported for OVS
        strcmp(scalar(node), "balance-slb") == 0))  // only supported for OVS
        return yaml_error(npp, node, error, "unknown bond mode '%s'", scalar(node));

    /* Implicitly set NETPLAN_BACKEND_OVS if ovs-only mode selected */
    if (!strcmp(scalar(node), "balance-tcp") ||
        !strcmp(scalar(node), "balance-slb")) {
        g_debug("%s: mode '%s' only supported with Open vSwitch, choosing this backend",
                npp->current.netdef->id, scalar(node));
        npp->current.netdef->backend = NETPLAN_BACKEND_OVS;
    }

    return handle_netdef_str(npp, node, data, error);
}

/**
 * Handler for bond "interfaces:" list.
 * @data: ignored
 */
STATIC gboolean
handle_bond_interfaces(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    /* all entries must refer to already defined IDs */
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        NetplanNetDefinition *component;

        assert_type(npp, entry, YAML_SCALAR_NODE);
        component = g_hash_table_lookup(npp->parsed_defs, scalar(entry));
        if (!component) {
            add_missing_node(npp, entry);
        } else {
            if (component->bridge)
                return yaml_error(npp, node, error, "%s: interface '%s' is already assigned to bridge %s",
                                  npp->current.netdef->id, scalar(entry), component->bridge);
            if (component->bond && g_strcmp0(component->bond, npp->current.netdef->id) != 0)
                return yaml_error(npp, node, error, "%s: interface '%s' is already assigned to bond %s",
                                  npp->current.netdef->id, scalar(entry), component->bond);
            if (!component->bond) {
                component->bond = g_strdup(npp->current.netdef->id);
                component->bond_link = npp->current.netdef;
            }
            if (component->backend == NETPLAN_BACKEND_OVS) {
                g_debug("%s: Bond contains Open vSwitch interface, choosing OVS backend", npp->current.netdef->id);
                npp->current.netdef->backend = NETPLAN_BACKEND_OVS;
            }
        }
    }

    return TRUE;
}

STATIC gboolean
handle_nameservers_search(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        assert_type(npp, entry, YAML_SCALAR_NODE);
        g_autofree char* escaped_entry = g_strescape(scalar(entry), STRESCAPE_EXCEPTIONS);

        if (!npp->current.netdef->search_domains)
            npp->current.netdef->search_domains = g_array_new(FALSE, FALSE, sizeof(char*));

        if (!is_string_in_array(npp->current.netdef->search_domains, escaped_entry)) {
            char* s = g_strdup(escaped_entry);
            g_array_append_val(npp->current.netdef->search_domains, s);
        } else {
            g_debug("%s: Search domain '%s' has already been added", npp->current.netdef->id, escaped_entry);
        }
    }
    mark_data_as_dirty(npp, &npp->current.netdef->search_domains);
    return TRUE;
}

STATIC gboolean
handle_nameservers_addresses(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        GArray **nameservers = NULL;
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        assert_type(npp, entry, YAML_SCALAR_NODE);

        /* is it an IPv4 or IPv6 address? */
        if (is_ip4_address(scalar(entry)))
            nameservers = &npp->current.netdef->ip4_nameservers;
        else if (is_ip6_address(scalar(entry)))
            nameservers = &npp->current.netdef->ip6_nameservers;
        else
            return yaml_error(npp, node, error, "malformed address '%s', must be X.X.X.X or X:X:X:X:X:X:X:X", scalar(entry));

        if (!(*nameservers))
           *nameservers = g_array_new(FALSE, FALSE, sizeof(char*));

        if (!is_string_in_array(*nameservers, scalar(entry))) {
            char* s = g_strdup(scalar(entry));
            g_array_append_val(*nameservers, s);
        } else {
            g_debug("%s: Nameserver '%s' has already been added", npp->current.netdef->id, scalar(entry));
        }
    }

    mark_data_as_dirty(npp, &npp->current.netdef->ip4_nameservers);
    mark_data_as_dirty(npp, &npp->current.netdef->ip6_nameservers);
    return TRUE;
}

STATIC gboolean
handle_link_local(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    gboolean ipv4 = FALSE;
    gboolean ipv6 = FALSE;

    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);

        assert_type(npp, entry, YAML_SCALAR_NODE);

        if (g_ascii_strcasecmp(scalar(entry), "ipv4") == 0) {
            ipv4 = TRUE;
            mark_data_as_dirty(npp, &npp->current.netdef->linklocal.ipv4);
        } else if (g_ascii_strcasecmp(scalar(entry), "ipv6") == 0) {
            ipv6 = TRUE;
            mark_data_as_dirty(npp, &npp->current.netdef->linklocal.ipv6);
        } else
            return yaml_error(npp, node, error, "invalid value for link-local: '%s'", scalar(entry));
    }

    npp->current.netdef->linklocal.ipv4 = ipv4;
    npp->current.netdef->linklocal.ipv6 = ipv6;

    return TRUE;
}

struct NetplanOptionalAddressType
NETPLAN_OPTIONAL_ADDRESS_TYPES[] = {
    {"ipv4-ll", NETPLAN_OPTIONAL_IPV4_LL},
    {"ipv6-ra", NETPLAN_OPTIONAL_IPV6_RA},
    {"dhcp4",   NETPLAN_OPTIONAL_DHCP4},
    {"dhcp6",   NETPLAN_OPTIONAL_DHCP6},
    {"static",  NETPLAN_OPTIONAL_STATIC},
    {NULL},
};

STATIC gboolean
handle_optional_addresses(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        assert_type(npp, entry, YAML_SCALAR_NODE);
        int found = FALSE;

        for (unsigned i = 0; NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name != NULL; ++i) {
            if (g_ascii_strcasecmp(scalar(entry), NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name) == 0) {
                npp->current.netdef->optional_addresses |= NETPLAN_OPTIONAL_ADDRESS_TYPES[i].flag;
                found = TRUE;
                break;
            }
        }
        if (!found) {
            return yaml_error(npp, node, error, "invalid value for optional-addresses: '%s'", scalar(entry));
        }
    }
    return TRUE;
}

/* TODO: unify optional_addresses/wowlan_types, using flags */
STATIC gboolean
handle_vxlan_flags(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.vxlan);
    assert_type(npp, node, YAML_SEQUENCE_NODE);
    yaml_node_t* key_node = node-1; // The YAML key of given sequence `node`

    guint offset = GPOINTER_TO_UINT(data);
    const char* const* flags = NULL;
    guint flags_size = 0;
    NetplanFlags* out_ptr = NULL;
    switch (offset) {
        case offsetof(NetplanVxlan, notifications):
            out_ptr = &npp->current.vxlan->notifications;
            flags = netplan_vxlan_notification_to_str;
            flags_size = sizeof(netplan_vxlan_notification_to_str);
            break;
        case offsetof(NetplanVxlan, checksums):
            out_ptr = &npp->current.vxlan->checksums;
            flags = netplan_vxlan_checksum_to_str;
            flags_size = sizeof(netplan_vxlan_checksum_to_str);
            break;
        case offsetof(NetplanVxlan, extensions):
            out_ptr = &npp->current.vxlan->extensions;
            flags = netplan_vxlan_extension_to_str;
            flags_size = sizeof(netplan_vxlan_extension_to_str);
            break;
        default: g_assert_not_reached(); // LCOV_EXCL_LINE
    }
    g_assert(flags);
    g_assert(out_ptr);

    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        assert_type(npp, entry, YAML_SCALAR_NODE);
        int found = FALSE;
        /* Loop through the flags to find a matching string.
         * Once found, shift a bit to position INDEX-1 and use bitwise OR to
         * apply it to the corresponding flags field (i.e. *out_ptr) */
        // The minimum flag is always 0x1 (i.e. 0b0001), so start the loop at 1.
        for (unsigned j = 1; j < flags_size/sizeof(char*); ++j) {
            if (g_ascii_strcasecmp(scalar(entry), flags[j]) == 0) {
                *out_ptr |= 1<<(j-1);
                mark_data_as_dirty(npp, out_ptr);
                found = TRUE;
                break;
            }
        }
        if (!found) {
            return yaml_error(npp, node, error, "invalid value for %s: '%s'",
                              scalar(key_node), scalar(entry));
        }
    }
    return TRUE;
}

STATIC gboolean
handle_vxlan_guint(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.vxlan);
    return handle_generic_guint(npp, node, npp->current.vxlan, data, error);
}

STATIC gboolean
handle_vxlan_tristate(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.vxlan);
    return handle_generic_tristate(npp, node, npp->current.vxlan, data, error);
}

STATIC int
get_ip_family(const char* address)
{
    g_autofree char *ip_str;
    char *prefix_len;

    ip_str = g_strdup(address);
    prefix_len = strrchr(ip_str, '/');
    if (prefix_len)
        *prefix_len = '\0';

    if (is_ip4_address(ip_str))
        return AF_INET;

    if (is_ip6_address(ip_str))
        return AF_INET6;

    return -1;
}

STATIC gboolean
check_and_set_family(gint family, gint* dest)
{
    if (*dest != -1 && *dest != family)
        return FALSE;

    *dest = family;

    return TRUE;
}

/* TODO: (cyphermox) Refactor the functions below. There's a lot of room for reuse. */

STATIC gboolean
handle_routes_bool(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.route);
    return handle_generic_bool(npp, node, npp->current.route, data, error);
}

STATIC gboolean
handle_routes_scope(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    NetplanIPRoute* route = npp->current.route;
    if (route->scope)
        g_free(route->scope);
    route->scope = g_strdup(scalar(node));

    if (g_ascii_strcasecmp(route->scope, "global") == 0 ||
        g_ascii_strcasecmp(route->scope, "link") == 0 ||
        g_ascii_strcasecmp(route->scope, "host") == 0)
        return TRUE;

    return yaml_error(npp, node, error, "invalid route scope '%s'", route->scope);
}

STATIC gboolean
handle_routes_type(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    NetplanIPRoute* route = npp->current.route;
    if (route->type)
        g_free(route->type);
    route->type = g_strdup(scalar(node));

    /* local, broadcast, anycast, multicast, nat and xresolve are supported
     * since systemd-networkd v243 */
    /* keep "unicast" default at position 1 */
    if (   g_ascii_strcasecmp(route->type, "unicast") == 0
        || g_ascii_strcasecmp(route->type, "anycast") == 0
        || g_ascii_strcasecmp(route->type, "blackhole") == 0
        || g_ascii_strcasecmp(route->type, "broadcast") == 0
        || g_ascii_strcasecmp(route->type, "local") == 0
        || g_ascii_strcasecmp(route->type, "multicast") == 0
        || g_ascii_strcasecmp(route->type, "nat") == 0
        || g_ascii_strcasecmp(route->type, "prohibit") == 0
        || g_ascii_strcasecmp(route->type, "throw") == 0
        || g_ascii_strcasecmp(route->type, "unreachable") == 0
        || g_ascii_strcasecmp(route->type, "xresolve") == 0)
        return TRUE;

    return yaml_error(npp, node, error, "invalid route type '%s'", route->type);
}

STATIC gboolean
handle_routes_ip(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    NetplanIPRoute* route = npp->current.route;
    guint offset = GPOINTER_TO_UINT(data);
    int family = get_ip_family(scalar(node));
    char** dest = (char**) ((void*) route + offset);

    if (family < 0)
        return yaml_error(npp, node, error, "invalid IP family '%d'", family);

    if (!check_and_set_family(family, &route->family))
        return yaml_error(npp, node, error, "IP family mismatch in route to %s", scalar(node));

    g_free(*dest);
    *dest = g_strdup(scalar(node));
    mark_data_as_dirty(npp, dest);

    return TRUE;
}

STATIC gboolean
handle_routes_destination(NetplanParser *npp, yaml_node_t *node, __unused const void *data, GError **error)
{
    const char *addr = scalar(node);
    if (g_strcmp0(addr, "default") != 0) /* netplan-feature: default-routes */
        return handle_routes_ip(npp, node, route_offset(to), error);
    set_str_if_null(npp->current.route->to, addr);
    return TRUE;
}

STATIC gboolean
handle_ip_rule_ip(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    NetplanIPRule* ip_rule = npp->current.ip_rule;
    guint offset = GPOINTER_TO_UINT(data);
    int family = get_ip_family(scalar(node));
    char** dest = (char**) ((void*) ip_rule + offset);

    if (family < 0)
        return yaml_error(npp, node, error, "invalid IP family '%d'", family);

    if (!check_and_set_family(family, &ip_rule->family))
        return yaml_error(npp, node, error, "IP family mismatch in route to %s", scalar(node));

    g_free(*dest);
    *dest = g_strdup(scalar(node));
    mark_data_as_dirty(npp, dest);

    return TRUE;
}

STATIC gboolean
handle_ip_rule_guint(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.ip_rule);
    return handle_generic_guint(npp, node, npp->current.ip_rule, data, error);
}

STATIC gboolean
handle_routes_guint(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.route);
    return handle_generic_guint(npp, node, npp->current.route, data, error);
}

STATIC gboolean
handle_ip_rule_tos(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    NetplanIPRule* ip_rule = npp->current.ip_rule;
    gboolean ret = handle_generic_guint(npp, node, ip_rule, data, error);
    if (ip_rule->tos > 255)
        return yaml_error(npp, node, error, "invalid ToS (must be between 0 and 255): %s", scalar(node));
    return ret;
}

/****************************************************
 * Grammar and handlers for network config "bridge_params" entry
 ****************************************************/

STATIC gboolean
handle_bridge_path_cost(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, const void* data, GError** error)
{
    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        guint v;
        gchar* endptr;
        NetplanNetDefinition *component;
        guint* ref_ptr;

        key = yaml_document_get_node(&npp->doc, entry->key);
        assert_type(npp, key, YAML_SCALAR_NODE);
        value = yaml_document_get_node(&npp->doc, entry->value);
        assert_type(npp, value, YAML_SCALAR_NODE);

        if (key_prefix && npp->null_fields) {
            g_autofree char* full_key = NULL;
            full_key = g_strdup_printf("%s\t%s", key_prefix, key->data.scalar.value);
            if (g_hash_table_contains(npp->null_fields, full_key))
                continue;
        }

        component = g_hash_table_lookup(npp->parsed_defs, scalar(key));
        if (!component) {
            add_missing_node(npp, key);
        } else {
            ref_ptr = ((guint*) ((void*) component + GPOINTER_TO_UINT(data)));
            if (*ref_ptr)
                return yaml_error(npp, node, error, "%s: interface '%s' already has a path cost of %u",
                                  npp->current.netdef->id, scalar(key), *ref_ptr);

            v = g_ascii_strtoull(scalar(value), &endptr, 10);
            if (*endptr != '\0')
                return yaml_error(npp, node, error, "invalid unsigned int value '%s'", scalar(value));

            g_debug("%s: adding path '%s' of cost: %d", npp->current.netdef->id, scalar(key), v);

            *ref_ptr = v;
            mark_data_as_dirty(npp, ref_ptr);
        }
    }
    return TRUE;
}

STATIC gboolean
handle_bridge_port_priority(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, const void* data, GError** error)
{
    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        guint v;
        gchar* endptr;
        NetplanNetDefinition *component;
        guint* ref_ptr;

        key = yaml_document_get_node(&npp->doc, entry->key);
        assert_type(npp, key, YAML_SCALAR_NODE);
        value = yaml_document_get_node(&npp->doc, entry->value);
        assert_type(npp, value, YAML_SCALAR_NODE);

        if (key_prefix && npp->null_fields) {
            g_autofree char* full_key = NULL;
            full_key = g_strdup_printf("%s\t%s", key_prefix, key->data.scalar.value);
            if (g_hash_table_contains(npp->null_fields, full_key))
                continue;
        }

        component = g_hash_table_lookup(npp->parsed_defs, scalar(key));
        if (!component) {
            add_missing_node(npp, key);
        } else {
            ref_ptr = ((guint*) ((void*) component + GPOINTER_TO_UINT(data)));
            if (*ref_ptr)
                return yaml_error(npp, node, error, "%s: interface '%s' already has a port priority of %u",
                                  npp->current.netdef->id, scalar(key), *ref_ptr);

            v = g_ascii_strtoull(scalar(value), &endptr, 10);
            if (*endptr != '\0' || v > 63)
                return yaml_error(npp, node, error, "invalid port priority value (must be between 0 and 63): %s",
                                  scalar(value));

            g_debug("%s: adding port '%s' of priority: %d", npp->current.netdef->id, scalar(key), v);

            *ref_ptr = v;
            mark_data_as_dirty(npp, ref_ptr);
        }
    }
    return TRUE;
}

static const mapping_entry_handler bridge_params_handlers[] = {
    {"ageing-time", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bridge_params.ageing_time)},
    {"aging-time", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bridge_params.ageing_time)},
    {"forward-delay", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bridge_params.forward_delay)},
    {"hello-time", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bridge_params.hello_time)},
    {"max-age", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bridge_params.max_age)},
    {"path-cost", YAML_MAPPING_NODE, {.map={.custom=handle_bridge_path_cost}}, netdef_offset(bridge_params.path_cost)},
    {"port-priority", YAML_MAPPING_NODE, {.map={.custom=handle_bridge_port_priority}}, netdef_offset(bridge_params.port_priority)},
    {"priority", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(bridge_params.priority)},
    {"stp", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(bridge_params.stp)},
    {NULL}
};

STATIC gboolean
handle_bridge(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* _, GError** error)
{
    npp->current.netdef->custom_bridging = TRUE;
    npp->current.netdef->bridge_params.stp = TRUE;
    return process_mapping(npp, node, key_prefix, bridge_params_handlers, NULL, error);
}

/****************************************************
 * Grammar and handlers for network config "routes" entry
 ****************************************************/

static const mapping_entry_handler routes_handlers[] = {
    {"from", YAML_SCALAR_NODE, {.generic=handle_routes_ip}, route_offset(from)},
    {"on-link", YAML_SCALAR_NODE, {.generic=handle_routes_bool}, route_offset(onlink)},
    {"scope", YAML_SCALAR_NODE, {.generic=handle_routes_scope}, NULL},
    {"table", YAML_SCALAR_NODE, {.generic=handle_routes_guint}, route_offset(table)},
    {"to", YAML_SCALAR_NODE, {.generic=handle_routes_destination}, NULL},
    {"type", YAML_SCALAR_NODE, {.generic=handle_routes_type}, NULL},
    {"via", YAML_SCALAR_NODE, {.generic=handle_routes_ip}, route_offset(via)},
    {"metric", YAML_SCALAR_NODE, {.generic=handle_routes_guint}, route_offset(metric)},
    {"mtu", YAML_SCALAR_NODE, {.generic=handle_routes_guint}, route_offset(mtubytes)},
    {"congestion-window", YAML_SCALAR_NODE, {.generic=handle_routes_guint}, route_offset(congestion_window)},
    {"advertised-receive-window", YAML_SCALAR_NODE, {.generic=handle_routes_guint}, route_offset(advertised_receive_window)},
    {NULL}
};

STATIC gboolean
handle_routes(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    if (!npp->current.netdef->routes)
        npp->current.netdef->routes = g_array_new(FALSE, TRUE, sizeof(NetplanIPRoute*));

    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        NetplanIPRoute* route;

        assert_type(npp, entry, YAML_MAPPING_NODE);

        g_assert(npp->current.route == NULL);
        route = g_new0(NetplanIPRoute, 1);
        route->type = g_strdup("unicast");
        route->scope = NULL;
        route->family = -1; /* 0 is a valid family ID */
        route->metric = NETPLAN_METRIC_UNSPEC; /* 0 is a valid metric */
        route->table = NETPLAN_ROUTE_TABLE_UNSPEC;
        g_debug("%s: adding new route", npp->current.netdef->id);

        npp->current.route = route;

        if (!process_mapping(npp, entry, NULL, routes_handlers, NULL, error))
            goto err;

        /* Set the default scope, according to type */
        if (!route->scope) {
            if (   g_ascii_strcasecmp(route->type, "local") == 0
                || g_ascii_strcasecmp(route->type, "nat") == 0)
                route->scope = (g_strdup("host"));
            /* Non-gatewayed unicast routes are scope:link, too */
            else if (  (g_ascii_strcasecmp(route->type, "unicast") == 0 && !route->via)
                     || g_ascii_strcasecmp(route->type, "broadcast") == 0
                     || g_ascii_strcasecmp(route->type, "multicast") == 0
                     || g_ascii_strcasecmp(route->type, "anycast") == 0)
                route->scope = g_strdup("link");
            else
                route->scope = g_strdup("global");
        }

        if (       (   g_ascii_strcasecmp(route->scope, "link") == 0
                    || g_ascii_strcasecmp(route->scope, "host") == 0)
                && !route->to) {
            yaml_error(npp, node, error, "link and host routes must specify a 'to' IP");
            goto err;
        } else if (   g_ascii_strcasecmp(route->type, "unicast") == 0
                   && g_ascii_strcasecmp(route->scope, "global") == 0
                   && (!route->to || !route->via)) {
            yaml_error(npp, node, error, "global unicast route must include both a 'to' and 'via' IP");
            goto err;
        } else if (g_ascii_strcasecmp(route->type, "unicast") != 0 && !route->to) {
            yaml_error(npp, node, error, "non-unicast routes must specify a 'to' IP");
            goto err;
        }

        if (is_route_present(npp->current.netdef, route)) {
            g_debug("%s: route (to: %s, via: %s, table: %d, metric: %d) has already been added",
                    npp->current.netdef->id,
                    route->to,
                    route->via,
                    route->table,
                    route->metric);
            route_clear(&npp->current.route);
            npp->current.route = NULL;
            continue;
        }

        g_array_append_val(npp->current.netdef->routes, route);
        npp->current.route = NULL;
    }
    mark_data_as_dirty(npp, &npp->current.netdef->routes);
    return TRUE;

err:
    route_clear(&npp->current.route);
    npp->current.route = NULL;
    return FALSE;
}

static const mapping_entry_handler ip_rules_handlers[] = {
    {"from", YAML_SCALAR_NODE, {.generic=handle_ip_rule_ip}, ip_rule_offset(from)},
    {"mark", YAML_SCALAR_NODE, {.generic=handle_ip_rule_guint}, ip_rule_offset(fwmark)},
    {"priority", YAML_SCALAR_NODE, {.generic=handle_ip_rule_guint}, ip_rule_offset(priority)},
    {"table", YAML_SCALAR_NODE, {.generic=handle_ip_rule_guint}, ip_rule_offset(table)},
    {"to", YAML_SCALAR_NODE, {.generic=handle_ip_rule_ip}, ip_rule_offset(to)},
    {"type-of-service", YAML_SCALAR_NODE, {.generic=handle_ip_rule_tos}, ip_rule_offset(tos)},
    {NULL}
};

STATIC gboolean
handle_ip_rules(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        gboolean ret;

        NetplanIPRule* ip_rule = g_new0(NetplanIPRule, 1);
        reset_ip_rule(ip_rule);

        npp->current.ip_rule = ip_rule;
        ret = process_mapping(npp, entry, NULL, ip_rules_handlers, NULL, error);
        npp->current.ip_rule = NULL;

        if (ret && !ip_rule->from && !ip_rule->to)
            ret = yaml_error(npp, node, error, "IP routing policy must include either a 'from' or 'to' IP");

        if (!ret) {
            ip_rule_clear(&ip_rule);
            return FALSE;
        }

        if (!npp->current.netdef->ip_rules)
            npp->current.netdef->ip_rules = g_array_new(FALSE, FALSE, sizeof(NetplanIPRule*));

        if (is_route_rule_present(npp->current.netdef, ip_rule)) {
            g_debug("%s: rule (from: %s, to: %s, table: %d) has already been added",
                    npp->current.netdef->id,
                    ip_rule->from,
                    ip_rule->to,
                    ip_rule->table);
            ip_rule_clear(&ip_rule);
            npp->current.ip_rule = NULL;
            continue;
        }

        g_array_append_val(npp->current.netdef->ip_rules, ip_rule);
    }
    mark_data_as_dirty(npp, &npp->current.netdef->ip_rules);
    return TRUE;
}

/****************************************************
 * Grammar and handlers for bond parameters
 ****************************************************/

STATIC gboolean
handle_arp_ip_targets(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    if (!npp->current.netdef->bond_params.arp_ip_targets) {
        npp->current.netdef->bond_params.arp_ip_targets = g_array_new(FALSE, FALSE, sizeof(char *));
    }

    /* Avoid adding the same arp_ip_targets in a 2nd parsing pass by comparing
     * the array size to the YAML sequence size. Skip if they are equal. */
    guint item_count = node->data.sequence.items.top - node->data.sequence.items.start;
    if (npp->current.netdef->bond_params.arp_ip_targets->len == item_count) {
        g_debug("%s: all arp ip targets have already been added", npp->current.netdef->id);
        return TRUE;
    }

    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        g_autofree char* addr = NULL;
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        assert_type(npp, entry, YAML_SCALAR_NODE);

        addr = g_strdup(scalar(entry));

        /* is it an IPv4 address? */
        if (is_ip4_address(addr)) {
            char* s = g_strdup(scalar(entry));
            g_array_append_val(npp->current.netdef->bond_params.arp_ip_targets, s);
            continue;
        }

        return yaml_error(npp, node, error, "malformed address '%s', must be X.X.X.X or X:X:X:X:X:X:X:X", scalar(entry));
    }

    mark_data_as_dirty(npp, &npp->current.netdef->bond_params.arp_ip_targets);
    return TRUE;
}

STATIC gboolean
handle_bond_primary_member(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    NetplanNetDefinition *component;
    char** ref_ptr;

    component = g_hash_table_lookup(npp->parsed_defs, scalar(node));
    if (!component) {
        add_missing_node(npp, node);
    } else {
        /* If this is not the primary pass, the primary member might already be equally set. */
        if (!g_strcmp0(npp->current.netdef->bond_params.primary_member, scalar(node))) {
            return TRUE;
        } else if (npp->current.netdef->bond_params.primary_member)
            return yaml_error(npp, node, error, "%s: bond already has a primary member: %s",
                              npp->current.netdef->id, npp->current.netdef->bond_params.primary_member);

        ref_ptr = ((char**) ((void*) component + GPOINTER_TO_UINT(data)));
        if (*ref_ptr) {
            NetplanNetDefinition* bond = _netplan_parser_find_bond_for_primary_member(npp, *ref_ptr);
            return yaml_error(npp, node, error, "%s: interface '%s' is already a primary of %s",
                              npp->current.netdef->id, *ref_ptr, bond->id);
        }
        *ref_ptr = g_strdup(scalar(node));
        npp->current.netdef->bond_params.primary_member = g_strdup(scalar(node));
        mark_data_as_dirty(npp, ref_ptr);
    }

    mark_data_as_dirty(npp, &npp->current.netdef->bond_params.primary_member);
    return TRUE;
}

STATIC gboolean
handle_bond_lacp_rate(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (!(strcmp(scalar(node), "slow") == 0 || strcmp(scalar(node), "fast") == 0))
        return yaml_error(npp, node, error, "unknown lacp-rate value '%s' (expected 'fast' or 'slow')", scalar(node));

    return handle_netdef_str(npp, node, data, error);
}

static const mapping_entry_handler bond_params_handlers[] = {
    {"mode", YAML_SCALAR_NODE, {.generic=handle_bond_mode}, netdef_offset(bond_params.mode)},
    {"lacp-rate", YAML_SCALAR_NODE, {.generic=handle_bond_lacp_rate}, netdef_offset(bond_params.lacp_rate)},
    {"mii-monitor-interval", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.monitor_interval)},
    {"min-links", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(bond_params.min_links)},
    {"transmit-hash-policy", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.transmit_hash_policy)},
    {"ad-select", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.selection_logic)},
    {"all-slaves-active", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(bond_params.all_members_active)}, /* wokeignore:rule=slave */
    {"all-members-active", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(bond_params.all_members_active)},
    {"arp-interval", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.arp_interval)},
    /* TODO: arp_ip_targets */
    {"arp-ip-targets", YAML_SEQUENCE_NODE, {.generic=handle_arp_ip_targets}, NULL},
    {"arp-validate", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.arp_validate)},
    {"arp-all-targets", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.arp_all_targets)},
    {"up-delay", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.up_delay)},
    {"down-delay", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.down_delay)},
    {"fail-over-mac-policy", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.fail_over_mac_policy)},
    {"gratuitous-arp", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(bond_params.gratuitous_arp)},
    /* Handle the old misspelling */
    {"gratuitious-arp", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(bond_params.gratuitous_arp)},
    /* TODO: unsolicited_na */
    {"packets-per-slave", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(bond_params.packets_per_member)}, /* wokeignore:rule=slave */
    {"packets-per-member", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(bond_params.packets_per_member)},
    {"primary-reselect-policy", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.primary_reselect_policy)},
    {"resend-igmp", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(bond_params.resend_igmp)},
    {"learn-packet-interval", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(bond_params.learn_interval)},
    {"primary", YAML_SCALAR_NODE, {.generic=handle_bond_primary_member}, netdef_offset(bond_params.primary_member)},
    {NULL}
};

STATIC gboolean
handle_vrf_interfaces(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    /* all entries must refer to already defined IDs */
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        NetplanNetDefinition *component;

        assert_type(npp, entry, YAML_SCALAR_NODE);
        component = g_hash_table_lookup(npp->parsed_defs, scalar(entry));
        if (!component) {
            add_missing_node(npp, entry);
        } else {
            if (component->vrf_link && component->vrf_link != npp->current.netdef)
                return yaml_error(npp, node, error, "%s: interface '%s' is already assigned to vrf %s",
                                  npp->current.netdef->id, scalar(entry), component->vrf_link->id);
            component->vrf_link = npp->current.netdef;
        }
    }

    return TRUE;
}

STATIC gboolean
handle_vxlan_source_port(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    assert_type(npp, node, YAML_SEQUENCE_NODE);
    if (node->data.sequence.items.top - node->data.sequence.items.start != 2)
        return yaml_error(npp, node, error, "%s: Expected exactly two values for port-range",
                          npp->current.netdef->id);

    yaml_node_t* itm1 = yaml_document_get_node(&npp->doc, *node->data.sequence.items.start);
    yaml_node_t* itm2 = yaml_document_get_node(&npp->doc, *node->data.sequence.items.start+1);

    if (!handle_generic_guint(npp, itm1, npp->current.vxlan, vxlan_offset(source_port_min), error))
        return FALSE;
    if (!handle_generic_guint(npp, itm2, npp->current.vxlan, vxlan_offset(source_port_max), error))
        return FALSE;

    guint tmp = 0;
    if (npp->current.netdef->vxlan->source_port_min > npp->current.netdef->vxlan->source_port_max) {
        tmp = npp->current.netdef->vxlan->source_port_min;
        npp->current.netdef->vxlan->source_port_min = npp->current.netdef->vxlan->source_port_max;
        npp->current.netdef->vxlan->source_port_max = tmp;
        g_warning("%s: swapped invalid port-range order [MIN, MAX]", npp->current.netdef->id);
    }

    return TRUE;
}

STATIC gboolean
handle_bonding(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* _, GError** error)
{
    return process_mapping(npp, node, key_prefix, bond_params_handlers, NULL, error);
}

STATIC gboolean
handle_dhcp_identifier(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    g_free(npp->current.netdef->dhcp_identifier);
    /* "duid" is the default case, so we don't store it. */
    if (g_ascii_strcasecmp(scalar(node), "duid") != 0)
        npp->current.netdef->dhcp_identifier = g_strdup(scalar(node));
    else
        npp->current.netdef->dhcp_identifier = NULL;

    if (npp->current.netdef->dhcp_identifier == NULL ||
        g_ascii_strcasecmp(npp->current.netdef->dhcp_identifier, "mac") == 0)
        return TRUE;

    return yaml_error(npp, node, error, "invalid DHCP client identifier type '%s'", npp->current.netdef->dhcp_identifier);
}

/****************************************************
 * Grammar and handlers for tunnels
 ****************************************************/

STATIC gboolean
handle_tunnel_addr(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_autofree char* addr = NULL;
    char* prefix_len;

    /* split off /prefix_len */
    addr = g_strdup(scalar(node));
    prefix_len = strrchr(addr, '/');
    if (prefix_len)
        return yaml_error(npp, node, error, "address '%s' should not include /prefixlength", scalar(node));

    /* is it an IPv4 address? */
    if (is_ip4_address(addr))
        return handle_netdef_ip4(npp, node, data, error);

    /* is it an IPv6 address? */
    if (is_ip6_address(addr))
        return handle_netdef_ip6(npp, node, data, error);

    return yaml_error(npp, node, error, "malformed address '%s', must be X.X.X.X or X:X:X:X:X:X:X:X", scalar(node));
}

STATIC gboolean
handle_tunnel_mode(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    const char *key = scalar(node);
    NetplanTunnelMode i;

    // Skip over unknown (0) tunnel mode.
    for (i = 1; i < NETPLAN_TUNNEL_MODE_MAX_; ++i) {
        if (g_strcmp0(netplan_tunnel_mode_name(i), key) == 0) {
            npp->current.netdef->tunnel.mode = i;
            return TRUE;
        }
    }

    return yaml_error(npp, node, error, "%s: tunnel mode '%s' is not supported", npp->current.netdef->id, key);
}

static const mapping_entry_handler tunnel_keys_handlers[] = {
    {"input", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(tunnel.input_key)},
    {"output", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(tunnel.output_key)},
    {"private", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(tunnel.private_key)},
    {"private-key-flags", YAML_SEQUENCE_NODE, {.generic=handle_tunnel_key_flags}, NULL},
    {NULL}
};

STATIC gboolean
handle_tunnel_key_mapping(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* _, GError** error)
{
    gboolean ret = FALSE;

    /* We overload the 'key[s]' setting for tunnels; such that it can either be a
     * single scalar with the same key to use for both input, output and private
     * keys, or a mapping where one can specify each. */
    if (node->type == YAML_SCALAR_NODE) {
        ret = handle_netdef_str(npp, node, netdef_offset(tunnel.input_key), error);
        if (ret)
            ret = handle_netdef_str(npp, node, netdef_offset(tunnel.output_key), error);
        if (ret)
            ret = handle_netdef_str(npp, node, netdef_offset(tunnel.private_key), error);
    } else if (node->type == YAML_MAPPING_NODE)
        ret = process_mapping(npp, node, key_prefix, tunnel_keys_handlers, NULL, error);
    else
        return yaml_error(npp, node, error, "invalid type for 'key[s]': must be a scalar or mapping");

    return ret;
}

/**
 * Handler for setting a NetplanWireguardPeer string field from a scalar node
 * @data: pointer to the const char* field to write
 */
STATIC gboolean
handle_wireguard_peer_str(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.wireguard_peer);
    return handle_generic_str(npp, node, npp->current.wireguard_peer, data, error);
}

/**
 * Handler for setting a NetplanWireguardPeer string field from a scalar node
 * @data: pointer to the guint field to write
 */
STATIC gboolean
handle_wireguard_peer_guint(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(npp->current.wireguard_peer);
    return handle_generic_guint(npp, node, npp->current.wireguard_peer, data, error);
}

STATIC gboolean
handle_wireguard_allowed_ips(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    return handle_generic_addresses(npp, node, FALSE, &(npp->current.wireguard_peer->allowed_ips),
                                    &(npp->current.wireguard_peer->allowed_ips), error);
}

STATIC gboolean
handle_wireguard_endpoint(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    g_autofree char* endpoint = NULL;
    char* port;
    char* address;
    guint64 port_num;

    /* If endpoint is an empty string just ignore it */
    if (!g_strcmp0(scalar(node), "")) {
        return TRUE;
    }

    endpoint = g_strdup(scalar(node));
    /* absolute minimal length of endpoint is 3 chars: 'h:8' */
    if (strlen(endpoint) < 3) {
        return yaml_error(npp, node, error, "invalid endpoint address or hostname '%s'", scalar(node));
    }
    if (endpoint[0] == '[') {
        /* this is an ipv6 endpoint in [ad:rr:ee::ss]:port form */
        char *endbrace = strrchr(endpoint, ']');
        if (!endbrace)
            return yaml_error(npp, node, error, "invalid address in endpoint '%s'", scalar(node));
        address = endpoint + 1;
        *endbrace = '\0';
        port = strrchr(endbrace + 1, ':');
    } else {
        address = endpoint;
        port = strrchr(endpoint, ':');
    }
    /* split off :port */
    if (!port)
        return yaml_error(npp, node, error, "endpoint '%s' is missing :port", scalar(node));
    *port = '\0';
    port++; /* skip former ':' into first char of port */
    port_num = g_ascii_strtoull(port, NULL, 10);
    if (port_num > 65535)
        return yaml_error(npp, node, error, "invalid port in endpoint '%s'", scalar(node));
    if (is_ip4_address(address) || is_ip6_address(address) || is_hostname(address)) {
        return handle_wireguard_peer_str(npp, node, wireguard_peer_offset(endpoint), error);
    }
    return yaml_error(npp, node, error, "invalid endpoint address or hostname '%s'", scalar(node));
}

static const mapping_entry_handler wireguard_peer_keys_handlers[] = {
    {"public", YAML_SCALAR_NODE, {.generic=handle_wireguard_peer_str}, wireguard_peer_offset(public_key)},
    {"shared", YAML_SCALAR_NODE, {.generic=handle_wireguard_peer_str}, wireguard_peer_offset(preshared_key)},
    {NULL}
};

STATIC gboolean
handle_wireguard_peer_key_mapping(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* _, GError** error)
{
    return process_mapping(npp, node, key_prefix, wireguard_peer_keys_handlers, NULL, error);
}

const mapping_entry_handler wireguard_peer_handlers[] = {
    {"keys", YAML_MAPPING_NODE, {.map={.custom=handle_wireguard_peer_key_mapping}}, NULL},
    {"keepalive", YAML_SCALAR_NODE, {.generic=handle_wireguard_peer_guint}, wireguard_peer_offset(keepalive)},
    {"endpoint", YAML_SCALAR_NODE, {.generic=handle_wireguard_endpoint}, NULL},
    {"allowed-ips", YAML_SEQUENCE_NODE, {.generic=handle_wireguard_allowed_ips}, NULL},
    {NULL}
};

STATIC gboolean
handle_wireguard_peers(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    if (!npp->current.netdef->wireguard_peers)
        npp->current.netdef->wireguard_peers = g_array_new(FALSE, TRUE, sizeof(NetplanWireguardPeer*));

    /* Avoid adding the same peers in a 2nd parsing pass by comparing
     * the array size to the YAML sequence size. Skip if they are equal. */
    guint item_count = node->data.sequence.items.top - node->data.sequence.items.start;
    if (npp->current.netdef->wireguard_peers->len == item_count) {
        g_debug("%s: all wireguard peers have already been added", npp->current.netdef->id);
        return TRUE;
    }

    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        assert_type(npp, entry, YAML_MAPPING_NODE);

        g_assert(npp->current.wireguard_peer == NULL);
        npp->current.wireguard_peer = g_new0(NetplanWireguardPeer, 1);
        npp->current.wireguard_peer->allowed_ips = g_array_new(FALSE, FALSE, sizeof(char*));
        g_debug("%s: adding new wireguard peer", npp->current.netdef->id);

        if (!process_mapping(npp, entry, NULL, wireguard_peer_handlers, NULL, error)) {
            wireguard_peer_clear(&npp->current.wireguard_peer);
            npp->current.wireguard_peer = NULL;
            return FALSE;
        }
        g_array_append_val(npp->current.netdef->wireguard_peers, npp->current.wireguard_peer);
        npp->current.wireguard_peer = NULL;
    }
    return TRUE;
}

/****************************************************
 * Grammar and handlers for network devices
 ****************************************************/

STATIC gboolean
handle_ovs_bond_lacp(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (npp->current.netdef->type != NETPLAN_DEF_TYPE_BOND)
        return yaml_error(npp, node, error, "Key 'lacp' is only valid for interface type 'Open vSwitch bond'");

    if (g_strcmp0(scalar(node), "active") && g_strcmp0(scalar(node), "passive") && g_strcmp0(scalar(node), "off"))
        return yaml_error(npp, node, error, "Value of 'lacp' needs to be 'active', 'passive' or 'off");

    return handle_netdef_str(npp, node, data, error);
}

STATIC gboolean
handle_ovs_bridge_bool(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (npp->current.netdef->type != NETPLAN_DEF_TYPE_BRIDGE)
        return yaml_error(npp, node, error, "Key is only valid for interface type 'Open vSwitch bridge'");

    return handle_netdef_bool(npp, node, data, error);
}

STATIC gboolean
handle_ovs_bridge_fail_mode(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (npp->current.netdef->type != NETPLAN_DEF_TYPE_BRIDGE)
        return yaml_error(npp, node, error, "Key 'fail-mode' is only valid for interface type 'Open vSwitch bridge'");

    if (g_strcmp0(scalar(node), "standalone") && g_strcmp0(scalar(node), "secure"))
        return yaml_error(npp, node, error, "Value of 'fail-mode' needs to be 'standalone' or 'secure'");

    return handle_netdef_str(npp, node, data, error);
}

STATIC gboolean
handle_ovs_protocol(NetplanParser* npp, yaml_node_t* node, void* entryptr, const void* data, GError** error)
{
    const char* deprecated[] = { "OpenFlow16" };
    const char* supported[] = {
        "OpenFlow10", "OpenFlow11", "OpenFlow12", "OpenFlow13", "OpenFlow14", "OpenFlow15", NULL
    };
    unsigned i = 0;
    guint offset = GPOINTER_TO_UINT(data);
    GArray** protocols = (GArray**) ((void*) entryptr + offset);

    for (yaml_node_item_t *iter = node->data.sequence.items.start; iter < node->data.sequence.items.top; iter++) {
        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *iter);
        assert_type(npp, entry, YAML_SCALAR_NODE);

        if (!g_strcmp0(scalar(entry), deprecated[0])) {
            g_warning("Open vSwitch: Ignoring deprecated protocol: %s", scalar(entry));
            continue;
        }

        for (i = 0; supported[i] != NULL; ++i)
            if (!g_strcmp0(scalar(entry), supported[i]))
                break;

        if (supported[i] == NULL)
            return yaml_error(npp, node, error, "Unsupported OVS 'protocol' value: %s", scalar(entry));

        if (!*protocols)
            *protocols = g_array_new(FALSE, FALSE, sizeof(char*));

        /* Do not insert the same address twice in the list */
        if (!is_string_in_array(*protocols, scalar(entry))) {
            char* s = g_strdup(scalar(entry));
            g_array_append_val(*protocols, s);
        }
    }

    return TRUE;
}

STATIC gboolean
handle_ovs_bridge_protocol(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (npp->current.netdef->type != NETPLAN_DEF_TYPE_BRIDGE)
        return yaml_error(npp, node, error, "Key 'protocols' is only valid for interface type 'Open vSwitch bridge'");

    return handle_ovs_protocol(npp, node, npp->current.netdef, data, error);
}

STATIC gboolean
handle_ovs_bridge_controller_connection_mode(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    if (npp->current.netdef->type != NETPLAN_DEF_TYPE_BRIDGE)
        return yaml_error(npp, node, error, "Key 'controller.connection-mode' is only valid for interface type 'Open vSwitch bridge'");

    if (g_strcmp0(scalar(node), "in-band") && g_strcmp0(scalar(node), "out-of-band"))
        return yaml_error(npp, node, error, "Value of 'connection-mode' needs to be 'in-band' or 'out-of-band'");

    return handle_netdef_str(npp, node, data, error);
}

STATIC gboolean
handle_ovs_bridge_controller_addresses(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    if (npp->current.netdef->type != NETPLAN_DEF_TYPE_BRIDGE)
        return yaml_error(npp, node, error, "Key 'controller.addresses' is only valid for interface type 'Open vSwitch bridge'");

    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        gchar** vec = NULL;
        gboolean is_host = FALSE;
        gboolean is_port = FALSE;
        gboolean is_unix = FALSE;

        yaml_node_t *entry = yaml_document_get_node(&npp->doc, *i);
        assert_type(npp, entry, YAML_SCALAR_NODE);
        /* We always need at least one colon */
        if (!g_strrstr(scalar(entry), ":"))
            return yaml_error(npp, node, error, "Unsupported OVS controller target: %s", scalar(entry));

        vec = g_strsplit (scalar(entry), ":", 2);

        is_host = !g_strcmp0(vec[0], "tcp") || !g_strcmp0(vec[0], "ssl");
        is_port = !g_strcmp0(vec[0], "ptcp") || !g_strcmp0(vec[0], "pssl");
        is_unix = !g_strcmp0(vec[0], "unix") || !g_strcmp0(vec[0], "punix");

        if (!npp->current.netdef->ovs_settings.controller.addresses)
            npp->current.netdef->ovs_settings.controller.addresses = g_array_new(FALSE, FALSE, sizeof(char*));

        /* Do not insert the same address twice in the list */
        if (is_string_in_array(npp->current.netdef->ovs_settings.controller.addresses, scalar(entry))) {
            g_strfreev(vec);
            continue;
        }

        /* Format: [p]unix:file */
        if (is_unix && vec[1] != NULL && vec[2] == NULL) {
            char* s = g_strescape(scalar(entry), STRESCAPE_EXCEPTIONS);
            g_array_append_val(npp->current.netdef->ovs_settings.controller.addresses, s);
            g_strfreev(vec);
            continue;
        /* Format tcp:host[:port] or ssl:host[:port] */
        } else if (is_host && validate_ovs_target(TRUE, vec[1])) {
            char* s = g_strescape(scalar(entry), STRESCAPE_EXCEPTIONS);
            g_array_append_val(npp->current.netdef->ovs_settings.controller.addresses, s);
            g_strfreev(vec);
            continue;
        /* Format ptcp:[port][:host] or pssl:[port][:host] */
        } else if (is_port && validate_ovs_target(FALSE, vec[1])) {
            char* s = g_strescape(scalar(entry), STRESCAPE_EXCEPTIONS);
            g_array_append_val(npp->current.netdef->ovs_settings.controller.addresses, s);
            g_strfreev(vec);
            continue;
        }

        g_strfreev(vec);
        return yaml_error(npp, node, error, "Unsupported OVS controller target: %s", scalar(entry));
    }

    return TRUE;
}

static const mapping_entry_handler ovs_controller_handlers[] = {
    {"addresses", YAML_SEQUENCE_NODE, {.generic=handle_ovs_bridge_controller_addresses}, netdef_offset(ovs_settings.controller.addresses)},
    {"connection-mode", YAML_SCALAR_NODE, {.generic=handle_ovs_bridge_controller_connection_mode}, netdef_offset(ovs_settings.controller.connection_mode)},
    {NULL},
};

static const mapping_entry_handler ovs_backend_settings_handlers[] = {
    {"external-ids", YAML_MAPPING_NODE, {.map={.custom=handle_netdef_map}}, netdef_offset(ovs_settings.external_ids)},
    {"other-config", YAML_MAPPING_NODE, {.map={.custom=handle_netdef_map}}, netdef_offset(ovs_settings.other_config)},
    {"lacp", YAML_SCALAR_NODE, {.generic=handle_ovs_bond_lacp}, netdef_offset(ovs_settings.lacp)},
    {"fail-mode", YAML_SCALAR_NODE, {.generic=handle_ovs_bridge_fail_mode}, netdef_offset(ovs_settings.fail_mode)},
    {"mcast-snooping", YAML_SCALAR_NODE, {.generic=handle_ovs_bridge_bool}, netdef_offset(ovs_settings.mcast_snooping)},
    {"rstp", YAML_SCALAR_NODE, {.generic=handle_ovs_bridge_bool}, netdef_offset(ovs_settings.rstp)},
    {"protocols", YAML_SEQUENCE_NODE, {.generic=handle_ovs_bridge_protocol}, netdef_offset(ovs_settings.protocols)},
    {"controller", YAML_MAPPING_NODE, {.map={.handlers=ovs_controller_handlers}}, NULL},
    {NULL}
};

STATIC gboolean
handle_ovs_backend(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* _, GError** error)
{
    GList* values = NULL;
    gboolean ret = process_mapping(npp, node, key_prefix, ovs_backend_settings_handlers, &values, error);
    guint len = g_list_length(values);

    if (npp->current.netdef->type != NETPLAN_DEF_TYPE_BOND && npp->current.netdef->type != NETPLAN_DEF_TYPE_BRIDGE) {
        GList *other_config = g_list_find_custom(values, "other-config", (GCompareFunc) strcmp);
        GList *external_ids = g_list_find_custom(values, "external-ids", (GCompareFunc) strcmp);
        /* Non-bond/non-bridge interfaces might still be handled by the networkd backend */
        if (len == 1 && (other_config || external_ids))
            goto cleanup;
        else if (len == 2 && other_config && external_ids)
            goto cleanup;
    }

    /* Set the renderer for this device to NETPLAN_BACKEND_OVS, implicitly.
     * But only if empty "openvswitch: {}" or "openvswitch:" with more than
     * "other-config" or "external-ids" keys is given. */
    npp->current.netdef->backend = NETPLAN_BACKEND_OVS;
cleanup:
    g_list_free_full(values, g_free);
    return ret;
}

static const mapping_entry_handler nameservers_handlers[] = {
    {"search", YAML_SEQUENCE_NODE, {.generic=handle_nameservers_search}, NULL},
    {"addresses", YAML_SEQUENCE_NODE, {.generic=handle_nameservers_addresses}, NULL},
    {NULL}
};

/* Handlers for DHCP overrides. */
#define COMMON_DHCP_OVERRIDES_HANDLERS(overrides)                                                           \
    {"hostname", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(overrides.hostname)},             \
    {"route-metric", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(overrides.metric)},         \
    {"send-hostname", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(overrides.send_hostname)},  \
    {"use-dns", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(overrides.use_dns)},              \
    {"use-domains", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(overrides.use_domains)},       \
    {"use-hostname", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(overrides.use_hostname)},    \
    {"use-mtu", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(overrides.use_mtu)},              \
    {"use-ntp", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(overrides.use_ntp)},              \
    {"use-routes", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(overrides.use_routes)}

static const mapping_entry_handler dhcp4_overrides_handlers[] = {
    COMMON_DHCP_OVERRIDES_HANDLERS(dhcp4_overrides),
    {NULL},
};

static const mapping_entry_handler dhcp6_overrides_handlers[] = {
    COMMON_DHCP_OVERRIDES_HANDLERS(dhcp6_overrides),
    {NULL},
};

static const mapping_entry_handler ra_overrides_handlers[] = {
    {"use-dns", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(ra_overrides.use_dns)},
    {"use-domains", YAML_SCALAR_NODE, {.generic=handle_netdef_use_domains}, netdef_offset(ra_overrides.use_domains)},
    {"table", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(ra_overrides.table)},
    {NULL},
};

/* Handlers shared by all link types */
#define COMMON_LINK_HANDLERS \
    {"accept-ra", YAML_SCALAR_NODE, {.generic=handle_accept_ra}, netdef_offset(accept_ra)}, \
    {"activation-mode", YAML_SCALAR_NODE, {.generic=handle_activation_mode}, netdef_offset(activation_mode)}, \
    {"addresses", YAML_SEQUENCE_NODE, {.generic=handle_addresses}, NULL}, \
    {"critical", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(critical)}, \
    {"ignore-carrier", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(ignore_carrier)}, \
    {"dhcp4", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(dhcp4)}, \
    {"dhcp6", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(dhcp6)}, \
    {"dhcp-identifier", YAML_SCALAR_NODE, {.generic=handle_dhcp_identifier}, NULL}, \
    {"dhcp4-overrides", YAML_MAPPING_NODE, {.map={.handlers=dhcp4_overrides_handlers}}, NULL}, \
    {"dhcp6-overrides", YAML_MAPPING_NODE, {.map={.handlers=dhcp6_overrides_handlers}}, NULL}, \
    {"ra-overrides", YAML_MAPPING_NODE, {.map={.handlers=ra_overrides_handlers}}, NULL}, \
    {"gateway4", YAML_SCALAR_NODE, {.generic=handle_gateway4}, NULL}, \
    {"gateway6", YAML_SCALAR_NODE, {.generic=handle_gateway6}, NULL}, \
    {"ipv6-address-generation", YAML_SCALAR_NODE, {.generic=handle_netdef_addrgen}, NULL}, \
    {"ipv6-address-token", YAML_SCALAR_NODE, {.generic=handle_netdef_addrtok}, netdef_offset(ip6_addr_gen_token)}, \
    {"ipv6-mtu", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(ipv6_mtubytes)}, \
    {"ipv6-privacy", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(ip6_privacy)}, \
    {"link-local", YAML_SEQUENCE_NODE, {.generic=handle_link_local}, NULL}, \
    {"macaddress", YAML_SCALAR_NODE, {.generic=handle_netdef_set_mac}, netdef_offset(set_mac)}, \
    {"mtu", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(mtubytes)}, \
    {"nameservers", YAML_MAPPING_NODE, {.map={.handlers=nameservers_handlers}}, NULL}, \
    {"optional", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(optional)}, \
    {"optional-addresses", YAML_SEQUENCE_NODE, {.generic=handle_optional_addresses}, NULL}, \
    {"renderer", YAML_SCALAR_NODE, {.generic=handle_netdef_renderer}, NULL}, \
    {"routes", YAML_SEQUENCE_NODE, {.generic=handle_routes}, NULL}, \
    {"routing-policy", YAML_SEQUENCE_NODE, {.generic=handle_ip_rules}, NULL}, \
    {"hairpin", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(bridge_hairpin)}, \
    {"port-mac-learning", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(bridge_learning)}, \
    {"neigh-suppress", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(bridge_neigh_suppress)}

#define COMMON_BACKEND_HANDLERS \
    {"networkmanager", YAML_MAPPING_NODE, {.map={.handlers=nm_backend_settings_handlers}}, NULL}, \
    {"openvswitch", YAML_MAPPING_NODE, {.map={.custom=handle_ovs_backend}}, NULL}

/* Handlers for physical links */
#define PHYSICAL_LINK_HANDLERS \
    {"match", YAML_MAPPING_NODE, {.map={.custom=handle_match}}, NULL}, \
    {"set-name", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(set_name)}, \
    {"wakeonlan", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(wake_on_lan)}, \
    {"wakeonwlan", YAML_SEQUENCE_NODE, {.generic=handle_wowlan}, netdef_offset(wowlan)}, \
    {"emit-lldp", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(emit_lldp)}, \
    {"receive-checksum-offload", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(receive_checksum_offload)}, \
    {"transmit-checksum-offload", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(transmit_checksum_offload)}, \
    {"tcp-segmentation-offload", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(tcp_segmentation_offload)}, \
    {"tcp6-segmentation-offload", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(tcp6_segmentation_offload)}, \
    {"generic-segmentation-offload", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(generic_segmentation_offload)}, \
    {"generic-receive-offload", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(generic_receive_offload)}, \
    {"large-receive-offload", YAML_SCALAR_NODE, {.generic=handle_netdef_tristate}, netdef_offset(large_receive_offload)}

static const mapping_entry_handler ethernet_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    PHYSICAL_LINK_HANDLERS,
    {"auth", YAML_MAPPING_NODE, {.map={.custom=handle_auth}}, NULL},
    {"link", YAML_SCALAR_NODE, {.generic=handle_netdef_id_ref}, netdef_offset(sriov_link)},
    {"virtual-function-count", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(sriov_explicit_vf_count)},
    {"embedded-switch-mode", YAML_SCALAR_NODE, {.generic=handle_embedded_switch_mode}, netdef_offset(embedded_switch_mode)},
    {"delay-virtual-functions-rebind", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(sriov_delay_virtual_functions_rebind)},
    {"infiniband-mode", YAML_SCALAR_NODE, {.generic=handle_ib_mode}, netdef_offset(ib_mode)},
    {NULL}
};

static const mapping_entry_handler veth_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"peer", YAML_SCALAR_NODE, {.generic=handle_veth_peer}, netdef_offset(veth_peer_link)},
    {NULL}
};


static const mapping_entry_handler wifi_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    PHYSICAL_LINK_HANDLERS,
    {"access-points", YAML_MAPPING_NODE, {.map={.custom=handle_wifi_access_points}}, NULL},
    {"auth", YAML_MAPPING_NODE, {.map={.custom=handle_auth}}, NULL},
    {"regulatory-domain", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(regulatory_domain)},
    {NULL}
};

static const mapping_entry_handler bridge_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"interfaces", YAML_SEQUENCE_NODE, {.generic=handle_bridge_interfaces}, NULL},
    {"parameters", YAML_MAPPING_NODE, {.map={.custom=handle_bridge}}, NULL},
    {NULL}
};

static const mapping_entry_handler bond_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"interfaces", YAML_SEQUENCE_NODE, {.generic=handle_bond_interfaces}, NULL},
    {"parameters", YAML_MAPPING_NODE, {.map={.custom=handle_bonding}}, NULL},
    {NULL}
};

static const mapping_entry_handler vlan_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"id", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(vlan_id)},
    {"link", YAML_SCALAR_NODE, {.generic=handle_netdef_id_ref}, netdef_offset(vlan_link)},
    {NULL}
};

static const mapping_entry_handler vrf_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"renderer", YAML_SCALAR_NODE, {.generic=handle_netdef_renderer}, NULL},
    {"interfaces", YAML_SEQUENCE_NODE, {.generic=handle_vrf_interfaces}, NULL},
    {"table", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(vrf_table)},
    {"routes", YAML_SEQUENCE_NODE, {.generic=handle_routes}, NULL},
    {"routing-policy", YAML_SEQUENCE_NODE, {.generic=handle_ip_rules}, NULL},
    {NULL}
};

static const mapping_entry_handler modem_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    PHYSICAL_LINK_HANDLERS,
    {"apn", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.apn)},
    {"auto-config", YAML_SCALAR_NODE, {.generic=handle_netdef_bool}, netdef_offset(modem_params.auto_config)},
    {"device-id", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.device_id)},
    {"network-id", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.network_id)},
    {"number", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.number)},
    {"password", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.password)},
    {"pin", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.pin)},
    {"sim-id", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.sim_id)},
    {"sim-operator-id", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.sim_operator_id)},
    {"username", YAML_SCALAR_NODE, {.generic=handle_netdef_str}, netdef_offset(modem_params.username)},
};

static const mapping_entry_handler dummy_def_handlers[] = {     /* wokeignore:rule=dummy */
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {NULL}
};

static const mapping_entry_handler tunnel_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"mode", YAML_SCALAR_NODE, {.generic=handle_tunnel_mode}, NULL},
    {"local", YAML_SCALAR_NODE, {.generic=handle_tunnel_addr}, netdef_offset(tunnel.local_ip)},
    {"remote", YAML_SCALAR_NODE, {.generic=handle_tunnel_addr}, netdef_offset(tunnel.remote_ip)},
    {"ttl", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(tunnel_ttl)},

    /* Handle key/keys for clarity in config: this can be either a scalar or
     * mapping of multiple keys (input and output)
     */
    {"key", YAML_NO_NODE, {.variable=handle_tunnel_key_mapping}, NULL},
    {"keys", YAML_NO_NODE, {.variable=handle_tunnel_key_mapping}, NULL},

    /* wireguard */
    {"mark", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(tunnel.fwmark)},
    {"port", YAML_SCALAR_NODE, {.generic=handle_netdef_guint}, netdef_offset(tunnel.port)},
    {"peers", YAML_SEQUENCE_NODE, {.generic=handle_wireguard_peers}, NULL},

    /* vxlan */
    {"link", YAML_SCALAR_NODE, {.generic=handle_vxlan_id_ref}, vxlan_offset(link)},
    {"ageing", YAML_SCALAR_NODE, {.generic=handle_vxlan_guint}, vxlan_offset(ageing)},
    {"aging", YAML_SCALAR_NODE, {.generic=handle_vxlan_guint}, vxlan_offset(ageing)},
    {"id", YAML_SCALAR_NODE, {.generic=handle_vxlan_guint}, vxlan_offset(vni)},
    {"limit", YAML_SCALAR_NODE, {.generic=handle_vxlan_guint}, vxlan_offset(limit)},
    {"type-of-service", YAML_SCALAR_NODE, {.generic=handle_vxlan_guint}, vxlan_offset(tos)},
    {"flow-label", YAML_SCALAR_NODE, {.generic=handle_vxlan_guint}, vxlan_offset(flow_label)},
    {"do-not-fragment", YAML_SCALAR_NODE, {.generic=handle_vxlan_tristate}, vxlan_offset(do_not_fragment)},
    {"short-circuit", YAML_SCALAR_NODE, {.generic=handle_vxlan_tristate}, vxlan_offset(short_circuit)},
    {"arp-proxy", YAML_SCALAR_NODE, {.generic=handle_vxlan_tristate}, vxlan_offset(arp_proxy)},
    {"mac-learning", YAML_SCALAR_NODE, {.generic=handle_vxlan_tristate}, vxlan_offset(mac_learning)},
    {"notifications", YAML_SEQUENCE_NODE, {.generic=handle_vxlan_flags}, vxlan_offset(notifications)},
    {"checksums", YAML_SEQUENCE_NODE, {.generic=handle_vxlan_flags}, vxlan_offset(checksums)},
    {"extensions", YAML_SEQUENCE_NODE, {.generic=handle_vxlan_flags}, vxlan_offset(extensions)},
    {"port-range", YAML_SEQUENCE_NODE, {.generic=handle_vxlan_source_port}, NULL},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network node
 ****************************************************/

STATIC gboolean
handle_network_version(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    long mangled_version;

    mangled_version = strtol(scalar(node), NULL, 10);

    if (mangled_version < NETPLAN_VERSION_MIN || mangled_version >= NETPLAN_VERSION_MAX)
        return yaml_error(npp, node, error, "Only version 2 is supported");
    return TRUE;
}

STATIC gboolean
handle_network_renderer(NetplanParser* npp, yaml_node_t* node, __unused const void* _, GError** error)
{
    gboolean res = parse_renderer(npp, node, &npp->global_backend, error);
    if (!npp->global_renderer)
        npp->global_renderer = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    char* key = npp->current.filepath ? g_strdup(npp->current.filepath) : g_strdup("");
    /* Track the global renderer value of the current file.
     * If current.filepath is empty, this YAML is parsed from an unnamed YAML
     * patch (e.g. via 'netplan set <SOME_PATCH>'). */
    g_hash_table_insert(npp->global_renderer, key, GINT_TO_POINTER(npp->global_backend));
    return res;
}

STATIC gboolean
handle_network_ovs_settings_global(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, const void* data, GError** error)
{
    return handle_generic_map(npp, node, key_prefix, &npp->global_ovs_settings, data, error);
}

STATIC gboolean
handle_network_ovs_settings_global_protocol(NetplanParser* npp, yaml_node_t* node, const void* data, GError** error)
{
    return handle_ovs_protocol(npp, node, &npp->global_ovs_settings, data, error);
}

STATIC gboolean
handle_network_ovs_settings_global_ports(NetplanParser* npp, yaml_node_t* node, __unused const void* data, GError** error)
{
    yaml_node_t* port = NULL;
    yaml_node_t* peer = NULL;
    yaml_node_t* pair = NULL;
    yaml_node_item_t *item = NULL;
    NetplanNetDefinition *component1 = NULL;
    NetplanNetDefinition *component2 = NULL;

    for (yaml_node_item_t *iter = node->data.sequence.items.start; iter < node->data.sequence.items.top; iter++) {
        g_autofree char* escaped_port = NULL;
        g_autofree char* escaped_peer = NULL;
        pair = yaml_document_get_node(&npp->doc, *iter);
        assert_type(npp, pair, YAML_SEQUENCE_NODE);

        item = pair->data.sequence.items.start;
        /* A peer port definition must contain exactly 2 ports */
        if (item+2 != pair->data.sequence.items.top) {
            return yaml_error(npp, pair, error, "An Open vSwitch peer port sequence must have exactly two entries");
        }

        port = yaml_document_get_node(&npp->doc, *item);
        assert_type(npp, port, YAML_SCALAR_NODE);
        peer = yaml_document_get_node(&npp->doc, *(item+1));
        assert_type(npp, peer, YAML_SCALAR_NODE);

        escaped_port = g_strescape(scalar(port), STRESCAPE_EXCEPTIONS);
        escaped_peer = g_strescape(scalar(peer), STRESCAPE_EXCEPTIONS);

        if (!g_strcmp0(escaped_port, escaped_peer))
            return yaml_error(npp, peer, error, "Open vSwitch patch ports must be of different name");

        /* Create port 1 netdef */
        component1 = npp->parsed_defs ? g_hash_table_lookup(npp->parsed_defs, escaped_port) : NULL;
        if (!component1) {
            component1 = netplan_netdef_new(npp, escaped_port, NETPLAN_DEF_TYPE_PORT, NETPLAN_BACKEND_OVS);
            if (g_hash_table_remove(npp->missing_id, escaped_port))
                npp->missing_ids_found++;
        }

        if (npp->current.filepath) {
            if (component1->filepath)
                g_free(component1->filepath);

            component1->filepath = g_strdup(npp->current.filepath);
        }

        if (component1->peer && g_strcmp0(component1->peer, escaped_peer))
            return yaml_error(npp, port, error, "Open vSwitch port '%s' is already assigned to peer '%s'",
                              component1->id, component1->peer);

        /* Create port 2 (peer) netdef */
        component2 = npp->parsed_defs ? g_hash_table_lookup(npp->parsed_defs, escaped_peer) : NULL;
        if (!component2) {
            component2 = netplan_netdef_new(npp, escaped_peer, NETPLAN_DEF_TYPE_PORT, NETPLAN_BACKEND_OVS);
            if (g_hash_table_remove(npp->missing_id, escaped_peer))
                npp->missing_ids_found++;
        }

        if (npp->current.filepath) {
            if (component2->filepath)
                g_free(component2->filepath);

            component2->filepath = g_strdup(npp->current.filepath);
        }

        if (component2->peer && g_strcmp0(component2->peer, escaped_port))
            return yaml_error(npp, peer, error, "Open vSwitch port '%s' is already assigned to peer '%s'",
                              component2->id, component2->peer);

        if (!component1->peer) {
            component1->peer = g_strdup(escaped_peer);
            component1->peer_link = component2;
        }
        if (!component2->peer) {
            component2->peer = g_strdup(escaped_port);
            component2->peer_link = component1;
        }
    }
    return TRUE;
}

STATIC gboolean
node_is_nulled_out(yaml_document_t* doc, yaml_node_t* node, const char* key_prefix, GHashTable* null_fields)
{
    if (node->type != YAML_MAPPING_NODE)
        return FALSE;

    // Empty nodes are not nulled-out, they're just empty!
    if (node->data.mapping.pairs.start == node->data.mapping.pairs.top)
        return FALSE;

    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        g_autofree char* full_key = NULL;

        key = yaml_document_get_node(doc, entry->key);
        value = yaml_document_get_node(doc, entry->value);

        full_key = g_strdup_printf("%s\t%s", key_prefix, key->data.scalar.value);
        // null detected, so we now flip the default return.
        if (g_hash_table_contains(null_fields, full_key))
            continue;
        if (!node_is_nulled_out(doc, value, full_key, null_fields))
            return FALSE;
    }
    return TRUE;
}

/**
 * Callback for a net device type entry like "ethernets:" in "network:"
 * @data: netdef_type (as pointer)
 */
STATIC gboolean
handle_network_type(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, const void* data, GError** error)
{
    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        const mapping_entry_handler* handlers;
        g_autofree char* full_key = NULL;

        key = yaml_document_get_node(&npp->doc, entry->key);
        if (!assert_valid_id(npp, key, error))
            return FALSE;
        /* globbing is not allowed for IDs */
        if (strpbrk(scalar(key), "*[]?"))
            return yaml_error(npp, key, error, "Definition ID '%s' must not use globbing", scalar(key));

        value = yaml_document_get_node(&npp->doc, entry->value);

        if (key_prefix && (npp->null_fields || npp->null_overrides)) {
            full_key = g_strdup_printf("%s\t%s", key_prefix, key->data.scalar.value);
            /* Ignore NULL fields (about to be deleted) */
            if (npp->null_fields && (g_hash_table_contains(npp->null_fields, full_key) || node_is_nulled_out(&npp->doc, value, full_key, npp->null_fields)))
                continue;
            /* Ignore this netdef if it is supposed to be part of the resulting
             * origin-hint file, but we're not currently processing said filepath. */
            if (npp->null_overrides) {
                const gchar* origin_hint = g_hash_table_lookup(npp->null_overrides, full_key);
                g_autofree gchar* basename = npp->current.filepath ?
                    g_path_get_basename(npp->current.filepath) : NULL;
                if (origin_hint && basename && g_strcmp0(origin_hint, basename) != 0)
                    continue;
            }
        }

        /* special-case "renderer:" key to set the per-type backend */
        if (strcmp(scalar(key), "renderer") == 0) {
            if (!parse_renderer(npp, value, &npp->current.backend, error))
                return FALSE;
            continue;
        }

        assert_type(npp, value, YAML_MAPPING_NODE);

        /* At this point we've seen a new starting definition, if it has been
         * already mentioned in another netdef, removing it from our "missing"
         * list. */
        if(g_hash_table_remove(npp->missing_id, scalar(key)))
            npp->missing_ids_found++;

        npp->current.netdef = npp->parsed_defs ? g_hash_table_lookup(npp->parsed_defs, scalar(key)) : NULL;
        if (npp->current.netdef) {
            /* already exists, overriding/amending previous definition */
            if (npp->current.netdef->type != GPOINTER_TO_UINT(data)) {
                /* If the existing netdef is a place holder, we just repurpose it */
                if (npp->current.netdef->type == NETPLAN_DEF_TYPE_NM_PLACEHOLDER_)
                    npp->current.netdef->type = GPOINTER_TO_UINT(data);
                else
                    return yaml_error(npp, key, error, "Updated definition '%s' changes device type", scalar(key));
            }
        } else {
            npp->current.netdef = netplan_netdef_new(npp, scalar(key), GPOINTER_TO_UINT(data), npp->current.backend);
        }
        if (npp->current.filepath) {
            if (npp->current.netdef->filepath)
                g_free(npp->current.netdef->filepath);
            npp->current.netdef->filepath = g_strdup(npp->current.filepath);
        }

        // XXX: breaks multi-pass parsing.
        //if (!g_hash_table_add(ids_in_file, npp->current.netdef->id))
        //    return yaml_error(npp, key, error, "Duplicate net definition ID '%s'", npp->current.netdef->id);

        /* and fill it with definitions */
        switch (npp->current.netdef->type) {
            case NETPLAN_DEF_TYPE_BOND: handlers = bond_def_handlers; break;
            case NETPLAN_DEF_TYPE_BRIDGE: handlers = bridge_def_handlers; break;
            case NETPLAN_DEF_TYPE_ETHERNET: handlers = ethernet_def_handlers; break;
            case NETPLAN_DEF_TYPE_MODEM: handlers = modem_def_handlers; break;
            case NETPLAN_DEF_TYPE_TUNNEL: handlers = tunnel_def_handlers; break;
            case NETPLAN_DEF_TYPE_VLAN: handlers = vlan_def_handlers; break;
            case NETPLAN_DEF_TYPE_VRF: handlers = vrf_def_handlers; break;
            case NETPLAN_DEF_TYPE_WIFI: handlers = wifi_def_handlers; break;
            case NETPLAN_DEF_TYPE_DUMMY: handlers = dummy_def_handlers; break;      /* wokeignore:rule=dummy */
            case NETPLAN_DEF_TYPE_VETH: handlers = veth_def_handlers; break;
            case NETPLAN_DEF_TYPE_NM:
                g_debug("netplan: %s: handling NetworkManager passthrough device, settings are not fully supported.", npp->current.netdef->id);
                handlers = ethernet_def_handlers;
                if (npp->current.netdef->backend != NETPLAN_BACKEND_NM) {
                    g_warning("nm-device: %s: the renderer for nm-devices must be NetworkManager, it will be used instead of the defined one.",
                              npp->current.netdef->id);
                    npp->current.netdef->backend = NETPLAN_BACKEND_NM;
                }
                break;
            default: g_assert_not_reached(); // LCOV_EXCL_LINE
        }

        /* Preprocessing */
        /* Any tunnel netdef needs to carry the 'vxlan' struct, as it might
         * potentially be a VXLAN tunnel. */
        if (npp->current.netdef->type == NETPLAN_DEF_TYPE_TUNNEL) {
            NetplanVxlan* vxlan = g_new0(NetplanVxlan, 1);
            reset_vxlan(vxlan);
            npp->current.vxlan = vxlan;
            if (npp->current.netdef->vxlan)
                g_free(npp->current.netdef->vxlan);
            npp->current.netdef->vxlan = vxlan;
        }

        if (!process_mapping(npp, value, full_key, handlers, NULL, error)) {
            if (npp->flags & NETPLAN_PARSER_IGNORE_ERRORS) {
                if (error && *error) {
                    g_warning("Skipping definition due to parsing errors. %s: %s", scalar(key), (*error)->message);
                }
                g_clear_error(error);
                npp->error_count++;
            } else {
                return FALSE;
            }
        }

        /* Postprocessing */
        /* Implicit VXLAN settings, which can be deduced from parsed data. */
        if (npp->current.netdef->type == NETPLAN_DEF_TYPE_TUNNEL &&
            npp->current.netdef->tunnel.mode == NETPLAN_TUNNEL_MODE_VXLAN) {
            if (npp->current.netdef->vxlan->link)
                npp->current.netdef->vxlan->link->has_vxlans = TRUE;
            else
                npp->current.netdef->vxlan->independent = TRUE;
        }

        /* validate definition-level conditions */
        int ret = validate_netdef_grammar(npp, npp->current.netdef, error);
        if (!ret && (npp->flags & NETPLAN_PARSER_IGNORE_ERRORS) == 0)
            return FALSE;

        if (!ret && npp->flags & NETPLAN_PARSER_IGNORE_ERRORS) {
            g_warning("Ignoring validation error. %s: %s", scalar(key), (*error)->message);
            g_clear_error(error);
            npp->error_count++;
        }

        /* convenience shortcut: physical device without match: means match
         * name on ID */
        if (npp->current.netdef->type < NETPLAN_DEF_TYPE_VIRTUAL && !npp->current.netdef->has_match)
            set_str_if_null(npp->current.netdef->match.original_name, npp->current.netdef->id);
    }
    npp->current.backend = NETPLAN_BACKEND_NONE;
    return TRUE;
}

static const mapping_entry_handler ovs_global_ssl_handlers[] = {
    {"ca-cert", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(ca_certificate)},
    {"certificate", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(client_certificate)},
    {"private-key", YAML_SCALAR_NODE, {.generic=handle_auth_str}, auth_offset(client_key)},
    {NULL}
};

STATIC gboolean
handle_ovs_global_ssl(NetplanParser* npp, yaml_node_t* node, const char* key_prefix, __unused const void* _, GError** error)
{
    gboolean ret;

    npp->current.auth = &(npp->global_ovs_settings.ssl);
    ret = process_mapping(npp, node, key_prefix, ovs_global_ssl_handlers, NULL, error);
    npp->current.auth = NULL;

    return ret;
}

static const mapping_entry_handler ovs_network_settings_handlers[] = {
    {"external-ids", YAML_MAPPING_NODE, {.map={.custom=handle_network_ovs_settings_global}}, ovs_settings_offset(external_ids)},
    {"other-config", YAML_MAPPING_NODE, {.map={.custom=handle_network_ovs_settings_global}}, ovs_settings_offset(other_config)},
    {"protocols", YAML_SEQUENCE_NODE, {.generic=handle_network_ovs_settings_global_protocol}, ovs_settings_offset(protocols)},
    {"ports", YAML_SEQUENCE_NODE, {.generic=handle_network_ovs_settings_global_ports}, NULL},
    {"ssl", YAML_MAPPING_NODE, {.map={.custom=handle_ovs_global_ssl}}, NULL},
    {NULL}
};

static const mapping_entry_handler network_handlers[] = {
    {"bonds", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_BOND)},
    {"bridges", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_BRIDGE)},
    {"ethernets", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_ETHERNET)},
    {"renderer", YAML_SCALAR_NODE, {.generic=handle_network_renderer}, NULL},
    {"tunnels", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_TUNNEL)},
    {"version", YAML_SCALAR_NODE, {.generic=handle_network_version}, NULL},
    {"vlans", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_VLAN)},
    {"vrfs", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_VRF)},
    {"wifis", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_WIFI)},
    {"modems", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_MODEM)},
    {"dummy-devices", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_DUMMY)},    /* wokeignore:rule=dummy */
    {"virtual-ethernets", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_VETH)},
    {"nm-devices", YAML_MAPPING_NODE, {.map={.custom=handle_network_type}}, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_NM)},
    {"openvswitch", YAML_MAPPING_NODE, {.map={.handlers=ovs_network_settings_handlers}}, NULL},
    {NULL}
};

/****************************************************
 * Grammar and handlers for root node
 ****************************************************/

static const mapping_entry_handler root_handlers[] = {
    {"network", YAML_MAPPING_NODE, {.map={.handlers=network_handlers}}, NULL},
    {NULL}
};

/*
 * Post-process some specific missing interfaces that are not required
 * to exist but are needed in order to generate backend configuration.
 */
STATIC void
process_missing_ids(NetplanParser* npp, __unused GError** error)
{
    GHashTableIter iter;
    gpointer key, value;

    if (g_hash_table_size(npp->missing_id) == 0)
        return;

    g_hash_table_iter_init(&iter, npp->missing_id);

    while (g_hash_table_iter_next(&iter, &key, &value)) {
        NetplanMissingNode* missing = (NetplanMissingNode*) value;
        NetplanNetDefinition* netdef = g_hash_table_lookup(npp->parsed_defs, missing->netdef_id);
        NetplanBackend backend = netdef->backend != NETPLAN_BACKEND_NONE ? netdef->backend : npp->global_backend;

        /* VLAN case: NetworkManager doesn't enforce the existence of a parent interface in order to
         * create a VLAN.
         */
        if (netdef->type == NETPLAN_DEF_TYPE_VLAN && backend == NETPLAN_BACKEND_NM) {
            netdef->vlan_link = netplan_netdef_new(npp, scalar(missing->node), NETPLAN_DEF_TYPE_NM_PLACEHOLDER_, NETPLAN_BACKEND_NM);
            g_hash_table_iter_remove(&iter);
        }

        /* VETH case: NetworkManager doesn't enforce the existence of the veth peer.
         * NM will create one connection for each veth in the pair. In this case, due to our integration with
         * NM (netplan-everywhere), we can't enforce the existence of both peers at a given moment because
         * they might be created one after the other.
         * When we find that the peer is missing, we create a temporary one using the placeholder type. That is necessary
         * so we can generate the keyfile referring to the correct peer name, even though it still doesn't exist.
         */
        if (netdef->type == NETPLAN_DEF_TYPE_VETH && backend == NETPLAN_BACKEND_NM) {
            netdef->veth_peer_link = netplan_netdef_new(npp, scalar(missing->node), NETPLAN_DEF_TYPE_NM_PLACEHOLDER_, NETPLAN_BACKEND_NM);
            g_hash_table_iter_remove(&iter);
        }
    }
}

/**
 * Handle multiple-pass parsing of the yaml document.
 */
STATIC gboolean
process_document(NetplanParser* npp, GError** error)
{
    gboolean ret;
    int previously_found;
    int still_missing;

    g_assert(npp->missing_id == NULL);
    npp->missing_id = g_hash_table_new_full(g_str_hash, g_str_equal, NULL, g_free);

    do {
        g_debug("starting new processing pass");

        previously_found = npp->missing_ids_found;
        npp->missing_ids_found = 0;

        g_clear_error(error);

        ret = process_mapping(npp, yaml_document_get_root_node(&npp->doc), "", root_handlers, NULL, error);

        still_missing = g_hash_table_size(npp->missing_id);

        if (still_missing > 0 && npp->missing_ids_found == previously_found)
            break;
    } while (still_missing > 0 || npp->missing_ids_found > 0);

    /* If an error already occurred we should return and not assume it's a missing interface*/
    if (error && *error)
        goto cleanup;

    process_missing_ids(npp, error);

    if (g_hash_table_size(npp->missing_id) > 0) {
        GHashTableIter iter;
        gpointer key, value;
        NetplanMissingNode *missing;

        g_clear_error(error);

        /* Get the first missing identifier we can get from our list, to
         * approximate early failure and give the user a meaningful error. */
        g_hash_table_iter_init (&iter, npp->missing_id);
        g_hash_table_iter_next (&iter, &key, &value);
        missing = (NetplanMissingNode*) value;

        ret = yaml_error(npp, missing->node, error, "%s: interface '%s' is not defined",
                         missing->netdef_id, (char*)key);
        goto cleanup;
    }

cleanup:
    g_hash_table_destroy(npp->missing_id);
    npp->missing_id = NULL;
    return ret;
}

STATIC gboolean
_netplan_parser_load_single_file(NetplanParser* npp, const char *opt_filepath, yaml_document_t *doc, GError** error)
{
    int ret = FALSE;

    if (opt_filepath) {
        char* source = g_strdup(opt_filepath);
        if (!npp->sources)
            npp->sources = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
        g_hash_table_add(npp->sources, source);
    }

    /* empty file? */
    if (yaml_document_get_root_node(doc) == NULL)
        return TRUE;

    g_assert(npp->ids_in_file == NULL);
    npp->ids_in_file = g_hash_table_new(g_str_hash, NULL);

    npp->current.filepath = opt_filepath? g_strdup(opt_filepath) : NULL;
    ret = process_document(npp, error);
    g_free((void *)npp->current.filepath);
    npp->current.filepath = NULL;

    yaml_document_delete(doc);
    g_hash_table_destroy(npp->ids_in_file);
    npp->ids_in_file = NULL;

    if (!ret && npp->flags & NETPLAN_PARSER_IGNORE_ERRORS) {
        g_clear_error(error);
        npp->error_count++;
        return TRUE;
    }
    return ret;
}

gboolean
netplan_parser_load_yaml_from_fd(NetplanParser* npp, int fd, GError** error)
{
    yaml_document_t *doc = &npp->doc;

    if (!load_yaml_from_fd(fd, doc, error))
        return FALSE;
    return _netplan_parser_load_single_file(npp, NULL, doc, error);

}

gboolean
netplan_parser_load_yaml(NetplanParser* npp, const char* filename, GError** error)
{
    yaml_document_t *doc = &npp->doc;
    /* Log a warning if a file can be read or written by a non-owner.
     * It could contain sensitive information (e.g. WiFi passwords), so should
     * stay secret. */
    mode_t mask = S_IRGRP | S_IWGRP | S_IROTH | S_IWOTH;
    struct stat info;
    if (stat(filename, &info) < 0) {
        g_set_error(error, NETPLAN_FILE_ERROR, errno, "Cannot stat %s: %m", filename);
        return FALSE;
    } else if (info.st_mode & mask)
        g_warning("Permissions for %s are too open. Netplan configuration "
                  "should NOT be accessible by others.", filename);

    if (!load_yaml(filename, doc, error))
        return FALSE;
    return _netplan_parser_load_single_file(npp, filename, doc, error);
}

STATIC gboolean
finish_iterator(const NetplanParser* npp, NetplanNetDefinition* nd, GError **error)
{
    /* Take more steps to make sure we always have a backend set for netdefs */
    if (nd->backend == NETPLAN_BACKEND_NONE) {
        nd->backend = get_default_backend_for_type(npp->global_backend, nd->type);
        g_debug("%s: setting default backend to %i", nd->id, nd->backend);
    }

    /* Skip validation if the IGNORE_ERRORS flag is set */
    if (npp->flags & NETPLAN_PARSER_IGNORE_ERRORS) return TRUE;

    /* Do a final pass of validation for backend-specific conditions */
    return validate_backend_rules(npp, nd, error) && validate_sriov_rules(npp, nd, error);
}

STATIC gboolean
insert_kv_into_hash(void *key, void *value, void *hash)
{
    g_hash_table_insert(hash, key, value);
    return TRUE;
}

gboolean
netplan_state_import_parser_results(NetplanState* np_state, NetplanParser* npp, GError** error)
{
    if (npp->parsed_defs) {
        GError *recoverable = NULL;
        GHashTableIter iter;
        gpointer key, value;
        char *regdom = NULL;
        g_debug("We have some netdefs, pass them through a final round of validation");

        /* Check/adopt VRF routes before route consistency and validation */
        if (!adopt_and_validate_vrf_routes(npp, npp->parsed_defs, error))
            return FALSE;

        if (!validate_default_route_consistency(npp, npp->parsed_defs, &recoverable)) {
            g_warning("Problem encountered while validating default route consistency."
                      "Please set up multiple routing tables and use `routing-policy` instead.\n"
                      "Error: %s", (recoverable) ? recoverable->message : "");
            g_clear_error(&recoverable);
        }

        g_hash_table_iter_init (&iter, npp->parsed_defs);

        while (g_hash_table_iter_next (&iter, &key, &value)) {
            g_assert(np_state->netdefs == NULL ||
                    g_hash_table_lookup(np_state->netdefs, key) == NULL);
            NetplanNetDefinition *nd = value;
            if (nd->regulatory_domain) {
                if (!regdom)
                    regdom = nd->regulatory_domain;
                else if (g_strcmp0(regdom, nd->regulatory_domain) != 0)
                    g_warning("%s: Conflicting regulatory-domain (%s vs %s)",
                              nd->id, regdom, nd->regulatory_domain);
            }
            if (!finish_iterator(npp, nd, error))
                return FALSE;
            g_debug("Configuration is valid");
        }
    }

    if (npp->parsed_defs) {
        if (!np_state->netdefs)
            np_state->netdefs = g_hash_table_new(g_str_hash, g_str_equal);
        g_hash_table_foreach_steal(npp->parsed_defs, insert_kv_into_hash, np_state->netdefs);
    }
    np_state->netdefs_ordered = g_list_concat(np_state->netdefs_ordered, npp->ordered);
    np_state->ovs_settings = npp->global_ovs_settings;
    np_state->backend = npp->global_backend;

    if (npp->sources) {
        if (!np_state->sources)
            np_state->sources = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
        g_hash_table_foreach_steal(npp->sources, insert_kv_into_hash, np_state->sources);
    }

    if (npp->global_renderer) {
        if (!np_state->global_renderer)
            np_state->global_renderer = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
        g_hash_table_foreach_steal(npp->global_renderer, insert_kv_into_hash, np_state->global_renderer);
    }

    /* We need to reset those fields manually as we transfered ownership of the underlying
       data to out. If we don't do this, netplan_clear_parser will deallocate data
       that we don't own anymore. */
    npp->ordered = NULL;
    memset(&npp->global_ovs_settings, 0, sizeof(NetplanOVSSettings));

    netplan_parser_reset(npp);
    return TRUE;
}

NetplanParser*
netplan_parser_new()
{
    NetplanParser* npp = g_new0(NetplanParser, 1);
    netplan_parser_reset(npp);
    return npp;
}

void
netplan_parser_reset(NetplanParser* npp)
{
    g_assert(npp != NULL);

    if(npp->parsed_defs) {
        /* FIXME: make sure that any dynamically allocated netdef data is freed */
        g_hash_table_destroy(npp->parsed_defs);
        npp->parsed_defs = NULL;
    }
    if(npp->ordered) {
        g_clear_list(&npp->ordered, clear_netdef_from_list);
        npp->ordered = NULL;
    }

    npp->global_backend = NETPLAN_BACKEND_NONE;
    reset_ovs_settings(&npp->global_ovs_settings);

    /* These pointers are non-owning, it's not our place to free their resources*/
    npp->current.netdef = NULL;
    npp->current.auth = NULL;
    npp->current.vxlan = NULL;

    access_point_clear(&npp->current.access_point, npp->current.backend);
    wireguard_peer_clear(&npp->current.wireguard_peer);
    address_options_clear(&npp->current.addr_options);
    route_clear(&npp->current.route);
    ip_rule_clear(&npp->current.ip_rule);
    g_free((void *)npp->current.filepath);
    npp->current.filepath = NULL;

    // LCOV_EXCL_START
    if (npp->ids_in_file) {
        g_hash_table_destroy(npp->ids_in_file);
        npp->ids_in_file = NULL;
    }
    // LCOV_EXCL_STOP

    if (npp->missing_id) {
        g_hash_table_destroy(npp->missing_id);
        npp->missing_id = NULL;
    }

    npp->missing_ids_found = 0;

    if (npp->null_fields) {
        g_hash_table_destroy(npp->null_fields);
        npp->null_fields = NULL;
    }

    if (npp->null_overrides) {
        g_hash_table_destroy(npp->null_overrides);
        npp->null_overrides = NULL;
    }

    if (npp->sources) {
        /* Properly configured at creation not to leak */
        g_hash_table_destroy(npp->sources);
        npp->sources = NULL;
    }

    if (npp->global_renderer) {
        g_hash_table_destroy(npp->global_renderer);
        npp->global_renderer = NULL;
    }

    npp->flags = 0;
    npp->error_count = 0;
}

void
netplan_parser_clear(NetplanParser** npp_p)
{
    NetplanParser* npp = *npp_p;
    *npp_p = NULL;
    netplan_parser_reset(npp);
    g_free(npp);
}

gboolean
netplan_parser_set_flags(NetplanParser* npp, const unsigned int flags, GError** error)
{
    if (flags >= NETPLAN_PARSER_FLAGS_MAX_) {
        g_set_error(error, NETPLAN_PARSER_ERROR, NETPLAN_ERROR_INVALID_FLAG,
                    "Invalid flag set");
        return FALSE;
    }

    npp->flags = flags;
    return TRUE;
}

unsigned int
netplan_parser_get_flags(const NetplanParser* npp)
{
    return npp->flags;
}

unsigned int
netplan_parser_get_error_count(const NetplanParser* npp)
{
    return npp->error_count;
}

/* Check if this is a Netdef-ID or global keyword which can be nullified.
 * Overrides (depending on YAML hierarchy) can only happen on global values
 * (like "renderer") or on the individual netdef level.
 * @return the Netdef-ID/keyword or NULL */
STATIC gboolean
is_netdef_id_or_global_value(const char* full_key)
{
    g_autofree gchar* key = g_strstrip(g_strdup(full_key)); // strip leading '\t'
    gboolean ret = FALSE;
    gchar** split = g_strsplit(key, "\t", 0);
    if (split[0] && g_strcmp0(split[0], "network") == 0) {
        if (split[1]) {
            if (g_strcmp0(split[1], "renderer") == 0) {
                ret = TRUE; // a valid global keyword
                goto cleanup;
            }
            /* check if is valid network type */
            for (unsigned i = 0; i < NETPLAN_DEF_TYPE_MAX_; ++i) {
                const char* def_type_name = netplan_def_type_name(i);
                if (def_type_name && g_strcmp0(split[1], def_type_name) == 0) {
                    /* return keyword if split[2] is a Netdef-ID
                     * e.g. "network.ethernets.eth0" */
                    if (split[2] && !split[3]) {
                        ret = TRUE; // a valid Netdef-ID
                        break;
                    }
                }
            }
        }
    }
cleanup:
    g_strfreev(split);
    return ret;
}

STATIC void
extract_null_fields(yaml_document_t* doc, yaml_node_t* node, GHashTable* null_fields, char* key_prefix, const char* origin_hint)
{
    yaml_node_pair_t* entry;
    switch (node->type) {
        // LCOV_EXCL_START
        case YAML_NO_NODE:
            g_hash_table_insert(null_fields, key_prefix, NULL);
            key_prefix = NULL;
            break;
        // LCOV_EXCL_STOP
        case YAML_SCALAR_NODE:
            if (       g_ascii_strcasecmp("null", scalar(node)) == 0
                    || g_strcmp0((char*)node->tag, YAML_NULL_TAG) == 0
                    || g_strcmp0(scalar(node), "~") == 0) {
                g_hash_table_insert(null_fields, key_prefix, NULL);
                key_prefix = NULL;
            }
            break;
        case YAML_SEQUENCE_NODE:
            /* Do nothing, we don't support nullifying *inside* sequences */
            break;
        case YAML_MAPPING_NODE:
            for (entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
                yaml_node_t* key, *value;
                char* full_key;
                key = yaml_document_get_node(doc, entry->key);
                value = yaml_document_get_node(doc, entry->value);
                full_key = g_strdup_printf("%s\t%s", key_prefix, key->data.scalar.value);
                /* If an origin_hint is given, nullify the overrides, like
                 * Netdef-IDs or global values (e.g. "renderer") and track the
                 * origin_hint filename as hashmap value. To ignore such netdefs
                 * or globals during the YAML parsing stage should they be
                 * defined somewhere else outside the origin-hint file. */
                if (origin_hint && is_netdef_id_or_global_value(full_key)) {
                    g_hash_table_insert(null_fields, g_strdup(full_key), g_strdup(origin_hint));
                    g_debug("ignoring previous definition of: %s (except in %s)", full_key, origin_hint);
                }
                extract_null_fields(doc, value, null_fields, full_key, origin_hint);
            }
            break;
        // LCOV_EXCL_START
        default:
            g_assert(FALSE); // supposedly unreachable!
        // LCOV_EXCL_STOP
    }
    g_free(key_prefix);
}

gboolean
netplan_parser_load_nullable_fields(NetplanParser* npp, int input_fd, GError** error)
{
    yaml_document_t doc;
    if (!load_yaml_from_fd(input_fd, &doc, error))
        return FALSE; // LCOV_EXCL_LINE

    /* empty file? */
    if (yaml_document_get_root_node(&doc) == NULL)
        return TRUE; // LCOV_EXCL_LINE

    if (!npp->null_fields)
        npp->null_fields = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_free);

    extract_null_fields(&doc, yaml_document_get_root_node(&doc), npp->null_fields, g_strdup(""), NULL);
    yaml_document_delete(&doc);
    return TRUE;
}

gboolean
netplan_parser_load_nullable_overrides(
    NetplanParser* npp, int input_fd, const char* constraint, GError** error)
{
    yaml_document_t doc;
    if (!load_yaml_from_fd(input_fd, &doc, error))
        return FALSE; // LCOV_EXCL_LINE

    /* empty file? */
    if (yaml_document_get_root_node(&doc) == NULL)
        return TRUE; // LCOV_EXCL_LINE

    if (!npp->null_overrides)
        npp->null_overrides = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_free);

    /* Track the given origin_hint filename, as a constraint, for any netdef or
     * global value of the given <input_fd> (i.e. YAML patch), so that those can
     * be ignored later (inside YAML the parsing stage), shouldn't they
     * originate from the origin-hint file, but from some other YAML file inside
     * the hierarchy.
     *
     * Examples for "origin_hint:hint.yaml" being tracked in npp->null_overrides:
     * yaml patch: "network.ethernets.eth0.dhcp4=false"
     * => network.ethernets.eth0: hint.yaml
     * yaml patch: "network.renderer=NetworkManager"
     * => network.renderer: hint.yaml */
    extract_null_fields(&doc, yaml_document_get_root_node(&doc), npp->null_overrides, g_strdup(""), constraint);
    yaml_document_delete(&doc);
    return TRUE;
}
