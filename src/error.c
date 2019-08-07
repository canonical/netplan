/*
 * Copyright (C) 2019 Canonical, Ltd.
 * Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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

#include <glib.h>
#include <glib/gstdio.h>
#include <gio/gio.h>

#include <yaml.h>

#include "parse.h"


/****************************************************
 * Loading and error handling
 ****************************************************/

static void
write_error_marker(GString *message, int column)
{
    int i;

    for (i = 0; (column > 0 && i < column); i++)
        g_string_append_printf(message, " ");

    g_string_append_printf(message, "^");
}

static char *
get_syntax_error_context(const int line_num, const int column, GError **error)
{
    GString *message = NULL;
    GFile *cur_file = g_file_new_for_path(current_file);
    GFileInputStream *file_stream;
    GDataInputStream *stream;
    gsize len;
    gchar* line = NULL;

    message = g_string_sized_new(200);
    file_stream = g_file_read(cur_file, NULL, error);
    stream = g_data_input_stream_new (G_INPUT_STREAM(file_stream));
    g_object_unref(file_stream);

    for (int i = 0; i < line_num + 1; i++) {
        g_free(line);
        line = g_data_input_stream_read_line(stream, &len, NULL, error);
    }
    g_string_append_printf(message, "%s\n", line);

    write_error_marker(message, column);

    g_object_unref(stream);
    g_object_unref(cur_file);

    return g_string_free(message, FALSE);
}

static char *
get_parser_error_context(const yaml_parser_t *parser, GError **error)
{
    GString *message = NULL;
    unsigned char* line = parser->buffer.pointer;
    unsigned char* current = line;

    message = g_string_sized_new(200);

    while (current > parser->buffer.start) {
        current--;
        if (*current == '\n') {
            line = current + 1;
            break;
        }
    }
    if (current <= parser->buffer.start)
        line = parser->buffer.start;
    current = line + 1;
    while (current <= parser->buffer.last) {
        if (*current == '\n') {
            *current = '\0';
            break;
        }
        current++;
    }

    g_string_append_printf(message, "%s\n", line);

    write_error_marker(message, parser->problem_mark.column);

    return g_string_free(message, FALSE);
}

gboolean
parser_error(const yaml_parser_t* parser, const char* yaml, GError** error)
{
    char *error_context = get_parser_error_context(parser, error);
    if ((char)*parser->buffer.pointer == '\t')
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                    "%s:%zu:%zu: Invalid YAML: tabs are not allowed for indent:\n%s",
                    yaml,
                    parser->problem_mark.line + 1,
                    parser->problem_mark.column + 1,
                    error_context);
    else if (((char)*parser->buffer.pointer == ' ' || (char)*parser->buffer.pointer == '\0')
             && !parser->token_available)
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                    "%s:%zu:%zu: Invalid YAML: aliases are not supported:\n%s",
                    yaml,
                    parser->problem_mark.line + 1,
                    parser->problem_mark.column + 1,
                    error_context);
    else if (parser->state == YAML_PARSE_BLOCK_MAPPING_KEY_STATE)
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                    "%s:%zu:%zu: Invalid YAML: inconsistent indentation:\n%s",
                    yaml,
                    parser->problem_mark.line + 1,
                    parser->problem_mark.column + 1,
                    error_context);
    else {
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                    "%s:%zu:%zu: Invalid YAML: %s:\n%s",
                    yaml,
                    parser->problem_mark.line + 1,
                    parser->problem_mark.column + 1,
                    parser->problem,
                    error_context);
    }
    g_free(error_context);

    return FALSE;
}

/**
 * Put a YAML specific error message for @node into @error.
 */
gboolean
yaml_error(const yaml_node_t* node, GError** error, const char* msg, ...)
{
    va_list argp;
    char* s;
    char* error_context = NULL;

    va_start(argp, msg);
    g_vasprintf(&s, msg, argp);
    if (node != NULL) {
        error_context = get_syntax_error_context(node->start_mark.line, node->start_mark.column, error);
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                    "%s:%zu:%zu: Error in network definition: %s\n%s",
                    current_file,
                    node->start_mark.line + 1,
                    node->start_mark.column + 1,
                    s,
                    error_context);
    } else {
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_PARSE,
                    "Error in network definition: %s", s);
    }
    g_free(s);
    va_end(argp);
    return FALSE;
}

