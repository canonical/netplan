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

#include <yaml.h>

#include "parse.h"

/* convenience macro to put the offset of a net_definition field into "void* data" */
#define netdef_offset(field) GUINT_TO_POINTER(offsetof(net_definition, field))
#define route_offset(field) GUINT_TO_POINTER(offsetof(ip_route, field))
#define ip_rule_offset(field) GUINT_TO_POINTER(offsetof(ip_rule, field))

/* file that is currently being processed, for useful error messages */
const char* current_file;
/* net_definition that is currently being processed */
net_definition* cur_netdef;

/* wifi AP that is currently being processed */
wifi_access_point* cur_access_point;

ip_route* cur_route;
ip_rule* cur_ip_rule;

netdef_backend backend_global, backend_cur_type;

/* Global ID → net_definition* map for all parsed config files */
GHashTable* netdefs;
/* Set of IDs in currently parsed YAML file, for being able to detect
 * "duplicate ID within one file" vs. allowing a drop-in to override/amend an
 * existing definition */
GHashTable* ids_in_file;

/* List of "seen" ids not found in netdefs yet by the parser.
 * These are removed when it exists in this list and we reach the point of
 * creating a netdef for that id; so by the time we're done parsing the yaml
 * document it should be empty. */
GHashTable *missing_id;
int missing_ids_found;

/****************************************************
 * Loading and error handling
 ****************************************************/

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
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                    "Invalid YAML at %s line %zu column %zu: %s",
                    yaml, parser.problem_mark.line, parser.problem_mark.column, parser.problem);
        ret = FALSE;
    }

    fclose(fyaml);
    return ret;
}

/**
 * Put a YAML specific error message for @node into @error.
 */
static gboolean
yaml_error(const yaml_node_t* node, GError** error, const char* msg, ...)
{
    va_list argp;
    gchar* s;

    va_start(argp, msg);
    g_vasprintf(&s, msg, argp);
    g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                "Error in network definition %s line %zu column %zu: %s",
                current_file, node->start_mark.line, node->start_mark.column, s);
    g_free(s);
    va_end(argp);
    return FALSE;
}

/**
 * Raise a GError about a type mismatch and return FALSE.
 */
