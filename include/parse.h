/*
 * Copyright (C) 2016-2024 Canonical, Ltd.
 * Author: Martin Pitt <martin.pitt@ubuntu.com>
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

/**
 * @file  parse.h
 * @brief Parsing Netplan YAML configuration into @ref NetplanParser data structures.
 */

#pragma once
#include <glib.h>
#include "types.h"

/****************************************************
 * Functions
 ****************************************************/

/**
 * @brief Allocate and initialize a new @ref NetplanParser object.
 * @note  This contains unvalidated Netplan configuration from raw input, like Netplan YAML or NetworkManager keyfile.
 * @return  An empty @ref NetplanParser
 */
NETPLAN_PUBLIC NetplanParser*
netplan_parser_new();

/**
 * @brief   Reset a @ref NetplanParser to its initial default values.
 * @details Freeing any dynamically allocated parsing data.
 * @param[in] npp The @ref NetplanParser to be reset
 */
NETPLAN_PUBLIC void
netplan_parser_reset(NetplanParser *npp);

/**
 * @brief   Free a @ref NetplanParser, including any dynamically allocated data.
 * @details Similar to @ref netplan_parser_reset, but also free and nullify the object itself.
 * @param[out] npp The @ref NetplanParser to free and nullify
 */
NETPLAN_PUBLIC void
netplan_parser_clear(NetplanParser **npp);

/**
 * @brief Parse a given YAML file and create or update the list of @ref NetplanNetDefinition inside @p npp.
 * @param[in]  npp      The @ref NetplanParser object that should contain the parsed data
 * @param[in]  filename Full path to a Netplan YAML configuration file
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_parser_load_yaml(NetplanParser* npp, const char* filename, NetplanError** error);

/**
 * @brief Parse a given YAML file from a file descriptor and create or update the list of
          @ref NetplanNetDefinition inside @p npp.
 * @param[in]  npp      The @ref NetplanParser object that should contain the parsed data
 * @param[in]  input_fd File descriptor reference to a Netplan YAML configuration file
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_parser_load_yaml_from_fd(NetplanParser* npp, int input_fd, NetplanError** error);

/**
 * @brief Parse a full hierarchy of `/{usr/lib,etc,run}/netplan/\*.yaml` files inside
 *        @p rootdir and create or update the list of @ref NetplanNetDefinition inside @p npp.
 * @note  Files with "asciibetically" higher names override/append settings from earlier ones
 *        (in all Netplan config directories); files in `/run/netplan/` shadow files in
 *        `/etc/netplan/`, which shadow files in `/usr/lib/netplan/`.
 * @param[in]  npp     The @ref NetplanParser object that should contain the parsed data
 * @param[in]  rootdir If not `NULL`, parse configuration from this root directory (useful for testing)
 * @param[out] error   Will be filled with a @ref NetplanError in case of failure
 * @return             Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_parser_load_yaml_hierarchy(NetplanParser* npp, const char* rootdir, NetplanError** error);

/**
 * @brief   Parse a Netplan YAML config file from a file descriptor, containing settings
 *          that are about to be deleted (e.g. `some.setting=NULL`).
 * @details The `NULL`-settings are ignored when parsing subsequent YAML files.
 * @param[in]  npp      The @ref NetplanParser object that should contain the parsed data
 * @param[in]  input_fd File descriptor reference to a Netplan YAML configuration file
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_parser_load_nullable_fields(NetplanParser* npp, int input_fd, NetplanError** error);

/**
 * @brief   Parse a Netplan YAML config file from a file descriptor, containing special settings that
 *          are supposed to be overriden inside the YAML hierarchy by the resulting "origin-hint" output file.
 * @details Global settings (like `renderer`) or @ref NetplanNetDefinition, defined in @p input_fd
 *          shall be ignored from the existing YAML hierarchy, as @p input_fd configuration is
 *          supposed to override those settings via the "origin-hint" output file.
 * @note    Those settings are supposed to be parsed from the "origin-hint" output file given in @p constraint only.
 * @param[in]  npp        The @ref NetplanParser object that should contain the parsed data
 * @param[in]  input_fd   File descriptor reference to a Netplan YAML configuration file, which would become the "origin-hint" output file afterwards
 * @param[in]  constraint Basename of the "origin-hint" output file
 * @param[out] error      Will be filled with a @ref NetplanError in case of failure
 * @return                Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_parser_load_nullable_overrides(
    NetplanParser* npp, int input_fd, const char* constraint, NetplanError** error);
