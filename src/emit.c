#include <stdarg.h>
#include <errno.h>

#include <yaml.h>

#include <glib.h>
#include <glib/gstdio.h>

/****************************************************
 * Built state
 ****************************************************/

typedef enum {
    ND_NONE,
    ND_ETHERNET,
} netdef_type;

/**
 * Represent one configuration stanza in "network". This is a linked list, so
 * that composite devices like bridges can refer to previous definitions as
 * components */
typedef struct net_definition {
    netdef_type type;
    const char* id;
    const char* set_name;
    gboolean wake_on_lan;
    struct {
        const char* driver;
        const char* mac;
    } match;

    /* singly-linked list */
    struct net_definition *prev;
} net_definition;

/* convenience macro to put the offset of a net_definition field into "void *data" */
#define netdef_offset(field) GUINT_TO_POINTER(offsetof(net_definition, field))

struct {
    /* file that is currently being processed, for useful error messages */
    const char *current_file;
    net_definition *netdefs;
} state;


/****************************************************
 * Loading and error handling
 ****************************************************/

/**
 * Load YAML file name into a yaml_document_t.
 *
 * Returns: TRUE on success, FALSE if the document is malformed; @error gets set then.
 */
gboolean
load_yaml(const char *yaml, yaml_document_t *doc, GError **error)
{
    FILE *fyaml = NULL;
    yaml_parser_t parser;
    gboolean ret = TRUE;

    state.current_file = yaml;

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
yaml_error(yaml_node_t *node, GError **error, const char *msg, ...)
{
    va_list argp;
    gchar *s;

    va_start(argp, msg);
    g_vasprintf(&s, msg, argp);
    g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                "Error in network definition %s line %zu column %zu: %s",
                state.current_file, node->start_mark.line, node->start_mark.column, s);
    g_free(s);
    va_end(argp);
    return FALSE;
}

/**
 * Raise a GError about a type mismatch and return FALSE.
 */
static gboolean
assert_type_fn(yaml_node_t *node, yaml_node_type_t expected_type, GError **error)
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
            g_assert_not_reached();
    }
    return FALSE;
}

#define assert_type(n,t) { if (!assert_type_fn(n,t,error)) return FALSE; }

/****************************************************
 * Data types and functions for interpreting YAML nodes
 ****************************************************/

typedef gboolean (*node_handler) (yaml_document_t *doc, yaml_node_t *node, const void* data, GError **error);

