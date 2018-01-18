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
#include <string.h>
#include <glob.h>
#include <unistd.h>
#include <errno.h>

#include <glib.h>
#include <glib/gstdio.h>
#include <glib-object.h>
#include <gio/gio.h>

#include "util.h"
#include "parse.h"
#include "networkd.h"
#include "nm.h"

static gchar* rootdir;
static gchar** files;
static gboolean any_networkd;
static gchar* mapping_iface;

static GOptionEntry options[] = {
    {"root-dir", 'r', 0, G_OPTION_ARG_FILENAME, &rootdir, "Search for and generate configuration files in this root directory instead of /"},
    {G_OPTION_REMAINING, 0, 0, G_OPTION_ARG_FILENAME_ARRAY, &files, "Read configuration from this/these file(s) instead of /etc/netplan/*.yaml", "[config file ..]"},
    {"mapping", 0, 0, G_OPTION_ARG_STRING, &mapping_iface, "Only show the device to backend mapping for the specified interface."},
    {NULL}
};

static void
reload_udevd(void)
{
    const gchar *argv[] = { "/sbin/udevadm", "control", "--reload", NULL };
    g_spawn_sync(NULL, (gchar**)argv, NULL, G_SPAWN_STDERR_TO_DEV_NULL, NULL, NULL, NULL, NULL, NULL, NULL);
};

static void
nd_iterator(gpointer key, gpointer value, gpointer user_data)
{
    if (write_networkd_conf((net_definition*) value, (const char*) user_data))
        any_networkd = TRUE;
    write_nm_conf((net_definition*) value, (const char*) user_data);
}


static int
find_interface(gchar* interface)
{
    GPtrArray *found;
    GFileInfo *info;
    GFile *driver_file;
    gchar *driver_path;
    gchar *driver = NULL;
    gpointer key, value;
    GHashTableIter iter;
    int ret = EXIT_FAILURE;

    found = g_ptr_array_new ();

    /* Try to get the driver name for the interface... */
    driver_path = g_strdup_printf("/sys/class/net/%s/device/driver", interface);
    driver_file = g_file_new_for_path (driver_path);
    info = g_file_query_info (driver_file,
                              G_FILE_ATTRIBUTE_STANDARD_SYMLINK_TARGET,
                              0, NULL, NULL);
    if (info != NULL) {
        driver = g_path_get_basename (g_file_info_get_symlink_target (info));
        g_object_unref (info);
    }
    g_object_unref (driver_file);
    g_free (driver_path);

    g_hash_table_iter_init (&iter, netdefs);
    while (g_hash_table_iter_next (&iter, &key, &value)) {
        net_definition *nd = (net_definition *) value;
        if (!g_strcmp0(nd->set_name, interface))
            g_ptr_array_add (found, (gpointer) nd);
        else if (!g_strcmp0(nd->id, interface))
            g_ptr_array_add (found, (gpointer) nd);
        else if (!g_strcmp0(nd->match.original_name, interface))
            g_ptr_array_add (found, (gpointer) nd);
    }
    if (found->len == 0 && driver != NULL) {
        g_hash_table_iter_init (&iter, netdefs);
        while (g_hash_table_iter_next (&iter, &key, &value)) {
            net_definition *nd = (net_definition *) value;
            if (!g_strcmp0(nd->match.driver, driver))
                g_ptr_array_add (found, (gpointer) nd);
        }
    }

    if (driver)
        g_free (driver);

    if (found->len != 1) {
        goto exit_find;
    }
    else {
         net_definition *nd = (net_definition *)g_ptr_array_index (found, 0);
         g_printf("id=%s, backend=%s, set_name=%s, match_name=%s, match_mac=%s, match_driver=%s\n",
             nd->id,
             netdef_backend_to_name[nd->backend],
             nd->set_name,
             nd->match.original_name,
             nd->match.mac,
             nd->match.driver);
    }

    ret = EXIT_SUCCESS;

exit_find:
    g_ptr_array_free (found, TRUE);
    return ret;
}

static void
process_input_file(const char* f)
{
    GError* error = NULL;

    g_debug("Processing input file %s..", f);
    if (!parse_yaml(f, &error)) {
        g_fprintf(stderr, "%s\n", error->message);
        exit(1);
    }
}

