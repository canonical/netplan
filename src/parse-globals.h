/*
 * Copyright (C) 2021 Canonical, Ltd.
 * Author: Simon Chopin <simon.chopin@canonical.com>
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
#include "types-internal.h"

/* Written/updated by parse_yaml(): char* id →  net_definition.
 *
 * Since both netdefs and netdefs_ordered store pointers to the same elements,
 * we consider that only netdefs_ordered is owner of this data. One should not
 * free() objects obtained from netdefs, and proper care should be taken to remove
 * any reference of an object in netdefs when destroying it from netdefs_ordered.
 */
extern GHashTable*
netdefs;

extern GList*
netdefs_ordered;

extern NetplanOVSSettings
ovs_settings_global;

extern NetplanBackend
global_backend;

extern NetplanParser
global_parser;
