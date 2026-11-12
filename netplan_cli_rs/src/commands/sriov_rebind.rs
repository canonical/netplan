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

//! `netplan rebind` – rebind SR-IOV virtual functions to their driver.
//!
//! Port of `netplan_cli/cli/commands/sriov_rebind.py`.
//!
//! PORT PENDING: only the argument handling exists so far.

use anyhow::Result;

use crate::argparse::{Arg, Nargs};
use crate::{cli, py};

/// `netplan rebind [--root-dir DIR] [netdevs ...]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "rebind", cli::description("rebind"));
    p.add(
        Arg::new(&["--root-dir"])
            .default_str("/")
            .help("Search for configuration files in this root directory instead of /"),
    );
    p.add(
        Arg::new(&["netdevs"])
            .nargs(Nargs::ZeroOrMore)
            .help("Space separated list of PF interface names"),
    );
    let _ns = cli::parse_leaf(&p, args)?;
    Err(py::Exception::err(
        "NotImplementedError",
        "netplan rebind is not implemented yet",
    ))
}
