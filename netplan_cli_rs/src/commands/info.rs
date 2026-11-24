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

//! `netplan info` – show available libnetplan features.
//!
//! Feature flags are extracted from `src/*.{h,c}` at build time by `build.rs`
//! and embedded as a `&[&str]` constant, mirroring `_features.py`.

use crate::argparse::Arg;
use crate::cli;
use anyhow::Result;
use serde_json::json;

// Feature flags generated at build time from /* netplan-feature: <name> */
// annotations in the C source tree.
mod features {
    include!(concat!(env!("OUT_DIR"), "/features.rs"));
}

pub struct InfoArgs {
    json: bool,
}

/// `netplan info [--json | --yaml]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "info", cli::description("info"));
    p.add_mutually_exclusive(vec![
        Arg::new(&["--json"])
            .store_const("version_format", "json")
            .help("Output version and features in JSON format"),
        Arg::new(&["--yaml"])
            .store_const("version_format", "yaml")
            .help("Output version and features in YAML format"),
    ]);
    let ns = cli::parse_leaf(&p, args)?;
    run(InfoArgs {
        json: ns.str("version_format").as_deref() == Some("json"),
    })
}

pub fn run(args: InfoArgs) -> Result<i32> {
    let flags = features::FEATURE_FLAGS;
    let website = "https://netplan.io/";

    if args.json {
        // Produce output equivalent to json.dumps(…, indent=2)
        let value = json!({
            "netplan.io": {
                "website": website,
                "features": flags,
            }
        });
        println!("{}", serde_json::to_string_pretty(&value)?);
    } else {
        // YAML (default) – matches Python's hand-formatted output exactly
        println!("netplan.io:");
        println!("  website: \"{}\"", website);
        println!("  features:");
        for f in flags {
            println!("  - {}", f);
        }
    }
    Ok(0)
}
