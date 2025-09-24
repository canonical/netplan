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

/* Public API (from include/) */
#include "netplan.h"
#include "parse.h"
#include "util.h"

/* Netplan internal (from src/) */
#include "names.h"
#include "networkd.h"
#include "nm.h"
#include "openvswitch.h"
#include "sriov.h"
#include "util-internal.h"

static gchar* rootdir;
static gchar** files;
static gboolean any_networkd = FALSE;
static gboolean any_nm = FALSE;
static gchar* mapping_iface;
static gboolean ignore_errors = FALSE;
static gboolean no_ignore_errors = FALSE;

static GOptionEntry options[] = {
    {"root-dir", 'r', 0, G_OPTION_ARG_FILENAME, &rootdir, "Search for and generate configuration files in this root directory instead of /", NULL},
    {G_OPTION_REMAINING, 0, 0, G_OPTION_ARG_FILENAME_ARRAY, &files, "Read configuration from this/these file(s) instead of /etc/netplan/*.yaml", "[config file ..]"},
    {"ignore-errors", 'i', 0, G_OPTION_ARG_NONE, &ignore_errors, "Ignores files and/or network definitions that fail parsing.", NULL},
    {"mapping", 0, 0, G_OPTION_ARG_STRING, &mapping_iface, "Only show the device to backend mapping for the specified interface.", NULL},
    {NULL}
};

/**
 * Create enablement symlink for systemd-networkd.service.
 */
static void
enable_networkd(const char* generator_dir, gboolean enable_wait_online)
{
    g_assert(generator_dir != NULL);
    g_autofree char* link = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "multi-user.target.wants", "systemd-networkd.service", NULL);
    g_debug("We created networkd configuration, adding %s enablement symlink", link);
    _netplan_safe_mkdir_p_dir(link);
    if (symlink("/usr/lib/systemd/system/systemd-networkd.service", link) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to create enablement symlink: %m\n");
        exit(1);
        // LCOV_EXCL_STOP
    }

    if (enable_wait_online) {
        g_autofree char* link2 = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "network-online.target.wants", "systemd-networkd-wait-online.service", NULL);
        _netplan_safe_mkdir_p_dir(link2);
        if (symlink("/usr/lib/systemd/system/systemd-networkd-wait-online.service", link2) < 0 && errno != EEXIST) {
            // LCOV_EXCL_START
            g_fprintf(stderr, "failed to create enablement symlink: %m\n");
            exit(1);
            // LCOV_EXCL_STOP
        }
    }
}

/**
 * XXX: consider moving this to configure.c (outside of the sd-generator), or
 * drop it with the next major release. It's only used for legacy reasons. The
 * 'netplan status' command should be used instead. See also the comment in
 * main() below.
 */
