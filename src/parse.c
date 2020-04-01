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

#include <stdarg.h>
#include <errno.h>
#include <regex.h>
#include <arpa/inet.h>

#include <glib.h>
#include <glib/gstdio.h>
#include <gio/gio.h>

#include <yaml.h>

#include "parse.h"
#include "error.h"
#include "validation.h"

/* convenience macro to put the offset of a NetplanNetDefinition field into "void* data" */
#define netdef_offset(field) GUINT_TO_POINTER(offsetof(NetplanNetDefinition, field))
#define route_offset(field) GUINT_TO_POINTER(offsetof(NetplanIPRoute, field))
#define ip_rule_offset(field) GUINT_TO_POINTER(offsetof(NetplanIPRule, field))
#define auth_offset(field) GUINT_TO_POINTER(offsetof(NetplanAuthenticationSettings, field))

/* NetplanNetDefinition that is currently being processed */
static NetplanNetDefinition* cur_netdef;

/* wifi AP that is currently being processed */
static NetplanWifiAccessPoint* cur_access_point;

/* authentication options that are currently being processed */
static NetplanAuthenticationSettings* cur_auth;

static NetplanIPRoute* cur_route;
static NetplanIPRule* cur_ip_rule;

static NetplanBackend backend_global, backend_cur_type;

/* Global ID → NetplanNetDefinition* map for all parsed config files */
GHashTable* netdefs;

/* Contains the same objects as 'netdefs' but ordered by dependency */
GList* netdefs_ordered;

/* Set of IDs in currently parsed YAML file, for being able to detect
 * "duplicate ID within one file" vs. allowing a drop-in to override/amend an
 * existing definition */
static GHashTable* ids_in_file;

/**
 * Load YAML file name into a yaml_document_t.
 *
 * Returns: TRUE on success, FALSE if the document is malformed; @error gets set then.
 */
static gboolean
load_yaml(const char* yaml, yaml_document_t* doc, GError** error)
{
    FILE* fyaml = NULL;
    yaml_parser_t parser;
    gboolean ret = TRUE;

    current_file = yaml;

    fyaml = g_fopen(yaml, "r");
    if (!fyaml) {
        g_set_error(error, G_FILE_ERROR, errno, "Cannot open %s: %s", yaml, g_strerror(errno));
        return FALSE;
    }

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
static gboolean
assert_type_fn(yaml_node_t* node, yaml_node_type_t expected_type, GError** error)
{
    if (node->type == expected_type)
        return TRUE;

    switch (expected_type) {
        case YAML_VARIABLE_NODE:
            /* Special case, defer sanity checking to the next handlers */
            return TRUE;
            break;
        case YAML_SCALAR_NODE:
            yaml_error(node, error, "expected scalar");
            break;
        case YAML_SEQUENCE_NODE:
            yaml_error(node, error, "expected sequence");
            break;
        case YAML_MAPPING_NODE:
            yaml_error(node, error, "expected mapping (check indentation)");
            break;

        // LCOV_EXCL_START
        default:
            g_assert_not_reached();
        // LCOV_EXCL_STOP
    }
    return FALSE;
}

#define assert_type(n,t) { if (!assert_type_fn(n,t,error)) return FALSE; }

static inline const char*
scalar(const yaml_node_t* node)
{
    return (const char*) node->data.scalar.value;
}

static void
add_missing_node(const yaml_node_t* node)
{
    NetplanMissingNode* missing;

    /* Let's capture the current netdef we were playing with along with the
     * actual yaml_node_t that errors (that is an identifier not previously
     * seen by the compiler). We can use it later to write an sensible error
     * message and point the user in the right direction. */
    missing = g_new0(NetplanMissingNode, 1);
    missing->netdef_id = cur_netdef->id;
    missing->node = node;

    g_debug("recording missing yaml_node_t %s", scalar(node));
    g_hash_table_insert(missing_id, (gpointer)scalar(node), missing);
}

/**
 * Check that node contains a valid ID/interface name. Raise GError if not.
 */
static gboolean
assert_valid_id(yaml_node_t* node, GError** error)
{
    static regex_t re;
    static gboolean re_inited = FALSE;

    assert_type(node, YAML_SCALAR_NODE);

    if (!re_inited) {
        g_assert(regcomp(&re, "^[[:alnum:][:punct:]]+$", REG_EXTENDED|REG_NOSUB) == 0);
        re_inited = TRUE;
    }

    if (regexec(&re, scalar(node), 0, NULL, 0) != 0)
        return yaml_error(node, error, "Invalid name '%s'", scalar(node));
    return TRUE;
}

/****************************************************
 * Data types and functions for interpreting YAML nodes
 ****************************************************/

typedef gboolean (*node_handler) (yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error);

typedef struct mapping_entry_handler_s {
    /* mapping key (must be scalar) */
    const char* key;
    /* expected type  of the mapped value */
    yaml_node_type_t type;
    /* handler for the value of this key */
    node_handler handler;
    /* if type == YAML_MAPPING_NODE and handler is NULL, use process_mapping()
     * on this handler map as handler */
    const struct mapping_entry_handler_s* map_handlers;
    /* user_data */
    const void* data;
} mapping_entry_handler;

/**
 * Return the #mapping_entry_handler that matches @key, or NULL if not found.
 */
static const mapping_entry_handler*
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
static gboolean
process_mapping(yaml_document_t* doc, yaml_node_t* node, const mapping_entry_handler* handlers, GError** error)
{
    yaml_node_pair_t* entry;

    assert_type(node, YAML_MAPPING_NODE);

    for (entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        const mapping_entry_handler* h;

        g_assert(*error == NULL);

        key = yaml_document_get_node(doc, entry->key);
        value = yaml_document_get_node(doc, entry->value);
        assert_type(key, YAML_SCALAR_NODE);
        h = get_handler(handlers, scalar(key));
        if (!h)
            return yaml_error(key, error, "unknown key '%s'", scalar(key));
        assert_type(value, h->type);
        if (h->map_handlers) {
            g_assert(h->handler == NULL);
            g_assert(h->type == YAML_MAPPING_NODE);
            if (!process_mapping(doc, value, h->map_handlers, error))
                return FALSE;
        } else {
            if (!h->handler(doc, value, h->data, error))
                return FALSE;
        }
    }

    return TRUE;
}

/**
 * Generic handler for setting a cur_netdef string field from a scalar node
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
static gboolean
handle_netdef_str(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) cur_netdef + offset);
    g_free(*dest);
    *dest = g_strdup(scalar(node));
    return TRUE;
}

/**
 * Generic handler for setting a cur_netdef ID/iface name field from a scalar node
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
static gboolean
handle_netdef_id(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    if (!assert_valid_id(node, error))
        return FALSE;
    return handle_netdef_str(doc, node, data, error);
}

/**
 * Generic handler for setting a cur_netdef ID/iface name field referring to an
 * existing ID from a scalar node
 * @data: offset into NetplanNetDefinition where the NetplanNetDefinition* field to write is
 *        located
 */
static gboolean
handle_netdef_id_ref(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    NetplanNetDefinition* ref = NULL;

    ref = g_hash_table_lookup(netdefs, scalar(node));
    if (!ref) {
        add_missing_node(node);
    } else {
        *((NetplanNetDefinition**) ((void*) cur_netdef + offset)) = ref;
    }
    return TRUE;
}


/**
 * Generic handler for setting a cur_netdef MAC address field from a scalar node
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
static gboolean
handle_netdef_mac(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    static regex_t re;
    static gboolean re_inited = FALSE;

    g_assert(node->type == YAML_SCALAR_NODE);

    if (!re_inited) {
        g_assert(regcomp(&re, "^[[:xdigit:]][[:xdigit:]]:[[:xdigit:]][[:xdigit:]]:[[:xdigit:]][[:xdigit:]]:[[:xdigit:]][[:xdigit:]]:[[:xdigit:]][[:xdigit:]]:[[:xdigit:]][[:xdigit:]]$", REG_EXTENDED|REG_NOSUB) == 0);
        re_inited = TRUE;
    }

    if (regexec(&re, scalar(node), 0, NULL, 0) != 0)
        return yaml_error(node, error, "Invalid MAC address '%s', must be XX:XX:XX:XX:XX:XX", scalar(node));

    return handle_netdef_str(doc, node, data, error);
}

/**
 * Generic handler for setting a cur_netdef gboolean field from a scalar node
 * @data: offset into NetplanNetDefinition where the gboolean field to write is located
 */
static gboolean
handle_netdef_bool(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    gboolean v;

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
        return yaml_error(node, error, "invalid boolean value '%s'", scalar(node));

    *((gboolean*) ((void*) cur_netdef + offset)) = v;
    return TRUE;
}

/**
 * Generic handler for setting a cur_netdef guint field from a scalar node
 * @data: offset into NetplanNetDefinition where the guint field to write is located
 */
static gboolean
handle_netdef_guint(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT)
        return yaml_error(node, error, "invalid unsigned int value '%s'", scalar(node));

    *((guint*) ((void*) cur_netdef + offset)) = (guint) v;
    return TRUE;
}

