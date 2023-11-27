/*
 * Copyright (C) 2021 Canonical, Ltd.
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

/*! \file parse-nm.h
 *  \brief Parsing native NetworkManager keyfile into Netplan state.
 */

#pragma once
#include "types.h"

#define NETPLAN_NM_EMPTY_GROUP "_"

NETPLAN_PUBLIC gboolean
netplan_parser_load_keyfile(NetplanParser* npp, const char* filename, NetplanError** error);

//TODO: needs to be implemented
//NETPLAN_PUBLIC gboolean
//netplan_parser_load_keyfile_from_fd(NetplanParser* npp, int input_fd, NetplanError** error);

/********** Old API below this ***********/

NETPLAN_PUBLIC gboolean
netplan_parse_keyfile(const char* filename, GError** error);
