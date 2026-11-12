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
//! Mirrors `netplan_cli/cli/commands/migrate.py`, including its quirks:
//! Python's text file reading, `str.split()`, `int()` and `ipaddress`
//! semantics, and PyYAML's `yaml.dump()` output.

use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::io::Write as _;

use anyhow::Result;

use crate::argparse::Arg;
use crate::utils::{self, py_repr_str};
use crate::{cli, py, pyprintln};

pub struct MigrateArgs {
    /// `--root-dir`, as given (`self.root_dir`)
    root_dir: Option<String>,
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
        root_dir: ns.str("root_dir"),
        dry_run: ns.bool("dry_run"),
    })
}

// ── Python string helpers ─────────────────────────────────────────────────────

/// `str.isspace()` for a single character.
fn py_isspace(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

/// `str.strip()`
fn py_strip(s: &str) -> &str {
    s.trim_matches(py_isspace)
}

/// `str.split()`
fn py_split(s: &str) -> Vec<&str> {
    s.split(py_isspace).filter(|w| !w.is_empty()).collect()
}

/// `str.split(maxsplit=1)`
fn py_split_max1(s: &str) -> Vec<&str> {
    let s = s.trim_start_matches(py_isspace);
    if s.is_empty() {
        return vec![];
    }
    match s.find(py_isspace) {
        None => vec![s],
        Some(i) => {
            let rest = s[i..].trim_start_matches(py_isspace);
            if rest.is_empty() {
                vec![&s[..i]]
            } else {
                vec![&s[..i], rest]
            }
        }
    }
}

/// `s[n:]` (code point based)
fn py_slice_from(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((i, _)) => &s[i..],
        None => "",
    }
}

/// `os.path.dirname()`
fn py_dirname(p: &str) -> &str {
    let i = p.rfind('/').map(|i| i + 1).unwrap_or(0);
    let head = &p[..i];
    if !head.is_empty() && !head.bytes().all(|b| b == b'/') {
        head.trim_end_matches('/')
    } else {
        head
    }
}

/// `os.path.split()`
fn py_path_split(p: &str) -> (&str, &str) {
    let i = p.rfind('/').map(|i| i + 1).unwrap_or(0);
    let (head, tail) = (&p[..i], &p[i..]);
    if !head.is_empty() && !head.bytes().all(|b| b == b'/') {
        (head.trim_end_matches('/'), tail)
    } else {
        (head, tail)
    }
}

