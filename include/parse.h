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

/*! \file parse.h
 *  \brief Netplan YAML parsing and validation.
 */

#pragma once
#include <glib.h>
#include "types.h"

/****************************************************
 * Functions
 ****************************************************/

NETPLAN_PUBLIC NetplanParser*
netplan_parser_new();

NETPLAN_PUBLIC void
netplan_parser_reset(NetplanParser *npp);

NETPLAN_PUBLIC void
netplan_parser_clear(NetplanParser **npp);

NETPLAN_PUBLIC gboolean
netplan_parser_load_yaml(NetplanParser* npp, const char* filename, NetplanError** error);

NETPLAN_PUBLIC gboolean
netplan_parser_load_yaml_from_fd(NetplanParser* npp, int input_fd, NetplanError** error);

NETPLAN_PUBLIC gboolean
netplan_parser_load_yaml_hierarchy(NetplanParser* npp, const char* rootdir, NetplanError** error);

NETPLAN_PUBLIC gboolean
netplan_parser_load_nullable_fields(NetplanParser* npp, int input_fd, NetplanError** error);

NETPLAN_PUBLIC gboolean
netplan_state_import_parser_results(NetplanState* np_state, NetplanParser* npp, NetplanError** error);

/* Load the overrides, i.e. all global values (like "renderer") or Netdef-IDs
 * that are part of the given YAML patch (<input_fd>), and are supposed to be
 * overridden inside the yaml hierarchy by the resulting origin_hint file.
 * They are supposed to be parsed from the origin-hint file given in
 * <constraint> only. */
NETPLAN_PUBLIC gboolean
netplan_parser_load_nullable_overrides(
    NetplanParser* npp, int input_fd, const char* constraint, NetplanError** error);

