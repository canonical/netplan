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

static GOptionEntry options[] = {
    {"root-dir", 'r', 0, G_OPTION_ARG_FILENAME, &rootdir, "Search for and generate configuration files in this root directory instead of /", NULL},
    {G_OPTION_REMAINING, 0, 0, G_OPTION_ARG_FILENAME_ARRAY, &files, "Read configuration from this/these file(s) instead of /etc/netplan/*.yaml", "[config file ..]"},
    {"ignore-errors", 'i', 0, G_OPTION_ARG_NONE, &ignore_errors, "Ignores files and/or network definitions that fail parsing.", NULL},
    {"mapping", 0, 0, G_OPTION_ARG_STRING, &mapping_iface, "Only show the device to backend mapping for the specified interface.", NULL},
    {NULL}
};

// LCOV_EXCL_START
/* covered via 'cloud-init' integration test */
static gboolean
check_called_just_in_time()
{
    const gchar *argv[] = { "/bin/systemctl", "is-system-running", NULL };
    gchar *output = NULL;
    g_spawn_sync(NULL, (gchar**)argv, NULL, G_SPAWN_STDERR_TO_DEV_NULL, NULL, NULL, &output, NULL, NULL, NULL);
    if (output != NULL && strstr(output, "initializing") != NULL) {
        g_free(output);
        const gchar *argv2[] = { "/bin/systemctl", "is-active", "network.target", NULL };
        gint exit_code = 0;
        g_spawn_sync(NULL, (gchar**)argv2, NULL, G_SPAWN_STDERR_TO_DEV_NULL, NULL, NULL, NULL, NULL, &exit_code, NULL);
        /* return TRUE, if network.target is not yet active */
        #if GLIB_CHECK_VERSION (2, 70, 0)
        return !g_spawn_check_wait_status(exit_code, NULL);
        #else
        return !g_spawn_check_exit_status(exit_code, NULL);
        #endif
    }
    g_free(output);
    return FALSE;
};

