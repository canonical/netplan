#include <yaml.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <errno.h>

/**
 * Read network config from YAML and generate backend specific configuration
 * files.
 */
gboolean
generate_config(const char* yaml, GError **error)
{
    FILE* fyaml = NULL;
    yaml_parser_t parser;
    yaml_event_t event;
    int done = 0;

    fyaml = g_fopen(yaml, "r");
    if (!fyaml) {
        g_set_error(error, G_FILE_ERROR, errno, "Cannot open %s: %s", yaml, g_strerror(errno));
        return FALSE;
    }

    yaml_parser_initialize(&parser);
    yaml_parser_set_input_file(&parser, fyaml);

    while (!done) {
        /* Get the next event. */
        if (!yaml_parser_parse(&parser, &event)) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                        "Invalid YAML at %s line %zu column %zu: %s",
                        yaml, parser.problem_mark.line, parser.problem_mark.column, parser.problem);
            break;
        }

        switch (event.type) {
            case YAML_SCALAR_EVENT:
                g_printf("scalar %s anchor %s\n", event.data.scalar.value, event.data.scalar.anchor);
                break;

            case YAML_SEQUENCE_START_EVENT:
                g_printf("seq start anchor %s tag %s\n", event.data.sequence_start.anchor, event.data.sequence_start.tag);
                break;

            case YAML_SEQUENCE_END_EVENT:
                g_printf("seq end\n");
                break;

            case YAML_MAPPING_START_EVENT:
                g_printf("map start anchor %s tag %s\n", event.data.mapping_start.anchor, event.data.mapping_start.tag);
                break;

            case YAML_MAPPING_END_EVENT:
                g_printf("map end\n");
                break;

            case YAML_ALIAS_EVENT:
                g_printf("alias anchor: %s\n", event.data.alias.anchor);
                break;

            case YAML_STREAM_END_EVENT:
            case YAML_DOCUMENT_END_EVENT:
                done = 1;
                break;

            /* uninteresting */
            case YAML_NO_EVENT:
            case YAML_STREAM_START_EVENT:
            case YAML_DOCUMENT_START_EVENT:
                break;

        }

        yaml_event_delete(&event);
    }

    yaml_parser_delete(&parser);
    fclose(fyaml);
    return done > 0;
}


int main(int argc, char** argv)
{
    GError *err = NULL;
    if (!generate_config(argv[1], &err)) {
        g_fprintf(stderr, "%s\n", err->message);
        g_error_free(err);
        return 1;
    }
    return 0;
}