static gboolean
handle_netdef_ip4(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) cur_netdef + offset);
    g_autofree char* addr = NULL;
    char* prefix_len;

    /* these addresses can't have /prefix_len */
    addr = g_strdup(scalar(node));
    prefix_len = strrchr(addr, '/');

    /* FIXME: stop excluding this from coverage; refactor address handling instead */
    // LCOV_EXCL_START
    if (prefix_len)
        return yaml_error(node, error,
                          "invalid address: a single IPv4 address (without /prefixlength) is required");

    /* is it an IPv4 address? */
    if (!is_ip4_address(addr))
        return yaml_error(node, error,
                          "invalid IPv4 address: %s", scalar(node));
    // LCOV_EXCL_STOP

    g_free(*dest);
    *dest = g_strdup(scalar(node));

    return TRUE;
}

static gboolean
handle_netdef_ip6(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) cur_netdef + offset);
    g_autofree char* addr = NULL;
    char* prefix_len;

    /* these addresses can't have /prefix_len */
    addr = g_strdup(scalar(node));
    prefix_len = strrchr(addr, '/');

    /* FIXME: stop excluding this from coverage; refactor address handling instead */
    // LCOV_EXCL_START
    if (prefix_len)
        return yaml_error(node, error,
                          "invalid address: a single IPv6 address (without /prefixlength) is required");

    /* is it an IPv6 address? */
    if (!is_ip6_address(addr))
        return yaml_error(node, error,
                          "invalid IPv6 address: %s", scalar(node));
    // LCOV_EXCL_STOP

    g_free(*dest);
    *dest = g_strdup(scalar(node));

    return TRUE;
}


/****************************************************
 * Grammar and handlers for network config "match" entry
 ****************************************************/

static const mapping_entry_handler match_handlers[] = {
    {"driver", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(match.driver)},
    {"macaddress", YAML_SCALAR_NODE, handle_netdef_mac, NULL, netdef_offset(match.mac)},
    {"name", YAML_SCALAR_NODE, handle_netdef_id, NULL, netdef_offset(match.original_name)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network config "auth" entry
 ****************************************************/

static gboolean
handle_auth_str(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    g_assert(cur_auth);
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) cur_auth + offset);
    g_free(*dest);
    *dest = g_strdup(scalar(node));
    return TRUE;
}

static gboolean
handle_auth_key_management(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    g_assert(cur_auth);
    if (strcmp(scalar(node), "none") == 0)
        cur_auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_NONE;
    else if (strcmp(scalar(node), "psk") == 0)
        cur_auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK;
    else if (strcmp(scalar(node), "eap") == 0)
        cur_auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_EAP;
    else if (strcmp(scalar(node), "802.1x") == 0)
        cur_auth->key_management = NETPLAN_AUTH_KEY_MANAGEMENT_8021X;
    else
        return yaml_error(node, error, "unknown key management type '%s'", scalar(node));
    return TRUE;
}

static gboolean
handle_auth_method(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    g_assert(cur_auth);
    if (strcmp(scalar(node), "tls") == 0)
        cur_auth->eap_method = NETPLAN_AUTH_EAP_TLS;
    else if (strcmp(scalar(node), "peap") == 0)
        cur_auth->eap_method = NETPLAN_AUTH_EAP_PEAP;
    else if (strcmp(scalar(node), "ttls") == 0)
        cur_auth->eap_method = NETPLAN_AUTH_EAP_TTLS;
    else
        return yaml_error(node, error, "unknown EAP method '%s'", scalar(node));
    return TRUE;
}

