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

//! `netplan get` – query a configuration key from the YAML hierarchy.
//!
//! Mirrors `netplan_cli/cli/commands/get.py` and the `NetplanConfigState`
//! class in `cli/state.py`.

use crate::argparse::{Arg, Nargs};
use crate::cli;
use anyhow::Result;

use crate::{netplan, utils};

pub struct GetArgs {
    key: String,
    root_dir: String,
}

/// `netplan get [key] [--root-dir DIR]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "get", cli::description("get"));
    p.add(
        Arg::new(&["key"])
            .nargs(Nargs::Optional)
            .default_str("all")
            .help("The nested key in dotted format"),
    );
    p.add(
        Arg::new(&["--root-dir"])
            .default_str("/")
            .help("Read configuration files from this root directory instead of /"),
    );
    let ns = cli::parse_leaf(&p, args)?;
    run(GetArgs {
        key: ns.str("key").unwrap_or_default(),
        root_dir: ns.str("root_dir").unwrap_or_default(),
    })
}

pub fn run(args: GetArgs) -> Result<i32> {
    // Parse the YAML hierarchy and validate
    let state = netplan::load_state(&args.root_dir)?;

    // Dump the full config to a string
    let full_yaml = state.dump_yaml()?;

    let output = if args.key == "all" {
        full_yaml
    } else {
        // Build the path prefix: prepend "network" if not already present
        let key = if args.key.starts_with("network") {
            args.key.clone()
        } else {
            format!("network.{}", args.key)
        };

        // Split on '.' but treat '\.' as a literal dot (negative lookbehind)
        let prefix = utils::split_dotted_path(&key);

        netplan::dump_yaml_subtree(prefix.iter().map(String::as_str), &full_yaml)?
    };

    // Print without a trailing newline, matching Python's `print(state, end='')`
    print!("{}", output);
    Ok(0)
}