/// `os.path.join(a, b)` for a relative `b`
fn py_join(a: &str, b: &str) -> String {
    if b.starts_with('/') {
        b.to_string()
    } else if a.is_empty() || a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

/// First code points of the Unicode decimal digit runs (`unicodedata.decimal`).
const DECIMAL_ZEROS: &[u32] = &[
    0x30, 0x660, 0x6F0, 0x7C0, 0x966, 0x9E6, 0xA66, 0xAE6, 0xB66, 0xBE6, 0xC66, 0xCE6, 0xD66,
    0xDE6, 0xE50, 0xED0, 0xF20, 0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90,
    0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620, 0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0, 0xFF10,
    0x104A0, 0x10D30, 0x10D40, 0x11066, 0x110F0, 0x11136, 0x111D0, 0x112F0, 0x11450, 0x114D0,
    0x11650, 0x116C0, 0x116D0, 0x116DA, 0x11730, 0x118E0, 0x11950, 0x11BF0, 0x11C50, 0x11D50,
    0x11DA0, 0x11F50, 0x16130, 0x16A60, 0x16AC0, 0x16B50, 0x16D70, 0x1CCF0, 0x1D7CE, 0x1D7D8,
    0x1D7E2, 0x1D7EC, 0x1D7F6, 0x1E140, 0x1E2F0, 0x1E4F0, 0x1E5F1, 0x1E950, 0x1FBF0,
];

fn py_decimal(c: char) -> Option<u8> {
    let c = c as u32;
    DECIMAL_ZEROS
        .iter()
        .find(|&&z| (z..z + 10).contains(&c))
        .map(|z| (c - z) as u8)
}

/// A Python `int`, kept as its decimal string (`str(int)`).
#[derive(Debug, Clone, PartialEq)]
struct PyInt(String);

impl PyInt {
    /// `int(s)` for a string without surrounding whitespace.
    fn parse(s: &str) -> Option<PyInt> {
        let (neg, rest) = match s.chars().next() {
            Some('-') => (true, &s[1..]),
            Some('+') => (false, &s[1..]),
            _ => (false, s),
        };
        let mut digits = String::new();
        let mut prev_underscore = true;
        for c in rest.chars() {
            if c == '_' {
                if prev_underscore {
                    return None;
                }
                prev_underscore = true;
            } else {
                digits.push((b'0' + py_decimal(c)?) as char);
                prev_underscore = false;
            }
        }
        // empty, or a trailing underscore; sys.get_int_max_str_digits()
        if prev_underscore || digits.len() > 4300 {
            return None;
        }
        let digits = digits.trim_start_matches('0');
        Some(PyInt(match (digits.is_empty(), neg) {
            (true, _) => "0".to_string(),
            (false, true) => format!("-{digits}"),
            (false, false) => digits.to_string(),
        }))
    }
}

// ── Python text file reading ──────────────────────────────────────────────────

/// `TextIOWrapper._CHUNK_SIZE`
const CHUNK_SIZE: usize = 8192;

/// The lines `for line in open(path)` yields before a `UnicodeDecodeError`
/// (if any) is raised, simulating TextIOWrapper's chunked incremental
/// UTF-8 decoding with universal newlines.
fn py_text_lines(bytes: &[u8]) -> (Vec<String>, Option<String>) {
    let mut lines = Vec::new();
    let mut pending: Vec<u8> = Vec::new();
    let mut pendingcr = false;
    let mut buf = String::new();
    let mut pos = 0;
    loop {
        let chunk = &bytes[pos..(pos + CHUNK_SIZE).min(bytes.len())];
        pos += chunk.len();
        let last = chunk.is_empty();
        let mut data = std::mem::take(&mut pending);
        data.extend_from_slice(chunk);
        let mut out = match std::str::from_utf8(&data) {
            Ok(s) => s.to_string(),
            Err(e) => {
                let start = e.valid_up_to();
                let (end, reason) = match e.error_len() {
                    None if !last => {
                        pending = data[start..].to_vec();
                        data.truncate(start);
                        (0, "")
                    }
                    None => (data.len(), "unexpected end of data"),
                    Some(n) if (0xc2..=0xf4).contains(&data[start]) => {
                        (start + n, "invalid continuation byte")
                    }
                    Some(n) => (start + n, "invalid start byte"),
                };
                if !reason.is_empty() {
                    let msg = if end - start == 1 {
                        format!(
                            "'utf-8' codec can't decode byte 0x{:02x} in position {start}: {reason}",
                            data[start]
                        )
                    } else {
                        format!(
                            "'utf-8' codec can't decode bytes in position {start}-{}: {reason}",
                            end - 1
                        )
                    };
                    return (lines, Some(msg));
                }
                String::from_utf8(data).unwrap_or_default()
            }
        };
        // IncrementalNewlineDecoder(translate=True)
        if pendingcr && (!out.is_empty() || last) {
            out.insert(0, '\r');
            pendingcr = false;
        }
        if out.ends_with('\r') && !last {
            out.pop();
            pendingcr = true;
        }
        buf.push_str(&out.replace("\r\n", "\n").replace('\r', "\n"));
        while let Some(i) = buf.find('\n') {
            lines.push(buf[..=i].to_string());
            buf.drain(..=i);
        }
        if last {
            if !buf.is_empty() {
                lines.push(buf);
            }
            return (lines, None);
        }
    }
}

// ── Parsed ifupdown state ─────────────────────────────────────────────────────

/// An insertion-ordered `dict` of str → str.
#[derive(Debug, Clone, Default)]
struct Options(Vec<(String, String)>);

impl Options {
    fn get(&self, key: &str) -> Option<&String> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    fn set(&mut self, key: &str, value: String) {
        match self.0.iter_mut().find(|(k, _)| k == key) {
            Some(entry) => entry.1 = value,
            None => self.0.push((key.to_string(), value)),
        }
    }

    fn remove(&mut self, key: &str) -> Option<String> {
        let i = self.0.iter().position(|(k, _)| k == key)?;
        Some(self.0.remove(i).1)
    }

    fn keys(&self) -> impl Iterator<Item = &str> {
        self.0.iter().map(|(k, _)| k.as_str())
    }

    /// `repr(dict)`
    fn repr(&self) -> String {
        let items: Vec<String> = self
            .0
            .iter()
            .map(|(k, v)| format!("{}: {}", py_repr_str(k), py_repr_str(v)))
            .collect();
        format!("{{{}}}", items.join(", "))
    }
}

#[derive(Debug, Clone)]
struct IfaceConfig {
    method: String,
    options: Options,
}

impl IfaceConfig {
    fn repr(&self) -> String {
        format!(
            "{{'method': {}, 'options': {}}}",
            py_repr_str(&self.method),
            self.options.repr()
        )
    }
}

/// iface name → family → config, in insertion order (OrderedDicts)
type Ifaces = Vec<(String, Vec<(String, IfaceConfig)>)>;

fn value_error(msg: String) -> anyhow::Error {
    py::Exception::err("ValueError", msg)
}

/// Whether `err` is a Python `ValueError` (or subclass), which
/// `command_migrate()` catches.
fn as_value_error(err: &anyhow::Error) -> Option<&str> {
    match err.downcast_ref::<py::Exception>() {
        Some(e) if e.kind == "ValueError" || e.kind == "UnicodeDecodeError" => Some(&e.message),
        _ => None,
    }
}

// ── Entry point ───────────────────────────────────────────────────────────────

#[derive(Debug, Default)]
struct Nameservers {
    addresses: Option<Vec<String>>,
    search: Option<Vec<String>>,
}

/// One entry of `network.ethernets`.
#[derive(Debug, Default)]
struct EthConfig {
    accept_ra: Option<bool>,
    addresses: Option<Vec<String>>,
    dhcp4: Option<bool>,
    dhcp6: Option<bool>,
    gateway4: Option<String>,
    gateway6: Option<String>,
    macaddress: Option<String>,
    mtu: Option<PyInt>,
    nameservers: Option<Nameservers>,
}

pub fn run(args: MigrateArgs) -> Result<i32> {
    let root_dir = args.root_dir.unwrap_or_default();

    let (ifaces, auto_ifaces) = match parse_ifupdown(&root_dir) {
        Ok(r) => r,
        Err(e) => match as_value_error(&e) {
            Some(msg) => {
                py::error(msg);
                return py::exit(2);
            }
            None => return Err(e),
        },
    };

    // netplan_config['network']['ethernets'], sorted the way yaml.dump sorts keys
    let mut netplan_config: Option<BTreeMap<String, EthConfig>> = None;

    for (iface_name, family_config) in &ifaces {
        // `iface` is rebound for interface aliases and stays so for the
        // following families of the same interface
        let mut iface = iface_name.clone();
        for (family, config) in family_config {
            py::debug(&format!(
                "Converting {iface} family {family} {}",
                config.repr()
            ));
            if !auto_ifaces.contains(&iface) {
                py::error(&format!(
                    "{iface}: non-automatic interfaces are not supported"
                ));
                return py::exit(2);
            }
            let mut options = config.options.clone();
            match config.method.as_str() {
                "loopback" => {
                    // both systemd and modern ifupdown set up lo automatically
                    py::debug(&format!("Ignoring loopback interface {iface}"));
                }
                "dhcp" => {
                    let c = netplan_config
                        .get_or_insert_with(BTreeMap::new)
                        .entry(iface.clone())
                        .or_default();
                    parse_dns_options(&mut options, c);
                    parse_hwaddress(&iface, &mut options, c)?;
                    if !options.0.is_empty() {
                        py::error(&format!(
                            "{iface}: option(s) {} are not supported for dhcp method",
                            options.keys().collect::<Vec<_>>().join(", ")
                        ));
                        return py::exit(2);
                    }
                    if family == "inet" {
                        c.dhcp4 = Some(true);
                    } else {
                        c.dhcp6 = Some(true);
                    }
                }
                "static" => {
                    // Handle interface aliases
                    if iface.contains(':') {
                        iface = iface.split(':').next().unwrap_or_default().to_string();
                    }
                    let c = netplan_config
                        .get_or_insert_with(BTreeMap::new)
                        .entry(iface.clone())
                        .or_default();
                    c.addresses.get_or_insert_with(Vec::new);
                    parse_dns_options(&mut options, c);
                    parse_mtu(&iface, &mut options, c)?;
                    parse_hwaddress(&iface, &mut options, c)?;

                    let inet = family == "inet";
                    let (supported, unsupported): (&[&str], &[&str]) = if inet {
                        (
                            &["address", "netmask", "gateway"],
                            &["broadcast", "metric", "pointopoint", "scope"],
                        )
                    } else {
                        (
                            &["address", "netmask", "gateway", "accept_ra"],
                            &[
                                "metric",
                                "media",
                                "autoconf",
                                "privext",
                                "scope",
                                "preferred-lifetime",
                                "dad-attempts",
                                "dad-interval",
                            ],
                        )
                    };
                    // bad_opts is a set: Python's iteration order is
                    // arbitrary, unsupported options win over unknown ones
                    let bad_opts: Vec<&str> =
                        options.keys().filter(|k| !supported.contains(k)).collect();
                    if let Some(o) = bad_opts.iter().find(|k| unsupported.contains(k)) {
                        py::error(&format!("{iface}: unsupported {family} option \"{o}\""));
                        return py::exit(2);
                    }
                    if let Some(o) = bad_opts.first() {
                        py::error(&format!("{iface}: unknown {family} option \"{o}\""));
                        return py::exit(2);
                    }

                    // the address may contain a /prefix suffix, or
                    // the netmask property may be used. It's not clear
                    // what happens if both are supplied.
                    let Some(address) = options.get("address") else {
                        py::error(&format!("{iface}: no address supplied in static method"));
                        return py::exit(2);
                    };
                    let (addr_spec, net_spec) = if address.contains('/') {
                        (
                            address.split('/').next().unwrap_or_default().to_string(),
                            address.clone(),
                        )
                    } else {
                        let Some(netmask) = options.get("netmask") else {
                            py::error(&format!(
                                "{iface}: address does not specify prefix length, and netmask not specified"
                            ));
                            return py::exit(2);
                        };
                        (address.clone(), format!("{address}/{netmask}"))
                    };

                    let (version, addr, prefixlen) = if inet {
                        ("IPv4", ipv4_address(&addr_spec), ipv4_network(&net_spec))
                    } else {
                        ("IPv6", ipv6_address(&addr_spec), ipv6_network(&net_spec))
                    };
                    let ipaddr = match addr {
                        Ok(a) => a,
                        Err(e) => {
                            py::error(&format!(
                                "{iface}: error parsing \"{addr_spec}\" as an {version} address: {e}"
                            ));
                            return py::exit(2);
                        }
                    };
                    let prefixlen = match prefixlen {
                        Ok(p) => p,
                        Err(NetError::Netmask(e)) => {
                            py::error(&format!(
                                "{iface}: error parsing \"{net_spec}\" as an {version} network: {e}"
                            ));
                            return py::exit(2);
                        }
                        Err(NetError::Address(e)) => {
                            return Err(py::Exception::err("ipaddress.AddressValueError", e));
                        }
                    };
                    c.addresses
                        .get_or_insert_with(Vec::new)
                        .push(format!("{ipaddr}/{prefixlen}"));

                    if let Some(gateway) = options.get("gateway") {
                        // validate?
                        if inet {
                            c.gateway4 = Some(gateway.clone());
                        } else {
                            c.gateway6 = Some(gateway.clone());
                        }
                    }

                    if !inet {
                        if let Some(accept_ra) = options.get("accept_ra") {
                            match accept_ra.as_str() {
                                "0" => c.accept_ra = Some(false),
                                "1" => c.accept_ra = Some(true),
                                "2" => {
                                    py::error(&format!(
                                        "{iface}: netplan does not support accept_ra=2"
                                    ));
                                    return py::exit(2);
                                }
                                other => {
                                    py::error(&format!(
                                        "{iface}: unexpected accept_ra value \"{other}\""
                                    ));
                                    return py::exit(2);
                                }
                            }
                        }
                    }
                }
                other => {
                    // unreachable: parse_ifupdown() only accepts the above
                    py::error(&format!("{iface}: method {other} is not supported"));
                    return py::exit(2);
                }
            }
        }
    }

    let base = if root_dir.is_empty() { "/" } else { &root_dir };
    let if_config = py_join(base, "etc/network/interfaces");

    if let Some(ethernets) = &netplan_config {
        let netplan_yaml = dump_yaml(ethernets);
        if args.dry_run {
            pyprintln!("{netplan_yaml}");
        } else {
            let dest = py_join(base, "etc/netplan/10-ifupdown.yaml");
            match makedirs(py_dirname(&dest)) {
                Ok(()) => {}
                Err((e, _)) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err((e, path)) => return Err(utils::oserror(&e, std::path::Path::new(&path))),
            }
            let mut f = match fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&dest)
            {
                Ok(f) => f,
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                    py::error(&format!(
                        "{dest} already exists; remove it if you want to run the migration again"
                    ));
                    return py::exit(3);
                }
                Err(e) => return Err(utils::oserror(&e, std::path::Path::new(&dest))),
            };
            f.write_all(netplan_yaml.as_bytes())
                .map_err(|e| utils::oserror(&e, std::path::Path::new(&dest)))?;
            drop(f);
            py::info(&format!("migration complete, wrote {dest}"));
        }
    } else {
        py::info("ifupdown does not configure any interfaces, nothing to migrate");
    }

    if !args.dry_run {
        py::info(&format!(
            "renaming {if_config} to {if_config}.netplan-converted"
        ));
        let converted = format!("{if_config}.netplan-converted");
        if let Err(e) = fs::rename(&if_config, &converted) {
            let errno = e.raw_os_error().unwrap_or(0);
            let kind = match errno {
                2 => "FileNotFoundError",
                1 | 13 => "PermissionError",
                17 => "FileExistsError",
                20 => "NotADirectoryError",
                21 => "IsADirectoryError",
                _ => "OSError",
            };
            return Err(py::Exception::err(
                kind,
                format!(
                    "[Errno {errno}] {}: {} -> {}",
                    nix::errno::Errno::from_raw(errno).desc(),
                    py_repr_str(&if_config),
                    py_repr_str(&converted)
                ),
            ));
        }
    }

    Ok(0)
}