static const mapping_entry_handler auth_handlers[] = {
    {"key-management", YAML_SCALAR_NODE, handle_auth_key_management},
    {"method", YAML_SCALAR_NODE, handle_auth_method},
    {"identity", YAML_SCALAR_NODE, handle_auth_str, NULL, auth_offset(identity)},
    {"anonymous-identity", YAML_SCALAR_NODE, handle_auth_str, NULL, auth_offset(anonymous_identity)},
    {"password", YAML_SCALAR_NODE, handle_auth_str, NULL, auth_offset(password)},
    {"ca-certificate", YAML_SCALAR_NODE, handle_auth_str, NULL, auth_offset(ca_certificate)},
    {"client-certificate", YAML_SCALAR_NODE, handle_auth_str, NULL, auth_offset(client_certificate)},
    {"client-key", YAML_SCALAR_NODE, handle_auth_str, NULL, auth_offset(client_key)},
    {"client-key-password", YAML_SCALAR_NODE, handle_auth_str, NULL, auth_offset(client_key_password)},
    {"phase2-auth", YAML_SCALAR_NODE, handle_auth_str, NULL, auth_offset(phase2_auth)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network device definition
 ****************************************************/

static NetplanBackend
get_default_backend_for_type(NetplanDefType type)
{
    if (backend_global != NETPLAN_BACKEND_NONE)
        return backend_global;

    /* networkd can handle all device types at the moment, so nothing
     * type-specific */
    return NETPLAN_BACKEND_NETWORKD;
}

static gboolean
handle_access_point_password(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    g_assert(cur_access_point);
    /* shortcut for WPA-PSK */
    cur_access_point->has_auth = TRUE;
    cur_access_point->auth.key_management = NETPLAN_AUTH_KEY_MANAGEMENT_WPA_PSK;
    g_free(cur_access_point->auth.password);
    cur_access_point->auth.password = g_strdup(scalar(node));
    return TRUE;
}

static gboolean
handle_access_point_auth(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    gboolean ret;

    g_assert(cur_access_point);
    cur_access_point->has_auth = TRUE;

    cur_auth = &cur_access_point->auth;
    ret = process_mapping(doc, node, auth_handlers, error);
    cur_auth = NULL;

    return ret;
}

static gboolean
handle_access_point_mode(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    g_assert(cur_access_point);
    if (strcmp(scalar(node), "infrastructure") == 0)
        cur_access_point->mode = NETPLAN_WIFI_MODE_INFRASTRUCTURE;
    else if (strcmp(scalar(node), "adhoc") == 0)
        cur_access_point->mode = NETPLAN_WIFI_MODE_ADHOC;
    else if (strcmp(scalar(node), "ap") == 0)
        cur_access_point->mode = NETPLAN_WIFI_MODE_AP;
    else
        return yaml_error(node, error, "unknown wifi mode '%s'", scalar(node));
    return TRUE;
}

static const mapping_entry_handler wifi_access_point_handlers[] = {
    {"mode", YAML_SCALAR_NODE, handle_access_point_mode},
    {"password", YAML_SCALAR_NODE, handle_access_point_password},
    {"auth", YAML_MAPPING_NODE, handle_access_point_auth},
    {NULL}
};

/**
 * Parse scalar node's string into a netdef_backend.
 */
static gboolean
parse_renderer(yaml_node_t* node, NetplanBackend* backend, GError** error)
{
    if (strcmp(scalar(node), "networkd") == 0)
        *backend = NETPLAN_BACKEND_NETWORKD;
    else if (strcmp(scalar(node), "NetworkManager") == 0)
        *backend = NETPLAN_BACKEND_NM;
    else
        return yaml_error(node, error, "unknown renderer '%s'", scalar(node));
    return TRUE;
}

static gboolean
handle_netdef_renderer(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    return parse_renderer(node, &cur_netdef->backend, error);
}

static gboolean
handle_accept_ra(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    if (g_ascii_strcasecmp(scalar(node), "true") == 0 ||
        g_ascii_strcasecmp(scalar(node), "on") == 0 ||
        g_ascii_strcasecmp(scalar(node), "yes") == 0 ||
        g_ascii_strcasecmp(scalar(node), "y") == 0)
        cur_netdef->accept_ra = NETPLAN_RA_MODE_ENABLED;
    else if (g_ascii_strcasecmp(scalar(node), "false") == 0 ||
        g_ascii_strcasecmp(scalar(node), "off") == 0 ||
        g_ascii_strcasecmp(scalar(node), "no") == 0 ||
        g_ascii_strcasecmp(scalar(node), "n") == 0)
        cur_netdef->accept_ra = NETPLAN_RA_MODE_DISABLED;
    else
        return yaml_error(node, error, "invalid boolean value '%s'", scalar(node));

    return TRUE;
}

static gboolean
handle_match(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    cur_netdef->has_match = TRUE;
    return process_mapping(doc, node, match_handlers, error);
}

static gboolean
handle_auth(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    gboolean ret;

    cur_netdef->has_auth = TRUE;

    cur_auth = &cur_netdef->auth;
    ret = process_mapping(doc, node, auth_handlers, error);
    cur_auth = NULL;

    return ret;
}

static gboolean
handle_addresses(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        g_autofree char* addr = NULL;
        char* prefix_len;
        guint64 prefix_len_num;
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        assert_type(entry, YAML_SCALAR_NODE);

        /* split off /prefix_len */
        addr = g_strdup(scalar(entry));
        prefix_len = strrchr(addr, '/');
        if (!prefix_len)
            return yaml_error(node, error, "address '%s' is missing /prefixlength", scalar(entry));
        *prefix_len = '\0';
        prefix_len++; /* skip former '/' into first char of prefix */
        prefix_len_num = g_ascii_strtoull(prefix_len, NULL, 10);

        /* is it an IPv4 address? */
        if (is_ip4_address(addr)) {
            if (prefix_len_num == 0 || prefix_len_num > 32)
                return yaml_error(node, error, "invalid prefix length in address '%s'", scalar(entry));

            if (!cur_netdef->ip4_addresses)
                cur_netdef->ip4_addresses = g_array_new(FALSE, FALSE, sizeof(char*));
            char* s = g_strdup(scalar(entry));
            g_array_append_val(cur_netdef->ip4_addresses, s);
            continue;
        }

        /* is it an IPv6 address? */
        if (is_ip6_address(addr)) {
            if (prefix_len_num == 0 || prefix_len_num > 128)
                return yaml_error(node, error, "invalid prefix length in address '%s'", scalar(entry));
            if (!cur_netdef->ip6_addresses)
                cur_netdef->ip6_addresses = g_array_new(FALSE, FALSE, sizeof(char*));
            char* s = g_strdup(scalar(entry));
            g_array_append_val(cur_netdef->ip6_addresses, s);
            continue;
        }

        return yaml_error(node, error, "malformed address '%s', must be X.X.X.X/NN or X:X:X:X:X:X:X:X/NN", scalar(entry));
    }

    return TRUE;
}

static gboolean
handle_gateway4(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    if (!is_ip4_address(scalar(node)))
        return yaml_error(node, error, "invalid IPv4 address '%s'", scalar(node));
    cur_netdef->gateway4 = g_strdup(scalar(node));
    return TRUE;
}

static gboolean
handle_gateway6(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    if (!is_ip6_address(scalar(node)))
        return yaml_error(node, error, "invalid IPv6 address '%s'", scalar(node));
    cur_netdef->gateway6 = g_strdup(scalar(node));
    return TRUE;
}

static gboolean
handle_wifi_access_points(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;

        key = yaml_document_get_node(doc, entry->key);
        assert_type(key, YAML_SCALAR_NODE);
        value = yaml_document_get_node(doc, entry->value);
        assert_type(value, YAML_MAPPING_NODE);

        g_assert(cur_access_point == NULL);
        cur_access_point = g_new0(NetplanWifiAccessPoint, 1);
        cur_access_point->ssid = g_strdup(scalar(key));
        g_debug("%s: adding wifi AP '%s'", cur_netdef->id, cur_access_point->ssid);

        if (!cur_netdef->access_points)
            cur_netdef->access_points = g_hash_table_new(g_str_hash, g_str_equal);
        if (!g_hash_table_insert(cur_netdef->access_points, cur_access_point->ssid, cur_access_point)) {
            /* Even in the error case, NULL out cur_access_point. Otherwise we
             * have an assert failure if we do a multi-pass parse. */
            gboolean ret;

            ret = yaml_error(key, error, "%s: Duplicate access point SSID '%s'", cur_netdef->id, cur_access_point->ssid);
            cur_access_point = NULL;
            return ret;
        }

        if (!process_mapping(doc, value, wifi_access_point_handlers, error)) {
            cur_access_point = NULL;
            return FALSE;
        }

        cur_access_point = NULL;
    }
    return TRUE;
}

/**
 * Handler for bridge "interfaces:" list. We don't store that list in cur_netdef,
 * but set cur_netdef's ID in all listed interfaces' "bond" or "bridge" field.
 * @data: ignored
 */
static gboolean
handle_bridge_interfaces(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    /* all entries must refer to already defined IDs */
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        NetplanNetDefinition *component;

        assert_type(entry, YAML_SCALAR_NODE);
        component = g_hash_table_lookup(netdefs, scalar(entry));
        if (!component) {
            add_missing_node(entry);
        } else {
            if (component->bridge && g_strcmp0(component->bridge, cur_netdef->id) != 0)
                return yaml_error(node, error, "%s: interface '%s' is already assigned to bridge %s",
                                  cur_netdef->id, scalar(entry), component->bridge);
            if (component->bond)
                return yaml_error(node, error, "%s: interface '%s' is already assigned to bond %s",
                                  cur_netdef->id, scalar(entry), component->bond);
           component->bridge = g_strdup(cur_netdef->id);
        }
    }

    return TRUE;
}

/**
 * Handler for bond "mode" types.
 * @data: offset into NetplanNetDefinition where the const char* field to write is
 *        located
 */
static gboolean
handle_bond_mode(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    if (!(strcmp(scalar(node), "balance-rr") == 0 ||
        strcmp(scalar(node), "active-backup") == 0 ||
        strcmp(scalar(node), "balance-xor") == 0 ||
        strcmp(scalar(node), "broadcast") == 0 ||
        strcmp(scalar(node), "802.3ad") == 0 ||
        strcmp(scalar(node), "balance-tlb") == 0 ||
        strcmp(scalar(node), "balance-alb") == 0))
        return yaml_error(node, error, "unknown bond mode '%s'", scalar(node));

    return handle_netdef_str(doc, node, data, error);
}

