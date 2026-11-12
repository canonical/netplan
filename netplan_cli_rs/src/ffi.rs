// Copyright (C) 2026 Canonical, Ltd.
// SPDX-License-Identifier: GPL-3.0-only
//
// This program is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation; version 3.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <http://www.gnu.org/licenses/>.

//! Raw FFI bindings to libnetplan.
//!
//! Mirrors the public C API declared in include/netplan.h (parse.h, state.h,
//! netdef.h, util.h, types.h).  All functions are `unsafe`; use the safe
//! wrappers in [`crate::netplan`] instead.

#![allow(dead_code)]

use std::os::raw::{c_char, c_int, c_uint, c_void};

// ── GLib primitive aliases ────────────────────────────────────────────────────

/// `gboolean`: non-zero = TRUE, zero = FALSE.
pub type GBoolean = c_int;
/// `guint`
pub type GUint = c_uint;

// ── Opaque C structs ──────────────────────────────────────────────────────────

#[repr(C)]
pub struct NetplanParser(c_void);
#[repr(C)]
pub struct NetplanState(c_void);
#[repr(C)]
pub struct NetplanNetDefinition(c_void);
#[repr(C)]
pub struct NetplanError(c_void);

// ── NetplanStateIterator (non-opaque, stack-allocated in C) ───────────────────

/// Matches `struct _NetplanStateIterator { void* placeholder; }` in types.h.
#[repr(C)]
pub struct NetplanStateIterator {
    pub placeholder: *mut c_void,
}

// ── Enumerations ──────────────────────────────────────────────────────────────

/// `NetplanBackend` from types.h
pub type NetplanBackend = c_int;
pub const NETPLAN_BACKEND_NONE: NetplanBackend = 0;
pub const NETPLAN_BACKEND_NETWORKD: NetplanBackend = 1;
pub const NETPLAN_BACKEND_NM: NetplanBackend = 2;
pub const NETPLAN_BACKEND_OVS: NetplanBackend = 3;

/// `NetplanDefType` from types.h.
/// NETPLAN_DEF_TYPE_BRIDGE == NETPLAN_DEF_TYPE_VIRTUAL == 4 (alias in C).
pub type NetplanDefType = c_int;
pub const NETPLAN_DEF_TYPE_NONE: NetplanDefType = 0;
pub const NETPLAN_DEF_TYPE_ETHERNET: NetplanDefType = 1;
pub const NETPLAN_DEF_TYPE_WIFI: NetplanDefType = 2;
pub const NETPLAN_DEF_TYPE_MODEM: NetplanDefType = 3;
pub const NETPLAN_DEF_TYPE_BRIDGE: NetplanDefType = 4; // = VIRTUAL
pub const NETPLAN_DEF_TYPE_BOND: NetplanDefType = 5;
pub const NETPLAN_DEF_TYPE_VLAN: NetplanDefType = 6;
pub const NETPLAN_DEF_TYPE_TUNNEL: NetplanDefType = 7;
pub const NETPLAN_DEF_TYPE_PORT: NetplanDefType = 8;
pub const NETPLAN_DEF_TYPE_VRF: NetplanDefType = 9;
pub const NETPLAN_DEF_TYPE_NM: NetplanDefType = 10;
pub const NETPLAN_DEF_TYPE_DUMMY: NetplanDefType = 11;
pub const NETPLAN_DEF_TYPE_VETH: NetplanDefType = 12;

/// Returned by `netplan_netdef_get_{id,set_name,...}` when the output buffer
/// is too small.
pub const NETPLAN_BUFFER_TOO_SMALL: isize = -2;

// ── libnetplan C API ──────────────────────────────────────────────────────────

