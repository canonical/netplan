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
 * @file  netplan.h
 * @brief Functions for manipulating @ref NetplanState and @ref NetplanNetDefinition objects.
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
 * @details Similar to @ref netplan_state_reset, but also free and nullify the structure itself.
 * @param[out] np_state The @ref NetplanState to free and nullify
 */
NETPLAN_PUBLIC void
netplan_state_clear(NetplanState** np_state);

/**
 * @brief Get the global @ref NetplanBackend defined in this @ref NetplanState.
 * @note  This will be the default fallback backend to render any contained @ref NetplanNetDefinition on, if not otherwise specified.
 * @param[in] np_state The @ref NetplanState to query
 * @return             Enumeration value, specifiying the @ref NetplanBackend
 */
NETPLAN_PUBLIC NetplanBackend
netplan_state_get_backend(const NetplanState* np_state);

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
 * @brief   Get the origin filepath of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small its content will not be `NUL`-terminated.
 * @param[in]  netdef          The @ref NetplanNetDefinition to query
 * @param[out] out_buffer      A pre-allocated buffer to write the output string into, owned by the caller
 * @param[in]  out_buffer_size The maximum size (in bytes) available for @p out_buffer
 * @return                     The size of the copied string, including the final `NUL` character.
 *                             If the buffer is too small, returns @ref NETPLAN_BUFFER_TOO_SMALL instead.
 */
NETPLAN_PUBLIC ssize_t
netplan_netdef_get_filepath(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);

/**
 * @brief Get the specific @ref NetplanBackend defined for this @ref NetplanNetDefinition.
 * @param[in] np_state The @ref NetplanState to query
 * @return             Enumeration value, specifiying the @ref NetplanBackend
 */
NETPLAN_PUBLIC NetplanBackend
netplan_netdef_get_backend(const NetplanNetDefinition* netdef);

/**
 * @brief Get the interface type for a given @ref NetplanNetDefinition.
 * @param[in] np_state The @ref NetplanState to query
 * @return             Enumeration value of @ref NetplanDefType, specifiying the interface type
 */
NETPLAN_PUBLIC NetplanDefType
netplan_netdef_get_type(const NetplanNetDefinition* netdef);

/**
 * @brief   Get the Netplan ID of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small its content will not be `NUL`-terminated.
 * @param[in]  netdef          The @ref NetplanNetDefinition to query
 * @param[out] out_buffer      A pre-allocated buffer to write the output string into, owned by the caller
 * @param[in]  out_buffer_size The maximum size (in bytes) available for @p out_buffer
 * @return                     The size of the copied string, including the final `NUL` character.
 *                             If the buffer is too small, returns @ref NETPLAN_BUFFER_TOO_SMALL instead.
 */
NETPLAN_PUBLIC ssize_t
netplan_netdef_get_id(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);

/**
 * @brief   Get a reference to a linked @ref NetplanNetDefinition for a given @p netdef.
 * @details This defines the parent-child relationship between bridged interfaces.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Reference to the parent of @p netdef
 */
NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_bridge_link(const NetplanNetDefinition* netdef);

/**
 * @brief   Get a reference to a linked @ref NetplanNetDefinition for a given @p netdef.
 * @details This defines the parent-child relationship between bonded interfaces.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Reference to the parent of @p netdef
 */
NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_bond_link(const NetplanNetDefinition* netdef);

/**
 * @brief   Get a reference to a linked @ref NetplanNetDefinition for a given @p netdef.
 * @details This defines the peer relationship between veth or Open vSwitch interfaces.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Reference to the peer of @p netdef
 */
NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_peer_link(const NetplanNetDefinition* netdef);

/**
 * @brief   Get a reference to a linked @ref NetplanNetDefinition for a given @p netdef.
 * @details This defines the parent-child relationship of VLAN interfaces.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Reference to the parent of @p netdef
 */
NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_vlan_link(const NetplanNetDefinition* netdef);

/**
 * @brief   Get a reference to a linked @ref NetplanNetDefinition for a given @p netdef.
 * @details This defines the parent-child relationship of SR-IOV virtual functions.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Reference to the physical function of @p netdef
 */
NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_sriov_link(const NetplanNetDefinition* netdef);

/**
 * @brief   Get the `set-name` setting of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small its content will not be `NUL`-terminated.
 * @note    This is unrelated to the `match.name` setting.
 * @param[in]  netdef          The @ref NetplanNetDefinition to query
 * @param[out] out_buffer      A pre-allocated buffer to write the output string into, owned by the caller
 * @param[in]  out_buffer_size The maximum size (in bytes) available for @p out_buffer
 * @return                     The size of the copied string, including the final `NUL` character.
 *                             If the buffer is too small, returns @ref NETPLAN_BUFFER_TOO_SMALL instead.
 */
NETPLAN_PUBLIC ssize_t
netplan_netdef_get_set_name(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);

/**
 * @brief   Query a @ref NetplanNetDefinition for a `match` stanza in its configuration.
 * @details In the absence of a `match` stanza, the Netplan ID
            can be considered to be the interface name of a single interface. Otherwise, it could match multiple interfaces.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Indication if @p netdef uses custom interface matching rules
 */
NETPLAN_PUBLIC gboolean
netplan_netdef_has_match(const NetplanNetDefinition* netdef);

/**
 * @brief   Gheck if a @ref NetplanNetDefinition matches on given interface parameters.
 * @details If defined in @p netdef calculate if it would match on given @p mac AND @p name AND @p driver_name parameters.
 * @note    Matching a single driver out of a list given in the YAML configuration is enough to satisfy the condition.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @param[in] name   The interface name match, optionally using shell wildcard patterns (`fnmatch()`)
 * @param[in] mac    The exact, case insensitive match on the interface MAC address
 * @param[in] driver_name The driver match, optionally using shell wildcard patterns (`fnmatch()`)
 * @return           Indication if @p netdef uses custom interface matching rules
 */
NETPLAN_PUBLIC gboolean
netplan_netdef_match_interface(const NetplanNetDefinition* netdef, const char* name, const char* mac, const char* driver_name);

/**
 * @brief   Query a @ref NetplanNetDefinition for the value of its `dhcp4` setting.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Indication if @p netdef is configured to enable DHCP for IPv4
 */
NETPLAN_PUBLIC gboolean
netplan_netdef_get_dhcp4(const NetplanNetDefinition* netdef);

/**
 * @brief   Query a @ref NetplanNetDefinition for the value of its `dhcp6` setting.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Indication if @p netdef is configured to enable DHCP for IPv6
 */
NETPLAN_PUBLIC gboolean
netplan_netdef_get_dhcp6(const NetplanNetDefinition* netdef);

/**
 * @brief   Get the `macaddress` setting of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small its content will not be `NUL`-terminated.
 * @note    This is unrelated to the `match.macaddress` setting.
 * @param[in]  netdef          The @ref NetplanNetDefinition to query
 * @param[out] out_buffer      A pre-allocated buffer to write the output string into, owned by the caller
 * @param[in]  out_buffer_size The maximum size (in bytes) available for @p out_buffer
 * @return                     The size of the copied string, including the final `NUL` character.
 *                             If the buffer is too small, returns @ref NETPLAN_BUFFER_TOO_SMALL instead.
 */
NETPLAN_PUBLIC ssize_t
netplan_netdef_get_macaddress(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);
