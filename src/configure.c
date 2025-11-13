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
static gboolean nm_only = FALSE;
static gboolean ignore_errors = FALSE;

static GOptionEntry options[] = {
    {"root-dir", 'r', 0, G_OPTION_ARG_FILENAME, &rootdir, "Search for and generate configuration files in this root directory instead of /", NULL},
    {G_OPTION_REMAINING, 0, 0, G_OPTION_ARG_FILENAME_ARRAY, &files, "Read configuration from this/these file(s) instead of /etc/netplan/*.yaml", "[config file ..]"},
    {"ignore-errors", 'i', 0, G_OPTION_ARG_NONE, &ignore_errors, "Ignores files and/or network definitions that fail parsing.", NULL},
    {"networkmanager-only", 'N', 0, G_OPTION_ARG_NONE, &nm_only, "Write only NetworkManager configuration.", NULL},
    {NULL}
};

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
        } else if (!g_strcmp0(ignore_errors_env, "0")) {
            g_debug("NETPLAN_PARSER_IGNORE_ERRORS=0 environment variable exists, unsetting ignore_errors flags");
            ignore_errors = FALSE;
        }
        // LCOV_EXCL_STOP
    }

    npp = netplan_parser_new();
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

    /* Clean up generated config from previous runs */
    if (!nm_only) _netplan_networkd_cleanup(rootdir);
    _netplan_nm_cleanup(rootdir);
    if (!nm_only) _netplan_ovs_cleanup(rootdir);
    if (!nm_only) _netplan_sriov_cleanup(rootdir);

    /* Generate backend specific configuration files from merged data. */
    // sd-generator late-stage validation
    if (!nm_only) {
        CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
        CHECK_CALL(_netplan_state_finish_ovs_generate(np_state, "", &error), ignore_errors);
        CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);
    }
    if (!nm_only) CHECK_CALL(netplan_state_finish_ovs_write(np_state, rootdir, &error), ignore_errors); // OVS cleanup unit is always written
    if (np_state->netdefs) {
        g_debug("Generating output files..");
        for (GList* iterator = np_state->netdefs_ordered; iterator; iterator = iterator->next) {
            NetplanNetDefinition* def = (NetplanNetDefinition*) iterator->data;
            gboolean has_been_written = FALSE;

            // sd-generator late-stage validation
            if (!nm_only) {
                CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
                CHECK_CALL(_netplan_netdef_generate_networkd(np_state, def, "", &has_been_written, &error), ignore_errors);
                CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);
                any_networkd = any_networkd || has_been_written;
            }
            if (!nm_only) CHECK_CALL(_netplan_netdef_write_networkd(np_state, def, rootdir, &has_been_written, &error), ignore_errors);
            any_networkd = any_networkd || has_been_written;

            // sd-generator late-stage validation
            if (!nm_only) {
                CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
                CHECK_CALL(_netplan_netdef_generate_ovs(np_state, def, "", &has_been_written, &error), ignore_errors);
                CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);
            }
            if (!nm_only) CHECK_CALL(_netplan_netdef_write_ovs(np_state, def, rootdir, &has_been_written, &error), ignore_errors);

            // We don't have any _netplan_netdef_generate_nm() function for sd-generator late-stage validation
            CHECK_CALL(_netplan_netdef_write_nm(np_state, def, rootdir, &has_been_written, &error), ignore_errors);
            any_nm = any_nm || has_been_written;
        }

        // We don't have any _netplan_state_finish_nm_generate() function for sd-generator late-stage validation
        CHECK_CALL(netplan_state_finish_nm_write(np_state, rootdir, &error), ignore_errors);

        // sd-generator late-stage validation
        if (!nm_only) {
            CHECK_CALL(_netplan_state_set_flags(np_state, NETPLAN_STATE_VALIDATION_ONLY, &error), ignore_errors);
            CHECK_CALL(_netplan_state_finish_sriov_generate(np_state, "", &error), ignore_errors);
            CHECK_CALL(_netplan_state_set_flags(np_state, 0, &error), ignore_errors);
        }
        if (!nm_only) CHECK_CALL(netplan_state_finish_sriov_write(np_state, rootdir, &error), ignore_errors);
    }

    /* Disable /usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf
     * (which restricts NM to wifi and wwan) if "renderer: NetworkManager" is used anywhere */
    if (netplan_state_get_backend(np_state) == NETPLAN_BACKEND_NM || any_nm)
        _netplan_g_string_free_to_file(g_string_new(NULL), rootdir, "/run/NetworkManager/conf.d/10-globally-managed-devices.conf", NULL);

    if (nm_only) goto cleanup;

    // Only logic that is not relevant for NetworkManager config below this point

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
