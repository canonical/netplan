#include <yaml.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <errno.h>

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

void
print_indent(unsigned indent)
{
    for (unsigned i = 0; i < indent; ++i)
        g_printf("  ");
}

/**
 * Recursively dump a yaml_node to stdout.
 */
void
dump_node(yaml_document_t *doc, yaml_node_t *node, unsigned indent, const char *prefix) {
    yaml_node_item_t *item;
    yaml_node_pair_t *pair;

    if (node == NULL)
        return;

    print_indent(indent);
    g_printf("%s", prefix);

    switch (node->type) {
        case YAML_SCALAR_NODE:
            g_printf("scalar %s\n", node->data.scalar.value);
            break;
        case YAML_SEQUENCE_NODE:
            g_printf("seq\n");
            for (item = node->data.sequence.items.start; item < node->data.sequence.items.top; item++)
                dump_node(doc, yaml_document_get_node(doc, *item), indent + 1, "- ");
            break;
        case YAML_MAPPING_NODE:
            g_printf("map\n");
            for (pair = node->data.mapping.pairs.start; pair < node->data.mapping.pairs.top; pair++) {
                dump_node(doc, yaml_document_get_node(doc, pair->key), indent + 1, "k: ");
                dump_node(doc, yaml_document_get_node(doc, pair->value), indent + 1, "v: ");
            }
            break;
        default:
            g_assert_not_reached();
            break;
    }
}

/**
 * Read network config from YAML and generate backend specific configuration
 * files.
 */
gboolean
generate_config(yaml_document_t *doc, GError **error)
{
    dump_node(doc, yaml_document_get_root_node(doc), 0, "");

    return TRUE;
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
    return 0;
}
