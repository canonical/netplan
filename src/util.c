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

#include <stdlib.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <fnmatch.h>
#include <errno.h>
#include <string.h>
#include <sys/mman.h>

#include <glib.h>
#include <glib/gprintf.h>
#include <yaml.h>

#include "util.h"
#include "util-internal.h"
#include "netplan.h"
#include "parse.h"
#include "parse-globals.h"
#include "names.h"
#include "yaml-helpers.h"

NETPLAN_ABI GHashTable*
wifi_frequency_24;

NETPLAN_ABI GHashTable*
wifi_frequency_5;

const gchar* FALLBACK_FILENAME = "70-netplan-set.yaml";

typedef struct netplan_state_iterator RealStateIter;
/**
 * Create the parent directories of given file path. Exit program on failure.
 */
void
safe_mkdir_p_dir(const char* file_path)
{
    g_autofree char* dir = g_path_get_dirname(file_path);

    if (g_mkdir_with_parents(dir, 0755) < 0) {
        g_fprintf(stderr, "ERROR: cannot create directory %s: %m\n", dir);
        exit(1);
    }
}

/**
 * Write a GString to a file and free it. Create necessary parent directories
 * and exit with error message on error.
 * @s: #GString whose contents to write. Will be fully freed afterwards.
 * @rootdir: optional rootdir (@NULL means "/")
 * @path: path of file to write (@rootdir will be prepended)
 * @suffix: optional suffix to append to path
 */
void g_string_free_to_file(GString* s, const char* rootdir, const char* path, const char* suffix)
{
    g_autofree char* full_path = NULL;
    g_autofree char* path_suffix = NULL;
    g_autofree char* contents = g_string_free(s, FALSE);
    GError* error = NULL;

    path_suffix = g_strjoin(NULL, path, suffix, NULL);
    full_path = g_build_path(G_DIR_SEPARATOR_S, rootdir ?: G_DIR_SEPARATOR_S, path_suffix, NULL);
    safe_mkdir_p_dir(full_path);
    if (!g_file_set_contents(full_path, contents, -1, &error)) {
        /* the mkdir() just succeeded, there is no sensible
         * method to test this without root privileges, bind mounts, and
         * simulating ENOSPC */
        // LCOV_EXCL_START
        g_fprintf(stderr, "ERROR: cannot create file %s: %s\n", path, error->message);
        exit(1);
        // LCOV_EXCL_STOP
    }
}

/**
 * Remove all files matching given glob.
 */
void
unlink_glob(const char* rootdir, const char* _glob)
{
    glob_t gl;
    int rc;
    g_autofree char* rglob = g_strjoin(NULL, rootdir ?: "", G_DIR_SEPARATOR_S, _glob, NULL);

    rc = glob(rglob, GLOB_BRACE, NULL, &gl);
    if (rc != 0 && rc != GLOB_NOMATCH) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to glob for %s: %m\n", rglob);
        return;
        // LCOV_EXCL_STOP
    }

    for (size_t i = 0; i < gl.gl_pathc; ++i)
        unlink(gl.gl_pathv[i]);
    globfree(&gl);
}

/**
 * Return a glob of all *.yaml files in /{lib,etc,run}/netplan/ (in this order)
 */
int find_yaml_glob(const char* rootdir, glob_t* out_glob)
{
    int rc;
    g_autofree char* rglob = g_build_path(G_DIR_SEPARATOR_S,
                                          rootdir ?: G_DIR_SEPARATOR_S,
                                          "{lib,etc,run}/netplan/*.yaml", NULL);
    rc = glob(rglob, GLOB_BRACE, NULL, out_glob);
    if (rc != 0 && rc != GLOB_NOMATCH) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to glob for %s: %m\n", rglob);
        return 1;
        // LCOV_EXCL_STOP
    }

    return 0;
}


/**
 * create a yaml patch from a "set expression"
 *
 * A "set expression" here consists of a path formed of TAB-separated
 * keys, indicating where in the YAML doc we want to make our changes, and
 * a valid YAML expression that will be the payload to insert at that
 * place. The result is a well-formed YAML document.
 *
 * @conf_obj_path: TAB-separated YAML path
 * @obj_payload: YAML expression
 * @output_file: file path to write out the result document
 */

