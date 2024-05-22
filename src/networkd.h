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

#pragma once

#include "netplan.h"
#include <glib.h>

#define NETWORKD_GROUP "systemd-network"

NETPLAN_INTERNAL gboolean
_netplan_netdef_write_networkd(
        const NetplanState* np_state,
        const NetplanNetDefinition* def,
        const char *rootdir,
        gboolean* has_been_written,
        GError** error);

NETPLAN_INTERNAL gboolean
_netplan_netdef_write_network_file(
        const NetplanState* np_state,
        const NetplanNetDefinition* def,
        const char *rootdir,
        const char* path,
        gboolean* has_been_written,
        GError** error);

NETPLAN_INTERNAL gboolean
_netplan_networkd_write_wait_online(const NetplanState* np_state, const char* rootdir);

NETPLAN_INTERNAL void
_netplan_networkd_cleanup(const char* rootdir);
