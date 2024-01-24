/*
 * Copyright (C) 2021-2024 Canonical, Ltd.
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
 * @file  state.h
 * @brief Functions for manipulating @ref NetplanState objects, validating
 *        Netplan configurations and writing them to disk.
 */

#pragma once
#include <stdlib.h>
#include "types.h"

/**
 * @brief   Allocate and initialize a new @ref NetplanState object.
 * @details Can be used to validate and carry pre-parsed Netplan configuration.
 * @return  An empty @ref NetplanState
 */
NETPLAN_PUBLIC NetplanState*
netplan_state_new();

/**
 * @brief   Reset a @ref NetplanState to its initial default values.
 * @details Freeing any dynamically allocated configuration data.
 * @param[in] np_state The @ref NetplanState to be reset
 */
NETPLAN_PUBLIC void
netplan_state_reset(NetplanState* np_state);

/**
 * @brief   Free a @ref NetplanState, including any dynamically allocated data.
 * @details Similar to @ref netplan_state_reset, but also free and nullify the object itself.
 * @param[out] np_state The @ref NetplanState to free and nullify
 */
NETPLAN_PUBLIC void
netplan_state_clear(NetplanState** np_state);

/**
 * @brief   Validate pre-parsed Netplan configuration data inside a @ref NetplanParser and import them into a @ref NetplanState.
 * @details This will transfer ownership of the contained data from @p npp to @p np_state and clean up by calling @ref netplan_parser_reset.
 * @param[in]  np_state The @ref NetplanState to be filled with validated Netplan configuration from @p npp
 * @param[in]  npp      The @ref NetplanParser containing unvalidated Netplan configuration from raw inputs
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_state_import_parser_results(NetplanState* np_state, NetplanParser* npp, NetplanError** error);

/**
 * @brief Get the number of @ref NetplanNetDefinition configurations stored in this @ref NetplanState
 * @note  Each @ref NetplanNetDefinition is identified by a unique Netplan ID.
 * @param[in] np_state The @ref NetplanState to query
 * @return             Number of unique @ref NetplanNetDefinition configurations
 */
NETPLAN_PUBLIC guint
netplan_state_get_netdefs_size(const NetplanState* np_state);

/**
 * @brief     Get a specific @ref NetplanNetDefinition from this @ref NetplanState
 * @param[in] np_state The @ref NetplanState to query
 * @param[in] id       The unique Netplan ID, referencing a @ref NetplanNetDefinition
 * @return             A handle to the specified @ref NetplanNetDefinition or `NULL` if not found
 */
NETPLAN_PUBLIC NetplanNetDefinition*
netplan_state_get_netdef(const NetplanState* np_state, const char* id);

/**
 * @brief Get the global @ref NetplanBackend defined in this @ref NetplanState.
 * @note  This will be the default fallback backend to render any contained @ref NetplanNetDefinition on, if not otherwise specified.
 * @param[in] np_state The @ref NetplanState to query
 * @return             Enumeration value, specifiying the @ref NetplanBackend
 */
NETPLAN_PUBLIC NetplanBackend
netplan_state_get_backend(const NetplanState* np_state);

