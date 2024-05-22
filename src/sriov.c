/*
 * Copyright (C) 2020-2022 Canonical, Ltd.
 * Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
 * Author: Lukas Märdian <slyon@ubuntu.com>
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

#include <unistd.h>
#include <errno.h>

#include <glib.h>
#include <glib/gstdio.h>
#include <glib-object.h>

#include "util-internal.h"
#include "sriov.h"

STATIC gboolean
write_sriov_rebind_systemd_unit(GHashTable* pfs, const char* rootdir, GError** error)
{
    g_autofree gchar* id_escaped = NULL;
    g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/multi-user.target.wants/netplan-sriov-rebind.service", NULL);
    g_autofree char* path = g_strjoin(NULL, "/run/systemd/system/netplan-sriov-rebind.service", NULL);

    GHashTableIter iter;
    gpointer key;
    GString* interfaces = g_string_new("");

    GString* s = g_string_new("[Unit]\n");
    g_string_append(s, "Description=(Re-)bind SR-IOV Virtual Functions to their driver\n");
    g_string_append_printf(s, "After=network.target\n");
    g_string_append_printf(s, "After=netplan-sriov-apply.service\n");

    /* Run after udev */
    g_hash_table_iter_init(&iter, pfs);
    while (g_hash_table_iter_next (&iter, &key, NULL)) {
        const gchar* id = key;
        g_string_append_printf(s, "After=sys-subsystem-net-devices-%s.device\n", id);
        g_string_append_printf(interfaces, "%s ", id);
    }

    g_string_append(s, "\n[Service]\nType=oneshot\n");
    g_string_truncate(interfaces, interfaces->len-1); /* cut trailing whitespace */
    g_string_append_printf(s, "ExecStart=" SBINDIR "/netplan rebind --debug %s\n", interfaces->str);

    _netplan_g_string_free_to_file_with_permissions(s, rootdir, path, NULL, "root", "root", 0640);
    g_string_free(interfaces, TRUE);

    _netplan_safe_mkdir_p_dir(link);
    if (symlink(path, link) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_set_error(error, NETPLAN_FILE_ERROR, errno,
                    "failed to create enablement symlink: %m");
        return FALSE;
        // LCOV_EXCL_STOP
    }
    return TRUE;
}

STATIC gboolean
write_sriov_apply_systemd_unit(GHashTable* pfs, const char* rootdir, GError** error)
{
    g_autofree gchar* id_escaped = NULL;
    g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/multi-user.target.wants/netplan-sriov-apply.service", NULL);
    g_autofree char* path = g_strjoin(NULL, "/run/systemd/system/netplan-sriov-apply.service", NULL);
    GHashTableIter iter;
    gpointer key;

    GString* s = g_string_new("[Unit]\n");
    g_string_append(s, "Description=Apply SR-IOV configuration\n");
    g_string_append(s, "DefaultDependencies=no\n");
    g_string_append(s, "Before=network-pre.target\n");

    g_hash_table_iter_init(&iter, pfs);
    while (g_hash_table_iter_next (&iter, &key, NULL)) {
        g_string_append_printf(s, "After=sys-subsystem-net-devices-%s.device\n", (gchar*) key);
    }

    g_string_append(s, "\n[Service]\nType=oneshot\n");
    g_string_append_printf(s, "ExecStart=" SBINDIR "/netplan apply --sriov-only\n");

    _netplan_g_string_free_to_file_with_permissions(s, rootdir, path, NULL, "root", "root", 0640);

    _netplan_safe_mkdir_p_dir(link);
    if (symlink(path, link) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT,
                    "failed to create enablement symlink: %m");
        return FALSE;
        // LCOV_EXCL_STOP
    }
    return TRUE;
}

/**
 * Finalize the SR-IOV configuration (global config)
 */