/**
 * Handler for bond "interfaces:" list.
 * @data: ignored
 */
static gboolean
handle_bond_interfaces(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    /* all entries must refer to already defined IDs */
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        NetplanNetDefinition *component;

        assert_type(entry, YAML_SCALAR_NODE);
        component = g_hash_table_lookup(netdefs, scalar(entry));
        if (!component) {
            add_missing_node(entry);
        } else {
            if (component->bridge)
                return yaml_error(node, error, "%s: interface '%s' is already assigned to bridge %s",
                                  cur_netdef->id, scalar(entry), component->bridge);
            if (component->bond && g_strcmp0(component->bond, cur_netdef->id) != 0)
                return yaml_error(node, error, "%s: interface '%s' is already assigned to bond %s",
                                  cur_netdef->id, scalar(entry), component->bond);
            component->bond = g_strdup(cur_netdef->id);
        }
    }

    return TRUE;
}


static gboolean
handle_nameservers_search(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        assert_type(entry, YAML_SCALAR_NODE);
        if (!cur_netdef->search_domains)
            cur_netdef->search_domains = g_array_new(FALSE, FALSE, sizeof(char*));
        char* s = g_strdup(scalar(entry));
        g_array_append_val(cur_netdef->search_domains, s);
    }
    return TRUE;
}

static gboolean
handle_nameservers_addresses(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        assert_type(entry, YAML_SCALAR_NODE);

        /* is it an IPv4 address? */
        if (is_ip4_address(scalar(entry))) {
            if (!cur_netdef->ip4_nameservers)
                cur_netdef->ip4_nameservers = g_array_new(FALSE, FALSE, sizeof(char*));
            char* s = g_strdup(scalar(entry));
            g_array_append_val(cur_netdef->ip4_nameservers, s);
            continue;
        }

        /* is it an IPv6 address? */
        if (is_ip6_address(scalar(entry))) {
            if (!cur_netdef->ip6_nameservers)
                cur_netdef->ip6_nameservers = g_array_new(FALSE, FALSE, sizeof(char*));
            char* s = g_strdup(scalar(entry));
            g_array_append_val(cur_netdef->ip6_nameservers, s);
            continue;
        }

        return yaml_error(node, error, "malformed address '%s', must be X.X.X.X or X:X:X:X:X:X:X:X", scalar(entry));
    }

    return TRUE;
}

static gboolean
handle_link_local(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    gboolean ipv4 = FALSE;
    gboolean ipv6 = FALSE;

    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);

        assert_type(entry, YAML_SCALAR_NODE);

        if (g_ascii_strcasecmp(scalar(entry), "ipv4") == 0)
            ipv4 = TRUE;
        else if (g_ascii_strcasecmp(scalar(entry), "ipv6") == 0)
            ipv6 = TRUE;
        else
            return yaml_error(node, error, "invalid value for link-local: '%s'", scalar(entry));
    }

    cur_netdef->linklocal.ipv4 = ipv4;
    cur_netdef->linklocal.ipv6 = ipv6;

    return TRUE;
}

struct NetplanOptionalAddressType NETPLAN_OPTIONAL_ADDRESS_TYPES[] = {
    {"ipv4-ll", NETPLAN_OPTIONAL_IPV4_LL},
    {"ipv6-ra", NETPLAN_OPTIONAL_IPV6_RA},
    {"dhcp4",   NETPLAN_OPTIONAL_DHCP4},
    {"dhcp6",   NETPLAN_OPTIONAL_DHCP6},
    {"static",  NETPLAN_OPTIONAL_STATIC},
    {NULL},
};

static gboolean
handle_optional_addresses(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        assert_type(entry, YAML_SCALAR_NODE);
        int found = FALSE;

        for (unsigned i = 0; NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name != NULL; ++i) {
            if (g_ascii_strcasecmp(scalar(entry), NETPLAN_OPTIONAL_ADDRESS_TYPES[i].name) == 0) {
                cur_netdef->optional_addresses |= NETPLAN_OPTIONAL_ADDRESS_TYPES[i].flag;
                found = TRUE;
                break;
            }
        }
        if (!found) {
            return yaml_error(node, error, "invalid value for optional-addresses: '%s'", scalar(entry));
        }
    }
    return TRUE;
}

static int
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

static gboolean
check_and_set_family(int family, guint* dest)
{
    if (*dest != -1 && *dest != family)
        return FALSE;

    *dest = family;

    return TRUE;
}

/* TODO: (cyphermox) Refactor the functions below. There's a lot of room for reuse. */

static gboolean
handle_routes_bool(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    gboolean v;

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
        return yaml_error(node, error, "invalid boolean value '%s'", scalar(node));

    *((gboolean*) ((void*) cur_route + offset)) = v;
    return TRUE;
}

static gboolean
handle_routes_scope(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    if (cur_route->scope)
        g_free(cur_route->scope);
    cur_route->scope = g_strdup(scalar(node));

    if (g_ascii_strcasecmp(cur_route->scope, "global") == 0 ||
        g_ascii_strcasecmp(cur_route->scope, "link") == 0 ||
        g_ascii_strcasecmp(cur_route->scope, "host") == 0)
        return TRUE;

    return yaml_error(node, error, "invalid route scope '%s'", cur_route->scope);
}

static gboolean
handle_routes_type(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    if (cur_route->type)
        g_free(cur_route->type);
    cur_route->type = g_strdup(scalar(node));

    if (g_ascii_strcasecmp(cur_route->type, "unicast") == 0 ||
        g_ascii_strcasecmp(cur_route->type, "unreachable") == 0 ||
        g_ascii_strcasecmp(cur_route->type, "blackhole") == 0 ||
        g_ascii_strcasecmp(cur_route->type, "prohibit") == 0)
        return TRUE;

    return yaml_error(node, error, "invalid route type '%s'", cur_route->type);
}

static gboolean
handle_routes_ip(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    int family = get_ip_family(scalar(node));
    char** dest = (char**) ((void*) cur_route + offset);
    g_free(*dest);

    if (family < 0)
        return yaml_error(node, error, "invalid IP family '%d'", family);

    if (!check_and_set_family(family, &cur_route->family))
        return yaml_error(node, error, "IP family mismatch in route to %s", scalar(node));

    *dest = g_strdup(scalar(node));

    return TRUE;
}

static gboolean
handle_ip_rule_ip(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    int family = get_ip_family(scalar(node));
    char** dest = (char**) ((void*) cur_ip_rule + offset);
    g_free(*dest);

    if (family < 0)
        return yaml_error(node, error, "invalid IP family '%d'", family);

    if (!check_and_set_family(family, &cur_ip_rule->family))
        return yaml_error(node, error, "IP family mismatch in route to %s", scalar(node));

    *dest = g_strdup(scalar(node));

    return TRUE;
}

static gboolean
handle_ip_rule_prio(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT)
        return yaml_error(node, error, "invalid priority value '%s'", scalar(node));

    cur_ip_rule->priority = (guint) v;
    return TRUE;
}

static gboolean
handle_ip_rule_tos(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > 255)
        return yaml_error(node, error, "invalid ToS (must be between 0 and 255): %s", scalar(node));

    cur_ip_rule->tos = (guint) v;
    return TRUE;
}

static gboolean
handle_routes_table(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT)
        return yaml_error(node, error, "invalid routing table '%s'", scalar(node));

    cur_route->table = (guint) v;
    return TRUE;
}