gboolean
netplan_util_create_yaml_patch(const char* conf_obj_path, const char* obj_payload, int output_fd, GError** error)
{
	yaml_emitter_t emitter;
	yaml_parser_t parser;
	yaml_event_t event;
	int token_depth = 0;
    int out_dup = -1;
    FILE* out_stream = NULL;
    int ret = FALSE;

    out_dup = dup(output_fd);
    if (out_dup < 0)
        goto file_error; // LCOV_EXCL_LINE
    out_stream = fdopen(out_dup, "w");
    if (!out_stream)
        goto file_error; // LCOV_EXCL_LINE

    yaml_emitter_initialize(&emitter);
    yaml_parser_initialize(&parser);
    yaml_emitter_set_output_file(&emitter, out_stream);
    yaml_stream_start_event_initialize(&event, YAML_UTF8_ENCODING);
    if (!yaml_emitter_emit(&emitter, &event))
        goto err_path; // LCOV_EXCL_LINE
    yaml_document_start_event_initialize(&event, NULL, NULL, NULL, 1);
    if (!yaml_emitter_emit(&emitter, &event))
        goto err_path; // LCOV_EXCL_LINE

    char **tokens = g_strsplit_set(conf_obj_path, "\t", -1);
	for (; tokens[token_depth] != NULL; token_depth++) {
        YAML_MAPPING_OPEN(&event, &emitter);
        YAML_SCALAR_PLAIN(&event, &emitter, tokens[token_depth]);
    }
    g_strfreev(tokens);

    yaml_parser_set_input_string(&parser, (const unsigned char *)obj_payload, strlen(obj_payload));
    while (TRUE) {
        if (!yaml_parser_parse(&parser, &event)) {
            g_set_error(error, NETPLAN_FORMAT_ERROR, NETPLAN_ERROR_FORMAT_INVALID_YAML, "Error parsing YAML: %s", parser.problem);
            goto cleanup;
        }
        if (event.type == YAML_STREAM_END_EVENT || event.type == YAML_DOCUMENT_END_EVENT)
            break;
        switch (event.type) {
            case YAML_STREAM_START_EVENT:
            case YAML_DOCUMENT_START_EVENT:
                break;
            case YAML_MAPPING_START_EVENT:
                YAML_MAPPING_OPEN(&event, &emitter);
                break;
            case YAML_SEQUENCE_START_EVENT:
                YAML_SEQUENCE_OPEN(&event, &emitter);
                break;
            default:
                if (!yaml_emitter_emit(&emitter, &event))
                    goto err_path; // LCOV_EXCL_LINE
        }
	}

	for (; token_depth > 0; token_depth--)
        YAML_MAPPING_CLOSE(&event, &emitter);

    yaml_document_end_event_initialize(&event, 1);
    if (!yaml_emitter_emit(&emitter, &event))
        goto err_path; // LCOV_EXCL_LINE
    yaml_stream_end_event_initialize(&event);
    if (!yaml_emitter_emit(&emitter, &event))
        goto err_path; // LCOV_EXCL_LINE
    yaml_emitter_flush(&emitter);
    fflush(out_stream);
    ret = TRUE;
    goto cleanup;

// LCOV_EXCL_START
err_path:
    g_set_error(error, NETPLAN_EMITTER_ERROR, NETPLAN_ERROR_YAML_EMITTER, "Error generating YAML: %s", emitter.problem);
    ret = FALSE;
// LCOV_EXCL_STOP
cleanup:
    /* also closes the dup FD */
    fclose(out_stream);
    yaml_emitter_delete(&emitter);
    yaml_parser_delete(&parser);
    return ret;

// LCOV_EXCL_START
file_error:
    g_set_error(error, NETPLAN_FILE_ERROR, errno, "Error when opening FD %d: %m", output_fd);
    if (out_dup >= 0)
        close(out_dup);
    return FALSE;
// LCOV_EXCL_STOP
}

static gboolean
copy_yaml_subtree(yaml_parser_t *parser, yaml_emitter_t *emitter, GError** error) {
	yaml_event_t event;
    int map_count = 0, seq_count = 0;
    do {
		if (!yaml_parser_parse(parser, &event)) {
            g_set_error(error, NETPLAN_FORMAT_ERROR, NETPLAN_ERROR_FORMAT_INVALID_YAML, "Error parsing YAML: %s", parser->problem);
            return FALSE;
        }

        switch (event.type) {
            case YAML_MAPPING_START_EVENT:
                map_count++;
                break;
            case YAML_SEQUENCE_START_EVENT:
                seq_count++;
                break;
            case YAML_MAPPING_END_EVENT:
                map_count--;
                break;
            case YAML_SEQUENCE_END_EVENT:
                seq_count--;
                break;
            default:
                break;
        }
        if (emitter && !yaml_emitter_emit(emitter, &event)) {
            // LCOV_EXCL_START
            g_set_error(error, NETPLAN_PARSER_ERROR, NETPLAN_ERROR_INVALID_YAML, "Error emitting YAML: %s", emitter->problem);
            return FALSE;
            // LCOV_EXCL_STOP
        }
    } while (map_count || seq_count);
    return TRUE;
}

/**
 * Given a YAML tree and a YAML path (array of keys with NULL as the last array element),
 * emits the subtree matching the path, while emitting the rest of the data into the void.
 */
