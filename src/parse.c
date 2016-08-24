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

/* file that is currently being processed, for useful error messages */
const char* current_file;
/* net_definition that is currently being processed */
net_definition* cur_netdef;

/* wifi AP that is currently being processed */
wifi_access_point* cur_access_point;

netdef_backend backend_global, backend_cur_type;

/* Global ID → net_definition* map for all parsed config files */
GHashTable* netdefs;
/* Set of IDs in currently parsed YAML file, for being able to detect
 * "duplicate ID within one file" vs. allowing a drop-in to override/amend an
 * existing definition */
GHashTable* ids_in_file;

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
yaml_error(yaml_node_t* node, GError** error, const char* msg, ...)
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
        default:
            g_assert_not_reached(); /* LCOV_EXCL_LINE */
    }
    return FALSE;
}

static inline const char*
scalar(const yaml_node_t* node)
{
    return (const char*) node->data.scalar.value;
}


/**
 * Check that node contains a valid ID/interface name. Raise GError if not.
 */
static gboolean
assert_valid_id(yaml_node_t* node, GError** error)
{
    static regex_t re;
    static gboolean re_inited = FALSE;

    g_assert(node->type == YAML_SCALAR_NODE);

    if (!re_inited) {
        g_assert(regcomp(&re, "^[[:alnum:][:punct:]]+$", REG_EXTENDED|REG_NOSUB) == 0);
        re_inited = TRUE;
    }

    if (regexec(&re, scalar(node), 0, NULL, 0) != 0)
        return yaml_error(node, error, "Invalid name '%s'", scalar(node));
    return TRUE;
}

#define assert_type(n,t) { if (!assert_type_fn(n,t,error)) return FALSE; }

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

    switch (type) {
        case ND_WIFI:
            return BACKEND_NM;
        default:
            return BACKEND_NETWORKD;
    }
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
        if (!g_hash_table_insert(cur_netdef->access_points, cur_access_point->ssid, cur_access_point))
            return yaml_error(key, error, "%s: Duplicate access point SSID '%s'", cur_netdef->id, cur_access_point->ssid);

        if (!process_mapping(doc, value, wifi_access_point_handlers, error))
            return FALSE;

        cur_access_point = NULL;
    }
    return TRUE;
}

static gboolean
handle_bridge_interfaces(yaml_document_t* doc, yaml_node_t* node, const void* _, GError** error)
{
    /* all entries must refer to already defined IDs */
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        net_definition *component;

        assert_type(entry, YAML_SCALAR_NODE);
        component = g_hash_table_lookup(netdefs, scalar(entry));
        if (!component)
            return yaml_error(node, error, "bridge %s: interface %s is not defined",
                              cur_netdef->id, scalar(entry));
        if (component->bridge)
            return yaml_error(node, error, "bridge %s: interface %s is already assigned to bridge %s",
                              cur_netdef->id, scalar(entry), component->bridge);
        component->bridge = cur_netdef->id;
    }

    return TRUE;
}

const mapping_entry_handler ethernet_def_handlers[] = {
    {"set-name", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(set_name)},
    {"match", YAML_MAPPING_NODE, handle_match},
    {"renderer", YAML_SCALAR_NODE, handle_netdef_renderer},
    {"wakeonlan", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(wake_on_lan)},
    {"dhcp4", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp4)},
    {"dhcp6", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp6)},
    {"addresses", YAML_SEQUENCE_NODE, handle_addresses},
    {"gateway4", YAML_SCALAR_NODE, handle_gateway4},
    {"gateway6", YAML_SCALAR_NODE, handle_gateway6},
    {NULL}
};

const mapping_entry_handler wifi_def_handlers[] = {
    {"set-name", YAML_SCALAR_NODE, handle_netdef_str, NULL, netdef_offset(set_name)},
    {"match", YAML_MAPPING_NODE, handle_match},
    {"renderer", YAML_SCALAR_NODE, handle_netdef_renderer},
    {"wakeonlan", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(wake_on_lan)},
    {"dhcp4", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp4)},
    {"dhcp6", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp6)},
    {"addresses", YAML_SEQUENCE_NODE, handle_addresses},
    {"gateway4", YAML_SCALAR_NODE, handle_gateway4},
    {"gateway6", YAML_SCALAR_NODE, handle_gateway6},
    {"access-points", YAML_MAPPING_NODE, handle_wifi_access_points},
    {NULL}
};

const mapping_entry_handler bridge_def_handlers[] = {
    {"renderer", YAML_SCALAR_NODE, handle_netdef_renderer},
    {"dhcp4", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp4)},
    {"dhcp6", YAML_SCALAR_NODE, handle_netdef_bool, NULL, netdef_offset(dhcp6)},
    {"addresses", YAML_SEQUENCE_NODE, handle_addresses},
    {"gateway4", YAML_SCALAR_NODE, handle_gateway4},
    {"gateway6", YAML_SCALAR_NODE, handle_gateway6},
    {"interfaces", YAML_SEQUENCE_NODE, handle_bridge_interfaces},
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
    g_assert(nd->type != ND_NONE);

    /* set-name: requires match: */
    if (nd->set_name && !nd->has_match)
        return yaml_error(node, error, "%s: set-name: requires match: properties", nd->id);

    if (nd->type == ND_WIFI && nd->access_points == NULL)
        return yaml_error(node, error, "%s: No access points defined", nd->id);

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
            g_hash_table_insert(netdefs, cur_netdef->id, cur_netdef);
        }

        if (!g_hash_table_add(ids_in_file, cur_netdef->id))
            return yaml_error(key, error, "Duplicate net definition ID '%s'", cur_netdef->id);

        /* and fill it with definitions */
        switch (cur_netdef->type) {
            case ND_ETHERNET: handlers = ethernet_def_handlers; break;
            case ND_WIFI: handlers = wifi_def_handlers; break;
            case ND_BRIDGE: handlers = bridge_def_handlers; break;
            default: g_assert_not_reached(); /* LCOV_EXCL_LINE */
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

    ret = process_mapping(&doc, yaml_document_get_root_node(&doc), root_handlers, error);
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