static gboolean
handle_ip_rule_table(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT)
        return yaml_error(node, error, "invalid routing table '%s'", scalar(node));

    cur_ip_rule->table = (guint) v;
    return TRUE;
}

static gboolean
handle_ip_rule_fwmark(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT)
        return yaml_error(node, error, "invalid fwmark value '%s'", scalar(node));

    cur_ip_rule->fwmark = (guint) v;
    return TRUE;
}

static gboolean
handle_routes_metric(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT)
        return yaml_error(node, error, "invalid unsigned int value '%s'", scalar(node));

    cur_route->metric = (guint) v;
    return TRUE;
}

/****************************************************
 * Grammar and handlers for network config "bridge_params" entry
 ****************************************************/

static gboolean
handle_bridge_path_cost(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        guint v;
        gchar* endptr;
        NetplanNetDefinition *component;
        guint* ref_ptr;

        key = yaml_document_get_node(doc, entry->key);
        assert_type(key, YAML_SCALAR_NODE);
        value = yaml_document_get_node(doc, entry->value);
        assert_type(value, YAML_SCALAR_NODE);

        component = g_hash_table_lookup(netdefs, scalar(key));
        if (!component) {
            add_missing_node(key);
        } else {
            ref_ptr = ((guint*) ((void*) component + GPOINTER_TO_UINT(data)));
            if (*ref_ptr)
                return yaml_error(node, error, "%s: interface '%s' already has a path cost of %u",
                                  cur_netdef->id, scalar(key), *ref_ptr);

            v = g_ascii_strtoull(scalar(value), &endptr, 10);
            if (*endptr != '\0' || v > G_MAXUINT)
                return yaml_error(node, error, "invalid unsigned int value '%s'", scalar(value));

            g_debug("%s: adding path '%s' of cost: %d", cur_netdef->id, scalar(key), v);

            *ref_ptr = v;
        }
    }
    return TRUE;
}

static gboolean
handle_bridge_port_priority(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        guint v;
        gchar* endptr;
        NetplanNetDefinition *component;
        guint* ref_ptr;

        key = yaml_document_get_node(doc, entry->key);
        assert_type(key, YAML_SCALAR_NODE);
        value = yaml_document_get_node(doc, entry->value);
        assert_type(value, YAML_SCALAR_NODE);

        component = g_hash_table_lookup(netdefs, scalar(key));
        if (!component) {
            add_missing_node(key);
        } else {
            ref_ptr = ((guint*) ((void*) component + GPOINTER_TO_UINT(data)));
            if (*ref_ptr)
                return yaml_error(node, error, "%s: interface '%s' already has a port priority of %u",
                                  cur_netdef->id, scalar(key), *ref_ptr);

            v = g_ascii_strtoull(scalar(value), &endptr, 10);
            if (*endptr != '\0' || v > 63)
                return yaml_error(node, error, "invalid port priority value (must be between 0 and 63): %s",
                                  scalar(value));

            g_debug("%s: adding port '%s' of priority: %d", cur_netdef->id, scalar(key), v);

            *ref_ptr = v;
        }
    }
    return TRUE;
}

static const mapping_entry_handler bridge_params_handlers[] = {
    {"ageing-time", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bridge_params.ageing_time)},
    {"forward-delay", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bridge_params.forward_delay)},
    {"hello-time", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bridge_params.hello_time)},
    {"max-age", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bridge_params.max_age)},
    {"path-cost", YAML_MAPPING_NODE, handle_bridge_path_cost, NULL, netdef_offset(bridge_params.path_cost)},
    {"port-priority", YAML_MAPPING_NODE, handle_bridge_port_priority, NULL, netdef_offset(bridge_params.port_priority)},
    {"priority", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(bridge_params.priority)},
    {"stp", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(bridge_params.stp)},
    {NULL}
};

static gboolean
handle_bridge(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    cur_netdef->custom_bridging = TRUE;
    cur_netdef->bridge_params.stp = TRUE;
    return process_mapping(doc, node, bridge_params_handlers, error);
}

/****************************************************
 * Grammar and handlers for network config "routes" entry
 ****************************************************/

static const mapping_entry_handler routes_handlers[] = {
    {"from", YAML_SCALAR_NODE, handle_routes_ip, NULL, route_offset(from)},
    {"on-link", YAML_SCALAR_NODE, handle_routes_bool, NULL, route_offset(onlink)},
    {"scope", YAML_SCALAR_NODE, handle_routes_scope},
    {"table", YAML_SCALAR_NODE, handle_routes_table},
    {"to", YAML_SCALAR_NODE, handle_routes_ip, NULL, route_offset(to)},
    {"type", YAML_SCALAR_NODE, handle_routes_type},
    {"via", YAML_SCALAR_NODE, handle_routes_ip, NULL, route_offset(via)},
    {"metric", YAML_SCALAR_NODE, handle_routes_metric},
    {NULL}
};

static gboolean
handle_routes(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);

        cur_route = g_new0(NetplanIPRoute, 1);
        cur_route->type = g_strdup("unicast");
        cur_route->scope = g_strdup("global");
        cur_route->family = G_MAXUINT; /* 0 is a valid family ID */
        cur_route->metric = NETPLAN_METRIC_UNSPEC; /* 0 is a valid metric */

        if (process_mapping(doc, entry, routes_handlers, error)) {
            if (!cur_netdef->routes) {
                cur_netdef->routes = g_array_new(FALSE, FALSE, sizeof(NetplanIPRoute*));
            }

            g_array_append_val(cur_netdef->routes, cur_route);
        }

        if (       (   g_ascii_strcasecmp(cur_route->scope, "link") == 0
                    || g_ascii_strcasecmp(cur_route->scope, "host") == 0)
                && !cur_route->to)
            return yaml_error(node, error, "link and host routes must specify a 'to' IP");
        else if (  g_ascii_strcasecmp(cur_route->type, "unicast") == 0
                && g_ascii_strcasecmp(cur_route->scope, "global") == 0
                && (!cur_route->to || !cur_route->via))
            return yaml_error(node, error, "unicast route must include both a 'to' and 'via' IP");
        else if (g_ascii_strcasecmp(cur_route->type, "unicast") != 0 && !cur_route->to)
            return yaml_error(node, error, "non-unicast routes must specify a 'to' IP");

        cur_route = NULL;

        if (error && *error)
            return FALSE;
    }
    return TRUE;
}

static const mapping_entry_handler ip_rules_handlers[] = {
    {"from", YAML_SCALAR_NODE, handle_ip_rule_ip, NULL, ip_rule_offset(from)},
    {"mark", YAML_SCALAR_NODE, handle_ip_rule_fwmark},
    {"priority", YAML_SCALAR_NODE, handle_ip_rule_prio},
    {"table", YAML_SCALAR_NODE, handle_ip_rule_table},
    {"to", YAML_SCALAR_NODE, handle_ip_rule_ip, NULL, ip_rule_offset(to)},
    {"type-of-service", YAML_SCALAR_NODE, handle_ip_rule_tos},
    {NULL}
};

static gboolean
handle_ip_rules(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);

        cur_ip_rule = g_new0(NetplanIPRule, 1);
        cur_ip_rule->family = G_MAXUINT; /* 0 is a valid family ID */
        cur_ip_rule->priority = NETPLAN_IP_RULE_PRIO_UNSPEC;
        cur_ip_rule->table = NETPLAN_ROUTE_TABLE_UNSPEC;
        cur_ip_rule->tos = NETPLAN_IP_RULE_TOS_UNSPEC;
        cur_ip_rule->fwmark = NETPLAN_IP_RULE_FW_MARK_UNSPEC;

        if (process_mapping(doc, entry, ip_rules_handlers, error)) {
            if (!cur_netdef->ip_rules) {
                cur_netdef->ip_rules = g_array_new(FALSE, FALSE, sizeof(NetplanIPRule*));
            }

            g_array_append_val(cur_netdef->ip_rules, cur_ip_rule);
        }

        if (!cur_ip_rule->from && !cur_ip_rule->to)
            return yaml_error(node, error, "IP routing policy must include either a 'from' or 'to' IP");

        cur_ip_rule = NULL;

        if (error && *error)
            return FALSE;
    }
    return TRUE;
}

