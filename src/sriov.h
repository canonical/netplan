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

#pragma once
#include "netplan.h"

NETPLAN_INTERNAL gboolean
netplan_state_finish_sriov_write(
        const NetplanState* np_state,
        const char* rootdir,
        GError** error);

NETPLAN_INTERNAL gboolean
netplan_sriov_cleanup(const char* rootdir);

/* Deprecated API */
NETPLAN_INTERNAL void
write_sriov_conf_finish(const char* rootdir);
NETPLAN_INTERNAL void
cleanup_sriov_conf(const char* rootdir);
