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

/*
 * The whole point of this file is to export the former ABI as simple wrappers
 * around the newer API. Most functions should thus be relatively short, the meat
 * of things being in the newer API implementation.
 */

#include "netplan.h"
#include "types.h"
#include "util-internal.h"
#include "parse-nm.h"
#include "names.h"
#include "networkd.h"
#include "nm.h"
#include "openvswitch.h"

/* These arrays are not useful per-say, but allow us to export the various
 * struct offsets of the netplan_state members to the linker, which can use
 * them in a linker script to create symbols pointing to the internal data
 * members of the global_state global object.
 */

/* The +8 is to prevent the compiler removing the array if the array is empty,
 * i.e. the data member is the first in the struct definition.
 */
__attribute__((used)) __attribute__((section("netdefs_offset")))
char _netdefs_off[8+offsetof(struct netplan_state, netdefs)] = {};

__attribute__((used)) __attribute__((section("netdefs_ordered_offset")))
char _netdefs_ordered_off[8+offsetof(struct netplan_state, netdefs_ordered)] = {};

__attribute__((used)) __attribute__((section("ovs_settings_offset")))
char _ovs_settings_global_off[8+offsetof(struct netplan_state, ovs_settings)] = {};

__attribute__((used)) __attribute__((section("global_backend_offset")))
char _global_backend_off[8+offsetof(struct netplan_state, backend)] = {};

NETPLAN_ABI
NetplanState global_state = {};

NetplanBackend
netplan_get_global_backend()
{
    return netplan_state_get_backend(&global_state);
}

/**
 * Clear NetplanNetDefinition hashtable
 */
guint
netplan_clear_netdefs()
{
    guint n = netplan_state_get_netdefs_size(&global_state);
    netplan_state_reset(&global_state);
    return n;
}