/****************************************************
 * Grammar and handlers for bond parameters
 ****************************************************/

static gboolean
handle_arp_ip_targets(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        g_autofree char* addr = NULL;
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        assert_type(entry, YAML_SCALAR_NODE);

        addr = g_strdup(scalar(entry));

        /* is it an IPv4 address? */
        if (is_ip4_address(addr)) {
            if (!cur_netdef->bond_params.arp_ip_targets)
                cur_netdef->bond_params.arp_ip_targets = g_array_new(FALSE, FALSE, sizeof(char*));
            char* s = g_strdup(scalar(entry));
            g_array_append_val(cur_netdef->bond_params.arp_ip_targets, s);
            continue;
        }

        return yaml_error(node, error, "malformed address '%s', must be X.X.X.X or X:X:X:X:X:X:X:X", scalar(entry));
    }

    return TRUE;
}

static gboolean
handle_bond_primary_slave(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    NetplanNetDefinition *component;
    char** ref_ptr;

    component = g_hash_table_lookup(netdefs, scalar(node));
    if (!component) {
        add_missing_node(node);
    } else {
        if (cur_netdef->bond_params.primary_slave)
            return yaml_error(node, error, "%s: bond already has a primary slave: %s",
                              cur_netdef->id, cur_netdef->bond_params.primary_slave);

        ref_ptr = ((char**) ((void*) component + GPOINTER_TO_UINT(data)));
        *ref_ptr = g_strdup(scalar(node));
        cur_netdef->bond_params.primary_slave = g_strdup(scalar(node));
    }

    return TRUE;
}

static const mapping_entry_handler bond_params_handlers[] = {
    {"mode", YAML_SCALAR_NODE, handle_bond_mode, NULL, netdef_offset(bond_params.mode)},
    {"lacp-rate", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.lacp_rate)},
    {"mii-monitor-interval", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.monitor_interval)},
    {"min-links", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(bond_params.min_links)},
    {"transmit-hash-policy", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.transmit_hash_policy)},
    {"ad-select", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.selection_logic)},
    {"all-slaves-active", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(bond_params.all_slaves_active)},
    {"arp-interval", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.arp_interval)},
    /* TODO: arp_ip_targets */
    {"arp-ip-targets", YAML_SEQUENCE_NODE, handle_arp_ip_targets},
    {"arp-validate", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.arp_validate)},
    {"arp-all-targets", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.arp_all_targets)},
    {"up-delay", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.up_delay)},
    {"down-delay", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.down_delay)},
    {"fail-over-mac-policy", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.fail_over_mac_policy)},
    {"gratuitous-arp", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(bond_params.gratuitous_arp)},
    /* Handle the old misspelling */
    {"gratuitious-arp", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(bond_params.gratuitous_arp)},
    /* TODO: unsolicited_na */
    {"packets-per-slave", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(bond_params.packets_per_slave)},
    {"primary-reselect-policy", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.primary_reselect_policy)},
    {"resend-igmp", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(bond_params.resend_igmp)},
    {"learn-packet-interval", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.learn_interval)},
    {"primary", YAML_SCALAR_NODE, handle_bond_primary_slave, NULL, netdef_offset(bond_params.primary_slave)},
    {NULL}
};

static gboolean
handle_bonding(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    return process_mapping(doc, node, bond_params_handlers, error);
}

static gboolean
handle_dhcp_identifier(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    if (cur_netdef->dhcp_identifier)
        g_free(cur_netdef->dhcp_identifier);
    cur_netdef->dhcp_identifier = g_strdup(scalar(node));

    if (g_ascii_strcasecmp(cur_netdef->dhcp_identifier, "duid") == 0 ||
        g_ascii_strcasecmp(cur_netdef->dhcp_identifier, "mac") == 0)
        return TRUE;

    return yaml_error(node, error, "invalid DHCP client identifier type '%s'", cur_netdef->dhcp_identifier);
}

/****************************************************
 * Grammar and handlers for tunnels
 ****************************************************/

const char*
tunnel_mode_to_string(NetplanTunnelMode mode)
{
    return netplan_tunnel_mode_table[mode];
}

static gboolean
handle_tunnel_addr(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    g_autofree char* addr = NULL;
    char* prefix_len;

    /* split off /prefix_len */
    addr = g_strdup(scalar(node));
    prefix_len = strrchr(addr, '/');
    if (prefix_len)
        return yaml_error(node, error, "address '%s' should not include /prefixlength", scalar(node));

    /* is it an IPv4 address? */
    if (is_ip4_address(addr))
        return handle_netdef_ip4(doc, node, data, error);

    /* is it an IPv6 address? */
    if (is_ip6_address(addr))
        return handle_netdef_ip6(doc, node, data, error);

    return yaml_error(node, error, "malformed address '%s', must be X.X.X.X or X:X:X:X:X:X:X:X", scalar(node));
}

static gboolean
handle_tunnel_mode(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    const char *key = scalar(node);
    NetplanTunnelMode i;

    // Skip over unknown (0) tunnel mode.
    for (i = 1; i < NETPLAN_TUNNEL_MODE_MAX_; ++i) {
        if (g_strcmp0(netplan_tunnel_mode_table[i], key) == 0) {
            cur_netdef->tunnel.mode = i;
            return TRUE;
        }
    }

    return yaml_error(node, error, "%s: tunnel mode '%s' is not supported", cur_netdef->id, key);
}

static gboolean
handle_tunnel_key(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    /* Tunnel key should be a number or dotted quad. */
    guint offset = GPOINTER_TO_UINT(data);
    char** dest = (char**) ((void*) cur_netdef + offset);
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT) {
        /* Not a simple uint, try for a dotted quad */
        if (!is_ip4_address(scalar(node)))
            return yaml_error(node, error, "invalid tunnel key '%s'", scalar(node));
    }

    g_free(*dest);
    *dest = g_strdup(scalar(node));

    return TRUE;
}

static const mapping_entry_handler tunnel_keys_handlers[] = {
    {"input", YAML_SCALAR_NODE, handle_tunnel_key, NULL, netdef_offset(tunnel.input_key)},
    {"output", YAML_SCALAR_NODE, handle_tunnel_key, NULL, netdef_offset(tunnel.output_key)},
    {NULL}
};

static gboolean
handle_tunnel_key_mapping(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    gboolean ret = FALSE;

    /* We overload the key 'key' for tunnels; such that it can either be a
     * single scalar with the same key to use for both input and output keys,
     * or a mapping where one can specify each.
     */
    if (node->type == YAML_SCALAR_NODE) {
        ret = handle_tunnel_key(doc, node, netdef_offset(tunnel.input_key), error);
        if (ret)
            ret = handle_tunnel_key(doc, node, netdef_offset(tunnel.output_key), error);
    }
    else if (node->type == YAML_MAPPING_NODE) {
        ret = process_mapping(doc, node, tunnel_keys_handlers, error);
    }
    else {
        return yaml_error(node, error, "invalid type for 'keys': must be a scalar or mapping");
    }

    return ret;
}

/****************************************************
 * Grammar and handlers for network devices
 ****************************************************/

