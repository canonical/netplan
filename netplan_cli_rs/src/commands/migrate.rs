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

//! `netplan migrate` – convert /etc/network/interfaces to netplan YAML.
//!
//! Mirrors `netplan_cli/cli/commands/migrate.py`.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;
use std::fs;
use std::net::{Ipv4Addr, Ipv6Addr};
use std::path::{Path, PathBuf};
use std::str::FromStr;

use crate::argparse::Arg;
use crate::cli;
use anyhow::{anyhow, Context, Result};

use crate::utils;

// ── Argument types ────────────────────────────────────────────────────────────

pub struct MigrateArgs {
    root_dir: String,
    dry_run: bool,
}

/// `netplan migrate [--root-dir DIR] [--dry-run]` (test command)
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "migrate", cli::description("migrate"));
    p.add(
        Arg::new(&["--root-dir"]).help(
            "Search for and generate configuration files in this root directory instead of /",
        ),
    );
    p.add(
        Arg::new(&["--dry-run"]).store_true().help(
            "Print converted netplan configuration to stdout instead of writing/changing files",
        ),
    );
    let ns = cli::parse_leaf(&p, args)?;
    run(MigrateArgs {
        // `if self.root_dir:` -- unset or empty means /
        root_dir: ns
            .str("root_dir")
            .filter(|r| !r.is_empty())
            .unwrap_or_else(|| "/".to_string()),
        dry_run: ns.bool("dry_run"),
    })
}

// ── Parsed ifupdown state ─────────────────────────────────────────────────────

/// `iface` address family, as used in `iface <name> <family> <method>` stanzas.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AddressFamily {
    Inet,
    Inet6,
}

impl fmt::Display for AddressFamily {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            AddressFamily::Inet => "inet",
            AddressFamily::Inet6 => "inet6",
        })
    }
}

/// `iface` configuration method, as used in `iface <name> <family> <method>` stanzas.
#[derive(Debug, Clone, Copy)]
enum Method {
    Loopback,
    Dhcp,
    Static,
}

#[derive(Debug)]
struct IfaceConfig {
    method: Method,
    options: HashMap<String, String>,
}

/// Parsed `/etc/network/interfaces` configuration.
struct IfupdownConfig {
    /// `iface name -> [(address family, config)]`, in file order.
    ifaces: Vec<(String, Vec<(AddressFamily, IfaceConfig)>)>,
    /// Interfaces marked `auto` / `allow-auto` / `allow-hotplug`.
    auto_ifaces: HashSet<String>,
}

// ── Entry point ───────────────────────────────────────────────────────────────

