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

NETPLAN_INTERNAL gboolean
_netplan_netdef_write_nm(
        const NetplanState* np_state,
        const NetplanNetDefinition* netdef,
        const char* rootdir,
        gboolean* has_been_written,
        GError** error);

NETPLAN_INTERNAL gboolean
_netplan_nm_cleanup(const char* rootdir);

NETPLAN_INTERNAL GString*
bridge_vlan_str(const NetplanBridgeVlan* vlan);
