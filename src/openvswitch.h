/*
 * Copyright (C) 2020 Canonical, Ltd.
 * Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@ubuntu.com>
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
_netplan_netdef_write_ovs(
        const NetplanState* np_state,
        const NetplanNetDefinition* netdef,
        const char* rootdir,
        gboolean* has_been_written,
        GError** error);

NETPLAN_INTERNAL gboolean
_netplan_netdef_generate_ovs(
        const NetplanState* np_state,
        const NetplanNetDefinition* netdef,
        const char* generator_dir,
        gboolean* has_been_written,
        GError** error);

NETPLAN_INTERNAL gboolean
_netplan_state_finish_ovs_generate(
        const NetplanState* np_state,
        const char* rootdir,
        NetplanError** error);

NETPLAN_INTERNAL gboolean
_netplan_ovs_cleanup(const char* rootdir);

const char *
_get_netplan_openvswitch_ovs_vsctl_path(void);