static const mapping_entry_handler nm_backend_settings_handlers[] = {
    {"name", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(backend_settings.nm.name)},
    {"uuid", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(backend_settings.nm.uuid)},
    {"stable-id", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(backend_settings.nm.stable_id)},
    {"device", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(backend_settings.nm.device)},
    {NULL}
};

static const mapping_entry_handler nameservers_handlers[] = {
    {"search", YAML_SEQUENCE_NODE, handle_nameservers_search},
    {"addresses", YAML_SEQUENCE_NODE, handle_nameservers_addresses},
    {NULL}
};

/* Handlers for DHCP overrides. */
#define COMMON_DHCP_OVERRIDES_HANDLERS(overrides)                                                           \
    {"hostname", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(overrides.hostname)},             \
    {"route-metric", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(overrides.metric)},         \
    {"send-hostname", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(overrides.send_hostname)},  \
    {"use-dns", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(overrides.use_dns)},              \
    {"use-domains", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(overrides.use_domains)},      \
    {"use-hostname", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(overrides.use_hostname)},    \
    {"use-mtu", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(overrides.use_mtu)},              \
    {"use-ntp", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(overrides.use_ntp)},              \
    {"use-routes", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(overrides.use_routes)}

static const mapping_entry_handler dhcp4_overrides_handlers[] = {
    COMMON_DHCP_OVERRIDES_HANDLERS(dhcp4_overrides),
    {NULL},
};

static const mapping_entry_handler dhcp6_overrides_handlers[] = {
    COMMON_DHCP_OVERRIDES_HANDLERS(dhcp6_overrides),
    {NULL},
};

/* Handlers shared by all link types */
#define COMMON_LINK_HANDLERS                                                                  \
    {"accept-ra", YAML_SCALAR_NODE, handle_accept_ra},                                        \
    {"addresses", YAML_SEQUENCE_NODE, handle_addresses},                                      \
    {"critical", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(critical)},        \
    {"dhcp4", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp4)},              \
    {"dhcp6", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp6)},              \
    {"dhcp-identifier", YAML_SCALAR_NODE, handle_dhcp_identifier},                            \
    {"dhcp4-overrides", YAML_MAPPING_NODE, NULL, dhcp4_overrides_handlers},                   \
    {"dhcp6-overrides", YAML_MAPPING_NODE, NULL, dhcp6_overrides_handlers},                   \
    {"gateway4", YAML_SCALAR_NODE, handle_gateway4},                                          \
    {"gateway6", YAML_SCALAR_NODE, handle_gateway6},                                          \
    {"ipv6-mtu", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(ipv6_mtubytes)},  \
    {"ipv6-privacy", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(ip6_privacy)}, \
    {"link-local", YAML_SEQUENCE_NODE, handle_link_local},                                    \
    {"macaddress", YAML_SCALAR_NODE, handle_netdef_mac, NULL, netdef_offset(set_mac)},        \
    {"mtu", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(mtubytes)},            \
    {"nameservers", YAML_MAPPING_NODE, NULL, nameservers_handlers},                           \
    {"optional", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(optional)},        \
    {"optional-addresses", YAML_SEQUENCE_NODE, handle_optional_addresses},                    \
    {"renderer", YAML_SCALAR_NODE, handle_netdef_renderer},                                   \
    {"routes", YAML_SEQUENCE_NODE, handle_routes},                                            \
    {"routing-policy", YAML_SEQUENCE_NODE, handle_ip_rules}

#define COMMON_BACKEND_HANDLERS							\
    {"networkmanager", YAML_MAPPING_NODE, NULL, nm_backend_settings_handlers}

/* Handlers for physical links */
#define PHYSICAL_LINK_HANDLERS                                                           \
    {"match", YAML_MAPPING_NODE, handle_match},                                          \
    {"set-name", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(set_name)},    \
    {"wakeonlan", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(wake_on_lan)}, \
    {"emit-lldp", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(emit_lldp)}

static const mapping_entry_handler ethernet_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    PHYSICAL_LINK_HANDLERS,
    {"auth", YAML_MAPPING_NODE, handle_auth},
    {NULL}
};

static const mapping_entry_handler wifi_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    PHYSICAL_LINK_HANDLERS,
    {"access-points", YAML_MAPPING_NODE, handle_wifi_access_points},
    {"auth", YAML_MAPPING_NODE, handle_auth},
    {NULL}
};

static const mapping_entry_handler bridge_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"interfaces", YAML_SEQUENCE_NODE, handle_bridge_interfaces, NULL, NULL},
    {"parameters", YAML_MAPPING_NODE, handle_bridge},
    {NULL}
};

static const mapping_entry_handler bond_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"interfaces", YAML_SEQUENCE_NODE, handle_bond_interfaces, NULL, NULL},
    {"parameters", YAML_MAPPING_NODE, handle_bonding},
    {NULL}
};

static const mapping_entry_handler vlan_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"id", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(vlan_id)},
    {"link", YAML_SCALAR_NODE, handle_netdef_id_ref, NULL, netdef_offset(vlan_link)},
    {NULL}
};

static const mapping_entry_handler modem_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    {"apn", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.apn)},
    {"auto-config", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(modem_params.auto_config)},
    {"device-id", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.device_id)},
    {"network-id", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.network_id)},
    {"number", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.number)},
    {"password", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.password)},
    {"pin", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.pin)},
    {"sim-id", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.sim_id)},
    {"sim-operator-id", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.sim_operator_id)},
    {"username", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(modem_params.username)},
};

static const mapping_entry_handler tunnel_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    COMMON_BACKEND_HANDLERS,
    {"mode", YAML_SCALAR_NODE, handle_tunnel_mode},
    {"local", YAML_SCALAR_NODE, handle_tunnel_addr, NULL, netdef_offset(tunnel.local_ip)},
    {"remote", YAML_SCALAR_NODE, handle_tunnel_addr, NULL, netdef_offset(tunnel.remote_ip)},

    /* Handle key/keys for clarity in config: this can be either a scalar or
     * mapping of multiple keys (input and output)
     */
    {"key", YAML_NO_NODE, handle_tunnel_key_mapping},
    {"keys", YAML_NO_NODE, handle_tunnel_key_mapping},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network node
 ****************************************************/

static gboolean
handle_network_version(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    long mangled_version;

    mangled_version = strtol(scalar(node), NULL, 10);

    if (mangled_version < NETPLAN_VERSION_MIN || mangled_version >= NETPLAN_VERSION_MAX)
        return yaml_error(node, error, "Only version 2 is supported");
    return TRUE;
}

static gboolean
handle_network_renderer(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    return parse_renderer(node, &backend_global, error);
}

static void
initialize_dhcp_overrides(NetplanDHCPOverrides* overrides)
{
    overrides->use_dns = TRUE;
    overrides->use_domains = NULL;
    overrides->use_ntp = TRUE;
    overrides->send_hostname = TRUE;
    overrides->use_hostname = TRUE;
    overrides->use_mtu = TRUE;
    overrides->use_routes = TRUE;
    overrides->hostname = NULL;
    overrides->metric = NETPLAN_METRIC_UNSPEC;
}

/**
 * Callback for a net device type entry like "ethernets:" in "networks:"
 * @data: netdef_type (as pointer)
 */
