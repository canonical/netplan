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

#include <glib.h>
#include <stdint.h>
#include "types.h"

NETPLAN_PUBLIC gboolean
netplan_delete_connection(const char* id, const char* rootdir);

NETPLAN_PUBLIC gboolean
netplan_generate(const char* rootdir);

NETPLAN_PUBLIC gchar*
netplan_get_id_from_nm_filename(const char* filename, const char* ssid);

NETPLAN_PUBLIC gchar*
netplan_get_filename_by_id(const char* netdef_id, const char* rootdir);

NETPLAN_PUBLIC void
netplan_error_free(NetplanError* error);

NETPLAN_PUBLIC ssize_t
netplan_error_message(NetplanError* error, char* buf, size_t buf_size);

NETPLAN_PUBLIC uint64_t
netplan_error_code(NetplanError* error);
