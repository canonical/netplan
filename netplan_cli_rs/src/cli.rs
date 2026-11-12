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

//! Command dispatch, mirroring `netplan_cli/cli/core.py` and
//! `utils.NetplanCommand`.
//!
//! Python parses in stages: the top-level parser only knows `--debug` and
//! the subcommand names (each subparser is empty), so everything after the
//! subcommand -- plus any unknown top-level option -- is handed to the
//! command, which parses it with its own parser and ignores what it does not
//! recognise. A leftover `help` argument prints usage (exit 64).

use anyhow::Result;

use crate::argparse::{Arg, ArgParser, Namespace};
use crate::py;

/// `os.EX_USAGE`
pub const EX_USAGE: i32 = 64;

/// The subcommands in the order Python registers them
/// (`inspect.getmembers()` sorts by class name), with their descriptions.
const COMMANDS: &[(&str, &str)] = &[
    ("apply", "Apply current netplan config to running system"),
    (
        "generate",
        "Generate backend specific configuration files from /etc/netplan/*.yaml",
    ),
    (
        "get",
        "Get a setting by specifying a nested key like \"ethernets.eth0.addresses\", or \"all\"",
    ),
    ("info", "Show available features"),
    ("ip", "Retrieve IP information from the system"),
    ("migrate", "Migration of /etc/network/interfaces to netplan"),
    (
        "set",
        "Add new setting by specifying a dotted key=value pair like ethernets.eth0.dhcp4=true",
    ),
    (
        "rebind",
        "Rebind SR-IOV virtual functions of given physical functions to their driver",
    ),
    ("status", "Query networking state of the running system"),
    (
        "try",
        "Try to apply a new netplan config to running system, with automatic rollback",
    ),
];

/// Commands only registered when `ENABLE_TEST_COMMANDS` is set.
const TEST_COMMANDS: &[&str] = &["migrate"];

pub fn description(command_id: &str) -> &'static str {
    COMMANDS
        .iter()
        .find(|(name, _)| *name == command_id)
        .map(|(_, d)| *d)
        .unwrap_or("")
}

/// The parser every `NetplanCommand` starts with.
pub fn command_parser(argv0: &str, command_id: &str, description: &str) -> ArgParser {
    let mut p = ArgParser::new(&format!("{argv0} {command_id}"), description, true);
    p.add(
        Arg::new(&["--debug"])
            .store_true()
            .help("Enable debug messages"),
    );
    p.add(Arg::new(&["--breakpoint"]).store_true().hidden());
    p
}

/// A non-leaf command parser: `subcommand` plus a `help` subcommand.
pub fn group_parser(argv0: &str, command_id: &str, description: &str) -> ArgParser {
    let mut p = command_parser(argv0, command_id, description);
    p.add_subparsers("subcommand");
    p.add_parser("help", Some("Show this help message"), true);
    p
}

/// `NetplanCommand.print_usage()`: help on stderr, exit 64.
pub fn print_usage(p: &ArgParser) -> anyhow::Error {
    py::flush_stdout();
    eprint!("{}", p.format_help());
    py::Exit(EX_USAGE).into()
}

/// `NetplanCommand.parse_args()` + `run_command()` for a leaf command:
/// returns the parsed namespace, or the exit the parse resulted in.
pub fn parse_leaf(p: &ArgParser, args: &[String]) -> Result<Namespace> {
    let (ns, rest) = p.parse(args).map_err(|e| py::Exit(e.report()))?;
    if rest.iter().any(|a| a == "help") {
        return Err(print_usage(p));
    }
    Ok(ns)
}

/// `NetplanCommand.parse_args()` for a non-leaf command: returns the chosen
/// subcommand and the arguments left for it.
pub fn parse_group(p: &ArgParser, args: &[String]) -> Result<(String, Vec<String>)> {
    let (ns, rest) = p.parse(args).map_err(|e| py::Exit(e.report()))?;
    let Some(sub) = ns.str("subcommand") else {
        py::flush_stdout();
        eprintln!("You need to specify a command");
        return Err(print_usage(p));
    };
    if sub == "help" {
        return Err(print_usage(p));
    }
    Ok((sub, rest))
}

/// `Netplan().main()`: returns the process exit status.
pub fn main(argv0: &str, args: &[String]) -> i32 {
    // Netplan.__init__()
    // SAFETY: single-threaded, before anything reads the environment.
    unsafe {
        std::env::set_var("LC_ALL", "C.UTF-8");
        if std::env::var_os("PATH").is_none() {
            std::env::set_var("PATH", "/usr/bin:/snap/bin");
        }
    }

    let test_commands = std::env::var_os("ENABLE_TEST_COMMANDS").is_some_and(|v| !v.is_empty());
    let mut top = ArgParser::new(&format!("{argv0} "), "Network configuration in YAML", true);
    top.add(
        Arg::new(&["--debug"])
            .store_true()
            .help("Enable debug messages"),
    );
    top.add(Arg::new(&["--breakpoint"]).store_true().hidden());
    top.add_subparsers("subcommand");
    top.add_parser("help", Some("Show this help message"), true);
    for (name, desc) in COMMANDS {
        if TEST_COMMANDS.contains(name) && !test_commands {
            continue;
        }
        top.add_parser(name, Some(desc), false);
    }

    let (ns, rest) = match top.parse(args) {
        Ok(r) => r,
        Err(e) => return e.report(),
    };
    let Some(subcommand) = ns.str("subcommand") else {
        py::flush_stdout();
        eprintln!("You need to specify a command");
        return py::report_uncaught(&print_usage(&top));
    };

    if ns.bool("debug") {
        py::enable_debug_logging();
        // SAFETY: still single-threaded.
        unsafe { std::env::set_var("G_MESSAGES_DEBUG", "all") };
    }

    let result = match subcommand.as_str() {
        "help" => Err(print_usage(&top)),
        cmd => crate::commands::run(cmd, argv0, &rest),
    };
    match result {
        Ok(code) => code,
        Err(e) => py::report_uncaught(&e),
    }
}