static void
start_unit_jit(gchar *unit)
{
    const gchar *argv[] = { "/bin/systemctl", "start", "--no-block", "--no-ask-password", unit, NULL };
    g_spawn_sync(NULL, (gchar**)argv, NULL, G_SPAWN_DEFAULT, NULL, NULL, NULL, NULL, NULL, NULL);
};
// LCOV_EXCL_STOP

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
    g_autofree char* generator_run_stamp = NULL;
    g_autofree char* netplan_try_stamp = NULL;
    glob_t gl;
    int error_code = 0;
    char* ignore_errors_env = NULL;
    NetplanParser* npp = NULL;
    NetplanState* np_state = NULL;

    /* Parse CLI options */
    opt_context = g_option_context_new(NULL);
    g_option_context_set_summary(opt_context, "Generate backend network configuration from netplan YAML definition.");
    g_option_context_set_description(opt_context,
                                     "This program reads the specified netplan YAML definition file(s)\n"
                                     "or, if none are given, /etc/netplan/*.yaml.\n"
                                     "It then generates the corresponding systemd-networkd, NetworkManager,\n"
                                     "and udev configuration files in /run.");
    g_option_context_add_main_entries(opt_context, options, NULL);

    if (!g_option_context_parse(opt_context, &argc, &argv, &error)) {
        fprintf(stderr, "failed to parse options: %s\n", error->message);
        return 1;
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
        }
        // LCOV_EXCL_STOP
    }

    npp = netplan_parser_new();
    // TODO: NETPLAN_PARSER_IGNORE_ERRORS=1 needs to be set from the netplan-configure.service
    if (ignore_errors)
        netplan_parser_set_flags(npp, NETPLAN_PARSER_IGNORE_ERRORS, &error);

    /* Read all input files */
    if (files) {
        for (gchar** f = files; f && *f; ++f) {
            CHECK_CALL(netplan_parser_load_yaml(npp, *f, &error), ignore_errors);
        }
    } else
        CHECK_CALL(netplan_parser_load_yaml_hierarchy(npp, rootdir, &error), ignore_errors);

    np_state = netplan_state_new();
    CHECK_CALL(netplan_state_import_parser_results(np_state, npp, &error), ignore_errors);

    if (mapping_iface) {
        if (np_state->netdefs)
            error_code = find_interface(mapping_iface, np_state->netdefs);
        else
            error_code = 1;

        goto cleanup;
    }

    /* Clean up generated config from previous runs */
    _netplan_networkd_cleanup(rootdir);
    _netplan_nm_cleanup(rootdir);
    _netplan_ovs_cleanup(rootdir);
    _netplan_sriov_cleanup(rootdir);

    /* Generate backend specific configuration files from merged data. */
    CHECK_CALL(netplan_state_finish_ovs_write(np_state, rootdir, &error), ignore_errors); // OVS cleanup unit is always written
    if (np_state->netdefs) {
        g_debug("Generating output files..");
        for (GList* iterator = np_state->netdefs_ordered; iterator; iterator = iterator->next) {
            NetplanNetDefinition* def = (NetplanNetDefinition*) iterator->data;
            gboolean has_been_written = FALSE;
            CHECK_CALL(_netplan_netdef_write_networkd(np_state, def, rootdir, &has_been_written, &error), ignore_errors);
            any_networkd = any_networkd || has_been_written;

            CHECK_CALL(_netplan_netdef_write_ovs(np_state, def, rootdir, &has_been_written, &error), ignore_errors);
            CHECK_CALL(_netplan_netdef_write_nm(np_state, def, rootdir, &has_been_written, &error), ignore_errors);
            any_nm = any_nm || has_been_written;
        }

        CHECK_CALL(netplan_state_finish_nm_write(np_state, rootdir, &error), ignore_errors);
        CHECK_CALL(netplan_state_finish_sriov_write(np_state, rootdir, &error), ignore_errors);
    }

    /* Disable /usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf
     * (which restricts NM to wifi and wwan) if "renderer: NetworkManager" is used anywhere */
    if (netplan_state_get_backend(np_state) == NETPLAN_BACKEND_NM || any_nm)
        _netplan_g_string_free_to_file(g_string_new(NULL), rootdir, "/run/NetworkManager/conf.d/10-globally-managed-devices.conf", NULL);

    gboolean enable_wait_online = FALSE;
    // FIXME: how to transfer state from the generator?
    if (any_networkd)
        enable_wait_online = _netplan_networkd_write_wait_online(np_state, rootdir);

    if (check_called_just_in_time()) {
        /* netplan-feature: generate-just-in-time */
        /* When booting with cloud-init, network configuration
         * might be provided just-in-time. Specifically after
         * system-generators were executed, but before
         * network.target is started. In such case, auxiliary
         * units that netplan enables have not been included in
         * the initial boot transaction. Detect such scenario and
         * add all netplan units to the initial boot transaction.
         */
        // LCOV_EXCL_START
        /* covered via 'cloud-init' integration test */
        if (any_networkd) {
            start_unit_jit("systemd-networkd.socket");
            if (enable_wait_online)
                start_unit_jit("systemd-networkd-wait-online.service");
            start_unit_jit("systemd-networkd.service");
        }
        g_autofree char* glob_run = g_build_path(G_DIR_SEPARATOR_S,
                                                 rootdir != NULL ? rootdir : G_DIR_SEPARATOR_S,
                                                 "run", "systemd", "system", "netplan-*.service",
                                                 NULL);
        if (!glob(glob_run, 0, NULL, &gl)) {
            for (size_t i = 0; i < gl.gl_pathc; ++i) {
                gchar *unit_name = g_path_get_basename(gl.gl_pathv[i]);
                start_unit_jit(unit_name);
                g_free(unit_name);
            }
        }
        // LCOV_EXCL_STOP
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