typedef struct mapping_entry_handler_s {
    /* mapping key (must be scalar) */
    const char *key;
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
process_mapping(yaml_document_t *doc, yaml_node_t *node, const mapping_entry_handler* handlers, const void* data, GError **error)
{
    yaml_node_pair_t *entry;

    assert_type(node, YAML_MAPPING_NODE);

    for (entry = node->data.mapping.pairs.start; entry < node->data.mapping.pairs.top; entry++) {
        yaml_node_t *key, *value;
        const mapping_entry_handler *h;

        key = yaml_document_get_node(doc, entry->key);
        value = yaml_document_get_node(doc, entry->value);
        assert_type(key, YAML_SCALAR_NODE);
        h = get_handler(handlers, (const char*) key->data.scalar.value);
        if (!h)
            return yaml_error(node, error, "unknown key %s", key->data.scalar.value);
        assert_type(value, h->type);
        if (h->map_handlers) {
            g_assert(h->handler == NULL);
            g_assert(h->type == YAML_MAPPING_NODE);
            if (!process_mapping(doc, value, h->map_handlers, h->data, error))
                return FALSE;
        } else {
            if (!h->handler(doc, value, h->data, error))
                return FALSE;
        }
    }

    return TRUE;
}

/**
 * Generic handler for setting a state.netdefs string field from a scalar node
 * @data: offset into state.netdefs where the const char* field to write is
 *        located
 */
static gboolean
handle_netdev_str(yaml_document_t *doc, yaml_node_t *node, const void* data, GError **error)
{
    guint offset = GPOINTER_TO_UINT(data);
    *((const char**) ((void*) state.netdefs + offset)) = (const char*) node->data.scalar.value;
    return TRUE;
}

/**
 * Generic handler for setting a state.netdefs gboolean field from a scalar node
 * @data: offset into state.netdefs where the gboolean field to write is located
 */
static gboolean
handle_netdev_bool(yaml_document_t *doc, yaml_node_t *node, const void* data, GError **error)
{
    guint offset = GPOINTER_TO_UINT(data);
    gboolean v;

    if (g_ascii_strcasecmp((const char*) node->data.scalar.value, "true") == 0 ||
        g_ascii_strcasecmp((const char*) node->data.scalar.value, "on") == 0 ||
        g_ascii_strcasecmp((const char*) node->data.scalar.value, "yes") == 0 ||
        g_ascii_strcasecmp((const char*) node->data.scalar.value, "1") == 0)
        v = TRUE;
    else if (g_ascii_strcasecmp((const char*) node->data.scalar.value, "false") == 0 ||
        g_ascii_strcasecmp((const char*) node->data.scalar.value, "off") == 0 ||
        g_ascii_strcasecmp((const char*) node->data.scalar.value, "no") == 0 ||
        g_ascii_strcasecmp((const char*) node->data.scalar.value, "0") == 0)
        v = FALSE;
    else
        return yaml_error(node, error, "invalid boolean value %s", node->data.scalar.value);

    *((gboolean*) ((void*) state.netdefs + offset)) = v;
    return TRUE;
}


/****************************************************
 * Grammar and handlers for network config "match" entry
 ****************************************************/

const mapping_entry_handler match_handlers[] = {
    {"driver", YAML_SCALAR_NODE, handle_netdev_str, NULL, netdef_offset(match.driver)},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network config list item
 ****************************************************/

static gboolean
handle_config_type(yaml_document_t *doc, yaml_node_t *node, const void* data, GError **error)
{
    g_debug("handle_config_type");
    return TRUE;
}

const mapping_entry_handler config_handlers[] = {
    {"id", YAML_SCALAR_NODE, handle_netdev_str, NULL, netdef_offset(id)},
    {"type", YAML_SCALAR_NODE, handle_config_type},
    {"set-name", YAML_SCALAR_NODE, handle_netdev_str, NULL, netdef_offset(set_name)},
    {"wakeonlan", YAML_SCALAR_NODE, handle_netdev_bool, NULL, netdef_offset(wake_on_lan)},
    {"match", YAML_MAPPING_NODE, NULL, match_handlers},
    {NULL}
};

/****************************************************
 * Grammar and handlers for network node
 ****************************************************/

static gboolean
handle_network_version(yaml_document_t *doc, yaml_node_t *node, const void* _, GError **error)
{
    if (strcmp((char*) node->data.scalar.value, "2") != 0)
        return yaml_error(node, error, "Only version 2 is supported");
    return TRUE;
}

static gboolean
handle_network_config(yaml_document_t *doc, yaml_node_t *node, const void* _, GError **error)
{
    g_debug("handle_network_config");
    for (yaml_node_item_t *i = node->data.sequence.items.start; i < node->data.sequence.items.top; i++) {
        yaml_node_t *entry = yaml_document_get_node(doc, *i);
        net_definition *nd;

        assert_type(entry, YAML_MAPPING_NODE);

        /* create new network definition */
        nd = g_new0(net_definition, 1);
        nd->prev = state.netdefs;
        state.netdefs = nd;

        /* and fill it with definitions */
        if (!process_mapping(doc, entry, config_handlers, NULL, error))
            return FALSE;
    }
    return TRUE;
}

const mapping_entry_handler network_handlers[] = {
    {"version", YAML_SCALAR_NODE, handle_network_version},
    {"config", YAML_SEQUENCE_NODE, handle_network_config},
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
 * Read network config from YAML and generate backend specific configuration
 * files.
 */
gboolean
generate_config(yaml_document_t *doc, GError **error)
{
    return process_mapping(doc, yaml_document_get_root_node(doc), root_handlers, NULL, error);
}

int main(int argc, char **argv)
{
    GError *err = NULL;
    yaml_document_t doc;

    if (!load_yaml(argv[1], &doc, &err) || !generate_config(&doc, &err)) {
        g_fprintf(stderr, "%s\n", err->message);
        g_error_free(err);
        return 1;
    }

    /* debugging: show the current netdev device to confirm written fields */
    g_printf("id: %s, set-name: %s, WOL: %i match.driver: %s, prev: %p\n", state.netdefs->id, state.netdefs->set_name, state.netdefs->wake_on_lan, state.netdefs->match.driver, state.netdefs->prev);
    return 0;
}