static int
find_interface(gchar* interface, GHashTable* netdefs)
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
        /* testing for driver matching is done via autopkgtest */
        // LCOV_EXCL_START
        driver = g_path_get_basename (g_file_info_get_symlink_target (info));
        g_object_unref (info);
        // LCOV_EXCL_STOP
    }
    g_object_unref (driver_file);
    g_free (driver_path);

    g_hash_table_iter_init (&iter, netdefs);
    while (g_hash_table_iter_next (&iter, &key, &value)) {
        NetplanNetDefinition *nd = (NetplanNetDefinition *) value;
        if (!g_strcmp0(nd->set_name, interface))
            g_ptr_array_add (found, (gpointer) nd);
        else if (!g_strcmp0(nd->id, interface))
            g_ptr_array_add (found, (gpointer) nd);
        else if (!g_strcmp0(nd->match.original_name, interface))
            g_ptr_array_add (found, (gpointer) nd);
    }
    if (found->len == 0 && driver != NULL) {
        /* testing for driver matching is done via autopkgtest */
        // LCOV_EXCL_START
        g_hash_table_iter_init (&iter, netdefs);
        while (g_hash_table_iter_next (&iter, &key, &value)) {
            NetplanNetDefinition *nd = (NetplanNetDefinition *) value;
            if (!g_strcmp0(nd->match.driver, driver))
                g_ptr_array_add (found, (gpointer) nd);
        }
        // LCOV_EXCL_STOP
    }

    if (driver)
        g_free (driver); // LCOV_EXCL_LINE

    if (found->len != 1) {
        goto exit_find;
    }
    else {
         const NetplanNetDefinition *nd = (NetplanNetDefinition *)g_ptr_array_index (found, 0);
         g_printf("id=%s, backend=%s, set_name=%s, match_name=%s, match_mac=%s, match_driver=%s\n",
             nd->id,
             netplan_backend_name(nd->backend),
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

#define CHECK_CALL(call, ignore_errors) {\
    if (!call && !ignore_errors) {\
        error_code = 1; \
        fprintf(stderr, "%s\n", error->message); \
        goto cleanup;\
    } else if (error && ignore_errors) {\
        fprintf(stderr, "Ignored: %s\n", error->message); \
        g_clear_error(&error); \
    }\
}

int main(int argc, char** argv)
{
    NetplanError* error = NULL;
    GOptionContext* opt_context;
    /* are we being called as systemd generator? */
    gboolean called_as_generator = (strstr(argv[0], "systemd/system-generators/") != NULL);
    g_autofree char* generator_run_stamp = NULL;
    g_autofree char* netplan_try_stamp = NULL;
    int error_code = 0;
    char* ignore_errors_env = NULL;
    NetplanParser* npp = NULL;
    NetplanState* np_state = NULL;
    const char* generator_normal_dir = NULL;
    const char* generator_late_dir = NULL;

    /* Parse CLI options */
    opt_context = g_option_context_new(NULL);
    if (called_as_generator) {
        g_option_context_set_help_enabled(opt_context, FALSE);
    }
    g_option_context_set_summary(opt_context, "Generate backend network configuration from netplan YAML definition.");
    g_option_context_set_description(opt_context,
                                     "This program reads netplan YAML definition file(s)\n"
                                     "from /etc/netplan/*.yaml.\n"
                                     "It then generates the corresponding systemd service-units\n"
                                     "in /run/systemd/generator[.late].");
    g_option_context_add_main_entries(opt_context, options, NULL);

    if (!g_option_context_parse(opt_context, &argc, &argv, &error)) {
        fprintf(stderr, "failed to parse options: %s\n", error->message);
        return 1;
    }

    if (called_as_generator) {
        if (files == NULL || g_strv_length(files) != 3 || files[0] == NULL) {
            g_fprintf(stderr, "%s can not be called directly, use 'netplan generate'.", argv[0]);
            return 1;
        }
        generator_normal_dir = files[0];
        generator_late_dir = files[2];
    }

    // The file at netplan_try_stamp is created while `netplan try` is waiting
    // for user confirmation. If generate is triggered while netplan try is
    // running, we shouldn't regenerate the configuration.
    // We can be called by either systemd (as a generator during daemon-reload)
    // or by NetworkManager when it is reloading configuration (Ubuntu >23.10),
    // see https://netplan.readthedocs.io/en/stable/netplan-everywhere/.
    // LP #2083029
    netplan_try_stamp = g_build_path(G_DIR_SEPARATOR_S,
                                     rootdir != NULL ? rootdir : G_DIR_SEPARATOR_S,
                                     "run", "netplan", "netplan-try.ready",
                                     NULL);
    if (g_access(netplan_try_stamp, F_OK) == 0) {
        g_fprintf(stderr, "'netplan try' is restoring configuration, remove %s to force re-run.\n", netplan_try_stamp);
        return 1;
    }

    if ((ignore_errors_env = getenv("NETPLAN_PARSER_IGNORE_ERRORS"))) {
        // This is used mostly by autopkgtests
        // LCOV_EXCL_START
        if (!g_strcmp0(ignore_errors_env, "1")) {
            g_debug("NETPLAN_PARSER_IGNORE_ERRORS=1 environment variable exists, setting ignore_errors flags");
            ignore_errors = TRUE;
        } else if (!g_strcmp0(ignore_errors_env, "0")) {
            g_debug("NETPLAN_PARSER_IGNORE_ERRORS=0 environment variable exists, unsetting ignore_errors flags");
            ignore_errors = FALSE;
            no_ignore_errors = TRUE;
        }
        // LCOV_EXCL_STOP
    }

    npp = netplan_parser_new();
    if ((ignore_errors || called_as_generator) && !no_ignore_errors)
        netplan_parser_set_flags(npp, NETPLAN_PARSER_IGNORE_ERRORS, &error);

    /* Read all input files */
    CHECK_CALL(netplan_parser_load_yaml_hierarchy(npp, rootdir, &error), ignore_errors);

    np_state = netplan_state_new();
    CHECK_CALL(netplan_state_import_parser_results(np_state, npp, &error), ignore_errors);

    // XXX: Remove this code path, it's only still supported for legacy reasons
    // and not supposed to be called in the scope of a systemd generator. The
    // 'netplan status' command should be used instead. Should it be moved to
    // the 'configure' binary to keep legacy functionality around?
    if (mapping_iface) {
        if (np_state->netdefs)
            error_code = find_interface(mapping_iface, np_state->netdefs);
        else
            error_code = 1;

        goto cleanup;
    }

    /* Generate specific systemd units from merged data. */
    // network-configurator late-stage validation
    CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
    CHECK_CALL(netplan_state_finish_ovs_write(np_state, NULL, &error), ignore_errors);
    CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);

    CHECK_CALL(_netplan_state_finish_ovs_generate(np_state, generator_late_dir, &error), ignore_errors); // OVS cleanup unit is always written
    if (np_state->netdefs) {
        g_debug("Generating output files..");
        for (GList* iterator = np_state->netdefs_ordered; iterator; iterator = iterator->next) {
            NetplanNetDefinition* def = (NetplanNetDefinition*) iterator->data;
            gboolean has_been_written = FALSE;

            // network-configurator late-stage validation
            CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
            CHECK_CALL(_netplan_netdef_write_networkd(np_state, def, NULL, &has_been_written, &error), ignore_errors);
            CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);
            any_networkd = any_networkd || has_been_written;

            CHECK_CALL(_netplan_netdef_generate_networkd(np_state, def, generator_late_dir, &has_been_written, &error), ignore_errors);
            any_networkd = any_networkd || has_been_written;

            // network-configurator late-stage validation
            CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
            CHECK_CALL(_netplan_netdef_write_ovs(np_state, def, NULL, &has_been_written, &error), ignore_errors);
            CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);

            CHECK_CALL(_netplan_netdef_generate_ovs(np_state, def, generator_late_dir, &has_been_written, &error), ignore_errors);
            any_nm = any_nm || has_been_written;

            // network-configurator late-stage validation
            CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
            CHECK_CALL(_netplan_netdef_write_nm(np_state, def, NULL, &has_been_written, &error), ignore_errors);
            CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);
            //We don't have any _netplan_netdef_generate_nm() function for sd-generator late-stage validation
        }

        // network-configurator late-stage validation
        CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
        CHECK_CALL(netplan_state_finish_nm_write(np_state, NULL, &error), ignore_errors);
        CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);
        //We don't have any _netplan_state_finish_nm_generate() function for sd-generator late-stage validation

        // network-configurator late-stage validation
        CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
        CHECK_CALL(netplan_state_finish_sriov_write(np_state, NULL, &error), ignore_errors);
        CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);

        CHECK_CALL(_netplan_state_finish_sriov_generate(np_state, generator_late_dir, &error), ignore_errors);
    }

    gboolean enable_wait_online = FALSE;
    if (any_networkd)
        enable_wait_online = _netplan_networkd_generate_wait_online(np_state, rootdir, generator_late_dir);

    if (called_as_generator) {
        /* Ensure networkd starts if we have any configuration for it */
        if (any_networkd) {
            enable_networkd(generator_normal_dir, enable_wait_online);
        }
    } else {
        // This generator should not be called directly, use 'netplan generate'
        // The only exception is the deprecated "--mapping" option, which will
        // jump into "cleanup" directly. Once we drop support for "--mapping",
        // the "called_as_generator" check and related code can be removed,
        // making this binary run as a pure systemd generator.
        g_assert(FALSE); // LCOV_EXCL_LINE
    }

cleanup:
    g_option_context_free(opt_context);
    if (error)
        g_error_free(error);
    if (npp)
        netplan_parser_clear(&npp);
    if (np_state)
        netplan_state_clear(&np_state);
    return error_code;
}