static gboolean
emit_yaml_subtree(yaml_parser_t *parser, yaml_emitter_t *emitter, char** yaml_path, GError** error) {
	yaml_event_t event;
    /* If the path component is NULL, we're done with the trimming, we can just copy the whole subtree */
    if (!(*yaml_path))
        return copy_yaml_subtree(parser, emitter, error);

    if (!yaml_parser_parse(parser, &event))
        goto parser_err_path; // LCOV_EXCL_LINE
    if (event.type != YAML_MAPPING_START_EVENT) {
        g_set_error(error, NETPLAN_FORMAT_ERROR, NETPLAN_ERROR_FORMAT_INVALID_YAML, "Unexpected YAML structure found");
        return FALSE;
    }
    while (TRUE) {
        if (!yaml_parser_parse(parser, &event))
            goto parser_err_path;
        if (event.type == YAML_MAPPING_END_EVENT)
            break;
        if (g_strcmp0(*yaml_path, (char*)event.data.scalar.value) == 0) {
            /* Go further down, popping the component we just used from the path */
            if (!emit_yaml_subtree(parser, emitter, yaml_path+1, error))
                return FALSE;
        } else {
            /* We're out of the path, so we trim the branch by "emitting" the data into a NULL emitter */
            if (!copy_yaml_subtree(parser, NULL, error))
                return FALSE;
        }
    }
    return TRUE;

parser_err_path:
    g_set_error(error, NETPLAN_FORMAT_ERROR, NETPLAN_ERROR_FORMAT_INVALID_YAML, "Error parsing YAML: %s", parser->problem);
    return FALSE;
}

NETPLAN_INTERNAL gboolean
netplan_util_dump_yaml_subtree(const char* prefix, int input_fd, int output_fd, GError** error) {
    gboolean ret = TRUE;
    char **yaml_path = NULL;
	yaml_emitter_t emitter;
	yaml_parser_t parser;
	yaml_event_t event;
    int in_dup = -1, out_dup = -1;
    FILE* input = NULL;
    FILE* output = NULL;

    in_dup = dup(input_fd);
    if (in_dup < 0)
        goto file_error; // LCOV_EXCL_LINE
    out_dup = dup(output_fd);
    if (out_dup < 0)
        goto file_error; // LCOV_EXCL_LINE

    input = fdopen(in_dup, "r");
    output = fdopen(out_dup, "w");
    if (!input || !output)
        goto file_error;

    if (fseek(input, 0, SEEK_SET) < 0)
        goto file_error; // LCOV_EXCL_LINE

    yaml_path = g_strsplit(prefix, "\t", -1);

    yaml_parser_initialize(&parser);
    yaml_parser_set_input_file(&parser, input);
    yaml_emitter_initialize(&emitter);
    yaml_emitter_set_output_file(&emitter, output);

    /* Copy over the stream and document start events */
    for (int i = 0; i < 2; ++i) {
        if (!yaml_parser_parse(&parser, &event))
            goto parser_err_path; // LCOV_EXCL_LINE
        if (!yaml_emitter_emit(&emitter, &event))
            goto err_path; // LCOV_EXCL_LINE
    }

    if (!emit_yaml_subtree(&parser, &emitter, yaml_path, error)) {
        ret = FALSE;
        goto cleanup;
    }

    if (emitter.events.head != emitter.events.tail) {
        YAML_NULL_PLAIN(&event, &emitter);
    }

    do {
        if (!yaml_parser_parse(&parser, &event))
            goto parser_err_path; // LCOV_EXCL_LINE
        if (!yaml_emitter_emit(&emitter, &event))
            goto err_path; // LCOV_EXCL_LINE
    } while (!parser.stream_end_produced);

    goto cleanup;

file_error:
        g_set_error(error, NETPLAN_FILE_ERROR, errno, "%m");
        ret = FALSE;
        goto cleanup;
// LCOV_EXCL_START
parser_err_path:
    g_set_error(error, NETPLAN_FORMAT_ERROR, NETPLAN_ERROR_FORMAT_INVALID_YAML, "Error parsing YAML: %s", parser.problem);
    ret = FALSE;
    goto cleanup;
err_path:
    g_set_error(error, NETPLAN_EMITTER_ERROR, NETPLAN_ERROR_YAML_EMITTER, "Error generating YAML: %s", emitter.problem);
    ret = FALSE;
// LCOV_EXCL_STOP
cleanup:
    if (input)
        fclose(input);
    else
        close(in_dup);

    if (output)
        fclose(output);
    else
        close(out_dup);

    if (yaml_path)
        g_strfreev(yaml_path);
    return ret;
}

/**
 * Get the frequency of a given 2.4GHz WiFi channel
 */