/**
 * @brief   Write the selected YAML file, filtered to the data relevant to this file.
 * @details Writes out all @ref NetplanNetDefinition settings that originate from the specified file,
 *          as well as those without any given origin. Any data that's assigned to another file is ignored.
 * @param[in]  np_state The @ref NetplanState for which to generate the config
 * @param[in]  filename Relevant file basename (e.g. origin-hint.yaml)
 * @param[in]  rootdir  If not `NULL`, generate configuration in this root directory (useful for testing)
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_state_write_yaml_file(
        const NetplanState* np_state,
        const char* filename,
        const char* rootdir,
        NetplanError** error);

/**
 * @brief   Update all the YAML files that were used to create this @ref NetplanState.
 * @details Any data that hasn't an associated filepath will use the @p default_filename
 *          output file in the standard config directory.
 * @param[in]  np_state The @ref NetplanState for which to generate the config
 * @param[in]  default_filename Default config file, cannot be `NULL` or empty
 * @param[in]  rootdir  If not `NULL`, generate configuration in this root directory (useful for testing)
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_state_update_yaml_hierarchy(
        const NetplanState* np_state,
        const char* default_filename,
        const char* rootdir,
        NetplanError** error);

/**
 * @brief   Dump the whole @ref NetplanState into a single YAML file.
 * @details Ignoring the origin of each @ref NetplanNetDefinition.
 * @param[in]  np_state The @ref NetplanState for which to generate the config
 * @param[in]  out_fd   File descriptor to an opened file into which to dump the content
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_state_dump_yaml(
        const NetplanState* np_state,
        int output_fd,
        NetplanError** error);

/**
 * @brief Generate the Netplan YAML configuration for the selected @ref NetplanNetDefinition.
 * @param[in]  np_state @ref NetplanState (as pointer), the global state to which the netdef belongs
 * @param[in]  netdef   @ref NetplanNetDefinition (as pointer), the data to be serialized
 * @param[in]  rootdir  If not `NULL`, generate configuration in this root directory (useful for testing)
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_netdef_write_yaml(
        const NetplanState* np_state,
        const NetplanNetDefinition* netdef,
        const char* rootdir,
        NetplanError** error);

/**
 * @brief Initialize a @ref NetplanStateIterator for walking through a list of @ref NetplanNetDefinition inside @p np_state.
 * @param[in]     np_state The @ref NetplanState to query
 * @param[in,out] iter     A @ref NetplanStateIterator structure to be initialized
 */
NETPLAN_PUBLIC void
netplan_state_iterator_init(const NetplanState* np_state, NetplanStateIterator* iter);

/**
 * @brief Get the next @ref NetplanNetDefinition in the list of a @ref NetplanState object.
 * @param[in,out] iter A @ref NetplanStateIterator to work with
 * @return             The next @ref NetplanNetDefinition or `NULL`
 */
NETPLAN_PUBLIC NetplanNetDefinition*
netplan_state_iterator_next(NetplanStateIterator* iter);

/**
 * @brief Check if there is any next @ref NetplanNetDefinition in the list of a @ref NetplanState object.
 * @param[in,out] iter A @ref NetplanStateIterator to work with
 * @return             Indication if this @ref NetplanStateIterator contains any further @ref NetplanNetDefinition
 */
NETPLAN_PUBLIC gboolean
netplan_state_iterator_has_next(const NetplanStateIterator* iter);

/**
 * @brief   Write generic NetworkManager configuration to disk.
 * @details This configures global settings, independent of @ref NetplanNetDefinition data, like udev blocklisting to make NetworkManager ignore certain interfaces using `[device].managed=false` or `NM_MANAGED=0`.
 * @param[in]  np_state The @ref NetplanState to read settings from
 * @param[in]  rootdir  If not `NULL`, generate configuration in this root directory (useful for testing)
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_state_finish_nm_write(
        const NetplanState* np_state,
        const char* rootdir,
        NetplanError** error);

/**
 * @brief   Write generic Open vSwitch  configuration to disk.
 * @details This configures global settings, independent of @ref NetplanNetDefinition data, like patch ports, SSL configuration or the `netplan-ovs-cleanup.service` unit.
 * @param[in]  np_state The @ref NetplanState to read settings from
 * @param[in]  rootdir  If not `NULL`, generate configuration in this root directory (useful for testing)
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_state_finish_ovs_write(
        const NetplanState* np_state,
        const char* rootdir,
        NetplanError** error);

/**
 * @brief   Write generic SR-IOV  configuration to disk.
 * @details This configures global settings, independent of @ref NetplanNetDefinition data, like udev rules or the `netplan-sriov-rebind.service` unit.
 * @param[in]  np_state The @ref NetplanState to read settings from
 * @param[in]  rootdir  If not `NULL`, generate configuration in this root directory (useful for testing)
 * @param[out] error    Will be filled with a @ref NetplanError in case of failure
 * @return              Indication of success or failure
 */
NETPLAN_PUBLIC gboolean
netplan_state_finish_sriov_write(
        const NetplanState* np_state,
        const char* rootdir,
        NetplanError** error);