extern "C" {
    // ── parse.h ──────────────────────────────────────────────────────────────

    pub fn netplan_parser_new() -> *mut NetplanParser;
    pub fn netplan_parser_clear(npp: *mut *mut NetplanParser);

    pub fn netplan_parser_load_yaml(
        npp: *mut NetplanParser,
        filename: *const c_char,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_parser_load_yaml_from_fd(
        npp: *mut NetplanParser,
        input_fd: c_int,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_parser_load_yaml_hierarchy(
        npp: *mut NetplanParser,
        rootdir: *const c_char,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_parser_load_nullable_fields(
        npp: *mut NetplanParser,
        input_fd: c_int,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_parser_load_nullable_overrides(
        npp: *mut NetplanParser,
        input_fd: c_int,
        constraint: *const c_char,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    // ── state.h ──────────────────────────────────────────────────────────────

    pub fn netplan_state_new() -> *mut NetplanState;
    pub fn netplan_state_clear(np_state: *mut *mut NetplanState);

    pub fn netplan_state_import_parser_results(
        np_state: *mut NetplanState,
        npp: *mut NetplanParser,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_state_get_backend(np_state: *const NetplanState) -> NetplanBackend;

    pub fn netplan_state_dump_yaml(
        np_state: *const NetplanState,
        output_fd: c_int,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_state_write_yaml_file(
        np_state: *const NetplanState,
        filename: *const c_char,
        rootdir: *const c_char,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_state_update_yaml_hierarchy(
        np_state: *const NetplanState,
        default_filename: *const c_char,
        rootdir: *const c_char,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_state_iterator_init(
        np_state: *const NetplanState,
        iter: *mut NetplanStateIterator,
    );

    pub fn netplan_state_iterator_next(
        iter: *mut NetplanStateIterator,
    ) -> *mut NetplanNetDefinition;

    pub fn netplan_state_iterator_has_next(iter: *mut NetplanStateIterator) -> GBoolean;

    // ── netdef.h ─────────────────────────────────────────────────────────────

    pub fn netplan_netdef_get_type(netdef: *const NetplanNetDefinition) -> NetplanDefType;

    pub fn netplan_netdef_get_id(
        netdef: *const NetplanNetDefinition,
        out_buffer: *mut c_char,
        out_buffer_size: usize,
    ) -> isize;

    pub fn netplan_netdef_get_set_name(
        netdef: *const NetplanNetDefinition,
        out_buffer: *mut c_char,
        out_buffer_size: usize,
    ) -> isize;

    pub fn netplan_netdef_has_match(netdef: *const NetplanNetDefinition) -> GBoolean;

    pub fn netplan_netdef_match_interface(
        netdef: *const NetplanNetDefinition,
        name: *const c_char,
        mac: *const c_char,
        driver_name: *const c_char,
    ) -> GBoolean;

    pub fn netplan_netdef_get_dhcp4(netdef: *const NetplanNetDefinition) -> GBoolean;
    pub fn netplan_netdef_get_dhcp6(netdef: *const NetplanNetDefinition) -> GBoolean;
    pub fn netplan_netdef_get_link_local_ipv4(netdef: *const NetplanNetDefinition) -> GBoolean;
    pub fn netplan_netdef_get_link_local_ipv6(netdef: *const NetplanNetDefinition) -> GBoolean;
    pub fn netplan_netdef_get_accept_ra(netdef: *const NetplanNetDefinition) -> c_int;
    pub fn netplan_netdef_get_macaddress(
        netdef: *const NetplanNetDefinition,
        out_buffer: *mut c_char,
        out_buffer_size: usize,
    ) -> isize;
    pub fn netplan_netdef_get_backend(netdef: *const NetplanNetDefinition) -> NetplanBackend;
    pub fn netplan_backend_name(val: NetplanBackend) -> *const c_char;

    pub fn netplan_netdef_get_bridge_link(
        netdef: *const NetplanNetDefinition,
    ) -> *mut NetplanNetDefinition;
    pub fn netplan_netdef_get_bond_link(
        netdef: *const NetplanNetDefinition,
    ) -> *mut NetplanNetDefinition;
    pub fn netplan_netdef_get_vrf_link(
        netdef: *const NetplanNetDefinition,
    ) -> *mut NetplanNetDefinition;

    // ── util.h ───────────────────────────────────────────────────────────────

    pub fn netplan_error_clear(error: *mut *mut NetplanError);

    pub fn netplan_error_message(
        error: *mut NetplanError,
        buf: *mut c_char,
        buf_size: usize,
    ) -> isize;

    /// Error domain in the upper 32 bits, error code in the lower 32 bits.
    pub fn netplan_error_code(error: *mut NetplanError) -> u64;

    // ── util-internal.h (exported for the Python bindings) ───────────────────

    pub fn _netplan_netdef_get_critical(netdef: *const NetplanNetDefinition) -> GBoolean;

    pub fn _netplan_netdef_is_trivial_compound_itf(netdef: *const NetplanNetDefinition)
        -> GBoolean;

    pub fn _netplan_state_new_netdef_pertype_iter(
        np_state: *mut NetplanState,
        def_type: *const c_char,
    ) -> *mut c_void;

    pub fn _netplan_netdef_pertype_iter_next(it: *mut c_void) -> *mut NetplanNetDefinition;

    pub fn _netplan_netdef_pertype_iter_free(it: *mut c_void);

    pub fn netplan_util_create_yaml_patch(
        conf_obj_path: *const c_char,
        obj_payload: *const c_char,
        out_fd: c_int,
        error: *mut *mut NetplanError,
    ) -> GBoolean;

    pub fn netplan_util_dump_yaml_subtree(
        prefix: *const c_char,
        input_fd: c_int,
        output_fd: c_int,
        error: *mut *mut NetplanError,
    ) -> GBoolean;
}