int
wifi_get_freq24(int channel)
{
    if (channel < 1 || channel > 14) {
        g_fprintf(stderr, "ERROR: invalid 2.4GHz WiFi channel: %d\n", channel);
        exit(1);
    }

    if (!wifi_frequency_24) {
        wifi_frequency_24 = g_hash_table_new(g_direct_hash, g_direct_equal);
        /* Initialize 2.4GHz frequencies, as of:
         * https://en.wikipedia.org/wiki/List_of_WLAN_channels#2.4_GHz_(802.11b/g/n/ax) */
        for (unsigned i = 0; i < 13; i++) {
            g_hash_table_insert(wifi_frequency_24, GINT_TO_POINTER(i+1),
                                GINT_TO_POINTER(2412+i*5));
        }
        g_hash_table_insert(wifi_frequency_24, GINT_TO_POINTER(14),
                            GINT_TO_POINTER(2484));
    }
    return GPOINTER_TO_INT(g_hash_table_lookup(wifi_frequency_24,
                           GINT_TO_POINTER(channel)));
}

/**
 * Get the frequency of a given 5GHz WiFi channel
 */
int
wifi_get_freq5(int channel)
{
    int channels[] = { 7, 8, 9, 11, 12, 16, 32, 34, 36, 38, 40, 42, 44, 46, 48,
                       50, 52, 54, 56, 58, 60, 62, 64, 68, 96, 100, 102, 104,
                       106, 108, 110, 112, 114, 116, 118, 120, 122, 124, 126,
                       128, 132, 134, 136, 138, 140, 142, 144, 149, 151, 153,
                       155, 157, 159, 161, 165, 169, 173 };
    gboolean found = FALSE;
    for (unsigned i = 0; i < sizeof(channels) / sizeof(int); i++) {
        if (channel == channels[i]) {
            found = TRUE;
            break;
        }
    }
    if (!found) {
        g_fprintf(stderr, "ERROR: invalid 5GHz WiFi channel: %d\n", channel);
        exit(1);
    }
    if (!wifi_frequency_5) {
        wifi_frequency_5 = g_hash_table_new(g_direct_hash, g_direct_equal);
        /* Initialize 5GHz frequencies, as of:
         * https://en.wikipedia.org/wiki/List_of_WLAN_channels#5.0_GHz_(802.11j)_WLAN
         * Skipping channels 183-196. They are valid only in Japan with registration needed */
        for (unsigned i = 0; i < sizeof(channels) / sizeof(int); i++) {
            g_hash_table_insert(wifi_frequency_5, GINT_TO_POINTER(channels[i]),
                                GINT_TO_POINTER(5000+channels[i]*5));
        }
    }
    return GPOINTER_TO_INT(g_hash_table_lookup(wifi_frequency_5,
                           GINT_TO_POINTER(channel)));
}

/**
 * Systemd-escape the given string. The caller is responsible for freeing
 * the allocated escaped string.
 */
gchar*
systemd_escape(char* string)
{
    g_autoptr(GError) err = NULL;
    g_autofree gchar* stderrh = NULL;
    gint exit_status = 0;
    gchar *escaped;

    gchar *argv[] = {"bin" "/" "systemd-escape", "--", string, NULL};
    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &escaped, &stderrh, &exit_status, &err);
    #if GLIB_CHECK_VERSION (2, 70, 0)
    g_spawn_check_wait_status(exit_status, &err);
    #else
    g_spawn_check_exit_status(exit_status, &err);
    #endif
    if (err != NULL) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to ask systemd to escape %s; exit %d\nstdout: '%s'\nstderr: '%s'", string, exit_status, escaped, stderrh);
        exit(1);
        // LCOV_EXCL_STOP
    }
    g_strstrip(escaped);

    return escaped;
}