static gboolean
assert_type_fn(yaml_node_t* node, yaml_node_type_t expected_type, GError** error)
{
    if (node->type == expected_type)
        return TRUE;

    switch (expected_type) {
        case YAML_SCALAR_NODE:
            yaml_error(node, error, "expected scalar");
            break;
        case YAML_SEQUENCE_NODE:
            yaml_error(node, error, "expected sequence");
            break;
        case YAML_MAPPING_NODE:
            yaml_error(node, error, "expected mapping");
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
    missing_node* missing;

    /* Let's capture the current netdef we were playing with along with the
     * actual yaml_node_t that errors (that is an identifier not previously
     * seen by the compiler). We can use it later to write an sensible error
     * message and point the user in the right direction. */
    missing = g_new0(missing_node, 1);
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
            return yaml_error(node, error, "unknown key %s", scalar(key));
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
 * @data: offset into net_definition where the const char* field to write is
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
 * @data: offset into net_definition where the const char* field to write is
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
 * @data: offset into net_definition where the net_definition* field to write is
 *        located
 */
static gboolean
handle_netdef_id_ref(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    net_definition* ref = NULL;

    ref = g_hash_table_lookup(netdefs, scalar(node));
    if (!ref) {
        add_missing_node(node);
    } else {
        *((net_definition**) ((void*) cur_netdef + offset)) = ref;
    }
    return TRUE;
}


/**
 * Generic handler for setting a cur_netdef MAC address field from a scalar node
 * @data: offset into net_definition where the const char* field to write is
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
 * @data: offset into net_definition where the gboolean field to write is located
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
        return yaml_error(node, error, "invalid boolean value %s", scalar(node));

    *((gboolean*) ((void*) cur_netdef + offset)) = v;
    return TRUE;
}

/**
 * Generic handler for setting a cur_netdef guint field from a scalar node
 * @data: offset into net_definition where the guint field to write is located
 */
static gboolean
handle_netdef_guint(yaml_document_t* doc, yaml_node_t* node, const void* data, GError** error)
{
    guint offset = GPOINTER_TO_UINT(data);
    guint64 v;
    gchar* endptr;

    v = g_ascii_strtoull(scalar(node), &endptr, 10);
    if (*endptr != '\0' || v > G_MAXUINT)
        return yaml_error(node, error, "invalid unsigned int value %s", scalar(node));

    *((guint*) ((void*) cur_netdef + offset)) = (guint) v;
    return TRUE;
}

/****************************************************
 * Grammar and handlers for network config "match" entry
 ****************************************************/

const mapping_entry_handler match_handlers[] = {
    {"driver", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(match.driver)},
    {"macaddress", YAML_SCALAR_NODE, handle_netdef_mac, NULL, netdef_offset(match.mac)},
    {"name", YAML_SCALAR_NODE, handle_netdef_id, NULL, netdef_offset(match.original_name)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network device definition
 ****************************************************/

static netdef_backend
get_default_backend_for_type(netdef_type type)
{
    if (backend_global != BACKEND_NONE)
        return backend_global;

    /* networkd can handle all device types at the moment, so nothing
     * type-specific */
    return BACKEND_NETWORKD;
}

static gboolean
handle_access_point_password(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    g_assert(cur_access_point);
    cur_access_point->password = g_strdup(scalar(node));
    return TRUE;
}

static gboolean
handle_access_point_mode(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    g_assert(cur_access_point);
    if (strcmp(scalar(node), "infrastructure") == 0)
        cur_access_point->mode = WIFI_MODE_INFRASTRUCTURE;
    else if (strcmp(scalar(node), "adhoc") == 0)
        cur_access_point->mode = WIFI_MODE_ADHOC;
    else if (strcmp(scalar(node), "ap") == 0)
        cur_access_point->mode = WIFI_MODE_AP;
    else
        return yaml_error(node, error, "unknown wifi mode '%s'", scalar(node));
    return TRUE;
}

const mapping_entry_handler wifi_access_point_handlers[] = {
    {"mode", YAML_SCALAR_NODE, handle_access_point_mode},
    {"password", YAML_SCALAR_NODE, handle_access_point_password},
    {NULL}
};

/**
 * Parse scalar node's string into a netdef_backend.
 */
static gboolean
parse_renderer(yaml_node_t* node, netdef_backend* backend, GError** error)
{
    if (strcmp(scalar(node), "networkd") == 0)
        *backend = BACKEND_NETWORKD;
    else if (strcmp(scalar(node), "NetworkManager") == 0)
        *backend = BACKEND_NM;
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
        cur_netdef->accept_ra = ACCEPT_RA_ENABLED;
    else if (g_ascii_strcasecmp(scalar(node), "false") == 0 ||
        g_ascii_strcasecmp(scalar(node), "off") == 0 ||
        g_ascii_strcasecmp(scalar(node), "no") == 0 ||
        g_ascii_strcasecmp(scalar(node), "n") == 0)
        cur_netdef->accept_ra = ACCEPT_RA_DISABLED;
    else
        return yaml_error(node, error, "invalid boolean value %s", scalar(node));

    return TRUE;
}

static gboolean
handle_match(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    cur_netdef->has_match = TRUE;
    return process_mapping(doc, node, match_handlers, error);
}

static gboolean
handle_addresses(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        struct in_addr a4;
        struct in6_addr a6;
        int ret;
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
        ret = inet_pton(AF_INET, addr, &a4);
        g_assert(ret >= 0);
        if (ret > 0) {
            if (prefix_len_num == 0 || prefix_len_num > 32)
                return yaml_error(node, error, "invalid prefix length in address '%s'", scalar(entry));

            if (!cur_netdef->ip4_addresses)
                cur_netdef->ip4_addresses = g_array_new(FALSE, FALSE, sizeof(char*));
            char* s = g_strdup(scalar(entry));
            g_array_append_val(cur_netdef->ip4_addresses, s);
            continue;
        }

        /* is it an IPv6 address? */
        ret = inet_pton(AF_INET6, addr, &a6);
        g_assert(ret >= 0);
        if (ret > 0) {
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
    struct in_addr a4;
    int ret = inet_pton(AF_INET, scalar(node), &a4);
    g_assert(ret >= 0);
    if (ret == 0)
        return yaml_error(node, error, "invalid IPv4 address '%s'", scalar(node));
    cur_netdef->gateway4 = g_strdup(scalar(node));
    return TRUE;
}

static gboolean
handle_gateway6(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    struct in6_addr a6;
    int ret = inet_pton(AF_INET6, scalar(node), &a6);
    g_assert(ret >= 0);
    if (ret == 0)
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
        cur_access_point = g_new0(wifi_access_point, 1);
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
        net_definition *component;

        assert_type(entry, YAML_SCALAR_NODE);
        component = g_hash_table_lookup(netdefs, scalar(entry));
        if (!component) {
            add_missing_node(entry);
        } else {
            if (component->bridge && g_strcmp0(component->bridge, cur_netdef->id) != 0)
                return yaml_error(node, error, "%s: interface %s is already assigned to bridge %s",
                                  cur_netdef->id, scalar(entry), component->bridge);
            if (component->bond)
                return yaml_error(node, error, "%s: interface %s is already assigned to bond %s",
                                  cur_netdef->id, scalar(entry), component->bond);
           component->bridge = g_strdup(cur_netdef->id);
        }
    }

    return TRUE;
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
        net_definition *component;

        assert_type(entry, YAML_SCALAR_NODE);
        component = g_hash_table_lookup(netdefs, scalar(entry));
        if (!component) {
            add_missing_node(entry);
        } else {
            if (component->bridge)
                return yaml_error(node, error, "%s: interface %s is already assigned to bridge %s",
                                  cur_netdef->id, scalar(entry), component->bridge);
            if (component->bond && g_strcmp0(component->bond, cur_netdef->id) != 0)
                return yaml_error(node, error, "%s: interface %s is already assigned to bond %s",
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
        struct in_addr a4;
        struct in6_addr a6;
        int ret;
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        assert_type(entry, YAML_SCALAR_NODE);

        /* is it an IPv4 address? */
        ret = inet_pton(AF_INET, scalar(entry), &a4);
        g_assert(ret >= 0);
        if (ret > 0) {
            if (!cur_netdef->ip4_nameservers)
                cur_netdef->ip4_nameservers = g_array_new(FALSE, FALSE, sizeof(char*));
            char* s = g_strdup(scalar(entry));
            g_array_append_val(cur_netdef->ip4_nameservers, s);
            continue;
        }

        /* is it an IPv6 address? */
        ret = inet_pton(AF_INET6, scalar(entry), &a6);
        g_assert(ret >= 0);
        if (ret > 0) {
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
            return yaml_error(node, error, "invalid value for link-local: %s", scalar(entry));
    }

    cur_netdef->linklocal.ipv4 = ipv4;
    cur_netdef->linklocal.ipv6 = ipv6;

    return TRUE;
}

struct optional_address_option optional_address_options[] = {
    {"ipv4-ll", OPTIONAL_IPV4_LL},
    {"ipv6-ra", OPTIONAL_IPV6_RA},
    {"dhcp4",   OPTIONAL_DHCP4},
    {"dhcp6",   OPTIONAL_DHCP6},
    {"static",  OPTIONAL_STATIC},
    {NULL},
};

static gboolean
handle_optional_addresses(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        assert_type(entry, YAML_SCALAR_NODE);
	int found = FALSE;

	for (unsigned i = 0; optional_address_options[i].name != NULL; ++i) {
	    if (g_ascii_strcasecmp(scalar(entry), optional_address_options[i].name) == 0) {
		cur_netdef->optional_addresses |= optional_address_options[i].flag;
		found = TRUE;
		break;
	    }
	}
	if (!found) {
            return yaml_error(node, error, "invalid value for optional-addresses: %s", scalar(entry));
	}
    }
    return TRUE;
}

static int
get_ip_family(const char* address)
{
    struct in_addr a4;
    struct in6_addr a6;
    g_autofree char *ip_str;
    char *prefix_len;
    int ret = -1;

    ip_str = g_strdup(address);
    prefix_len = strrchr(ip_str, '/');
    if (prefix_len)
        *prefix_len = '\0';

    ret = inet_pton(AF_INET, ip_str, &a4);
    g_assert(ret >= 0);
    if (ret > 0)
        return AF_INET;

    ret = inet_pton(AF_INET6, ip_str, &a6);
    g_assert(ret >= 0);
    if (ret > 0)
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
        return yaml_error(node, error, "invalid boolean value %s", scalar(node));

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
        return yaml_error(node, error, "invalid IP family %d", family);

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
        return yaml_error(node, error, "invalid IP family %d", family);

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
        return yaml_error(node, error, "invalid priority value %s", scalar(node));

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
        return yaml_error(node, error, "invalid routing table %s", scalar(node));

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
        return yaml_error(node, error, "invalid routing table %s", scalar(node));

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
        return yaml_error(node, error, "invalid fwmark value %s", scalar(node));

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
        return yaml_error(node, error, "invalid unsigned int value %s", scalar(node));

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
        net_definition *component;
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
                return yaml_error(node, error, "%s: interface %s already has a path cost of %u",
                                  cur_netdef->id, scalar(key), *ref_ptr);

            v = g_ascii_strtoull(scalar(value), &endptr, 10);
            if (*endptr != '\0' || v > G_MAXUINT)
                return yaml_error(node, error, "invalid unsigned int value %s", scalar(value));

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
        net_definition *component;
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
                return yaml_error(node, error, "%s: interface %s already has a port priority of %u",
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
const mapping_entry_handler bridge_params_handlers[] = {
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

const mapping_entry_handler routes_handlers[] = {
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

        cur_route = g_new0(ip_route, 1);
        cur_route->type = g_strdup("unicast");
        cur_route->scope = g_strdup("global");
        cur_route->family = G_MAXUINT; /* 0 is a valid family ID */
        cur_route->metric = G_MAXUINT; /* 0 is a valid metric */

        if (process_mapping(doc, entry, routes_handlers, error)) {
            if (!cur_netdef->routes) {
                cur_netdef->routes = g_array_new(FALSE, FALSE, sizeof(ip_route*));
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

const mapping_entry_handler ip_rules_handlers[] = {
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

        cur_ip_rule = g_new0(ip_rule, 1);
        cur_ip_rule->family = G_MAXUINT; /* 0 is a valid family ID */
        cur_ip_rule->priority = IP_RULE_PRIO_UNSPEC;
        cur_ip_rule->table = ROUTE_TABLE_UNSPEC;
        cur_ip_rule->tos = IP_RULE_TOS_UNSPEC;
        cur_ip_rule->fwmark = IP_RULE_FW_MARK_UNSPEC;

        if (process_mapping(doc, entry, ip_rules_handlers, error)) {
            if (!cur_netdef->ip_rules) {
                cur_netdef->ip_rules = g_array_new(FALSE, FALSE, sizeof(ip_rule*));
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
        struct in_addr a4;
        int ret;
        g_autofree char* addr = NULL;
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        assert_type(entry, YAML_SCALAR_NODE);

        addr = g_strdup(scalar(entry));

        /* is it an IPv4 address? */
        ret = inet_pton(AF_INET, addr, &a4);
        g_assert(ret >= 0);
        if (ret > 0) {
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
    net_definition *component;
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

const mapping_entry_handler bond_params_handlers[] = {
    {"mode", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(bond_params.mode)},
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
 * Grammar and handlers for network devices
 ****************************************************/

const mapping_entry_handler nameservers_handlers[] = {
    {"search", YAML_SEQUENCE_NODE, handle_nameservers_search},
    {"addresses", YAML_SEQUENCE_NODE, handle_nameservers_addresses},
    {NULL}
};

/* Handlers shared by all link types */
#define COMMON_LINK_HANDLERS                                                             \
    {"accept-ra", YAML_SCALAR_NODE, handle_accept_ra},                                   \
    {"addresses", YAML_SEQUENCE_NODE, handle_addresses},                                 \
    {"critical", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(critical)},   \
    {"dhcp4", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp4)},         \
    {"dhcp6", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp6)},         \
    {"dhcp-identifier", YAML_SCALAR_NODE, handle_dhcp_identifier},                       \
    {"gateway4", YAML_SCALAR_NODE, handle_gateway4},                                     \
    {"gateway6", YAML_SCALAR_NODE, handle_gateway6},                                     \
    {"link-local", YAML_SEQUENCE_NODE, handle_link_local},                               \
    {"macaddress", YAML_SCALAR_NODE, handle_netdef_mac, NULL, netdef_offset(set_mac)},   \
    {"mtu", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(mtubytes)},       \
    {"nameservers", YAML_MAPPING_NODE, NULL, nameservers_handlers},                      \
    {"optional", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(optional)},   \
    {"optional-addresses", YAML_SEQUENCE_NODE, handle_optional_addresses},               \
    {"renderer", YAML_SCALAR_NODE, handle_netdef_renderer},                              \
    {"routes", YAML_SEQUENCE_NODE, handle_routes},                                       \
    {"routing-policy", YAML_SEQUENCE_NODE, handle_ip_rules}

/* Handlers for physical links */
#define PHYSICAL_LINK_HANDLERS                                                           \
    {"match", YAML_MAPPING_NODE, handle_match},						 \
    {"set-name", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(set_name)},	 \
    {"wakeonlan", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(wake_on_lan)}

const mapping_entry_handler ethernet_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    PHYSICAL_LINK_HANDLERS,
    {NULL},
};

const mapping_entry_handler wifi_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    PHYSICAL_LINK_HANDLERS,
    {"access-points", YAML_MAPPING_NODE, handle_wifi_access_points},
    {NULL}
};

const mapping_entry_handler bridge_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    {"interfaces", YAML_SEQUENCE_NODE, handle_bridge_interfaces, NULL, NULL},
    {"parameters", YAML_MAPPING_NODE, handle_bridge},
    {NULL}
};

const mapping_entry_handler bond_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    {"interfaces", YAML_SEQUENCE_NODE, handle_bond_interfaces, NULL, NULL},
    {"parameters", YAML_MAPPING_NODE, handle_bonding},
    {NULL}
};

const mapping_entry_handler vlan_def_handlers[] = {
    COMMON_LINK_HANDLERS,
    {"id", YAML_SCALAR_NODE, handle_netdef_guint, NULL, netdef_offset(vlan_id)},
    {"link", YAML_SCALAR_NODE, handle_netdef_id_ref, NULL, netdef_offset(vlan_link)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network node
 ****************************************************/

static gboolean
handle_network_version(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    if (strcmp(scalar(node), "2") != 0)
        return yaml_error(node, error, "Only version 2 is supported");
    return TRUE;
}

static gboolean
handle_network_renderer(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    return parse_renderer(node, &backend_global, error);
}

static gboolean
validate_netdef(net_definition* nd, yaml_node_t* node, GError** error)
{
    int missing_id_count = g_hash_table_size(missing_id);
    g_assert(nd->type != ND_NONE);

    /* Skip all validation if we're missing some definition IDs (devices).
     * The ones we have yet to see may be necessary for validation to succeed,
     * we can complete it on the next parser pass. */
    if (missing_id_count > 0)
        return TRUE;

    /* set-name: requires match: */
    if (nd->set_name && !nd->has_match)
        return yaml_error(node, error, "%s: set-name: requires match: properties", nd->id);

    if (nd->type == ND_WIFI && nd->access_points == NULL)
        return yaml_error(node, error, "%s: No access points defined", nd->id);

    if (nd->type == ND_VLAN) {
        if (!nd->vlan_link)
            return yaml_error(node, error, "%s: missing link property", nd->id);
        nd->vlan_link->has_vlans = TRUE;
        if (nd->vlan_id == G_MAXUINT)
            return yaml_error(node, error, "%s: missing id property", nd->id);
        if (nd->vlan_id > 4094)
            return yaml_error(node, error, "%s: invalid id %u (allowed values are 0 to 4094)", nd->id, nd->vlan_id);
    }

    return TRUE;
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
            cur_netdef = g_new0(net_definition, 1);
            cur_netdef->type = GPOINTER_TO_UINT(data);
            cur_netdef->backend = backend_cur_type ?: BACKEND_NONE;
            cur_netdef->id = g_strdup(scalar(key));
            cur_netdef->vlan_id = G_MAXUINT; /* 0 is a valid ID */
            cur_netdef->dhcp_identifier = g_strdup("duid"); /* keep networkd's default */
            /* systemd-networkd defaults to IPv6 LL enabled; keep that default */
            cur_netdef->linklocal.ipv6 = TRUE;
            g_hash_table_insert(netdefs, cur_netdef->id, cur_netdef);
        }

        // XXX: breaks multi-pass parsing.
        //if (!g_hash_table_add(ids_in_file, cur_netdef->id))
        //    return yaml_error(key, error, "Duplicate net definition ID '%s'", cur_netdef->id);

        /* and fill it with definitions */
        switch (cur_netdef->type) {
            case ND_ETHERNET: handlers = ethernet_def_handlers; break;
            case ND_WIFI: handlers = wifi_def_handlers; break;
            case ND_BRIDGE: handlers = bridge_def_handlers; break;
            case ND_BOND: handlers = bond_def_handlers; break;
            case ND_VLAN: handlers = vlan_def_handlers; break;
            default: g_assert_not_reached(); // LCOV_EXCL_LINE
        }
        if (!process_mapping(doc, value, handlers, error))
            return FALSE;

        /* validate definition-level conditions */
        if (!validate_netdef(cur_netdef, value, error))
            return FALSE;

        /* convenience shortcut: physical device without match: means match
         * name on ID */
        if (cur_netdef->type < ND_VIRTUAL && !cur_netdef->has_match)
            cur_netdef->match.original_name = cur_netdef->id;
    }
    backend_cur_type = BACKEND_NONE;
    return TRUE;
}

const mapping_entry_handler network_handlers[] = {
    {"version", YAML_SCALAR_NODE, handle_network_version},
    {"renderer", YAML_SCALAR_NODE, handle_network_renderer},
    {"ethernets", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(ND_ETHERNET)},
    {"wifis", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(ND_WIFI)},
    {"bridges", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(ND_BRIDGE)},
    {"bonds", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(ND_BOND)},
    {"vlans", YAML_MAPPING_NODE, handle_network_type, NULL, GUINT_TO_POINTER(ND_VLAN)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for root node
 ****************************************************/

const mapping_entry_handler root_handlers[] = {
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
        missing_node *missing;

        g_clear_error(error);

        /* Get the first missing identifier we can get from our list, to
         * approximate early failure and give the user a meaningful error. */
        g_hash_table_iter_init (&iter, missing_id);
        g_hash_table_iter_next (&iter, &key, &value);
        missing = (missing_node*) value;

        return yaml_error(missing->node, error, "%s: interface %s is not defined",
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
parse_yaml(const char* filename, GError** error)
{
    yaml_document_t doc;
    gboolean ret;

    if (!load_yaml(filename, &doc, error))
        return FALSE;

    /* empty file? */
    if (yaml_document_get_root_node(&doc) == NULL)
        return TRUE;

    if (!netdefs)
        netdefs = g_hash_table_new(g_str_hash, g_str_equal);

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
    net_definition* nd = value;
    if (nd->backend == BACKEND_NONE) {
        nd->backend = get_default_backend_for_type(nd->type);
        g_debug("%s: setting default backend to %i", nd->id, nd->backend);
    }
}

/**
 * Post-processing after parsing all config files
 */
gboolean
finish_parse(GError** error)
{
    if (netdefs)
        g_hash_table_foreach(netdefs, finish_iterator, NULL);
    return TRUE;
}

/**
 * Return current global backend.
 */
netdef_backend
get_global_backend()
{
    return backend_global;
}