pub fn run(args: MigrateArgs) -> Result<i32> {
    let rootdir = args.root_dir.trim_end_matches('/').to_string();
    let dry_run = args.dry_run;

    let config = match parse_ifupdown(&rootdir) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            return Ok(2);
        }
    };
    let IfupdownConfig {
        ifaces,
        auto_ifaces,
    } = config;

    // map: iface → BTreeMap of netplan keys
    let mut ethernets: BTreeMap<String, IfNetplanConfig> = BTreeMap::new();

    for (iface, families) in &ifaces {
        for (family, config) in families {
            if !auto_ifaces.contains(iface.as_str()) {
                eprintln!("{iface}: non-automatic interfaces are not supported");
                return Ok(2);
            }

            match config.method {
                Method::Loopback => {
                    // systemd sets up lo automatically
                }
                Method::Dhcp => {
                    let c = ethernets.entry(iface.clone()).or_default();
                    let mut opts = config.options.clone();

                    if let Err(e) = parse_dns_options(&mut opts, c) {
                        eprintln!("{e}");
                        return Ok(2);
                    }
                    if let Err(e) = parse_hwaddress(iface, &mut opts, c) {
                        eprintln!("{e}");
                        return Ok(2);
                    }

                    if !opts.is_empty() {
                        eprintln!(
                            "{iface}: option(s) {} are not supported for dhcp method",
                            opts.keys().cloned().collect::<Vec<_>>().join(", ")
                        );
                        return Ok(2);
                    }

                    if *family == AddressFamily::Inet {
                        c.dhcp4 = Some(true);
                    } else {
                        c.dhcp6 = Some(true);
                    }
                }
                Method::Static => {
                    let base_iface = if iface.contains(':') {
                        iface.split(':').next().unwrap().to_string()
                    } else {
                        iface.clone()
                    };
                    let c = ethernets.entry(base_iface.clone()).or_default();
                    let mut opts = config.options.clone();

                    if let Err(e) = parse_dns_options(&mut opts, c) {
                        eprintln!("{e}");
                        return Ok(2);
                    }
                    if let Err(e) = parse_mtu(&base_iface, &mut opts, c) {
                        eprintln!("{e}");
                        return Ok(2);
                    }
                    if let Err(e) = parse_hwaddress(&base_iface, &mut opts, c) {
                        eprintln!("{e}");
                        return Ok(2);
                    }

                    if *family == AddressFamily::Inet {
                        let supported = ["address", "netmask", "gateway"];
                        let unsupported = ["broadcast", "metric", "pointopoint", "scope"];
                        if let Some(code) =
                            check_options(&base_iface, *family, &opts, &supported, &unsupported)
                        {
                            return Ok(code);
                        }

                        let addr_str = match opts.get("address") {
                            Some(a) => a,
                            None => {
                                eprintln!("{base_iface}: no address supplied in static method");
                                return Ok(2);
                            }
                        };

                        let (addr_part, net_spec) = if addr_str.contains('/') {
                            let addr_part = addr_str.split('/').next().unwrap().to_string();
                            (addr_part, addr_str.clone())
                        } else {
                            let netmask = match opts.get("netmask") {
                                Some(n) => n,
                                None => {
                                    eprintln!(
                                        "{base_iface}: address does not specify prefix length, and netmask not specified"
                                    );
                                    return Ok(2);
                                }
                            };
                            (addr_str.clone(), format!("{addr_str}/{netmask}"))
                        };

                        let ipaddr = match Ipv4Addr::from_str(&addr_part) {
                            Ok(a) => a,
                            Err(e) => {
                                eprintln!(
                                    "{base_iface}: error parsing \"{addr_part}\" as an IPv4 address: {e}"
                                );
                                return Ok(2);
                            }
                        };

                        let prefix = match parse_ipv4_network(&net_spec) {
                            Ok(p) => p,
                            Err(e) => {
                                eprintln!(
                                    "{base_iface}: error parsing \"{net_spec}\" as an IPv4 network: {e}"
                                );
                                return Ok(2);
                            }
                        };

                        c.addresses.push(format!("{ipaddr}/{prefix}"));

                        if let Some(gw) = opts.get("gateway") {
                            c.gateway4 = Some(gw.clone());
                        }
                    } else {
                        // inet6
                        let supported = ["address", "netmask", "gateway", "accept_ra"];
                        let unsupported = [
                            "metric",
                            "media",
                            "autoconf",
                            "privext",
                            "scope",
                            "preferred-lifetime",
                            "dad-attempts",
                            "dad-interval",
                        ];
                        if let Some(code) =
                            check_options(&base_iface, *family, &opts, &supported, &unsupported)
                        {
                            return Ok(code);
                        }

                        let addr_str = match opts.get("address") {
                            Some(a) => a,
                            None => {
                                eprintln!("{base_iface}: no address supplied in static method");
                                return Ok(2);
                            }
                        };

                        let (addr_part, net_spec) = if addr_str.contains('/') {
                            let addr_part = addr_str.split('/').next().unwrap().to_string();
                            (addr_part, addr_str.clone())
                        } else {
                            let netmask = match opts.get("netmask") {
                                Some(n) => n,
                                None => {
                                    eprintln!(
                                        "{base_iface}: address does not specify prefix length, and netmask not specified"
                                    );
                                    return Ok(2);
                                }
                            };
                            (addr_str.clone(), format!("{addr_str}/{netmask}"))
                        };

                        let ipaddr = match Ipv6Addr::from_str(&addr_part) {
                            Ok(a) => a,
                            Err(e) => {
                                eprintln!(
                                    "{base_iface}: error parsing \"{addr_part}\" as an IPv6 address: {e}"
                                );
                                return Ok(2);
                            }
                        };

                        let prefix = match parse_ipv6_network(&net_spec) {
                            Ok(p) => p,
                            Err(e) => {
                                eprintln!(
                                    "{base_iface}: error parsing \"{net_spec}\" as an IPv6 network: {e}"
                                );
                                return Ok(2);
                            }
                        };

                        c.addresses.push(format!("{ipaddr}/{prefix}"));

                        if let Some(gw) = opts.get("gateway") {
                            c.gateway6 = Some(gw.clone());
                        }

                        if let Some(ra) = opts.get("accept_ra") {
                            match ra.as_str() {
                                "0" => c.accept_ra = Some(false),
                                "1" => c.accept_ra = Some(true),
                                "2" => {
                                    eprintln!("{base_iface}: netplan does not support accept_ra=2");
                                    return Ok(2);
                                }
                                other => {
                                    eprintln!(
                                        "{base_iface}: unexpected accept_ra value \"{other}\""
                                    );
                                    return Ok(2);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    let if_config = PathBuf::from(format!("{rootdir}/etc/network/interfaces"));

    if !ethernets.is_empty() {
        let yaml = render_yaml(&ethernets);
        if dry_run {
            print!("{yaml}");
        } else {
            let dest = PathBuf::from(format!("{rootdir}/etc/netplan/10-ifupdown.yaml"));
            if let Some(parent) = dest.parent() {
                fs::create_dir_all(parent)
                    .with_context(|| format!("Cannot create {:?}", parent))?;
            }
            // Use exclusive create (fail if exists)
            match fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&dest)
            {
                Ok(mut f) => {
                    use std::io::Write;
                    f.write_all(yaml.as_bytes())
                        .with_context(|| format!("failed to write {dest:?}"))?;
                    eprintln!("migration complete, wrote {}", dest.display());
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                    eprintln!(
                        "{} already exists; remove it if you want to run the migration again",
                        dest.display()
                    );
                    return Ok(3);
                }
                Err(e) => {
                    return Err(e).with_context(|| format!("failed to write {dest:?}"));
                }
            }
        }
    } else {
        eprintln!("ifupdown does not configure any interfaces, nothing to migrate");
    }

    if !dry_run {
        let converted = format!("{}.netplan-converted", if_config.display());
        eprintln!(
            "renaming {} to {}",
            if_config.display(),
            if_config.display()
        );
        fs::rename(&if_config, &converted)
            .with_context(|| format!("failed to rename {if_config:?}"))?;
    }

    Ok(0)
}

// ── Netplan config structure ──────────────────────────────────────────────────

#[derive(Debug, Default)]
struct IfNetplanConfig {
    dhcp4: Option<bool>,
    dhcp6: Option<bool>,
    addresses: Vec<String>,
    gateway4: Option<String>,
    gateway6: Option<String>,
    accept_ra: Option<bool>,
    mtu: Option<u32>,
    macaddress: Option<String>,
    nameservers_addresses: Vec<String>,
    nameservers_search: Vec<String>,
}

// ── Option parsers ────────────────────────────────────────────────────────────

fn parse_dns_options(opts: &mut HashMap<String, String>, c: &mut IfNetplanConfig) -> Result<()> {
    if let Some(ns) = opts.remove("dns-nameservers") {
        for s in ns.split_whitespace() {
            c.nameservers_addresses.push(s.to_string());
        }
    }
    if let Some(search) = opts.remove("dns-search") {
        for s in search.split_whitespace() {
            c.nameservers_search.push(s.to_string());
        }
    }
    Ok(())
}

fn parse_mtu(
    iface: &str,
    opts: &mut HashMap<String, String>,
    c: &mut IfNetplanConfig,
) -> Result<()> {
    if let Some(mtu_str) = opts.remove("mtu") {
        let mtu: u32 = mtu_str
            .parse()
            .map_err(|_| anyhow::anyhow!("{iface}: cannot parse \"{mtu_str}\" as an MTU"))?;
        if let Some(existing) = c.mtu {
            if existing != mtu {
                return Err(anyhow!(
                    "{iface}: tried to set MTU={mtu}, but already have MTU={existing}"
                ));
            }
        }
        c.mtu = Some(mtu);
    }
    Ok(())
}

fn parse_hwaddress(
    iface: &str,
    opts: &mut HashMap<String, String>,
    c: &mut IfNetplanConfig,
) -> Result<()> {
    if let Some(mac) = opts.remove("hwaddress") {
        if let Some(ref existing) = c.macaddress {
            if existing != &mac {
                return Err(anyhow!(
                    "{iface}: tried to set MAC {mac}, but already have MAC {existing}"
                ));
            }
        }
        c.macaddress = Some(mac);
    }
    Ok(())
}

fn check_options(
    iface: &str,
    family: AddressFamily,
    opts: &HashMap<String, String>,
    supported: &[&str],
    unsupported: &[&str],
) -> Option<i32> {
    for key in opts.keys() {
        if !supported.contains(&key.as_str()) {
            if unsupported.contains(&key.as_str()) {
                eprintln!("{iface}: unsupported {family} option \"{key}\"");
            } else {
                eprintln!("{iface}: unknown {family} option \"{key}\"");
            }
            return Some(2);
        }
    }
    None
}

// ── IP address/network helpers ────────────────────────────────────────────────

/// Parse "addr/prefix_or_netmask" → prefix length. Returns Err with message on failure.
fn parse_ipv4_network(spec: &str) -> Result<u8> {
    let (addr_part, mask_part) = spec.split_once('/').unwrap_or((spec, "32"));

    // Try parsing mask as a number first
    if let Ok(n) = mask_part.parse::<u8>() {
        if n > 32 {
            return Err(anyhow!("{addr_part}/{mask_part} has host bits set"));
        }
        return Ok(n);
    }

    // Try parsing as dotted-quad netmask
    let mask_addr = Ipv4Addr::from_str(mask_part)
        .map_err(|_| anyhow::anyhow!("Invalid netmask: {mask_part}"))?;
    let mask_bits = u32::from(mask_addr);

    // Validate it's a contiguous mask: leading 1-bits then all 0-bits.
    let leading_ones = mask_bits.leading_ones();
    let expected = if leading_ones == 32 {
        !0u32
    } else {
        !0u32 << (32 - leading_ones)
    };
    if mask_bits != expected {
        return Err(anyhow!("Non-contiguous netmask: {mask_part}"));
    }
    Ok(leading_ones as u8)
}

/// Parse "addr/prefix" for IPv6 → prefix length.
fn parse_ipv6_network(spec: &str) -> Result<u8> {
    let (addr_part, prefix_part) = match spec.split_once('/') {
        Some(p) => p,
        None => return Err(anyhow!("missing prefix length in {spec}")),
    };

    // Validate address
    Ipv6Addr::from_str(addr_part)
        .map_err(|e| anyhow::anyhow!("Invalid IPv6 address {addr_part}: {e}"))?;

    let prefix: u8 = prefix_part
        .parse()
        .map_err(|_| anyhow::anyhow!("Invalid prefix length: {prefix_part}"))?;
    if prefix > 128 {
        return Err(anyhow!("prefix length {prefix} > 128"));
    }
    Ok(prefix)
}

// ── YAML renderer ─────────────────────────────────────────────────────────────

/// A single netplan YAML value rendered under an interface's mapping.
enum FieldValue<'a> {
    Bool(bool),
    Str(&'a str),
    Num(u32),
    List(&'a [String]),
    Nameservers {
        addresses: &'a [String],
        search: &'a [String],
    },
}

fn render_yaml(ethernets: &BTreeMap<String, IfNetplanConfig>) -> String {
    use std::fmt::Write as _;

    let mut out = String::new();
    out.push_str("network:\n");
    out.push_str("  ethernets:\n");

    for (iface, c) in ethernets {
        writeln!(out, "    {iface}:").unwrap();

        // Collect (key, value) pairs that are set, in the order Python's
        // yaml.dump would emit them (alphabetical by key).
        let mut fields: Vec<(&str, FieldValue)> = Vec::new();
        if let Some(v) = c.accept_ra {
            fields.push(("accept_ra", FieldValue::Bool(v)));
        }
        if !c.addresses.is_empty() {
            fields.push(("addresses", FieldValue::List(&c.addresses)));
        }
        if let Some(v) = c.dhcp4 {
            fields.push(("dhcp4", FieldValue::Bool(v)));
        }
        if let Some(v) = c.dhcp6 {
            fields.push(("dhcp6", FieldValue::Bool(v)));
        }
        if let Some(ref v) = c.gateway4 {
            fields.push(("gateway4", FieldValue::Str(v)));
        }
        if let Some(ref v) = c.gateway6 {
            fields.push(("gateway6", FieldValue::Str(v)));
        }
        if let Some(ref v) = c.macaddress {
            fields.push(("macaddress", FieldValue::Str(v)));
        }
        if let Some(v) = c.mtu {
            fields.push(("mtu", FieldValue::Num(v)));
        }
        if !c.nameservers_addresses.is_empty() || !c.nameservers_search.is_empty() {
            fields.push((
                "nameservers",
                FieldValue::Nameservers {
                    addresses: &c.nameservers_addresses,
                    search: &c.nameservers_search,
                },
            ));
        }

        for (key, value) in fields {
            match value {
                FieldValue::Bool(b) => writeln!(out, "      {key}: {b}").unwrap(),
                FieldValue::Str(s) => writeln!(out, "      {key}: {s}").unwrap(),
                FieldValue::Num(n) => writeln!(out, "      {key}: {n}").unwrap(),
                FieldValue::List(items) => {
                    writeln!(out, "      {key}:").unwrap();
                    for item in items {
                        writeln!(out, "      - {item}").unwrap();
                    }
                }
                FieldValue::Nameservers { addresses, search } => {
                    writeln!(out, "      nameservers:").unwrap();
                    // Python yaml.dump sorts: addresses before search
                    if !addresses.is_empty() {
                        writeln!(out, "        addresses:").unwrap();
                        for addr in addresses {
                            writeln!(out, "        - {addr}").unwrap();
                        }
                    }
                    if !search.is_empty() {
                        writeln!(out, "        search:").unwrap();
                        for s in search {
                            writeln!(out, "        - {s}").unwrap();
                        }
                    }
                }
            }
        }
    }

    out.push_str("  version: 2\n");
    out
}

// ── ifupdown parser ───────────────────────────────────────────────────────────

/// Parse `/etc/network/interfaces` (including `source`/`source-directory` includes).
fn parse_ifupdown(rootdir: &str) -> Result<IfupdownConfig> {
    let lines = ifupdown_lines_from_file(rootdir, "/etc/network/interfaces")?;

    let mut ifaces: Vec<(String, Vec<(AddressFamily, IfaceConfig)>)> = Vec::new();
    let mut auto: HashSet<String> = HashSet::new();
    let mut in_iface: Option<String> = None;
    let mut in_family: Option<AddressFamily> = None;

    for line in &lines {
        let fields: Vec<&str> = line.split_whitespace().collect();
        if fields.is_empty() {
            continue;
        }

        match fields.as_slice() {
            ["auto" | "allow-auto" | "allow-hotplug", value] => {
                in_iface = None;
                in_family = None;
                auto.insert((*value).to_string());
            }
            ["mapping", _value] => {
                return Err(anyhow!("mapping stanza is not supported"));
            }
            ["no-scripts", _value] => {
                in_iface = None;
                in_family = None;
            }
            ["iface", name, family_str, method_str] => {
                let family = match *family_str {
                    "inet" => AddressFamily::Inet,
                    "inet6" => AddressFamily::Inet6,
                    other => return Err(anyhow!("Unknown address family {other}")),
                };
                let method = match *method_str {
                    "loopback" => Method::Loopback,
                    "static" => Method::Static,
                    "dhcp" => Method::Dhcp,
                    other => return Err(anyhow!("Unsupported method {other}")),
                };

                let iface_name = (*name).to_string();
                let config = IfaceConfig {
                    method,
                    options: HashMap::new(),
                };
                match ifaces.iter_mut().find(|(n, _)| n == &iface_name) {
                    Some(entry) => entry.1.push((family, config)),
                    None => ifaces.push((iface_name.clone(), vec![(family, config)])),
                }
                in_iface = Some(iface_name);
                in_family = Some(family);
            }
            [stanza @ ("auto" | "allow-auto" | "allow-hotplug" | "mapping" | "no-scripts"), ..] => {
                return Err(anyhow!(
                    "Expected 1 field for stanza type {stanza} but got {}",
                    fields.len() - 1
                ));
            }
            ["iface", ..] => {
                return Err(anyhow!(
                    "Expected 3 fields for stanza type iface but got {}",
                    fields.len() - 1
                ));
            }
            _ => match (&in_iface, &in_family) {
                (Some(iface_name), Some(family)) => {
                    let val = line
                        .split_once(char::is_whitespace)
                        .map(|(_, v)| v)
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    if let Some(entry) = ifaces.iter_mut().find(|(n, _)| n == iface_name) {
                        if let Some((_, cfg)) = entry.1.iter_mut().find(|(f, _)| f == family) {
                            cfg.options.insert(fields[0].to_string(), val);
                        }
                    }
                }
                _ => return Err(anyhow!("Unknown stanza type {}", fields[0])),
            },
        }
    }

    Ok(IfupdownConfig {
        ifaces,
        auto_ifaces: auto,
    })
}

/// Read and normalize ifupdown config lines, resolving source/source-directory includes.
fn ifupdown_lines_from_file(rootdir: &str, path: &str) -> Result<Vec<String>> {
    let full_path = format!("{rootdir}{path}");
    let rootdir_prefix_len = rootdir.len();

    let content = match fs::read_to_string(&full_path) {
        Ok(c) => c,
        Err(_) => return Ok(Vec::new()),
    };

    let curdir = Path::new(&full_path)
        .parent()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_default();

    let mut lines = Vec::new();

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        if line.starts_with("source-directory ") {
            let arg = line.split_whitespace().nth(1).unwrap_or("");
            let dir = expand_source_arg(rootdir, &curdir, arg);
            let dir_path = Path::new(&dir);
            if let Ok(entries) = fs::read_dir(dir_path) {
                let mut names: Vec<String> = entries
                    .filter_map(|e| e.ok())
                    .map(|e| e.file_name().to_string_lossy().into_owned())
                    .filter(|name| {
                        name.chars()
                            .all(|c| c.is_alphanumeric() || c == '_' || c == '-')
                    })
                    .collect();
                names.sort();
                for fname in names {
                    let sub_path = format!("{}/{fname}", &dir[rootdir_prefix_len..]);
                    lines.extend(ifupdown_lines_from_file(rootdir, &sub_path)?);
                }
            }
        } else if line.starts_with("source ") {
            let arg = line.split_whitespace().nth(1).unwrap_or("");
            let pattern = expand_source_arg(rootdir, &curdir, arg);
            let mut matched = glob_paths(&pattern)?;
            matched.sort();
            for full in matched {
                let sub_path = &full[rootdir_prefix_len..];
                lines.extend(ifupdown_lines_from_file(rootdir, sub_path)?);
            }
        } else {
            lines.push(line.to_string());
        }
    }

    Ok(lines)
}

/// Expand a source/source-directory argument relative to rootdir and curdir.
fn expand_source_arg(rootdir: &str, curdir: &str, arg: &str) -> String {
    if arg.starts_with('/') {
        format!("{rootdir}{arg}")
    } else {
        format!("{curdir}/{arg}")
    }
}

/// Resolve a `source` glob pattern to matching file paths.
///
/// Only the `*` wildcard is supported (matching ifupdown's own behaviour);
/// `?`/`[`/`]` are rejected rather than silently treated as glob character
/// classes by the underlying `glob` crate.
fn glob_paths(pattern: &str) -> Result<Vec<String>> {
    if pattern.contains(['?', '[', ']']) {
        return Err(anyhow!("unsupported glob pattern: {pattern}"));
    }
    Ok(utils::glob_paths(pattern))
}