gboolean
netplan_delete_connection(const char* id, const char* rootdir)
{
    g_autofree gchar* yaml_path = NULL;
    g_autoptr(GError) error = NULL;
    NetplanNetDefinition* nd = NULL;
    gboolean ret = TRUE;
    int patch_fd = -1;

    NetplanParser* input_parser = netplan_parser_new();
    NetplanState* input_state = netplan_state_new();
    NetplanParser* output_parser = NULL;
    NetplanState* output_state = NULL;

    /* parse all YAML files */
    if (   !netplan_parser_load_yaml_hierarchy(input_parser, rootdir, &error)
        || !netplan_state_import_parser_results(input_state, input_parser, &error)) {
        g_fprintf(stderr, "netplan_delete_connection: Cannot parse input: %s\n", error->message);
        ret = FALSE;
        goto cleanup;
    }

    /* find specified netdef in input state */
    nd = netplan_state_get_netdef(input_state, id);
    if (!nd) {
        g_fprintf(stderr, "netplan_delete_connection: Cannot delete %s, does not exist.\n", id);
        ret = FALSE;
        goto cleanup;
    }

    /* Build up a tab-separated YAML path for this Netdef (e.g. network.ethernets.eth0=...) */
    yaml_path = g_strdup_printf("network\t%s\t%s", netplan_def_type_name(nd->type), id);

    /* create a temporary file in memory, to hold our YAML patch */
    patch_fd = memfd_create("patch.yaml", 0);
    if (patch_fd < 0) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "netplan_delete_connection: Cannot create memfd: %m\n");
        ret = FALSE;
        goto cleanup;
        // LCOV_EXCL_STOP
    }
    if (!netplan_util_create_yaml_patch(yaml_path, "NULL", patch_fd, &error)) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "netplan_delete_connection: Cannot create YAML patch: %s\n", error->message);
        ret = FALSE;
        goto cleanup;
        // LCOV_EXCL_STOP
    }

    /* Create a new parser & state to hold our output YAML, ignoring the to be
     * deleted Netdef from the patch */
    output_parser = netplan_parser_new();
    output_state = netplan_state_new();

    lseek(patch_fd, 0, SEEK_SET);
    if (   !netplan_parser_load_nullable_fields(output_parser, patch_fd, &error)
        || !netplan_parser_load_yaml_hierarchy(output_parser, rootdir, &error)) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "netplan_delete_connection: Cannot load output state: %s\n", error->message);
        ret = FALSE;
        goto cleanup;
        // LCOV_EXCL_STOP
    }

    lseek(patch_fd, 0, SEEK_SET);
    if (!netplan_parser_load_yaml_from_fd(output_parser, patch_fd, &error)) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "netplan_delete_connection: Cannot parse YAML patch: %s\n", error->message);
        ret = FALSE;
        goto cleanup;
        // LCOV_EXCL_STOP
    }

    /* We're only deleting some data, so FALLBACK_FILENAME should never be created */
    if (   !netplan_state_import_parser_results(output_state, output_parser, &error)
        || !netplan_state_update_yaml_hierarchy(output_state, FALLBACK_FILENAME, rootdir, &error)) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "netplan_delete_connection: Cannot write output state: %s\n", error->message);
        ret = FALSE;
        goto cleanup;
        // LCOV_EXCL_STOP
    }

cleanup:
    if (input_parser) netplan_parser_clear(&input_parser);
    if (input_state) netplan_state_clear(&input_state);
    if (output_parser) netplan_parser_clear(&output_parser);
    if (output_state) netplan_state_clear(&output_state);
    if (patch_fd >= 0) close(patch_fd);
    return ret;
}

