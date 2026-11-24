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

//! netplan – a drop-in Rust replacement for the Python netplan CLI
//! (`netplan_cli`). See `py.rs` and `cli.rs` for how Python's runtime
//! behaviour and argument handling are reproduced.

use std::process::ExitCode;

mod argparse;
mod cli;
mod commands;
mod configmanager;
mod ffi;
mod ipaddress;
mod netplan;
mod ovs;
mod py;
mod pyjson;
mod pyyaml;
mod rich;
mod sriov;
mod state;
mod state_diff;
mod utils;
#[allow(dead_code)] // no user at the moment (`netplan status` used to)
mod yaml;

fn main() -> ExitCode {
    let mut argv = std::env::args_os().map(|a| a.to_string_lossy().into_owned());
    let argv0 = argv.next().unwrap_or_else(|| "netplan".into());
    let args: Vec<String> = argv.collect();
    let code = cli::main(&argv0, &args);
    py::flush_stdout();
    // Like sys.exit(): the status is reduced to 8 bits by the OS
    ExitCode::from((code & 0xff) as u8)
}
