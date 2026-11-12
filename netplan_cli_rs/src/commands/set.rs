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

//! `netplan set` – write or delete a configuration setting.
//!
//! Mirrors `netplan_cli/cli/commands/set.py` faithfully, including the
//! double-parser logic required by `--origin-hint`.

use std::io::Seek;
use std::io::SeekFrom;

use crate::argparse::Arg;
use crate::cli;
use anyhow::{anyhow, Context, Result};

use crate::{netplan, utils};

const FALLBACK_FILENAME: &str = "70-netplan-set.yaml";

pub struct SetArgs {
    key_value: String,
    origin_hint: Option<String>,
    root_dir: String,
}

/// `netplan set key=value [--origin-hint HINT] [--root-dir DIR]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "set", cli::description("set"));
    p.add(
        Arg::new(&["key_value"])
            .help("The nested key=value pair in dotted format. Value can be NULL to delete a key."),
    );
    p.add(Arg::new(&["--origin-hint"]).help(
        "Can be used to help choose a name for the overwrite YAML file. A .yaml suffix will be appended automatically.",
    ));
    p.add(
        Arg::new(&["--root-dir"])
            .default_str("/")
            .help("Overwrite configuration files in this root directory instead of /"),
    );
    let ns = cli::parse_leaf(&p, args)?;
    run(SetArgs {
        key_value: ns.str("key_value").unwrap_or_default(),
        origin_hint: ns.str("origin_hint"),
        root_dir: ns.str("root_dir").unwrap_or_default(),
    })
}

pub fn run(args: SetArgs) -> Result<i32> {
    // Validate origin-hint is non-empty when provided
    if let Some(ref hint) = args.origin_hint {
        if hint.is_empty() {
            return Err(anyhow!("Invalid/empty origin-hint"));
        }
    }

    let filename: Option<String> = args.origin_hint.as_deref().map(|h| format!("{}.yaml", h));

    // Split "key=value" on the first '='
    let (key_raw, value) = args
        .key_value
        .split_once('=')
        .context("Invalid value specified")?;

    // Prefix with "network." if not already present
    let key = if key_raw.starts_with("network") {
        key_raw.to_string()
    } else {
        format!("network.{}", key_raw)
    };

    // Split the key path (respecting escaped dots)
    let yaml_path = utils::split_dotted_path(&key);

    // ── Build the YAML patch ──────────────────────────────────────────────────
    // Returns a seekable memfd containing the patch document.
    let mut patch_file = netplan::create_yaml_patch(yaml_path.iter().map(String::as_str), value)
        .context("Failed to create YAML patch")?;

    // ── First parser: validate the full intended configuration ────────────────
    {
        let mut parser = netplan::Parser::new()?;

        // Tell the parser which fields are to be deleted (value=="NULL")
        patch_file.seek(SeekFrom::Start(0))?;
        parser.load_nullable_fields(&patch_file)?;

        // Load full existing hierarchy
        parser.load_yaml_hierarchy(&args.root_dir)?;

        // Apply the patch
        patch_file.seek(SeekFrom::Start(0))?;
        parser.load_yaml_from_fd(&patch_file)?;

        // Validate by importing into a state (errors bubble up here)
        let mut state = netplan::State::new()?;
        state.import_parser_results(&mut parser)?;

        // If no origin-hint, write via update_yaml_hierarchy and done
        if filename.is_none() {
            state.update_yaml_hierarchy(FALLBACK_FILENAME, &args.root_dir)?;
            return Ok(0);
        }
    }

    // ── Second parser: target only the origin-hint output file ───────────────
    // This ensures settings that should go into <hint>.yaml are written there,
    // even if they appear in other pre-existing YAML files.
    let filename = filename.unwrap();
    {
        let mut parser_out = netplan::Parser::new()?;

        // Nullable fields: ignore these settings when scanning the hierarchy
        patch_file.seek(SeekFrom::Start(0))?;
        parser_out.load_nullable_fields(&patch_file)?;

        // Nullable overrides: redirect any netdefs/globals found in the patch
        // to the output file, ignoring their presence in other YAML files
        patch_file.seek(SeekFrom::Start(0))?;
        parser_out.load_nullable_overrides(&patch_file, &filename)?;

        // Load the full hierarchy (some netdefs/globals are now overridden)
        parser_out.load_yaml_hierarchy(&args.root_dir)?;

        // Apply the patch
        patch_file.seek(SeekFrom::Start(0))?;
        parser_out.load_yaml_from_fd(&patch_file)?;

        // Import and write to the origin-hint file
        let mut state_out = netplan::State::new()?;
        state_out.import_parser_results(&mut parser_out)?;
        state_out.write_yaml_file(&filename, &args.root_dir)?;
    }

    Ok(0)
}