int main(int argc, char** argv)
{
    GError* error = NULL;
    GOptionContext* opt_context;
    /* are we being called as systemd generator? */
    gboolean called_as_generator = (strstr(argv[0], "systemd/system-generators/") != NULL);
    g_autofree char* generator_run_stamp = NULL;

    /* Parse CLI options */
    opt_context = g_option_context_new(NULL);
    if (called_as_generator)
        g_option_context_set_help_enabled(opt_context, FALSE);
    g_option_context_set_summary(opt_context, "Generate backend network configuration from netplan YAML definition.");
    g_option_context_set_description(opt_context,
                                     "This program reads the specified netplan YAML definition file(s)\n"
                                     "or, if none are given, /etc/netplan/*.yaml.\n"
                                     "It then generates the corresponding systemd-networkd, NetworkManager,\n"
                                     "and udev configuration files in /run.");
    g_option_context_add_main_entries(opt_context, options, NULL);

    if (!g_option_context_parse(opt_context, &argc, &argv, &error)) {
        g_fprintf(stderr, "failed to parse options: %s\n", error->message);
        return 1;
    }

    if (called_as_generator) {
        if (files == NULL || g_strv_length(files) != 3 || files[0] == NULL) {
            g_fprintf(stderr, "%s can not be called directly, use 'netplan generate'.", argv[0]);
            return 1;
        }
        generator_run_stamp = g_build_path(G_DIR_SEPARATOR_S, files[0], "netplan.stamp", NULL);
        if (g_access(generator_run_stamp, F_OK) == 0) {
            g_fprintf(stderr, "netplan generate already ran, remove %s to force re-run\n", generator_run_stamp);
            return 0;
        }
    }

    /* Read all input files */
    if (files && !called_as_generator) {
        for (gchar** f = files; f && *f; ++f)
            process_input_file(*f);
    } else {
        /* Files with asciibetically higher names override/append settings from
         * earlier ones (in all config dirs); files in /run/netplan/
         * shadow files in /etc/netplan/ which shadow files in /lib/netplan/.
         * To do that, we put all found files in a hash table, then sort it by
         * file name, and add the entries from /run after the ones from /etc
         * and those after the ones from /lib. */
        g_autofree char* glob_etc = g_strjoin(NULL, rootdir ?: "", G_DIR_SEPARATOR_S, "/etc/netplan/*.yaml", NULL);
        g_autofree char* glob_run = g_strjoin(NULL, rootdir ?: "", G_DIR_SEPARATOR_S, "/run/netplan/*.yaml", NULL);
        g_autofree char* glob_lib = g_strjoin(NULL, rootdir ?: "", G_DIR_SEPARATOR_S, "/lib/netplan/*.yaml", NULL);
        glob_t gl;
        int rc;
        /* keys are strdup()ed, free them; values point into the glob_t, don't free them */
        g_autoptr(GHashTable) configs = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
        g_autoptr(GList) config_keys = NULL;

        rc = glob(glob_lib, 0, NULL, &gl);
        if (rc != 0 && rc != GLOB_NOMATCH) {
            g_fprintf(stderr, "failed to glob for %s: %m\n", glob_lib); /* LCOV_EXCL_LINE */
            return 1; /* LCOV_EXCL_LINE */
        }

        rc = glob(glob_etc, GLOB_APPEND, NULL, &gl);
        if (rc != 0 && rc != GLOB_NOMATCH) {
            g_fprintf(stderr, "failed to glob for %s: %m\n", glob_etc); /* LCOV_EXCL_LINE */
            return 1; /* LCOV_EXCL_LINE */
        }

        rc = glob(glob_run, GLOB_APPEND, NULL, &gl);
        if (rc != 0 && rc != GLOB_NOMATCH) {
            g_fprintf(stderr, "failed to glob for %s: %m\n", glob_run); /* LCOV_EXCL_LINE */
            return 1; /* LCOV_EXCL_LINE */
        }

        for (size_t i = 0; i < gl.gl_pathc; ++i)
            g_hash_table_insert(configs, g_path_get_basename(gl.gl_pathv[i]), gl.gl_pathv[i]);

        config_keys = g_list_sort(g_hash_table_get_keys(configs), (GCompareFunc) strcmp);

        for (GList* i = config_keys; i != NULL; i = i->next)
            process_input_file(g_hash_table_lookup(configs, i->data));
    }

    g_assert(finish_parse(&error));

    /* Clean up generated config from previous runs */
    cleanup_networkd_conf(rootdir);
    cleanup_nm_conf(rootdir);

    if (mapping_iface && netdefs) {
        return find_interface(mapping_iface);
    }

    /* Generate backend specific configuration files from merged data. */
    if (netdefs) {
        g_debug("Generating output files..");
        g_hash_table_foreach(netdefs, nd_iterator, rootdir);
        write_nm_conf_finish(rootdir);
	/* We may have written .rules & .link files, thus we must
	 * invalidate udevd cache of its config as by default it only
	 * invalidates cache at most every 3 seconds. Not sure if this
	 * should live in `generate' or `apply', but it is confusing
	 * when udevd ignores just-in-time created rules files.
	 */
	reload_udevd();
    }

    /* Disable /usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf
     * (which restricts NM to wifi and wwan) if global renderer is NM */
    if (get_global_backend() == BACKEND_NM)
        g_string_free_to_file(g_string_new(NULL), rootdir, "/run/NetworkManager/conf.d/10-globally-managed-devices.conf", NULL);

    if (called_as_generator) {
        /* Ensure networkd starts if we have any configuration for it */
        if (any_networkd)
            enable_networkd(files[0]);

        /* Leave a stamp file so that we don't regenerate the configuration
         * multiple times and userspace can wait for it to finish */
        FILE* f = fopen(generator_run_stamp, "w");
        g_assert(f != NULL);
        fclose(f);
    }

    return 0;
}