/// `os.makedirs(name)`; on error, returns the path the failing call was for.
fn makedirs(name: &str) -> std::result::Result<(), (std::io::Error, String)> {
    let (mut head, mut tail) = py_path_split(name);
    if tail.is_empty() {
        (head, tail) = py_path_split(head);
    }
    if !head.is_empty() && !tail.is_empty() && !std::path::Path::new(head).exists() {
        match makedirs(head) {
            Err((e, _)) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(e) => return Err(e),
            Ok(()) => {}
        }
        if tail == "." {
            return Ok(());
        }
    }
    fs::create_dir(name).map_err(|e| (e, name.to_string()))
}

// ── Option parsers ────────────────────────────────────────────────────────────

/// Parse dns options (dns-nameservers and dns-search) into the interface
/// configuration.
fn parse_dns_options(options: &mut Options, c: &mut EthConfig) {
    if let Some(value) = options.remove("dns-nameservers") {
        let ns = c.nameservers.get_or_insert_with(Nameservers::default);
        let addresses = ns.addresses.get_or_insert_with(Vec::new);
        // allow multiple spaces in the dns-nameservers entry
        addresses.extend(value.split(' ').filter(|s| !s.is_empty()).map(String::from));
    }
    if let Some(value) = options.remove("dns-search") {
        let ns = c.nameservers.get_or_insert_with(Nameservers::default);
        let search = ns.search.get_or_insert_with(Vec::new);
        // allow multiple spaces in the dns-search entry
        search.extend(value.split(' ').filter(|s| !s.is_empty()).map(String::from));
    }
}

fn parse_mtu(iface: &str, options: &mut Options, c: &mut EthConfig) -> Result<()> {
    if let Some(value) = options.get("mtu") {
        let Some(mtu) = PyInt::parse(value) else {
            py::error(&format!("{iface}: cannot parse \"{value}\" as an MTU"));
            return py::exit(2);
        };
        if let Some(existing) = &c.mtu {
            if *existing != mtu {
                py::error(&format!(
                    "{iface}: tried to set MTU={}, but already have MTU={}",
                    mtu.0, existing.0
                ));
                return py::exit(2);
            }
        }
        c.mtu = Some(mtu);
        options.remove("mtu");
    }
    Ok(())
}

fn parse_hwaddress(iface: &str, options: &mut Options, c: &mut EthConfig) -> Result<()> {
    if let Some(value) = options.remove("hwaddress") {
        if let Some(existing) = &c.macaddress {
            if *existing != value {
                py::error(&format!(
                    "{iface}: tried to set MAC {value}, but already have MAC {existing}"
                ));
                return py::exit(2);
            }
        }
        c.macaddress = Some(value);
    }
    Ok(())
}

// ── ipaddress ─────────────────────────────────────────────────────────────────

/// Errors of `IPv4Network()` / `IPv6Network()`: only `NetmaskValueError`
/// is caught by migrate, an `AddressValueError` escapes as a traceback.
enum NetError {
    Netmask(String),
    Address(String),
}

/// `IPv4Address(s)._ip`
fn ipv4_int(ip_str: &str) -> std::result::Result<u32, String> {
    if ip_str.is_empty() {
        return Err("Address cannot be empty".to_string());
    }
    let octets: Vec<&str> = ip_str.split('.').collect();
    if octets.len() != 4 {
        return Err(format!("Expected 4 octets in {}", py_repr_str(ip_str)));
    }
    let mut ip: u32 = 0;
    for octet in octets {
        let v = parse_octet(octet).map_err(|e| format!("{e} in {}", py_repr_str(ip_str)))?;
        ip = (ip << 8) | v;
    }
    Ok(ip)
}

fn parse_octet(octet: &str) -> std::result::Result<u32, String> {
    if octet.is_empty() {
        return Err("Empty octet not permitted".to_string());
    }
    if !octet.bytes().all(|b| b.is_ascii_digit()) {
        return Err(format!(
            "Only decimal digits permitted in {}",
            py_repr_str(octet)
        ));
    }
    if octet.len() > 3 {
        return Err(format!(
            "At most 3 characters permitted in {}",
            py_repr_str(octet)
        ));
    }
    if octet != "0" && octet.starts_with('0') {
        return Err(format!(
            "Leading zeros are not permitted in {}",
            py_repr_str(octet)
        ));
    }
    let v: u32 = octet.parse().unwrap_or(0);
    if v > 255 {
        return Err(format!("Octet {v} (> 255) not permitted"));
    }
    Ok(v)
}

fn ipv4_str(ip: u32) -> String {
    let b = ip.to_be_bytes();
    format!("{}.{}.{}.{}", b[0], b[1], b[2], b[3])
}

/// `str(IPv4Address(s))`
fn ipv4_address(s: &str) -> std::result::Result<String, String> {
    if s.contains('/') {
        return Err(format!("Unexpected '/' in {}", py_repr_str(s)));
    }
    ipv4_int(s).map(ipv4_str)
}