static gboolean
handle_network_type(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    for (yaml_node_pair_t* entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t* key, *value;
        const mapping_entry_handler* handlers;

        key = yaml_document_get_node(doc, entry->key);
        if (!assert_valid_id(key, error))
            return FALSE;
        /* globbing is not allowed for IDs */
        if (strpbrk(scalar(key), "*[]?"))
            return yaml_error(key, error, "Definition ID '%s' must not use globbing", scalar(key));

        value = yaml_document_get_node(doc, entry->value);

        /* special-case "renderer:" key to set the per-type backend */
        if (strcmp(scalar(key), "renderer") == 0) {
            if (!parse_renderer(value, &backend_cur_type, error))
                return FALSE;
            continue;
        }

        assert_type(value, YAML_MAPPING_NODE);

        /* At this point we've seen a new starting definition, if it has been
         * already mentioned in another netdef, removing it from our "missing"
         * list. */
        if(g_hash_table_remove(missing_id, scalar(key)))
            missing_ids_found++;

        cur_netdef = g_hash_table_lookup(netdefs, scalar(key));
        if (cur_netdef) {
            /* already exists, overriding/amending previous definition */
            if (cur_netdef->type != GPOINTER_TO_UINT(data))
                return yaml_error(key, error, "Updated definition '%s' changes device type", scalar(key));
        } else {
            /* create new network definition */
            cur_netdef = g_new0(NetplanNetDefinition, 1);
            cur_netdef->type = GPOINTER_TO_UINT(data);
            cur_netdef->backend = backend_cur_type ?: NETPLAN_BACKEND_NONE;
            cur_netdef->id = g_strdup(scalar(key));

            /* Set some default values */
            cur_netdef->vlan_id = G_MAXUINT; /* 0 is a valid ID */
            cur_netdef->tunnel.mode = NETPLAN_TUNNEL_MODE_UNKNOWN;
            cur_netdef->dhcp_identifier = g_strdup("duid"); /* keep networkd's default */
            /* systemd-networkd defaults to IPv6 LL enabled; keep that default */
            cur_netdef->linklocal.ipv6 = TRUE;
            g_hash_table_insert(netdefs, cur_netdef->id, cur_netdef);
            netdefs_ordered = g_list_append(netdefs_ordered, cur_netdef);

            /* DHCP override defaults */
            initialize_dhcp_overrides(&cur_netdef->dhcp4_overrides);
            initialize_dhcp_overrides(&cur_netdef->dhcp6_overrides);

            g_hash_table_insert(netdefs, cur_netdef->id, cur_netdef);
        }

        // XXX: breaks multi-pass parsing.
        //if (!g_hash_table_add(ids_in_file, cur_netdef->id))
        //    return yaml_error(key, error, "Duplicate net definition ID '%s'", cur_netdef->id);

        /* and fill it with definitions */
        switch (cur_netdef->type) {
            case NETPLAN_DEF_TYPE_BOND: handlers = bond_def_handlers; break;
            case NETPLAN_DEF_TYPE_BRIDGE: handlers = bridge_def_handlers; break;
            case NETPLAN_DEF_TYPE_ETHERNET: handlers = ethernet_def_handlers; break;
            case NETPLAN_DEF_TYPE_MODEM: handlers = modem_def_handlers; break;
            case NETPLAN_DEF_TYPE_TUNNEL: handlers = tunnel_def_handlers; break;
            case NETPLAN_DEF_TYPE_VLAN: handlers = vlan_def_handlers; break;
            case NETPLAN_DEF_TYPE_WIFI: handlers = wifi_def_handlers; break;
            default: g_assert_not_reached(); // LCOV_EXCL_LINE
        }
        if (!process_mapping(doc, value, handlers, error))
            return FALSE;

        /* validate definition-level conditions */
        if (!validate_netdef_grammar(cur_netdef, value, error))
            return FALSE;

        /* convenience shortcut: physical device without match: means match
         * name on ID */
        if (cur_netdef->type < NETPLAN_DEF_TYPE_VIRTUAL && !cur_netdef->has_match)
            cur_netdef->match.original_name = cur_netdef->id;
    }
    backend_cur_type = NETPLAN_BACKEND_NONE;
    return TRUE;
}

static const mapping_entry_handler network_handlers[] = {
    {"bonds", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_BOND)},
    {"bridges", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_BRIDGE)},
    {"ethernets", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_ETHERNET)},
    {"renderer", YAML_SCALAR_NODE, handle_network_renderer},
    {"tunnels", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_TUNNEL)},
    {"version", YAML_SCALAR_NODE, handle_network_version},
    {"vlans", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_VLAN)},
    {"wifis", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_WIFI)},
    {"modems", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(NETPLAN_DEF_TYPE_MODEM)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for root node
 ****************************************************/

static const mapping_entry_handler root_handlers[] = {
    {"network", YAML_MAPPING_NODE, NULL, network_handlers},
    {NULL}
};

/**
 * Handle multiple-pass parsing of the yaml document.
 */
static gboolean
process_document(yaml_document_t* doc, GError** error)
{
    gboolean ret;
    int previously_found;
    int still_missing;

    g_assert(missing_id == NULL);
    missing_id = g_hash_table_new_full(g_str_hash, g_str_equal, NULL, g_free);

    do {
        g_debug("starting new processing pass");

        previously_found = missing_ids_found;
        missing_ids_found = 0;

        g_clear_error(error);

        ret = process_mapping(doc, yaml_document_get_root_node(doc), root_handlers, error);

        still_missing = g_hash_table_size(missing_id);

        if (still_missing > 0 && missing_ids_found == previously_found)
            break;
    } while (still_missing > 0 || missing_ids_found > 0);

    if (g_hash_table_size(missing_id) > 0) {
        GHashTableIter iter;
        gpointer key, value;
        NetplanMissingNode *missing;

        g_clear_error(error);

        /* Get the first missing identifier we can get from our list, to
         * approximate early failure and give the user a meaningful error. */
        g_hash_table_iter_init (&iter, missing_id);
        g_hash_table_iter_next (&iter, &key, &value);
        missing = (NetplanMissingNode*) value;

        return yaml_error(missing->node, error, "%s: interface '%s' is not defined",
                          missing->netdef_id,
                          key);
    }

    g_hash_table_destroy(missing_id);
    missing_id = NULL;
    return ret;
}

/**
 * Parse given YAML file and create/update global "netdefs" list.
 */
gboolean
netplan_parse_yaml(const char* filename, GError** error)
{
    yaml_document_t doc;
    gboolean ret;

    if (!load_yaml(filename, &doc, error))
        return FALSE;

    if (!netdefs)
        netdefs = g_hash_table_new(g_str_hash, g_str_equal);

    /* empty file? */
    if (yaml_document_get_root_node(&doc) == NULL)
        return TRUE;

    g_assert(ids_in_file == NULL);
    ids_in_file = g_hash_table_new(g_str_hash, NULL);

    ret = process_document(&doc, error);

    cur_netdef = NULL;
    yaml_document_delete(&doc);
    g_hash_table_destroy(ids_in_file);
    ids_in_file = NULL;
    return ret;
}

static void
finish_iterator(gpointer key, gpointer value, gpointer user_data)
{
    GError **error = (GError **)user_data;
    NetplanNetDefinition* nd = value;

    /* Take more steps to make sure we always have a backend set for netdefs */
    if (nd->backend == NETPLAN_BACKEND_NONE) {
        nd->backend = get_default_backend_for_type(nd->type);
        g_debug("%s: setting default backend to %i", nd->id, nd->backend);
    }

    /* Do a final pass of validation for backend-specific conditions */
    if (validate_backend_rules(nd, error))
        g_debug("Configuration is valid");
}

/**
 * Post-processing after parsing all config files
 */
GHashTable *
netplan_finish_parse(GError** error)
{
    if (netdefs) {
        g_debug("We have some netdefs, pass them through a final round of validation");
        g_hash_table_foreach(netdefs, finish_iterator, error);
    }

    if (error && *error)
        return NULL;

    return netdefs;
}

/**
 * Return current global backend.
 */
NetplanBackend
netplan_get_global_backend()
{
    return backend_global;
}