gboolean
netplan_generate(const char* rootdir)
{
    /* TODO: refactor logic to actually be inside the library instead of spawning another process */
    const gchar *argv[] = { SBINDIR "/" "netplan", "generate", NULL , NULL, NULL };
    if (rootdir) {
        argv[2] = "--root-dir";
        argv[3] = rootdir;
    }
    if (getenv("TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("TEST_NETPLAN_CMD");
    return g_spawn_sync(NULL, (gchar**)argv, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL);
}

/**
 * Extract the netplan netdef ID from a NetworkManager connection profile (keyfile),
 * generated by netplan. Used by the NetworkManager YAML backend.
 */
ssize_t
netplan_get_id_from_nm_filepath(const char* filename, const char* ssid, char* out_buffer, size_t out_buf_size)
{
    g_autofree gchar* escaped_ssid = NULL;
    g_autofree gchar* suffix = NULL;
    const char* nm_prefix = "/run/NetworkManager/system-connections/netplan-";
    const char* pos = g_strrstr(filename, nm_prefix);
    const char* start = NULL;
    const char* end = NULL;
    gsize id_len = 0;

    if (!pos)
        return 0;

    if (ssid) {
        escaped_ssid = g_uri_escape_string(ssid, NULL, TRUE);
        suffix = g_strdup_printf("-%s.nmconnection", escaped_ssid);
        end = g_strrstr(filename, suffix);
    } else
        end = g_strrstr(filename, ".nmconnection");

    if (!end)
        return 0;

    /* Move pointer to start of netplan ID inside filename string */
    start = pos + strlen(nm_prefix);
    id_len = end - start;

    if (out_buf_size < id_len + 1)
        return NETPLAN_BUFFER_TOO_SMALL;

    strncpy(out_buffer, start, id_len);
    out_buffer[id_len] = '\0';

    return id_len + 1;
}

ssize_t
netplan_netdef_get_output_filename(const NetplanNetDefinition* netdef, const char* ssid, char* out_buffer, size_t out_buf_size)
{
    g_autofree gchar* conf_path = NULL;

    if (netdef->backend == NETPLAN_BACKEND_NM) {
        if (ssid) {
            g_autofree char* escaped_ssid = g_uri_escape_string(ssid, NULL, TRUE);
            conf_path = g_strjoin(NULL, "/run/NetworkManager/system-connections/netplan-", netdef->id, "-", escaped_ssid, ".nmconnection", NULL);
        } else {
            conf_path = g_strjoin(NULL, "/run/NetworkManager/system-connections/netplan-", netdef->id, ".nmconnection", NULL);
        }

    } else if (netdef->backend == NETPLAN_BACKEND_NETWORKD || netdef->backend == NETPLAN_BACKEND_OVS) {
        conf_path = g_strjoin(NULL, "/run/systemd/network/10-netplan-", netdef->id, ".network", NULL);
    }

    if (conf_path)
        return netplan_copy_string(conf_path, out_buffer, out_buf_size);

    return 0;
}

gboolean
netplan_parser_load_yaml_hierarchy(NetplanParser* npp, const char* rootdir, GError** error)
{
    glob_t gl;
    /* Files with asciibetically higher names override/append settings from
     * earlier ones (in all config dirs); files in /run/netplan/
     * shadow files in /etc/netplan/ which shadow files in /lib/netplan/.
     * To do that, we put all found files in a hash table, then sort it by
     * file name, and add the entries from /run after the ones from /etc
     * and those after the ones from /lib. */
    if (find_yaml_glob(rootdir, &gl) != 0)
        return FALSE; // LCOV_EXCL_LINE
    /* keys are strdup()ed, free them; values point into the glob_t, don't free them */
    g_autoptr(GHashTable) configs = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    g_autoptr(GList) config_keys = NULL;

    for (size_t i = 0; i < gl.gl_pathc; ++i)
        g_hash_table_insert(configs, g_path_get_basename(gl.gl_pathv[i]), gl.gl_pathv[i]);

    config_keys = g_list_sort(g_hash_table_get_keys(configs), (GCompareFunc) strcmp);

    for (GList* i = config_keys; i != NULL; i = i->next)
        if (!netplan_parser_load_yaml(npp, g_hash_table_lookup(configs, i->data), error)) {
            globfree(&gl);
            return FALSE;
        }
    globfree(&gl);
    return TRUE;
}

/**
 * Get a static string describing the default global network
 * for a given address family.
 */
const char *
get_global_network(int ip_family)
{
    g_assert(ip_family == AF_INET || ip_family == AF_INET6);
    if (ip_family == AF_INET)
        return "0.0.0.0/0";
    else
        return "::/0";
}

const char *
get_unspecified_address(int ip_family)
{
    g_assert(ip_family == AF_INET || ip_family == AF_INET6);
    return (ip_family == AF_INET) ? "0.0.0.0" : "::";
}

struct netdef_address_iter {
    guint ip4_index;
    guint ip6_index;
    guint address_options_index;
    NetplanNetDefinition* netdef;
    NetplanAddressOptions* last_address;
};

NETPLAN_INTERNAL struct netdef_address_iter*
_netplan_new_netdef_address_iter(NetplanNetDefinition* netdef)
{
    struct netdef_address_iter* it = g_malloc0(sizeof(struct netdef_address_iter));
    it->ip4_index = 0;
    it->ip6_index = 0;
    it->address_options_index = 0;
    it->netdef = netdef;
    it->last_address = NULL;

    return it;
}

/*
 * The netdef address iterator produces NetplanAddressOptions
 * for all the addresses stored in ip4_address, ip6_address and
 * address_options (in this order).
 *
 * The current value produced by the iterator is saved in it->last_address
 * and the previous one is released. The idea is to not leave to the caller
 * the responsibility of releasing each value. The very last value
 * will be released either when the iterator is destroyed or when there is
 * nothing else to be produced and the iterator was called one last time.
 */
NETPLAN_INTERNAL NetplanAddressOptions*
_netplan_netdef_address_iter_next(struct netdef_address_iter* it)
{
    NetplanAddressOptions* options = NULL;

    if (it->last_address) {
        free_address_options(it->last_address);
        it->last_address = NULL;
    }

    if (it->netdef->ip4_addresses && it->ip4_index < it->netdef->ip4_addresses->len) {
        options = g_malloc0(sizeof(NetplanAddressOptions));
        options->address = g_strdup(g_array_index(it->netdef->ip4_addresses, char*, it->ip4_index++));
        it->last_address = options;
        return options;
    }

    if (it->netdef->ip6_addresses && it->ip6_index < it->netdef->ip6_addresses->len) {
        options = g_malloc0(sizeof(NetplanAddressOptions));
        options->address = g_strdup(g_array_index(it->netdef->ip6_addresses, char*, it->ip6_index++));
        it->last_address = options;
        return options;
    }

    if (it->netdef->address_options && it->address_options_index < it->netdef->address_options->len) {
        options = g_malloc0(sizeof(NetplanAddressOptions));
        NetplanAddressOptions* netdef_options = g_array_index(it->netdef->address_options, NetplanAddressOptions*, it->address_options_index++);
        options->address = g_strdup(netdef_options->address);
        options->lifetime = g_strdup(netdef_options->lifetime);
        options->label = g_strdup(netdef_options->label);
        it->last_address = options;
        return options;
    }

    return options;
}

NETPLAN_INTERNAL void
_netplan_netdef_address_free_iter(struct netdef_address_iter* it)
{
    if (it->last_address)
        free_address_options(it->last_address);
    g_free(it);
}

struct netdef_pertype_iter {
    NetplanDefType type;
    GHashTableIter iter;
    NetplanState* np_state;
};

NETPLAN_INTERNAL struct netdef_pertype_iter*
_netplan_state_new_netdef_pertype_iter(NetplanState* np_state, const char* def_type)
{
    NetplanDefType type = def_type ? netplan_def_type_from_name(def_type) : NETPLAN_DEF_TYPE_NONE;
    struct netdef_pertype_iter* iter = g_malloc0(sizeof(*iter));
    iter->type = type;
    iter->np_state = np_state;
    if (np_state->netdefs)
        g_hash_table_iter_init(&iter->iter, np_state->netdefs);
    return iter;
}


NETPLAN_INTERNAL NetplanNetDefinition*
_netplan_netdef_pertype_iter_next(struct netdef_pertype_iter* it)
{
    gpointer key, value;

    if (!it->np_state->netdefs)
        return NULL;

    while (g_hash_table_iter_next(&it->iter, &key, &value)) {
        NetplanNetDefinition* netdef = value;
        if (it->type == NETPLAN_DEF_TYPE_NONE || netdef->type == it->type)
            return netdef;
    }
    return NULL;
}

NETPLAN_INTERNAL void
_netplan_netdef_pertype_iter_free(struct netdef_pertype_iter* it)
{
    g_free(it);
}

__attribute((alias("_netplan_netdef_pertype_iter_next"))) NETPLAN_ABI NetplanNetDefinition*
_netplan_iter_defs_per_devtype_next(struct netdef_pertype_iter* it);

__attribute((alias("_netplan_netdef_pertype_iter_free"))) NETPLAN_ABI void
_netplan_iter_defs_per_devtype_free(struct netdef_pertype_iter* it);

gboolean
has_openvswitch(const NetplanOVSSettings* ovs, NetplanBackend backend, GHashTable *ovs_ports)
{
    return (ovs_ports && g_hash_table_size(ovs_ports) > 0)
            || (ovs->external_ids && g_hash_table_size(ovs->external_ids) > 0)
            || (ovs->other_config && g_hash_table_size(ovs->other_config) > 0)
            || ovs->lacp
            || ovs->fail_mode
            || ovs->mcast_snooping
            || ovs->rstp
            || ovs->protocols
            || (ovs->ssl.ca_certificate || ovs->ssl.client_certificate || ovs->ssl.client_key)
            || (ovs->controller.connection_mode || ovs->controller.addresses)
            || backend == NETPLAN_BACKEND_OVS;
}

void
mark_data_as_dirty(NetplanParser* npp, const void* data_ptr)
{
    // We don't support dirty tracking for globals yet.
    if (!npp->current.netdef)
        return;
    if (!npp->current.netdef->_private)
        npp->current.netdef->_private = g_new0(struct private_netdef_data, 1);
    if (!npp->current.netdef->_private->dirty_fields)
        npp->current.netdef->_private->dirty_fields = g_hash_table_new(g_direct_hash, g_direct_equal);
    g_hash_table_insert(npp->current.netdef->_private->dirty_fields, (void*)data_ptr, (void*)data_ptr);
}

gboolean
complex_object_is_dirty(const NetplanNetDefinition* def, const void* obj, size_t obj_size) {
    const char* ptr = obj;
    if (def->_private == NULL || def->_private->dirty_fields == NULL)
        return FALSE;
    for (size_t i = 0; i < obj_size; ++i) {
        if (g_hash_table_contains(def->_private->dirty_fields, ptr+i))
            return TRUE;
    }
    return FALSE;
}

/**
 * Copy a NUL-terminated string into a sized buffer, and returns the size of
 * the copied string, including the final NUL character. If the buffer is too
 * small, returns NETPLAN_BUFFER_TOO_SMALL instead.
 *
 * In all cases the contents of the output buffer will be entirely overwritten,
 * except if the input string is NULL. Notably, if the buffer is too small its
 * content will NOT be NUL-terminated.
 *
 * @input: the input string
 * @out_buffer: a pointer to a buffer into which we want to copy the string
 * @out_size: the size of the output buffer
 */
ssize_t
netplan_copy_string(const char* input, char* out_buffer, size_t out_size)
{
    if (input == NULL)
        return 0; // LCOV_EXCL_LINE
    char* end = stpncpy(out_buffer, input, out_size);
    // If it point to the first byte past the buffer, we don't have enough
    // space in the buffer.
    size_t len = end - out_buffer;
    if (len == out_size)
        return NETPLAN_BUFFER_TOO_SMALL;
    return end - out_buffer + 1;
}

gboolean
netplan_netdef_match_interface(const NetplanNetDefinition* netdef, const char* name, const char* mac, const char* driver_name)
{
    if (!netdef->has_match)
        return !g_strcmp0(name, netdef->id);

    if (netdef->match.mac) {
        if (g_ascii_strcasecmp(netdef->match.mac, mac))
            return FALSE;
    }

    if (netdef->match.original_name) {
        if (!name || fnmatch(netdef->match.original_name, name, 0))
            return FALSE;
    }

    if (netdef->match.driver) {
        gboolean matches_driver = FALSE;
        char** tokens;
        if (!driver_name)
            return FALSE;
        tokens = g_strsplit(netdef->match.driver, "\t", -1);
        for (char** it = tokens; *it; it++) {
            if (fnmatch(*it, driver_name, 0) == 0) {
                matches_driver = TRUE;
                break;
            }
        }
        g_strfreev(tokens);
        return matches_driver;
    }

    return TRUE;
}

ssize_t
netplan_netdef_get_set_name(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buf_size)
{
    return netplan_copy_string(netdef->set_name, out_buffer, out_buf_size);
}

gboolean
is_multicast_address(const char* address)
{
    struct in_addr a4;
    struct in6_addr a6;

    if (inet_pton(AF_INET, address, &a4) > 0) {
        if (ntohl(a4.s_addr) >> 28 == 0b1110) /* 224.0.0.0/4 */
            return TRUE;
    } else if (inet_pton(AF_INET6, address, &a6) > 0) {
        if (a6.s6_addr[0] == 0xff) /* FF00::/8 */
            return TRUE;
    }

    return FALSE;
}

void
netplan_state_iterator_init(const NetplanState* np_state, NetplanStateIterator* iter)
{
    g_assert(iter);
    RealStateIter* _iter = (RealStateIter*) iter;
    _iter->next = g_list_first(np_state->netdefs_ordered);
}

NetplanNetDefinition*
netplan_state_iterator_next(NetplanStateIterator* iter)
{
    NetplanNetDefinition* netdef = NULL;
    RealStateIter* _iter = (RealStateIter*) iter;

    if (_iter && _iter->next) {
        netdef = _iter->next->data;
        _iter->next = g_list_next(_iter->next);
    }

    return netdef;
}

gboolean
netplan_state_iterator_has_next(const NetplanStateIterator* iter)
{
    RealStateIter* _iter = (RealStateIter*) iter;

    if (!_iter)
        return FALSE;
    return _iter->next != NULL;
}

static const char*
normalize_ip_address(const char* addr, const guint family)
{
    if (!g_strcmp0(addr, "default")) {
        if (family == AF_INET)
            return "0.0.0.0/0";
        else
            return "::/0";
    }

    return addr;
}
/*
 * Returns true if a route already exists in the netdef routes list.
 *
 * We consider a route a duplicate if it is in the same table, has the same metric,
 * src, to, via and family values.
 *
 * XXX: in the future we could add a route "key" to a hash set so this verification could
 * be done faster.
 */
gboolean
is_route_present(const NetplanNetDefinition* netdef, const NetplanIPRoute* route)
{
    const GArray* routes = netdef->routes;

    for (guint i = 0; i < routes->len; i++) {
        const NetplanIPRoute* entry = g_array_index(routes, NetplanIPRoute*, i);
        if (
                entry->family == route->family &&
                entry->table == route->table &&
                entry->metric == route->metric &&
                g_strcmp0(entry->from, route->from) == 0 &&
                g_strcmp0(normalize_ip_address(entry->to, entry->family),
                    normalize_ip_address(route->to, route->family)) == 0 &&
                g_strcmp0(entry->via, route->via) == 0
           )
            return TRUE;
    }

    return FALSE;
}
/*
 * Returns true if a policy rule already exists in the netdef rules list.
 */
gboolean
is_route_rule_present(const NetplanNetDefinition* netdef, const NetplanIPRule* rule)
{
    const GArray* rules = netdef->ip_rules;

    for (guint i = 0; i < rules->len; i++) {
        const NetplanIPRule* entry = g_array_index(rules, NetplanIPRule*, i);
        if (
                entry->family == rule->family &&
                g_strcmp0(entry->from, rule->from) == 0 &&
                g_strcmp0(entry->to, rule->to) == 0 &&
                entry->table == rule->table &&
                entry->priority == rule->priority &&
                entry->fwmark == rule->fwmark &&
                entry->tos == rule->tos
           )
            return TRUE;
    }

    return FALSE;
}

gboolean
is_string_in_array(GArray* array, const char* value)
{
    for (unsigned i = 0; i < array->len; ++i) {
        char* item = g_array_index(array, char*, i);
        if (!g_strcmp0(value, item)) {
            return TRUE;
        }
    }
    return FALSE;
}
