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

#include <glib.h>
#include <glib/gprintf.h>

#include "util.h"
#include "parse.h"

GHashTable* wifi_frequency_24;
GHashTable* wifi_frequency_5;

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
    full_path = g_build_path(G_DIR_SEPARATOR_S, rootdir ?: "", path_suffix, NULL);
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
    g_spawn_check_exit_status(exit_status, &err);
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
    g_autofree gchar* filename = NULL;
    g_autofree gchar* del = NULL;
    g_autoptr(GError) error = NULL;
    NetplanNetDefinition* nd = NULL;

    /* parse all YAML files */
    if (!process_yaml_hierarchy(rootdir))
        return FALSE; // LCOV_EXCL_LINE

    netdefs = netplan_finish_parse(&error);
    if (!netdefs) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "netplan_delete_connection: %s\n", error->message);
        return FALSE;
        // LCOV_EXCL_STOP
    }

    /* find filename for specified netdef ID */
    nd = g_hash_table_lookup(netdefs, id);
    if (!nd) {
        g_warning("netplan_delete_connection: Cannot delete %s, does not exist.", id);
        return FALSE;
    }

    filename = g_path_get_basename(nd->filename);
    filename[strlen(filename) - 5] = '\0'; //stip ".yaml" suffix
    del = g_strdup_printf("network.%s.%s=NULL", netplan_def_type_to_str[nd->type], id);
    netplan_clear_netdefs();

    /* TODO: refactor logic to actually be inside the library instead of spawning another process */
    const gchar *argv[] = { "/sbin/netplan", "set", del, "--origin-hint" , filename, NULL, NULL, NULL };
    if (rootdir) {
        argv[5] = "--root-dir";
        argv[6] = rootdir;
    }
    if (getenv("TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("TEST_NETPLAN_CMD");
    return g_spawn_sync(NULL, (gchar**)argv, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL);
}

gboolean
netplan_generate(const char* rootdir)
{
    /* TODO: refactor logic to actually be inside the library instead of spawning another process */
    const gchar *argv[] = { "/sbin/netplan", "generate", NULL , NULL, NULL };
    if (rootdir) {
        argv[2] = "--root-dir";
        argv[3] = rootdir;
    }
    if (getenv("TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("TEST_NETPLAN_CMD");
    return g_spawn_sync(NULL, (gchar**)argv, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL);
}
