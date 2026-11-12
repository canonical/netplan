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

//! `netplan ip leases` – display DHCP lease information for a network interface.
//!
//! Port of `netplan_cli/cli/commands/ip.py`.

use std::path::Path;

use anyhow::Result;

use crate::argparse::Arg;
use crate::utils::{self, sub};
use crate::{cli, py};

/// `netplan ip <subcommand>`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::group_parser(argv0, "ip", cli::description("ip"));
    p.add_parser("leases", Some("Display IP leases"), false);
    let (sub, rest) = cli::parse_group(&p, args)?;
    match sub.as_str() {
        "leases" => leases(argv0, &rest),
        _ => unreachable!("argparse only accepts known subcommands"),
    }
}

/// `netplan ip leases INTERFACE [--root-dir DIR]`
fn leases(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "ip leases", "Display IP leases");
    p.add(Arg::new(&["interface"]).help("Interface for which to display IP lease settings."));
    p.add(
        Arg::new(&["--root-dir"])
            .help("Search for configuration files in this root directory instead of /"),
    );
    let ns = cli::parse_leaf(&p, args)?;
    let interface = ns.str("interface").unwrap_or_default();
    let root_dir = ns.str("root_dir").filter(|r| !r.is_empty());

    if interface == "help" {
        return Err(cli::print_usage(&p));
    }

    // XXX: This code path is only still supported for legacy reasons and
    // not supposed to be called in the scope of a systemd generator. The
    // 'netplan status' command should be used instead.
    let generator = utils::get_generator_path();
    let mut argv: Vec<&str> = vec![&generator];
    if let Some(r) = &root_dir {
        argv.extend(["--root-dir", r]);
    }
    argv.extend(["--mapping", &interface]);

    // Extract out of the generator our mapping in a dict.
    py::debug(&format!(
        "command ip leases: running {}",
        utils::py_repr_list(&argv)
    ));
    let out = match sub::check_output(&argv) {
        Ok(o) => o,
        Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => {
            py::flush_stdout();
            eprintln!("No lease found for interface '{interface}' (not managed by Netplan)");
            return py::exit(1);
        }
        Err(e) => return Err(e),
    };
    let mut mapping: Vec<(String, String)> = vec![];
    for keyvalue in out.split(',') {
        let parts: Vec<&str> = keyvalue.trim().split('=').collect();
        if parts.len() != 2 {
            return Err(py::Exception::err("ValueError", unpack_error(parts.len())));
        }
        match mapping.iter_mut().find(|(k, _)| k == parts[0]) {
            Some(e) => e.1 = parts[1].to_string(),
            None => mapping.push((parts[0].to_string(), parts[1].to_string())),
        }
    }

    find_lease_file(&interface, root_dir.as_deref(), &mapping)
}

/// The ValueError of `key, value = s.split('=')`
fn unpack_error(n: usize) -> String {
    if n < 2 {
        format!("not enough values to unpack (expected 2, got {n})")
    } else {
        format!("too many values to unpack (expected 2, got {n})")
    }
}

fn find_lease_file(
    interface: &str,
    root_dir: Option<&str>,
    mapping: &[(String, String)],
) -> Result<i32> {
    let get = |key: &str| -> Result<String> {
        mapping
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.clone())
            .ok_or_else(|| py::Exception::err("KeyError", utils::py_repr_str(key)))
    };
    let backend = get("backend")?;
    let (pattern, nm) = match backend.as_str() {
        "networkd" => ("run/systemd/netif/leases/{lease_id}", false),
        "NetworkManager" => (
            "var/lib/NetworkManager/internal-{lease_id}-{interface}.lease",
            true,
        ),
        other => return Err(py::Exception::err("KeyError", utils::py_repr_str(other))),
    };

    let result = (|| -> Result<()> {
        let lease_id = if nm {
            lease_method_nm_connection(interface)?
        } else {
            lease_method_ifindex(interface)?
        };
        // We found something to build the path to the lease file with,
        // at this point we may have something to look at; but if not,
        // we'll rely on open() throwing an error.
        let rel = pattern
            .replace("{lease_id}", &lease_id)
            .replace("{interface}", interface);
        let mut path = match root_dir {
            Some(r) => format!("{}/{rel}", abspath(r).trim_end_matches('/')),
            None => format!("/{rel}"),
        };
        // Fallback to 'dhclient' if no lease of NetworkManager's
        // internal DHCP client is found
        if !Path::new(&path).is_file() {
            path = path.replace("NetworkManager/internal-", "NetworkManager/dhclient-");
        }
        let content = utils::read_text(&path)?;
        for line in content.split_inclusive('\n') {
            crate::pyprintln!("{}", line.trim_end());
        }
        Ok(())
    })();
    match result {
        Ok(()) => Ok(0),
        Err(e) if sub::is_exception(&e, &["Exception"]) => {
            py::flush_stdout();
            eprintln!("No lease found for interface '{interface}': {e}");
            py::exit(1)
        }
        Err(e) => Err(e),
    }
}

fn lease_method_ifindex(interface: &str) -> Result<String> {
    let ifindex_f = format!("/sys/class/net/{interface}/ifindex");
    let result = utils::read_text(&ifindex_f).and_then(|content| {
        content
            .split_inclusive('\n')
            .next()
            .map(|l| l.trim().to_string())
            .ok_or_else(|| py::Exception::err("IndexError", "list index out of range"))
    });
    if let Err(e) = &result {
        py::debug(&format!("Cannot read file {ifindex_f}: {e}"));
    }
    result
}

fn lease_method_nm_connection(interface: &str) -> Result<String> {
    // FIXME: handle older versions of NM where 'nmcli dev show' doesn't exist
    let found = (|| -> Result<Option<String>> {
        let nmcli_dev_out = utils::nmcli_out(&["dev", "show", interface])?;
        for line in utils::py_splitlines(&nmcli_dev_out) {
            if line.contains("GENERAL.CONNECTION") {
                let conn_id = field_after_colon(line)?;
                let nmcli_con_out = utils::nmcli_out(&["con", "show", "id", &conn_id])?;
                for line in utils::py_splitlines(&nmcli_con_out) {
                    if line.contains("connection.uuid") {
                        return Ok(Some(field_after_colon(line)?));
                    }
                }
            }
        }
        Ok(None)
    })();
    match found {
        Ok(Some(uuid)) => Ok(uuid),
        Ok(None) => Err(py::Exception::err(
            "Exception",
            "Could not find a NetworkManager connection for the interface",
        )),
        Err(e) if sub::is_exception(&e, &["Exception"]) => Err(py::Exception::err(
            "Exception",
            format!("Could not find a NetworkManager connection for the interface: {e}"),
        )),
        Err(e) => Err(e),
    }
}

/// `line.split(':')[1].rstrip().strip()`
fn field_after_colon(line: &str) -> Result<String> {
    line.split(':')
        .nth(1)
        .map(|s| s.trim().to_string())
        .ok_or_else(|| py::Exception::err("IndexError", "list index out of range"))
}

/// `os.path.abspath(path)`
fn abspath(path: &str) -> String {
    let joined = if path.starts_with('/') {
        path.to_string()
    } else {
        let cwd = std::env::current_dir()
            .map(|c| c.to_string_lossy().into_owned())
            .unwrap_or_default();
        format!("{cwd}/{path}")
    };
    let mut parts: Vec<&str> = vec![];
    for c in joined.split('/') {
        match c {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            c => parts.push(c),
        }
    }
    format!("/{}", parts.join("/"))
}
