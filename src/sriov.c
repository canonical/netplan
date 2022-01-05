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

static gboolean
write_sriov_rebind_systemd_unit(const GString* pfs, const char* rootdir, GError** error)
{
    g_autofree gchar* id_escaped = NULL;
    g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/multi-user.target.wants/netplan-sriov-rebind.service", NULL);
    g_autofree char* path = g_strjoin(NULL, "/run/systemd/system/netplan-sriov-rebind.service", NULL);
    gchar** split = NULL;

    GString* s = g_string_new("[Unit]\n");
    g_string_append(s, "Description=(Re-)bind SR-IOV Virtual Functions to their driver\n");
    g_string_append_printf(s, "After=network.target\n");

    /* Run after udev */
    split = g_strsplit(pfs->str, " ", 0);
    for (unsigned i = 0; split[i]; ++i)
        g_string_append_printf(s, "After=sys-subsystem-net-devices-%s.device\n",
                               split[i]);
    g_strfreev(split);

    g_string_append(s, "\n[Service]\nType=oneshot\n");
    g_string_append_printf(s, "ExecStart=" SBINDIR "/netplan rebind %s\n", pfs->str);

    g_string_free_to_file(s, rootdir, path, NULL);

    safe_mkdir_p_dir(link);
    if (symlink(path, link) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_set_error(error, G_MARKUP_ERROR, G_MARKUP_ERROR_INVALID_CONTENT,
                    "failed to create enablement symlink: %m\n");
        return FALSE;
        // LCOV_EXCL_STOP
    }
    return TRUE;
}

/**
 * Finalize the SR-IOV configuration (global config)
 */
gboolean
netplan_state_finish_sriov_write(const NetplanState* np_state, const char* rootdir, GError** error)
{
    NetplanNetDefinition* def = NULL;
    NetplanNetDefinition* pf = NULL;
    gboolean any_sriov = FALSE;
    gboolean ret = TRUE;

    if (np_state) {
        GString* pfs = g_string_new(NULL);
        /* Find netdev interface names for SR-IOV PFs*/
        for (GList* iterator = np_state->netdefs_ordered; iterator; iterator = iterator->next) {
            def = (NetplanNetDefinition*) iterator->data;
            pf = NULL;
            if (def->sriov_explicit_vf_count < G_MAXUINT || def->sriov_link) {
                any_sriov = TRUE;
                if (def->sriov_explicit_vf_count < G_MAXUINT)
                    pf = def;
                else if (def->sriov_link)
                    pf = def->sriov_link;
            }

            if (pf && pf->sriov_delay_virtual_functions_rebind) {
                if (pf->set_name)
                    g_string_append_printf(pfs, "%s ", pf->set_name);
                else if (!pf->has_match) /* netdef_id == interface name */
                    g_string_append_printf(pfs, "%s ", pf->id);
                else
                    g_warning("%s: Cannot rebind SR-IOV virtual functions, unknown interface name. "
                              "Use 'netplan rebind <IFACE>' to rebind manually or use the 'set-name' stanza.",
                              pf->id);
            }
        }
        if (pfs->len > 0) {
            g_string_truncate(pfs, pfs->len-1); /* cut trailing whitespace */
            ret = write_sriov_rebind_systemd_unit(pfs, rootdir, NULL);
        }
        g_string_free(pfs, TRUE);
    }

    if (any_sriov) {
        /* For now we execute apply --sriov-only everytime there is a new
        SR-IOV device appearing, which is fine as it's relatively fast */
        GString *udev_rule = g_string_new("ACTION==\"add\", SUBSYSTEM==\"net\", ATTRS{sriov_totalvfs}==\"?*\", RUN+=\"/usr/sbin/netplan apply --sriov-only\"\n");
        g_string_free_to_file(udev_rule, rootdir, "run/udev/rules.d/99-sriov-netplan-setup.rules", NULL);
    }

    return ret;
}

gboolean
netplan_sriov_cleanup(const char* rootdir)
{
    unlink_glob(rootdir, "/run/udev/rules.d/*-sriov-netplan-*.rules");
    unlink_glob(rootdir, "/run/systemd/system/netplan-sriov-*.service");
    return TRUE;

}

NETPLAN_INTERNAL int
_netplan_state_get_vf_count_for_def(const NetplanState* np_state, const NetplanNetDefinition* netdef, GError** error)
{
    GHashTableIter iter;
    gpointer key, value;
    int count = 0;

    g_hash_table_iter_init(&iter, np_state->netdefs);
    while (g_hash_table_iter_next (&iter, &key, &value)) {
        const NetplanNetDefinition* def = value;
        if (def->sriov_link == netdef)
            count++;
    }

    if (netdef->sriov_explicit_vf_count != G_MAXUINT && count > netdef->sriov_explicit_vf_count) {
        g_set_error(error, 0, 0, "more VFs allocated than the explicit size declared: %d > %d", count, netdef->sriov_explicit_vf_count);
        return -1;
    }
    return netdef->sriov_explicit_vf_count != G_MAXUINT ? netdef->sriov_explicit_vf_count : count;
}
