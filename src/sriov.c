/*
 * Copyright (C) 2020 Canonical, Ltd.
 * Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@canonical.com>
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

#include <glib.h>
#include <glib/gstdio.h>
#include <glib-object.h>

#include "util.h"

void
write_sriov_conf_finish(const char* rootdir)
{
    /* For now we execute apply --sriov-only everytime there is a new
       SR-IOV device appearing, which is fine as it's relatively fast */
    GString *udev_rule = g_string_new("ACTION==\"add\", SUBSYSTEM==\"net\", ATTRS{sriov_totalvfs}==\"?*\", RUN+=\"/usr/sbin/netplan apply --sriov-only\"\n");
    g_string_free_to_file(udev_rule, rootdir, "run/udev/rules.d/99-sriov-netplan-setup.rules", NULL);
}

void
cleanup_sriov_conf(const char* rootdir)
{
    g_autofree char* rulepath = g_strjoin(NULL, rootdir ?: "", "/run/udev/rules.d/99-sriov-netplan-setup.rules", NULL);
    unlink(rulepath);
}
