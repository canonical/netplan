/*
 * Copyright (C) 2024 Canonical, Ltd.
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
 * @file  netdef.h
 * @brief Functions for manipulating @ref NetplanNetDefinition objects and querying properties of individual Netplan IDs.
 */

#pragma once
#include <stdlib.h>
#include "types.h"

/**
 * @brief   Get the full path that a @ref NetplanNetDefinition will be written to by its backend renderer.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small, its content is not `NUL`-terminated.
 * @note    Used by the NetworkManager YAML backend but also applicable to the systemd-networkd renderer.
 * @param[in]  netdef       The @ref NetplanNetDefinition to query
 * @param[in]  ssid         Wi-Fi SSID of this connection, or `NULL`
 * @param[out] out_buffer   A pre-allocated buffer to write the output string into, owned by the caller
 * @param[in]  out_buf_size The maximum size (in bytes) available for @p out_buffer
 * @return                  The size of the copied string, including the final `NUL` character.
 *                          If the buffer is too small, returns @ref NETPLAN_BUFFER_TOO_SMALL instead.
 */
NETPLAN_PUBLIC ssize_t
netplan_netdef_get_output_filename(const NetplanNetDefinition* netdef, const char* ssid, char* out_buffer, size_t out_buf_size);

/**
 * @brief   Get the origin filepath of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small, its content is not `NUL`-terminated.
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
 *          buffer is too small, its content is not `NUL`-terminated.
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
 * @brief   Get a reference to a linked @ref NetplanNetDefinition for a given @p netdef.
 * @details This defines the parent-child relationship of VRF interfaces.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Reference to the parent of @p netdef
 */
NETPLAN_PUBLIC NetplanNetDefinition*
netplan_netdef_get_vrf_link(const NetplanNetDefinition* netdef);

/**
 * @brief   Get the `set-name` setting of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small, its content is not `NUL`-terminated.
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
 * @brief   Check if a @ref NetplanNetDefinition matches on given interface parameters.
 * @details If defined in @p netdef, calculate if it would match on given @p mac AND @p name AND @p driver_name parameters.
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
 * @brief   Query a @ref NetplanNetDefinition for the value of its `link-local` setting for IPv4.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Indication if @p netdef is configured to enable the link-local address for IPv4
 */
NETPLAN_PUBLIC gboolean
netplan_netdef_get_link_local_ipv4(const NetplanNetDefinition* netdef);

/**
 * @brief   Query a @ref NetplanNetDefinition for the value of its `link-local` setting for IPv6.
 * @param[in] netdef The @ref NetplanNetDefinition to query
 * @return           Indication if @p netdef is configured to enable the link-local address for IPv6
 */
NETPLAN_PUBLIC gboolean
netplan_netdef_get_link_local_ipv6(const NetplanNetDefinition* netdef);

/**
 * @brief   Get the `macaddress` setting of a given @ref NetplanNetDefinition.
 * @details Copies a `NUL`-terminated string into a sized @p out_buffer. If the
 *          buffer is too small, its content is not `NUL`-terminated.
 * @note    This is unrelated to the `match.macaddress` setting.
 * @param[in]  netdef          The @ref NetplanNetDefinition to query
 * @param[out] out_buffer      A pre-allocated buffer to write the output string into, owned by the caller
 * @param[in]  out_buffer_size The maximum size (in bytes) available for @p out_buffer
 * @return                     The size of the copied string, including the final `NUL` character.
 *                             If the buffer is too small, returns @ref NETPLAN_BUFFER_TOO_SMALL instead.
 */
NETPLAN_PUBLIC ssize_t
netplan_netdef_get_macaddress(const NetplanNetDefinition* netdef, char* out_buffer, size_t out_buffer_size);