/// `_split_optional_netmask()`
fn split_net(s: &str) -> std::result::Result<(&str, &str), NetError> {
    let parts: Vec<&str> = s.split('/').collect();
    match parts.as_slice() {
        [addr, mask] => Ok((addr, mask)),
        [_, _, _, ..] => Err(NetError::Address(format!(
            "Only one '/' permitted in {}",
            py_repr_str(s)
        ))),
        _ => unreachable!("the network spec always contains a '/'"),
    }
}

/// `_prefix_from_prefix_string()`
fn prefix_from_prefix_string(s: &str, max: u32) -> std::result::Result<u32, NetError> {
    let invalid = || NetError::Netmask(format!("{} is not a valid netmask", py_repr_str(s)));
    if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
        return Err(invalid());
    }
    let digits = s.trim_start_matches('0');
    match digits.parse::<u32>() {
        Ok(p) if p <= max => Ok(p),
        _ if digits.is_empty() => Ok(0),
        _ => Err(invalid()),
    }
}

/// `_prefix_from_ip_int()` for IPv4
fn prefix_from_ip_int(ip: u32) -> Option<u32> {
    let trailing_zeroes = if ip == 0 { 32 } else { ip.trailing_zeros() };
    let prefixlen = 32 - trailing_zeroes;
    let leading_ones = if trailing_zeroes == 32 {
        0
    } else {
        ip >> trailing_zeroes
    };
    let all_ones = if prefixlen == 32 {
        u32::MAX
    } else {
        (1u32 << prefixlen) - 1
    };
    (leading_ones == all_ones).then_some(prefixlen)
}

/// `IPv4Network(s, strict=False).prefixlen`
fn ipv4_network(s: &str) -> std::result::Result<u32, NetError> {
    let (addr, mask) = split_net(s)?;
    ipv4_address(addr).map_err(NetError::Address)?;
    match prefix_from_prefix_string(mask, 32) {
        Ok(p) => Ok(p),
        Err(_) => {
            let invalid =
                || NetError::Netmask(format!("{} is not a valid netmask", py_repr_str(mask)));
            let ip = ipv4_int(mask).map_err(|_| invalid())?;
            prefix_from_ip_int(ip)
                .or_else(|| prefix_from_ip_int(!ip))
                .ok_or_else(invalid)
        }
    }
}

/// `IPv6Address._ip_int_from_string()`
fn ipv6_int(ip_str: &str) -> std::result::Result<u128, String> {
    const HEXTET_COUNT: usize = 8;
    if ip_str.is_empty() {
        return Err("Address cannot be empty".to_string());
    }
    let len = ip_str.chars().count();
    if len > 45 {
        let shorten = if len > 100 {
            let chars: Vec<char> = ip_str.chars().collect();
            format!(
                "{}({} chars elided){}",
                chars[..45].iter().collect::<String>(),
                len - 90,
                chars[len - 45..].iter().collect::<String>()
            )
        } else {
            ip_str.to_string()
        };
        return Err(format!(
            "At most 45 characters expected in {}",
            py_repr_str(&shorten)
        ));
    }
    let max_parts = HEXTET_COUNT + 1;
    let mut parts: Vec<String> = ip_str
        .splitn(max_parts + 1, ':')
        .map(String::from)
        .collect();
    if parts.len() < 3 {
        return Err(format!(
            "At least 3 parts expected in {}",
            py_repr_str(ip_str)
        ));
    }
    if parts.last().is_some_and(|p| p.contains('.')) {
        let v4 = parts.pop().unwrap_or_default();
        let ipv4 = ipv4_address(&v4)
            .and_then(|_| ipv4_int(&v4))
            .map_err(|e| format!("{e} in {}", py_repr_str(ip_str)))?;
        parts.push(format!("{:x}", (ipv4 >> 16) & 0xffff));
        parts.push(format!("{:x}", ipv4 & 0xffff));
    }
    if parts.len() > max_parts {
        return Err(format!(
            "At most {} colons permitted in {}",
            max_parts - 1,
            py_repr_str(ip_str)
        ));
    }
    let mut skip_index = None;
    for (i, part) in parts.iter().enumerate().take(parts.len() - 1).skip(1) {
        if part.is_empty() {
            if skip_index.is_some() {
                return Err(format!(
                    "At most one '::' permitted in {}",
                    py_repr_str(ip_str)
                ));
            }
            skip_index = Some(i);
        }
    }
    let (parts_hi, parts_lo, parts_skipped);
    if let Some(skip) = skip_index {
        let mut hi = skip;
        let mut lo = parts.len() - skip - 1;
        if parts[0].is_empty() {
            hi -= 1;
            if hi != 0 {
                return Err(format!(
                    "Leading ':' only permitted as part of '::' in {}",
                    py_repr_str(ip_str)
                ));
            }
        }
        if parts[parts.len() - 1].is_empty() {
            lo -= 1;
            if lo != 0 {
                return Err(format!(
                    "Trailing ':' only permitted as part of '::' in {}",
                    py_repr_str(ip_str)
                ));
            }
        }
        if hi + lo >= HEXTET_COUNT {
            return Err(format!(
                "Expected at most {} other parts with '::' in {}",
                HEXTET_COUNT - 1,
                py_repr_str(ip_str)
            ));
        }
        (parts_hi, parts_lo, parts_skipped) = (hi, lo, HEXTET_COUNT - (hi + lo));
    } else {
        if parts.len() != HEXTET_COUNT {
            return Err(format!(
                "Exactly {HEXTET_COUNT} parts expected without '::' in {}",
                py_repr_str(ip_str)
            ));
        }
        if parts[0].is_empty() {
            return Err(format!(
                "Leading ':' only permitted as part of '::' in {}",
                py_repr_str(ip_str)
            ));
        }
        if parts[parts.len() - 1].is_empty() {
            return Err(format!(
                "Trailing ':' only permitted as part of '::' in {}",
                py_repr_str(ip_str)
            ));
        }
        (parts_hi, parts_lo, parts_skipped) = (parts.len(), 0, 0);
    }
    let wrap = |e: String| format!("{e} in {}", py_repr_str(ip_str));
    let mut ip: u128 = 0;
    for part in &parts[..parts_hi] {
        ip = (ip << 16) | parse_hextet(part).map_err(wrap)?;
    }
    ip = ip.checked_shl(16 * parts_skipped as u32).unwrap_or(0);
    for part in &parts[parts.len() - parts_lo..] {
        ip = (ip << 16) | parse_hextet(part).map_err(wrap)?;
    }
    Ok(ip)
}

fn parse_hextet(s: &str) -> std::result::Result<u128, String> {
    if !s.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(format!("Only hex digits permitted in {}", py_repr_str(s)));
    }
    if s.chars().count() > 4 {
        return Err(format!(
            "At most 4 characters permitted in {}",
            py_repr_str(s)
        ));
    }
    u128::from_str_radix(s, 16)
        .map_err(|_| format!("invalid literal for int() with base 16: {}", py_repr_str(s)))
}

/// `_BaseV6._string_from_ip_int()`
fn ipv6_str_from_int(ip: u128) -> String {
    let hextets: Vec<String> = (0..8)
        .map(|i| format!("{:x}", (ip >> (112 - 16 * i)) & 0xffff))
        .collect();
    // _compress_hextets()
    let (mut best_start, mut best_len) = (0, 0);
    let (mut start, mut len) = (None, 0);
    for (i, h) in hextets.iter().enumerate() {
        if h == "0" {
            len += 1;
            let s = *start.get_or_insert(i);
            if len > best_len {
                best_len = len;
                best_start = s;
            }
        } else {
            len = 0;
            start = None;
        }
    }
    if best_len > 1 {
        let end = best_start + best_len;
        let mut out: Vec<String> = hextets[..best_start].to_vec();
        if best_start == 0 {
            out.push(String::new());
        }
        out.push(String::new());
        out.extend_from_slice(&hextets[end..]);
        if end == hextets.len() {
            out.push(String::new());
        }
        out.join(":")
    } else {
        hextets.join(":")
    }
}