gboolean
netplan_state_finish_sriov_write(const NetplanState* np_state, const char* rootdir, __unused GError** error)
{
    NetplanNetDefinition* def = NULL;
    NetplanNetDefinition* pf = NULL;
    gboolean any_sriov = FALSE;
    gboolean ret = TRUE;

    if (np_state) {
        GHashTable* rebind_pfs = g_hash_table_new(g_str_hash, g_str_equal);
        GHashTable* apply_pfs = g_hash_table_new(g_str_hash, g_str_equal);

        /* Find netdev interface names for SR-IOV PFs
         * We consider an interface to be a PF if at least of the conditions below is true:
         * 1) the user explicitly set a desired number of VFs
         * 2) there is at least one interface with a link to it (meaning the interface is a VF of this PF)
         * 3) the user set the embedded-switch-mode (which can be applied regardless if the interface has VFs) 
         * */
        for (GList* iterator = np_state->netdefs_ordered; iterator; iterator = iterator->next) {
            def = (NetplanNetDefinition*) iterator->data;
            pf = NULL;
            if (def->sriov_explicit_vf_count < G_MAXUINT || def->sriov_link || def->embedded_switch_mode) {
                any_sriov = TRUE;
                if (def->sriov_explicit_vf_count < G_MAXUINT || def->embedded_switch_mode)
                    pf = def;
                else if (def->sriov_link)
                    pf = def->sriov_link;

                if (pf) {
                    if (pf->set_name)
                        g_hash_table_add(apply_pfs, pf->set_name);
                    else if (!pf->has_match) /* netdef_id == interface name */
                        g_hash_table_add(apply_pfs, pf->id);
                    else
                        g_warning("%s: Cannot determine SR-IOV PF interface name.", pf->id);
                }
            }

            if (pf && pf->sriov_delay_virtual_functions_rebind) {
                if (pf->set_name)
                    g_hash_table_add(rebind_pfs, pf->set_name);
                else if (!pf->has_match) /* netdef_id == interface name */
                    g_hash_table_add(rebind_pfs, pf->id);
                else
                    g_warning("%s: Cannot rebind SR-IOV virtual functions, unknown interface name. "
                              "Use 'netplan rebind <IFACE>' to rebind manually or use the 'set-name' stanza.",
                              pf->id);
            }
        }

        if (any_sriov) {
            ret = write_sriov_apply_systemd_unit(apply_pfs, rootdir, NULL);
            if (!ret) {
                // LCOV_EXCL_START
                g_warning("netplan-sriov-apply.service cannot be created.");
                goto error;
                // LCOV_EXCL_STOP
            }

            /*
             * The sriov-apply service will always be created (as long as there is any sr-iov configuration)
             * and the sriov-rebind MUST only run after apply. As sriov-apply will always be there if sriov-rebind
             * is present, using the After= dependency statement is enough (Requires= is not necessary).
            */
            if (g_hash_table_size(rebind_pfs) > 0) {
                ret = write_sriov_rebind_systemd_unit(rebind_pfs, rootdir, NULL);
                if (!ret)
                // LCOV_EXCL_START
                    g_warning("netplan-sriov-rebind.service cannot be created.");
                // LCOV_EXCL_STOP
            }
        }

error:
        g_hash_table_destroy(rebind_pfs);
        g_hash_table_destroy(apply_pfs);
    }

    return ret;
}

gboolean
_netplan_sriov_cleanup(const char* rootdir)
{
    _netplan_unlink_glob(rootdir, "/run/udev/rules.d/*-sriov-netplan-*.rules");
    _netplan_unlink_glob(rootdir, "/run/systemd/system/netplan-sriov-*.service");
    return TRUE;

}

int
_netplan_state_get_vf_count_for_def(const NetplanState* np_state, const NetplanNetDefinition* netdef, GError** error)
{
    GHashTableIter iter;
    gpointer key, value;
    guint count = 0;

    g_hash_table_iter_init(&iter, np_state->netdefs);
    while (g_hash_table_iter_next (&iter, &key, &value)) {
        const NetplanNetDefinition* def = value;
        if (def->sriov_link == netdef)
            count++;
    }

    if (netdef->sriov_explicit_vf_count != G_MAXUINT && count > netdef->sriov_explicit_vf_count) {
        g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_VALIDATION, "more VFs allocated than the explicit size declared: %d > %d", count, netdef->sriov_explicit_vf_count);
        return -1;
    }
    return netdef->sriov_explicit_vf_count != G_MAXUINT ? netdef->sriov_explicit_vf_count : count;
}
