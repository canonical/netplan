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
#include <errno.h>
#include <string.h>

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
    g_autofree char* rglob = g_strjoin(NULL, rootdir ?: "", G_DIR_SEPARATOR_S, "{lib,etc,run}/netplan/*.yaml", NULL);
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

    yaml_parser_initialize(&parser);
    yaml_parser_set_input_string(&parser, (const unsigned char *)obj_payload, strlen(obj_payload));
    while (TRUE) {
        if (!yaml_parser_parse(&parser, &event)) {
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "Error parsing YAML: %s", parser.problem);
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
    g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "Error generating YAML: %s", emitter.problem);
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
    g_set_error(error, G_FILE_ERROR, errno, "Error when opening FD %d: %s", output_fd, g_strerror(errno));
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
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "Error parsing YAML: %s", parser->problem);
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
            g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "Error emitting YAML: %s", emitter->problem);
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
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "Unexpected YAML structure found");
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
    g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "Error parsing YAML: %s", parser->problem);
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
        g_set_error(error, G_FILE_ERROR, errno, "%s", g_strerror(errno));
        ret = FALSE;
        goto cleanup;
// LCOV_EXCL_START
parser_err_path:
    g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "Error parsing YAML: %s", parser.problem);
    ret = FALSE;
    goto cleanup;
err_path:
    g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT, "Error generating YAML: %s", emitter.problem);
    ret = FALSE;
// LCOV_EXCL_STOP
cleanup:
    if (input)
        fclose(input);
    if (output)
        fclose(output);
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

    gchar *argv[] = {"bin" "/" "systemd-escape", string, NULL};
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
    g_autofree gchar* del = NULL;
    g_autoptr(GError) error = NULL;
    NetplanNetDefinition* nd = NULL;
    gboolean ret = TRUE;

    NetplanState* np_state = netplan_state_new();
    NetplanParser* npp = netplan_parser_new();

    /* parse all YAML files */
    if (   !netplan_parser_load_yaml_hierarchy(npp, rootdir, &error)
        || !netplan_state_import_parser_results(np_state, npp, &error)) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "%s\n", error->message);
        ret = FALSE;
        goto cleanup;
        // LCOV_EXCL_STOP
    }

    if (!np_state->netdefs) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "netplan_delete_connection: %s\n", error->message);
        ret = FALSE;
        goto cleanup;
        // LCOV_EXCL_STOP
    }

    /* find filename for specified netdef ID */
    nd = g_hash_table_lookup(np_state->netdefs, id);
    if (!nd) {
        g_warning("netplan_delete_connection: Cannot delete %s, does not exist.", id);
        ret = FALSE;
        goto cleanup;
    }

    del = g_strdup_printf("network.%s.%s=NULL", netplan_def_type_name(nd->type), id);

    /* TODO: refactor logic to actually be inside the library instead of spawning another process */
    const gchar *argv[] = { SBINDIR "/" "netplan", "set", del, NULL, NULL, NULL };
    if (rootdir) {
        argv[3] = "--root-dir";
        argv[4] = rootdir;
    }
    if (getenv("TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("TEST_NETPLAN_CMD");
    ret = g_spawn_sync(NULL, (gchar**)argv, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL);

cleanup:
    if (npp) netplan_parser_clear(&npp);
    if (np_state) netplan_state_clear(&np_state);
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
gchar*
netplan_get_id_from_nm_filename(const char* filename, const char* ssid)
{
    g_autofree gchar* escaped_ssid = NULL;
    g_autofree gchar* suffix = NULL;
    const char* nm_prefix = "/run/NetworkManager/system-connections/netplan-";
    const char* pos = g_strrstr(filename, nm_prefix);
    const char* start = NULL;
    const char* end = NULL;
    gsize id_len = 0;

    if (!pos)
        return NULL;

    if (ssid) {
        escaped_ssid = g_uri_escape_string(ssid, NULL, TRUE);
        suffix = g_strdup_printf("-%s.nmconnection", escaped_ssid);
        end = g_strrstr(filename, suffix);
    } else
        end = g_strrstr(filename, ".nmconnection");

    if (!end)
        return NULL;

    /* Move pointer to start of netplan ID inside filename string */
    start = pos + strlen(nm_prefix);
    id_len = end - start;
    return g_strndup(start, id_len);
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
        if (!netplan_parser_load_yaml(npp, g_hash_table_lookup(configs, i->data), error))
            return FALSE;
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
mark_data_as_dirty(NetplanParser* npp, void* data_ptr)
{
    // We don't support dirty tracking for globals yet.
    if (!npp->current.netdef)
        return;
    if (!npp->current.netdef->_private)
        npp->current.netdef->_private = g_new0(struct private_netdef_data, 1);
    if (!npp->current.netdef->_private->dirty_fields)
        npp->current.netdef->_private->dirty_fields = g_hash_table_new(g_direct_hash, g_direct_equal);
    g_hash_table_insert(npp->current.netdef->_private->dirty_fields, data_ptr, data_ptr);
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
    if (end - out_buffer == out_size)
        return NETPLAN_BUFFER_TOO_SMALL;
    return end - out_buffer + 1;
}