/// `str(IPv6Address(s))`
fn ipv6_address(s: &str) -> std::result::Result<String, String> {
    if s.contains('/') {
        return Err(format!("Unexpected '/' in {}", py_repr_str(s)));
    }
    let (addr, scope) = match s.split_once('%') {
        None => (s, None),
        Some((_, scope)) if scope.is_empty() || scope.contains('%') => {
            return Err(format!("Invalid IPv6 address: \"{}\"", py_repr_str(s)));
        }
        Some((addr, scope)) => (addr, Some(scope)),
    };
    let ip = ipv6_int(addr)?;
    let ip_str = if ip >> 32 == 0xffff {
        format!(
            "{}:{}",
            ipv6_str_from_int(ip >> 32),
            ipv4_str((ip & 0xffff_ffff) as u32)
        )
    } else {
        ipv6_str_from_int(ip)
    };
    Ok(match scope {
        Some(scope) => format!("{ip_str}%{scope}"),
        None => ip_str,
    })
}

/// `IPv6Network(s, strict=False).prefixlen`
fn ipv6_network(s: &str) -> std::result::Result<u32, NetError> {
    let (addr, mask) = split_net(s)?;
    ipv6_address(addr).map_err(NetError::Address)?;
    prefix_from_prefix_string(mask, 128)
}

// ── ifupdown parser ───────────────────────────────────────────────────────────

/// Return normalized lines from ifupdown config.
///
/// This resolves "source" and "source-directory" includes.
fn ifupdown_lines_from_file(rootdir: &str, path: &str) -> Result<Vec<String>> {
    let mut lines = Vec::new();
    let rootdir_len = rootdir.chars().count() + 1;
    let name = format!("{rootdir}/{path}");
    let bytes = match fs::read(&name) {
        Ok(b) => b,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            py::debug(&format!("{rootdir}/{path} does not exist, ignoring"));
            return Ok(lines);
        }
        Err(e) => return Err(utils::oserror(&e, std::path::Path::new(&name))),
    };
    py::debug(&format!("reading {name}"));
    let (raw_lines, decode_error) = py_text_lines(&bytes);
    // `f` is the file object until a `for f in ...` loop rebinds it to a str
    let mut f_is_file = true;
    let curdir = py_dirname(&name).to_string();
    let expand_source_arg = |f_is_file: bool, line: &str| -> Result<String> {
        if !f_is_file {
            return Err(py::Exception::err(
                "AttributeError",
                "'str' object has no attribute 'name'",
            ));
        }
        let arg = py_split(line)[1];
        Ok(if arg.starts_with('/') {
            format!("{rootdir}{arg}")
        } else {
            format!("{curdir}/{arg}")
        })
    };

    for line in &raw_lines {
        // normalize, strip empty lines and comments
        let line = py_strip(line);
        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        if line.starts_with("source-directory ") {
            let d = expand_source_arg(f_is_file, line)?;
            let entries = match fs::read_dir(&d) {
                Ok(entries) => entries,
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                    py::debug(&format!("{rootdir}/{path} does not exist, ignoring"));
                    return Ok(lines);
                }
                Err(e) => return Err(utils::oserror(&e, std::path::Path::new(&d))),
            };
            for entry in entries {
                let entry = entry.map_err(|e| utils::oserror(&e, std::path::Path::new(&d)))?;
                f_is_file = false;
                let fname = entry.file_name().to_string_lossy().into_owned();
                // re.match('^[a-zA-Z0-9_-]+$', f)
                let stem = fname.strip_suffix('\n').unwrap_or(&fname);
                if !stem.is_empty()
                    && stem
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
                {
                    lines.extend(ifupdown_lines_from_file(
                        rootdir,
                        &py_join(py_slice_from(&d, rootdir_len), &fname),
                    )?);
                }
            }
        } else if line.starts_with("source ") {
            let pattern = expand_source_arg(f_is_file, line)?;
            for f in utils::glob_paths(&pattern) {
                f_is_file = false;
                lines.extend(ifupdown_lines_from_file(
                    rootdir,
                    py_slice_from(&f, rootdir_len),
                )?);
            }
        } else {
            lines.push(line.to_string());
        }
    }
    if let Some(msg) = decode_error {
        return Err(py::Exception::err("UnicodeDecodeError", msg));
    }
    Ok(lines)
}

/// Parse ifupdown configuration.
///
/// Return (iface_name → family → {method, options}, auto_ifaces) on
/// successful parsing, or a ValueError when encountering an invalid file or
/// ifupdown features which are not supported (such as "mapping").
fn parse_ifupdown(rootdir: &str) -> Result<(Ifaces, HashSet<String>)> {
    // read and normalize all lines from config, with resolving includes
    let lines = ifupdown_lines_from_file(rootdir, "/etc/network/interfaces")?;

    let mut ifaces: Ifaces = Vec::new();
    let mut auto: HashSet<String> = HashSet::new();
    // interface name and family if parsing options lines after iface stanza
    let mut in_options: Option<(String, String)> = None;

    // we now have resolved all includes and normalized lines
    for line in &lines {
        let fields = py_split(line);

        // expected number of fields for every possible keyword, excluding the keyword itself
        let exp_len = match fields[0] {
            "auto" | "allow-auto" | "allow-hotplug" | "mapping" | "no-scripts" => 1,
            "iface" => 3,
            _ => {
                // no known stanza field, are we in an iface stanza and parsing options?
                let Some((name, family)) = &in_options else {
                    return Err(value_error(format!("Unknown stanza type {}", fields[0])));
                };
                py::debug(&format!("in_options {name}, parsing as option: {line}"));
                let Some(value) = py_split_max1(line).get(1).map(|v| v.to_string()) else {
                    return Err(py::Exception::err("IndexError", "list index out of range"));
                };
                let config = ifaces
                    .iter_mut()
                    .find(|(n, _)| n == name)
                    .and_then(|(_, fams)| fams.iter_mut().find(|(f, _)| f == family))
                    .map(|(_, c)| c);
                if let Some(config) = config {
                    config.options.set(fields[0], value);
                }
                continue;
            }
        };
        py::debug(&format!(
            "line fields {} (expected length: {exp_len})",
            utils::py_repr_list(&fields)
        ));
        in_options = None; // stop option line parsing of iface stanza

        // do we have the expected #parameters?
        if fields.len() != exp_len + 1 {
            return Err(value_error(format!(
                "Expected {exp_len} fields for stanza type {} but got {}",
                fields[0],
                fields.len() - 1
            )));
        }

        // we have a valid stanza line now, handle them
        match fields[0] {
            "auto" | "allow-auto" | "allow-hotplug" => {
                auto.insert(fields[1].to_string());
            }
            "mapping" => return Err(value_error("mapping stanza is not supported".into())),
            "no-scripts" => {} // ignore these
            _ => {
                // iface
                if !["inet", "inet6"].contains(&fields[2]) {
                    return Err(value_error(format!("Unknown address family {}", fields[2])));
                }
                if !["loopback", "static", "dhcp"].contains(&fields[3]) {
                    return Err(value_error(format!("Unsupported method {}", fields[3])));
                }
                let config = IfaceConfig {
                    method: fields[3].to_string(),
                    options: Options::default(),
                };
                let families = match ifaces.iter_mut().position(|(n, _)| n == fields[1]) {
                    Some(i) => &mut ifaces[i].1,
                    None => {
                        ifaces.push((fields[1].to_string(), Vec::new()));
                        &mut ifaces.last_mut().unwrap().1
                    }
                };
                match families.iter_mut().find(|(f, _)| f == fields[2]) {
                    Some(entry) => entry.1 = config,
                    None => families.push((fields[2].to_string(), config)),
                }
                in_options = Some((fields[1].to_string(), fields[2].to_string()));
            }
        }
    }

    py::debug("final parsed interfaces and auto ifaces collected");
    Ok((ifaces, auto))
}

// ── yaml.dump() ───────────────────────────────────────────────────────────────

enum Node {
    Str(String),
    /// A non-str scalar (int or bool), always emitted plain
    Plain(String),
    Seq(Vec<Node>),
    Map(Vec<(String, Node)>),
}

fn str_list(items: &[String]) -> Node {
    Node::Seq(items.iter().map(|s| Node::Str(s.clone())).collect())
}

/// `yaml.dump({'network': {'ethernets': ..., 'version': 2}})`
fn dump_yaml(ethernets: &BTreeMap<String, EthConfig>) -> String {
    let mut eths = Vec::new();
    for (name, c) in ethernets {
        let mut m = Vec::new();
        let mut put = |k: &str, n: Node| m.push((k.to_string(), n));
        let b = |v: bool| Node::Plain(if v { "true" } else { "false" }.to_string());
        if let Some(v) = c.accept_ra {
            put("accept_ra", b(v));
        }
        if let Some(v) = &c.addresses {
            put("addresses", str_list(v));
        }
        if let Some(v) = c.dhcp4 {
            put("dhcp4", b(v));
        }
        if let Some(v) = c.dhcp6 {
            put("dhcp6", b(v));
        }
        if let Some(v) = &c.gateway4 {
            put("gateway4", Node::Str(v.clone()));
        }
        if let Some(v) = &c.gateway6 {
            put("gateway6", Node::Str(v.clone()));
        }
        if let Some(v) = &c.macaddress {
            put("macaddress", Node::Str(v.clone()));
        }
        if let Some(v) = &c.mtu {
            put("mtu", Node::Plain(v.0.clone()));
        }
        if let Some(ns) = &c.nameservers {
            let mut n = Vec::new();
            if let Some(v) = &ns.addresses {
                n.push(("addresses".to_string(), str_list(v)));
            }
            if let Some(v) = &ns.search {
                n.push(("search".to_string(), str_list(v)));
            }
            put("nameservers", Node::Map(n));
        }
        eths.push((name.clone(), Node::Map(m)));
    }
    let root = Node::Map(vec![(
        "network".to_string(),
        Node::Map(vec![
            ("ethernets".to_string(), Node::Map(eths)),
            ("version".to_string(), Node::Plain("2".to_string())),
        ]),
    )]);
    let mut e = Emitter::default();
    e.expect_node(&root, false, false);
    // DocumentEndEvent
    e.write_indent();
    e.out
}

/// The parts of `yaml.resolver.Resolver`'s implicit resolvers: whether a
/// plain scalar with this value would load as something other than a str.
fn resolves_to_non_str(v: &str) -> bool {
    const BOOLS: &[&str] = &[
        "yes", "Yes", "YES", "no", "No", "NO", "true", "True", "TRUE", "false", "False", "FALSE",
        "on", "On", "ON", "off", "Off", "OFF",
    ];
    const NULLS: &[&str] = &["~", "null", "Null", "NULL", ""];
    BOOLS.contains(&v)
        || NULLS.contains(&v)
        || ["<<", "=", "!", "&", "*"].contains(&v)
        || is_yaml_float(v.as_bytes())
        || is_yaml_int(v.as_bytes())
        || is_yaml_timestamp(v.as_bytes())
}

/// Length of the longest prefix of `s` whose bytes satisfy `f`.
fn span(s: &[u8], f: impl Fn(u8) -> bool) -> usize {
    s.iter().take_while(|&&b| f(b)).count()
}

fn skip_sign(s: &[u8]) -> &[u8] {
    match s.first() {
        Some(b'-' | b'+') => &s[1..],
        _ => s,
    }
}

fn digit_(b: u8) -> bool {
    b.is_ascii_digit() || b == b'_'
}

/// `(?::[0-5]?[0-9])+` followed by the rest; returns the rest.
fn sexagesimal(mut s: &[u8]) -> Option<&[u8]> {
    let mut n = 0;
    while s.first() == Some(&b':') {
        let d = span(&s[1..], |b| b.is_ascii_digit());
        if !(d == 1 || (d == 2 && s[1] <= b'5')) {
            return None;
        }
        s = &s[1 + d..];
        n += 1;
    }
    (n > 0).then_some(s)
}

fn is_yaml_float(s: &[u8]) -> bool {
    let exp = |s: &[u8]| -> bool {
        s.is_empty()
            || (s.len() > 2
                && matches!(s[0], b'e' | b'E')
                && matches!(s[1], b'-' | b'+')
                && s[2..].iter().all(u8::is_ascii_digit))
    };
    // [-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?
    let t = skip_sign(s);
    if t.first().is_some_and(u8::is_ascii_digit) {
        let r = &t[span(t, digit_)..];
        if r.first() == Some(&b'.') {
            let r = &r[1..];
            if exp(&r[span(r, digit_)..]) {
                return true;
            }
        }
        // [-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*
        if let Some(r) = sexagesimal(r) {
            if r.first() == Some(&b'.') && r[1..].iter().all(|&b| digit_(b)) {
                return true;
            }
        }
    }
    // \.[0-9][0-9_]*(?:[eE][-+][0-9]+)?
    if s.len() > 1 && s[0] == b'.' && s[1].is_ascii_digit() {
        let r = &s[1..];
        if exp(&r[span(r, digit_)..]) {
            return true;
        }
    }
    // [-+]?\.(?:inf|Inf|INF) | \.(?:nan|NaN|NAN)
    [b".inf".as_slice(), b".Inf", b".INF"].contains(&t)
        || [b".nan".as_slice(), b".NaN", b".NAN"].contains(&s)
}

fn is_yaml_int(s: &[u8]) -> bool {
    let t = skip_sign(s);
    let all = |s: &[u8], f: fn(u8) -> bool| !s.is_empty() && s.iter().all(|&b| f(b));
    if let Some(r) = t.strip_prefix(b"0b") {
        if all(r, |b| matches!(b, b'0' | b'1' | b'_')) {
            return true;
        }
    }
    if let Some(r) = t.strip_prefix(b"0x") {
        if all(r, |b| b.is_ascii_hexdigit() || b == b'_') {
            return true;
        }
    }
    if let Some(r) = t.strip_prefix(b"0") {
        if r.is_empty() || all(r, |b| matches!(b, b'0'..=b'7' | b'_')) {
            return true;
        }
    }
    if t.first().is_some_and(|b| matches!(b, b'1'..=b'9')) {
        let r = &t[span(t, digit_)..];
        if r.is_empty() || sexagesimal(r).is_some_and(<[u8]>::is_empty) {
            return true;
        }
    }
    false
}

fn is_yaml_timestamp(s: &[u8]) -> bool {
    let d = |s: &[u8], i: usize| s.get(i).is_some_and(u8::is_ascii_digit);
    // [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]
    if s.len() == 10
        && (0..4).all(|i| d(s, i))
        && s[4] == b'-'
        && d(s, 5)
        && d(s, 6)
        && s[7] == b'-'
        && d(s, 8)
        && d(s, 9)
    {
        return true;
    }
    // [0-9]{4}-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9]
    //   (?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?
    let one_or_two = |s: &[u8]| -> Option<usize> {
        match span(s, |b| b.is_ascii_digit()).min(2) {
            0 => None,
            n => Some(n),
        }
    };
    let parse = || -> Option<()> {
        if !(0..4).all(|i| d(s, i)) || s.get(4) != Some(&b'-') {
            return None;
        }
        let mut r = &s[5..];
        r = &r[one_or_two(r)?..];
        r = r.strip_prefix(b"-")?;
        r = &r[one_or_two(r)?..];
        match r.first() {
            Some(b'T' | b't') => r = &r[1..],
            Some(b' ' | b'\t') => r = &r[span(r, |b| b == b' ' || b == b'\t')..],
            _ => return None,
        }
        r = &r[one_or_two(r)?..];
        for _ in 0..2 {
            r = r.strip_prefix(b":")?;
            if !(d(r, 0) && d(r, 1)) {
                return None;
            }
            r = &r[2..];
        }
        if let Some(f) = r.strip_prefix(b".") {
            r = &f[span(f, |b| b.is_ascii_digit())..];
        }
        if r.is_empty() {
            return Some(());
        }
        r = &r[span(r, |b| b == b' ' || b == b'\t')..];
        match r.first() {
            Some(b'Z') => r = &r[1..],
            Some(b'-' | b'+') => {
                r = &r[1..];
                r = &r[one_or_two(r)?..];
                if let Some(m) = r.strip_prefix(b":") {
                    if !(d(m, 0) && d(m, 1)) {
                        return None;
                    }
                    r = &m[2..];
                }
            }
            _ => return None,
        }
        r.is_empty().then_some(())
    };
    parse().is_some()
}

/// `yaml.emitter.ScalarAnalysis`
struct Analysis {
    empty: bool,
    multiline: bool,
    allow_block_plain: bool,
    allow_single_quoted: bool,
}

fn is_break(c: char) -> bool {
    matches!(c, '\n' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

fn is_blank_or_break(c: char) -> bool {
    matches!(
        c,
        '\0' | ' ' | '\t' | '\r' | '\n' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

/// `Emitter.analyze_scalar()` (block context, allow_unicode=False)
fn analyze_scalar(scalar: &[char]) -> Analysis {
    if scalar.is_empty() {
        return Analysis {
            empty: true,
            multiline: false,
            allow_block_plain: true,
            allow_single_quoted: true,
        };
    }
    let mut block_indicators = false;
    let mut line_breaks = false;
    let mut special_characters = false;
    let (mut leading_space, mut leading_break) = (false, false);
    let (mut trailing_space, mut trailing_break) = (false, false);
    let (mut break_space, mut space_break) = (false, false);

    let starts = |p: &str| scalar.iter().take(3).copied().eq(p.chars());
    if starts("---") || starts("...") {
        block_indicators = true;
    }
    let mut preceded_by_whitespace = true;
    let mut followed_by_whitespace = scalar.len() == 1 || is_blank_or_break(scalar[1]);
    let (mut previous_space, mut previous_break) = (false, false);

    let n = scalar.len();
    for (index, &ch) in scalar.iter().enumerate() {
        if index == 0 {
            if "#,[]{}&*!|>'\"%@`".contains(ch) {
                block_indicators = true;
            }
            if (ch == '?' || ch == ':') && followed_by_whitespace {
                block_indicators = true;
            }
            if ch == '-' && followed_by_whitespace {
                block_indicators = true;
            }
        } else {
            if ch == ':' && followed_by_whitespace {
                block_indicators = true;
            }
            if ch == '#' && preceded_by_whitespace {
                block_indicators = true;
            }
        }
        if is_break(ch) {
            line_breaks = true;
        }
        if !(ch == '\n' || ('\x20'..='\x7e').contains(&ch)) {
            // unicode characters are special without allow_unicode
            special_characters = true;
        }
        if ch == ' ' {
            if index == 0 {
                leading_space = true;
            }
            if index == n - 1 {
                trailing_space = true;
            }
            if previous_break {
                break_space = true;
            }
            previous_space = true;
            previous_break = false;
        } else if is_break(ch) {
            if index == 0 {
                leading_break = true;
            }
            if index == n - 1 {
                trailing_break = true;
            }
            if previous_space {
                space_break = true;
            }
            previous_space = false;
            previous_break = true;
        } else {
            previous_space = false;
            previous_break = false;
        }
        preceded_by_whitespace = is_blank_or_break(ch);
        followed_by_whitespace = index + 2 >= n || is_blank_or_break(scalar[index + 2]);
    }

    let mut allow_block_plain = true;
    let mut allow_single_quoted = true;
    if leading_space || leading_break || trailing_space || trailing_break {
        allow_block_plain = false;
    }
    if break_space {
        allow_block_plain = false;
        allow_single_quoted = false;
    }
    if space_break || special_characters {
        allow_block_plain = false;
        allow_single_quoted = false;
    }
    if line_breaks || block_indicators {
        allow_block_plain = false;
    }
    Analysis {
        empty: false,
        multiline: line_breaks,
        allow_block_plain,
        allow_single_quoted,
    }
}

const BEST_WIDTH: usize = 80;
const BEST_INDENT: usize = 2;

/// The block-style subset of `yaml.emitter.Emitter` that `yaml.dump()`
/// uses for migrate's data.
struct Emitter {
    out: String,
    indents: Vec<Option<usize>>,
    indent: Option<usize>,
    column: usize,
    whitespace: bool,
    indention: bool,
    mapping_context: bool,
    simple_key_context: bool,
}

impl Default for Emitter {
    fn default() -> Self {
        Emitter {
            out: String::new(),
            indents: Vec::new(),
            indent: None,
            column: 0,
            whitespace: true,
            indention: true,
            mapping_context: false,
            simple_key_context: false,
        }
    }
}

impl Emitter {
    fn increase_indent(&mut self, flow: bool, indentless: bool) {
        self.indents.push(self.indent);
        match self.indent {
            None => self.indent = Some(if flow { BEST_INDENT } else { 0 }),
            Some(i) if !indentless => self.indent = Some(i + BEST_INDENT),
            Some(_) => {}
        }
    }

    fn pop_indent(&mut self) {
        self.indent = self.indents.pop().flatten();
    }

    fn write(&mut self, data: &str) {
        self.column += data.chars().count();
        self.out.push_str(data);
    }

    fn write_indicator(
        &mut self,
        indicator: &str,
        need_whitespace: bool,
        whitespace: bool,
        indention: bool,
    ) {
        let data = if self.whitespace || !need_whitespace {
            indicator.to_string()
        } else {
            format!(" {indicator}")
        };
        self.whitespace = whitespace;
        self.indention = self.indention && indention;
        self.write(&data);
    }

    fn write_indent(&mut self) {
        let indent = self.indent.unwrap_or(0);
        if !self.indention || self.column > indent || (self.column == indent && !self.whitespace) {
            self.write_line_break(None);
        }
        if self.column < indent {
            self.whitespace = true;
            self.out.push_str(&" ".repeat(indent - self.column));
            self.column = indent;
        }
    }

    fn write_line_break(&mut self, data: Option<char>) {
        self.whitespace = true;
        self.indention = true;
        self.column = 0;
        self.out.push(data.unwrap_or('\n'));
    }

    fn expect_node(&mut self, node: &Node, mapping: bool, simple_key: bool) {
        self.mapping_context = mapping;
        self.simple_key_context = simple_key;
        match node {
            Node::Str(s) => self.expect_scalar(s, !resolves_to_non_str(s)),
            Node::Plain(s) => self.expect_scalar(s, true),
            Node::Seq(items) if items.is_empty() => {
                self.write_indicator("[", true, true, false);
                self.write_indicator("]", false, false, false);
            }
            Node::Map(items) if items.is_empty() => {
                self.write_indicator("{", true, true, false);
                self.write_indicator("}", false, false, false);
            }
            Node::Seq(items) => {
                let indentless = self.mapping_context && !self.indention;
                self.increase_indent(false, indentless);
                for item in items {
                    self.write_indent();
                    self.write_indicator("-", true, false, true);
                    self.expect_node(item, false, false);
                }
                self.pop_indent();
            }
            Node::Map(items) => {
                self.increase_indent(false, false);
                for (key, value) in items {
                    self.write_indent();
                    let chars: Vec<char> = key.chars().collect();
                    let a = analyze_scalar(&chars);
                    // len('!!str') + len(key) < 128
                    if 5 + chars.len() < 128 && !a.empty && !a.multiline {
                        self.expect_node(&Node::Str(key.clone()), true, true);
                        self.write_indicator(":", false, false, false);
                    } else {
                        self.write_indicator("?", true, false, true);
                        self.expect_node(&Node::Str(key.clone()), true, false);
                        self.write_indent();
                        self.write_indicator(":", true, false, true);
                    }
                    self.expect_node(value, true, false);
                }
                self.pop_indent();
            }
        }
    }

    fn expect_scalar(&mut self, value: &str, implicit_plain: bool) {
        self.increase_indent(true, false);
        let text: Vec<char> = value.chars().collect();
        let a = analyze_scalar(&text);
        let split = !self.simple_key_context;
        // choose_scalar_style()
        if implicit_plain
            && !(self.simple_key_context && (a.empty || a.multiline))
            && a.allow_block_plain
        {
            self.write_plain(&text, split);
        } else if a.allow_single_quoted && !(self.simple_key_context && a.multiline) {
            self.write_single_quoted(&text, split);
        } else {
            self.write_double_quoted(&text, split);
        }
        self.pop_indent();
    }

    fn write_chars(&mut self, text: &[char]) {
        let s: String = text.iter().collect();
        self.write(&s);
    }

    fn write_breaks(&mut self, text: &[char]) {
        for &br in text {
            self.write_line_break(if br == '\n' { None } else { Some(br) });
        }
    }

    fn write_plain(&mut self, text: &[char], split: bool) {
        if text.is_empty() {
            return;
        }
        if !self.whitespace {
            self.write(" ");
        }
        self.whitespace = false;
        self.indention = false;
        let (mut spaces, mut breaks) = (false, false);
        let (mut start, mut end) = (0, 0);
        while end <= text.len() {
            let ch = text.get(end).copied();
            if spaces {
                if ch != Some(' ') {
                    if start + 1 == end && self.column > BEST_WIDTH && split {
                        self.write_indent();
                        self.whitespace = false;
                        self.indention = false;
                    } else {
                        self.write_chars(&text[start..end]);
                    }
                    start = end;
                }
            } else if breaks {
                if !ch.is_some_and(is_break) {
                    if text[start] == '\n' {
                        self.write_line_break(None);
                    }
                    self.write_breaks(&text[start..end]);
                    self.write_indent();
                    self.whitespace = false;
                    self.indention = false;
                    start = end;
                }
            } else if ch.is_none_or(|c| c == ' ' || is_break(c)) {
                self.write_chars(&text[start..end]);
                start = end;
            }
            if let Some(c) = ch {
                spaces = c == ' ';
                breaks = is_break(c);
            }
            end += 1;
        }
    }

    fn write_single_quoted(&mut self, text: &[char], split: bool) {
        self.write_indicator("'", true, false, false);
        let (mut spaces, mut breaks) = (false, false);
        let (mut start, mut end) = (0, 0);
        while end <= text.len() {
            let ch = text.get(end).copied();
            if spaces {
                if ch != Some(' ') {
                    if start + 1 == end
                        && self.column > BEST_WIDTH
                        && split
                        && start != 0
                        && end != text.len()
                    {
                        self.write_indent();
                    } else {
                        self.write_chars(&text[start..end]);
                    }
                    start = end;
                }
            } else if breaks {
                if !ch.is_some_and(is_break) {
                    if text[start] == '\n' {
                        self.write_line_break(None);
                    }
                    self.write_breaks(&text[start..end]);
                    self.write_indent();
                    start = end;
                }
            } else if ch.is_none_or(|c| c == ' ' || is_break(c) || c == '\'') && start < end {
                self.write_chars(&text[start..end]);
                start = end;
            }
            if ch == Some('\'') {
                self.write("''");
                start = end + 1;
            }
            if let Some(c) = ch {
                spaces = c == ' ';
                breaks = is_break(c);
            }
            end += 1;
        }
        self.write_indicator("'", false, false, false);
    }

    fn write_double_quoted(&mut self, text: &[char], split: bool) {
        self.write_indicator("\"", true, false, false);
        let (mut start, mut end) = (0, 0);
        while end <= text.len() {
            let ch = text.get(end).copied();
            if ch.is_none_or(|c| {
                matches!(
                    c,
                    '"' | '\\' | '\u{85}' | '\u{2028}' | '\u{2029}' | '\u{feff}'
                ) || !('\x20'..='\x7e').contains(&c)
            }) {
                if start < end {
                    self.write_chars(&text[start..end]);
                    start = end;
                }
                if let Some(c) = ch {
                    let data = match c {
                        '\0' => "\\0".to_string(),
                        '\x07' => "\\a".to_string(),
                        '\x08' => "\\b".to_string(),
                        '\x09' => "\\t".to_string(),
                        '\x0a' => "\\n".to_string(),
                        '\x0b' => "\\v".to_string(),
                        '\x0c' => "\\f".to_string(),
                        '\x0d' => "\\r".to_string(),
                        '\x1b' => "\\e".to_string(),
                        '"' => "\\\"".to_string(),
                        '\\' => "\\\\".to_string(),
                        '\u{85}' => "\\N".to_string(),
                        '\u{a0}' => "\\_".to_string(),
                        '\u{2028}' => "\\L".to_string(),
                        '\u{2029}' => "\\P".to_string(),
                        c if (c as u32) <= 0xff => format!("\\x{:02X}", c as u32),
                        c if (c as u32) <= 0xffff => format!("\\u{:04X}", c as u32),
                        c => format!("\\U{:08X}", c as u32),
                    };
                    self.write(&data);
                    start = end + 1;
                }
            }
            if 0 < end
                && end + 1 < text.len()
                && (ch == Some(' ') || start >= end)
                && self.column as isize + end as isize - start as isize > BEST_WIDTH as isize
                && split
            {
                let mut data: String = if start < end {
                    text[start..end].iter().collect()
                } else {
                    String::new()
                };
                data.push('\\');
                if start < end {
                    start = end;
                }
                self.write(&data);
                self.write_indent();
                self.whitespace = false;
                self.indention = false;
                if text[start] == ' ' {
                    self.write("\\");
                }
            }
            end += 1;
        }
        self.write_indicator("\"", false, false, false);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn yaml_resolvers() {
        for v in [
            "1",
            "-5",
            "0x1f",
            "0b101",
            "017",
            "1:20",
            "10:11:22:33:44:55",
            "1.5",
            "1:20.5",
            ".inf",
            "-.Inf",
            ".NaN",
            "2001-12-14",
            "2001-12-14t21:59:43.10-05:00",
            "2001-12-14 21:59:43.10 -5",
            "2001-1-1 1:00:00",
            "yes",
            "Off",
            "~",
            "",
            "<<",
            "=",
        ] {
            assert!(resolves_to_non_str(v), "{v}");
        }
        for v in [
            "00:11:22:33:44:55",
            "1.2.3.4",
            "fe80::1",
            "1:60",
            "08",
            "eth0",
            "1e5",
            "2001-12-14x",
            "1.5e5",
            "-",
            ".",
            "0x",
            "0b2",
        ] {
            assert!(!resolves_to_non_str(v), "{v}");
        }
    }

    #[test]
    fn ipv6() {
        assert_eq!(
            ipv6_address("fc00:0123:4567:89ab:cdef::1234").unwrap(),
            "fc00:123:4567:89ab:cdef::1234"
        );
        assert_eq!(ipv6_address("::ffff:1.2.3.4").unwrap(), "::ffff:1.2.3.4");
        assert_eq!(ipv6_address("::").unwrap(), "::");
        assert_eq!(ipv6_address("1::").unwrap(), "1::");
        assert_eq!(ipv6_address("fe80::1%eth0").unwrap(), "fe80::1%eth0");
        assert_eq!(ipv6_address("1:0:0:1:0:0:0:1").unwrap(), "1:0:0:1::1");
    }

    #[test]
    fn text_lines() {
        assert_eq!(
            py_text_lines(b"a\r\nb\rc\n\nd"),
            (
                vec![
                    "a\n".into(),
                    "b\n".into(),
                    "c\n".into(),
                    "\n".into(),
                    "d".into()
                ],
                None
            )
        );
        let (lines, err) = py_text_lines(b"abc\n\xe2\x82");
        assert_eq!(lines, vec!["abc\n".to_string()]);
        assert_eq!(
            err.unwrap(),
            "'utf-8' codec can't decode bytes in position 0-1: unexpected end of data"
        );
    }
}
