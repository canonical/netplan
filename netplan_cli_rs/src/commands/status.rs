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

//! `netplan status` – show system network state.
//!
//! Mirrors `netplan_cli/cli/commands/status.py` and `netplan_cli/cli/state.py`.

use std::collections::{HashMap, HashSet};
use std::fmt;
use std::net::{Ipv4Addr, Ipv6Addr};

use crate::argparse::{Arg, Nargs};
use crate::cli;
use anyhow::{Context, Result};
use serde_json::{Map, Value};

use crate::utils::process::CommandRunner;

// ── Argument types ────────────────────────────────────────────────────────────

pub struct StatusArgs {
    pub ifname: Option<String>,
    pub all: bool,
    pub verbose: bool,
    pub format: String,
    pub diff: bool,
    pub diff_only: bool,
    pub root_dir: String,
}

/// `netplan status [ifname] [-a] [-v] [-f FORMAT] [--diff] [--diff-only] [--root-dir DIR]`
pub fn command(argv0: &str, args: &[String], runner: &impl CommandRunner) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "status", cli::description("status"));
    p.add(
        Arg::new(&["ifname"])
            .nargs(Nargs::Optional)
            .help("Show only this interface"),
    );
    p.add(
        Arg::new(&["-a", "--all"])
            .store_true()
            .help("Show all interface data (incl. inactive)"),
    );
    p.add(
        Arg::new(&["-v", "--verbose"])
            .store_true()
            .help("Show extra information"),
    );
    p.add(
        Arg::new(&["-f", "--format"])
            .default_str("tabular")
            .help("Output in machine readable `json` or `yaml` format"),
    );
    p.add(
        Arg::new(&["--diff"])
            .store_true()
            .help("Show the differences between the system's and netplan's states"),
    );
    p.add(
        Arg::new(&["--diff-only"])
            .store_true()
            .help("Only show the differences between the system's and netplan's states"),
    );
    p.add(
        Arg::new(&["--root-dir"])
            .help("Search for configuration files in this root directory instead of /"),
    );
    let ns = cli::parse_leaf(&p, args)?;
    run(
        StatusArgs {
            ifname: ns.str("ifname"),
            all: ns.bool("all"),
            verbose: ns.bool("verbose"),
            format: ns.str("format").unwrap_or_default(),
            diff: ns.bool("diff"),
            diff_only: ns.bool("diff_only"),
            // PORT PENDING: Python passes None through; "/" is equivalent for now
            root_dir: ns
                .str("root_dir")
                .filter(|r| !r.is_empty())
                .unwrap_or_else(|| "/".into()),
        },
        runner,
    )
}

// ── Entry point ───────────────────────────────────────────────────────────────

pub fn run(args: StatusArgs, runner: &impl CommandRunner) -> Result<i32> {
    // --diff-only implies --diff, both need all interfaces
    let show_all = args.all || args.diff || args.diff_only;

    // Gather system data
    let iproute2 = query_iproute2(runner).context("Cannot query iproute2")?;
    let networkd = query_networkd(runner).context("Cannot query systemd-networkd")?;
    if iproute2.is_empty() || networkd.is_empty() {
        eprintln!("Could not query iproute2 or systemd-networkd");
        return Ok(1);
    }

    let nm_data = query_nm(runner);
    let (routes4, routes6) = query_routes(runner);
    let (dns_addresses, dns_search) = query_resolved(runner);

    // Build interface list
    let mut ifaces: Vec<IfaceData> = iproute2
        .iter()
        .map(|ip| {
            build_iface(
                ip,
                &networkd,
                &nm_data,
                &dns_addresses,
                &dns_search,
                &routes4,
                &routes6,
                runner,
            )
        })
        .collect();

    correlate_members_and_uplinks(&mut ifaces, runner);

    // Filter for online state: non-DOWN interfaces
    let active: Vec<&IfaceData> = ifaces.iter().filter(|i| i.operstate != "DOWN").collect();
    let online = query_online_state(&active);

    let total = ifaces.len();

    // Apply interface name filter
    if let Some(ifname) = &args.ifname {
        if !ifaces.iter().any(|i| i.name == *ifname) {
            eprintln!("Could not find interface {}", ifname);
            return Ok(1);
        }
    }

    // Build state map (insertion order via serde_json preserve_order)
    let mut state: Map<String, Value> = Map::new();

    let mut global = Map::new();
    global.insert("online".into(), Value::Bool(online));
    global.insert(
        "nameservers".into(),
        Value::Object(resolvconf_json(&args.root_dir)),
    );
    state.insert("netplan-global-state".into(), Value::Object(global));

    let iter: Box<dyn Iterator<Item = &IfaceData>> = if show_all {
        Box::new(ifaces.iter())
    } else if let Some(target) = &args.ifname {
        // When a specific interface is requested: include it even if DOWN
        let target = target.clone();
        Box::new(ifaces.iter().filter(move |i| i.name == target))
    } else {
        Box::new(ifaces.iter().filter(|i| i.operstate != "DOWN"))
    };

    for iface in iter {
        state.insert(iface.name.clone(), Value::Object(iface.to_json_obj(runner)));
    }

    let format = args.format.to_lowercase();

    if args.diff || args.diff_only {
        let netplan_ifaces = load_netplan_ifaces(&args.root_dir);
        let report = compute_diff(&state, &netplan_ifaces, args.ifname.as_deref());

        match format.as_str() {
            "json" => {
                println!("{}", python_json_dumps(&diff_to_json(&report)));
            }
            "yaml" => {
                let json_val = diff_to_json(&report);
                if let Value::Object(m) = json_val {
                    print!("{}", render_yaml(&m));
                }
            }
            _ => {
                pretty_print_diff(
                    &state,
                    &report,
                    args.verbose,
                    args.diff_only,
                    args.ifname.as_deref(),
                );
            }
        }
    } else {
        match format.as_str() {
            "json" => {
                println!("{}", python_json_dumps(&Value::Object(state)));
            }
            "yaml" => {
                print!("{}", render_yaml(&state));
            }
            _ => {
                pretty_print(&state, total, args.ifname.as_deref(), args.verbose);
            }
        }
    }

    Ok(0)
}

// ── Device type mapping ───────────────────────────────────────────────────────

fn device_type(nd_type: &str) -> Option<&'static str> {
    match nd_type {
        "bond" => Some("bond"),
        "bridge" => Some("bridge"),
        "dummy" => Some("dummy-device"),
        "erspan" => Some("tunnel"),
        "ether" => Some("ethernet"),
        "gretap" => Some("tunnel"),
        "ipgre" => Some("tunnel"),
        "ip6gre" => Some("tunnel"),
        "loopback" => Some("ethernet"),
        "sit" => Some("tunnel"),
        "tunnel" => Some("tunnel"),
        "tun" => Some("tunnel"),
        "tunnel6" => Some("tunnel"),
        "wireguard" => Some("tunnel"),
        "wlan" => Some("wifi"),
        "wwan" => Some("modem"),
        "veth" => Some("virtual-ethernet"),
        "vlan" => Some("vlan"),
        "vrf" => Some("vrf"),
        "ieee80211_radiotap" => Some("wifi"),
        "none" => None,
        _ => None,
    }
}

// ── Backends ──────────────────────────────────────────────────────────────────

/// The handful of backends netplan can hand an interface off to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Backend {
    Networkd,
    NetworkManager,
}

impl fmt::Display for Backend {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Backend::Networkd => "networkd",
            Backend::NetworkManager => "NetworkManager",
        })
    }
}

// ── Per-interface data ────────────────────────────────────────────────────────

#[derive(Debug)]
struct IfaceData {
    idx: u64,
    name: String,
    adminstate: String,
    operstate: String,
    iproute_type: Option<String>,
    macaddress: Option<String>,

    // networkd JSON fields
    nd_type: Option<String>,
    nd_kind: Option<String>,
    nd_setup_state: Option<String>,
    nd_network_file: Option<String>,
    nd_vendor: Option<String>,
    // networkctl text (for activation_mode and wifi SSID)
    networkctl_text: String,

    // NetworkManager CSV fields
    nm_filename: Option<String>,
    nm_name: Option<String>,
    nm_type: Option<String>,
    nm_autoconnect: Option<String>,

    // DNS
    dns_addresses: Option<Vec<String>>,
    dns_search: Option<Vec<String>>,

    // Routes (raw iproute2 route objects filtered to this dev)
    routes: Option<Vec<Map<String, Value>>>,

    // Addresses
    addresses: Option<Vec<Value>>,

    // Members and uplink (filled later by correlate step)
    bridge: Option<String>,
    bond: Option<String>,
    vrf: Option<String>,
    members: Vec<String>,
}

impl IfaceData {
    fn iface_type(&self) -> Option<&'static str> {
        let mut t = self.nd_type.as_deref();
        // 'none' → fall back to Kind
        if t == Some("none") {
            t = self.nd_kind.as_deref();
        }
        // 'ether' with a Kind → use Kind
        if t == Some("ether") {
            if let Some(k) = &self.nd_kind {
                t = Some(k.as_str());
            }
        }
        device_type(t.unwrap_or(""))
    }

    fn tunnel_mode(&self) -> Option<&str> {
        if self.iface_type() == Some("tunnel") {
            self.iproute_type.as_deref()
        } else {
            None
        }
    }

    fn backend(&self) -> Option<Backend> {
        let setup = self.nd_setup_state.as_deref().unwrap_or("");
        let netfile = self.nd_network_file.as_deref().unwrap_or("");
        if !setup.contains("unmanaged") && netfile.contains("run/systemd/network/10-netplan-") {
            return Some(Backend::Networkd);
        }
        let nm_file = self.nm_filename.as_deref().unwrap_or("");
        if nm_file.contains("run/NetworkManager/system-connections/netplan-") {
            return Some(Backend::NetworkManager);
        }
        None
    }

    fn netdef_id(&self, runner: &impl CommandRunner) -> Option<String> {
        match self.backend() {
            Some(Backend::Networkd) => {
                let netfile = self.nd_network_file.as_deref()?;
                let after = netfile.split("run/systemd/network/10-netplan-").nth(1)?;
                Some(after.split(".network").next()?.to_string())
            }
            Some(Backend::NetworkManager) => {
                let nm_file = self.nm_filename.as_deref()?;
                let after = nm_file
                    .split("run/NetworkManager/system-connections/netplan-")
                    .nth(1)?;
                let mut netdef = after.split(".nmconnection").next()?.to_string();
                if self.nm_type.as_deref() == Some("802-11-wireless") {
                    if let Some(ssid) = self.ssid(runner) {
                        let suffix = format!("-{}", ssid);
                        if let Some(pos) = netdef.find(&suffix) {
                            netdef.truncate(pos);
                        }
                    }
                }
                Some(netdef)
            }
            _ => None,
        }
    }

    fn vendor(&self) -> Option<&str> {
        self.nd_vendor
            .as_deref()
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
    }

    fn ssid(&self, runner: &impl CommandRunner) -> Option<String> {
        if self.iface_type() != Some("wifi") {
            return None;
        }
        if self.backend() == Some(Backend::NetworkManager) {
            if let Some(nm_name) = &self.nm_name {
                return query_nm_ssid(nm_name, runner);
            }
        }
        // Parse networkctl text for "Wi-Fi access point: <SSID> (<mac>)"
        for line in self.networkctl_text.lines() {
            let line = line.trim();
            // Match "WiFi access point:" or "Wi-Fi access point:"
            let key_variants = ["WiFi access point: ", "Wi-Fi access point: "];
            for key in &key_variants {
                if let Some(rest) = line.strip_prefix(key) {
                    // strip trailing " (mac)" part
                    let ssid = if let Some(pos) = rest.rfind(" (") {
                        &rest[..pos]
                    } else {
                        rest
                    };
                    if !ssid.is_empty() {
                        return Some(ssid.to_string());
                    }
                }
            }
        }
        None
    }

    fn activation_mode(&self) -> Option<String> {
        match self.backend() {
            Some(Backend::Networkd) => {
                for line in self.networkctl_text.lines() {
                    let line = line.trim();
                    if let Some(rest) = line.strip_prefix("Activation Policy: ") {
                        let mode = rest.trim();
                        return if mode == "up" {
                            None
                        } else {
                            Some(mode.to_string())
                        };
                    }
                }
                None
            }
            Some(Backend::NetworkManager) => {
                let autoconnect = self.nm_autoconnect.as_deref().unwrap_or("yes");
                if autoconnect == "no" {
                    Some("manual".to_string())
                } else {
                    None
                }
            }
            _ => None,
        }
    }

    /// Is interface up (both admin and oper)?
    fn is_up(&self) -> bool {
        self.adminstate == "UP" && self.operstate == "UP"
    }

    fn to_json_obj(&self, runner: &impl CommandRunner) -> Map<String, Value> {
        let mut m = Map::new();
        m.insert("index".into(), Value::Number(self.idx.into()));
        m.insert("adminstate".into(), Value::String(self.adminstate.clone()));
        m.insert("operstate".into(), Value::String(self.operstate.clone()));

        if let Some(t) = self.iface_type() {
            m.insert("type".into(), Value::String(t.to_string()));
        }
        if let Some(s) = self.ssid(runner) {
            m.insert("ssid".into(), Value::String(s));
        }
        if let Some(tm) = self.tunnel_mode() {
            m.insert("tunnel_mode".into(), Value::String(tm.to_string()));
        }
        if let Some(b) = self.backend() {
            m.insert("backend".into(), Value::String(b.to_string()));
        }
        if let Some(id) = self.netdef_id(runner) {
            m.insert("id".into(), Value::String(id));
        }
        if let Some(mac) = &self.macaddress {
            m.insert("macaddress".into(), Value::String(mac.clone()));
        }
        if let Some(v) = self.vendor() {
            m.insert("vendor".into(), Value::String(v.to_string()));
        }
        if let Some(addrs) = &self.addresses {
            if !addrs.is_empty() {
                m.insert("addresses".into(), Value::Array(addrs.clone()));
            }
        }
        if let Some(dns) = &self.dns_addresses {
            if !dns.is_empty() {
                m.insert(
                    "dns_addresses".into(),
                    Value::Array(dns.iter().map(|s| Value::String(s.clone())).collect()),
                );
            }
        }
        if let Some(srch) = &self.dns_search {
            if !srch.is_empty() {
                m.insert(
                    "dns_search".into(),
                    Value::Array(srch.iter().map(|s| Value::String(s.clone())).collect()),
                );
            }
        }
        if let Some(routes) = &self.routes {
            if !routes.is_empty() {
                m.insert(
                    "routes".into(),
                    Value::Array(routes.iter().map(|r| Value::Object(r.clone())).collect()),
                );
            }
        }
        if let Some(am) = self.activation_mode() {
            m.insert("activation_mode".into(), Value::String(am));
        }
        if let Some(br) = &self.bridge {
            m.insert("bridge".into(), Value::String(br.clone()));
        }
        if let Some(bo) = &self.bond {
            m.insert("bond".into(), Value::String(bo.clone()));
        }
        if let Some(vf) = &self.vrf {
            m.insert("vrf".into(), Value::String(vf.clone()));
        }
        if !self.members.is_empty() {
            m.insert(
                "interfaces".into(),
                Value::Array(
                    self.members
                        .iter()
                        .map(|s| Value::String(s.clone()))
                        .collect(),
                ),
            );
        }
        m
    }
}

// ── System queries ────────────────────────────────────────────────────────────

fn capture_cmd(args: &[&str], runner: &impl CommandRunner) -> Result<String> {
    use crate::utils::process::Command;
    let output = Command::new(args[0])
        .args(args[1..].iter().copied())
        .run_with(runner)?;
    Ok(String::from_utf8_lossy(&output.stdout).into_owned())
}

fn query_iproute2(runner: &impl CommandRunner) -> Result<Vec<Value>> {
    let out = capture_cmd(&["ip", "-d", "-j", "addr"], runner)?;
    let v: Value = serde_json::from_str(&out).context("ip addr JSON parse failed")?;
    Ok(v.as_array().cloned().unwrap_or_default())
}

fn query_networkd(runner: &impl CommandRunner) -> Result<Vec<Value>> {
    let out = capture_cmd(&["networkctl", "--json=short"], runner)?;
    let v: Value = serde_json::from_str(&out).context("networkctl JSON parse failed")?;
    Ok(v["Interfaces"].as_array().cloned().unwrap_or_default())
}

fn query_nm(runner: &impl CommandRunner) -> Vec<Value> {
    let out = match capture_cmd(
        &[
            "nmcli",
            "-t",
            "-f",
            "DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT",
            "con",
            "show",
        ],
        runner,
    ) {
        Ok(o) => o,
        Err(_) => return vec![],
    };
    let mut data = vec![];
    for line in out.lines() {
        let parts: Vec<&str> = line.split(':').collect();
        if parts.len() >= 6 && !parts[0].is_empty() {
            let mut m = Map::new();
            m.insert("device".into(), Value::String(parts[0].to_string()));
            m.insert("name".into(), Value::String(parts[1].to_string()));
            m.insert("uuid".into(), Value::String(parts[2].to_string()));
            m.insert("filename".into(), Value::String(parts[3].to_string()));
            m.insert("type".into(), Value::String(parts[4].to_string()));
            m.insert("autoconnect".into(), Value::String(parts[5].to_string()));
            data.push(Value::Object(m));
        }
    }
    data
}

fn query_routes(runner: &impl CommandRunner) -> (Vec<Value>, Vec<Value>) {
    let mut r4 = vec![];
    let mut r6 = vec![];
    match capture_cmd(
        &["ip", "-d", "-j", "-4", "route", "show", "table", "all"],
        runner,
    ) {
        Ok(o) => match serde_json::from_str::<Value>(&o) {
            Ok(v) => {
                if let Some(arr) = v.as_array() {
                    r4 = arr
                        .iter()
                        .map(|x| {
                            let mut v = x.clone();
                            v.as_object_mut()
                                .map(|m| m.insert("family".into(), Value::Number(2.into())));
                            v
                        })
                        .collect();
                }
            }
            Err(e) => log::warn!("failed to parse 'ip -4 route' output: {e}"),
        },
        Err(e) => log::warn!("failed to query IPv4 routes: {e}"),
    }
    match capture_cmd(
        &["ip", "-d", "-j", "-6", "route", "show", "table", "all"],
        runner,
    ) {
        Ok(o) => match serde_json::from_str::<Value>(&o) {
            Ok(v) => {
                if let Some(arr) = v.as_array() {
                    r6 = arr
                        .iter()
                        .map(|x| {
                            let mut v = x.clone();
                            v.as_object_mut()
                                .map(|m| m.insert("family".into(), Value::Number(10.into())));
                            v
                        })
                        .collect();
                }
            }
            Err(e) => log::warn!("failed to parse 'ip -6 route' output: {e}"),
        },
        Err(e) => log::warn!("failed to query IPv6 routes: {e}"),
    }
    (r4, r6)
}

/// A DNS server entry as reported by resolved: (interface index, address family, raw address bytes).
type ResolvedDnsAddress = (u64, u64, Vec<u8>);
/// A search domain entry as reported by resolved: (interface index, domain name).
type ResolvedSearchDomain = (u64, String);

/// Parse busctl DNS data. Returns (addresses, search_domains).
fn query_resolved(
    runner: &impl CommandRunner,
) -> (Vec<ResolvedDnsAddress>, Vec<ResolvedSearchDomain>) {
    let busctl = match which_busctl(runner) {
        Some(b) => b,
        None => return (vec![], vec![]),
    };
    let out = match capture_cmd(
        &[
            &busctl,
            "--json=short",
            "call",
            "--system",
            "org.freedesktop.resolve1",
            "/org/freedesktop/resolve1",
            "org.freedesktop.DBus.Properties",
            "GetAll",
            "s",
            "org.freedesktop.resolve1.Manager",
        ],
        runner,
    ) {
        Ok(o) => o,
        Err(_) => return (vec![], vec![]),
    };
    parse_resolved_json(&out)
}

fn which_busctl(runner: &impl CommandRunner) -> Option<String> {
    use crate::utils::process::Command;
    let output = Command::new("which")
        .args(["busctl"])
        .run_with(runner)
        .ok()?;
    let s = String::from_utf8_lossy(&output.stdout);
    let s = s.trim();
    if s.is_empty() {
        None
    } else {
        Some(s.to_string())
    }
}

fn parse_resolved_json(json_str: &str) -> (Vec<ResolvedDnsAddress>, Vec<ResolvedSearchDomain>) {
    let v: Value = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(_) => return (vec![], vec![]),
    };
    let data = match v.get("data").and_then(|d| d.get(0)) {
        Some(d) => d,
        None => return (vec![], vec![]),
    };

    let mut addresses = vec![];
    if let Some(dns_arr) = data
        .get("DNS")
        .and_then(|d| d.get("data"))
        .and_then(|d| d.as_array())
    {
        for entry in dns_arr {
            if let Some(arr) = entry.as_array() {
                if arr.len() >= 3 {
                    let ifidx = arr[0].as_u64().unwrap_or(0);
                    let family = arr[1].as_u64().unwrap_or(0);
                    let bytes: Vec<u8> = arr[2]
                        .as_array()
                        .map(|a| {
                            a.iter()
                                .filter_map(|v| v.as_u64().map(|n| n as u8))
                                .collect()
                        })
                        .unwrap_or_default();
                    addresses.push((ifidx, family, bytes));
                }
            }
        }
    }

    let mut search = vec![];
    if let Some(dom_arr) = data
        .get("Domains")
        .and_then(|d| d.get("data"))
        .and_then(|d| d.as_array())
    {
        for entry in dom_arr {
            if let Some(arr) = entry.as_array() {
                if arr.len() >= 2 {
                    let ifidx = arr[0].as_u64().unwrap_or(0);
                    let domain = arr[1].as_str().unwrap_or("").to_string();
                    search.push((ifidx, domain));
                }
            }
        }
    }

    (addresses, search)
}

fn query_nm_ssid(con_name: &str, runner: &impl CommandRunner) -> Option<String> {
    let out = capture_cmd(
        &[
            "nmcli",
            "--get-values",
            "802-11-wireless.ssid",
            "con",
            "show",
            "id",
            con_name,
        ],
        runner,
    )
    .ok()?;
    let s = out.trim().to_string();
    if s.is_empty() {
        None
    } else {
        Some(s)
    }
}

fn query_networkctl_text(ifname: &str, runner: &impl CommandRunner) -> String {
    capture_cmd(&["networkctl", "status", "--", ifname], runner).unwrap_or_default()
}

fn query_members(ifname: &str, runner: &impl CommandRunner) -> Vec<String> {
    let out = match capture_cmd(
        &["ip", "-d", "-j", "link", "show", "master", ifname],
        runner,
    ) {
        Ok(o) => o,
        Err(_) => return vec![],
    };
    let v: Value = match serde_json::from_str(&out) {
        Ok(v) => v,
        Err(_) => return vec![],
    };
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|m| {
                    m.get("ifname")
                        .and_then(|n| n.as_str())
                        .map(|s| s.to_string())
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Parse {root_dir}/etc/resolv.conf → {addresses, search, mode}
fn resolvconf_json(root_dir: &str) -> Map<String, Value> {
    let mut res = Map::new();
    res.insert("addresses".into(), Value::Array(vec![]));
    res.insert("search".into(), Value::Array(vec![]));
    res.insert("mode".into(), Value::Null);

    let path = std::path::PathBuf::from(root_dir).join("etc/resolv.conf");
    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return res,
    };
    let mut lines = content.lines();
    let firstline = lines.next().unwrap_or("");
    let mode = if firstline.contains("# This is /run/systemd/resolve/stub-resolv.conf") {
        Some("stub")
    } else if firstline.contains("# This is /run/systemd/resolve/resolv.conf") {
        Some("compat")
    } else {
        None
    };
    if let Some(m) = mode {
        *res.get_mut("mode").unwrap() = Value::String(m.to_string());
    }

    let mut addresses: Vec<Value> = vec![];
    let mut search: Vec<Value> = vec![];

    // process firstline + rest
    let all_lines = std::iter::once(firstline).chain(lines);
    for line in all_lines {
        if let Some(rest) = line.strip_prefix("nameserver") {
            for addr in rest.split_whitespace() {
                addresses.push(Value::String(addr.to_string()));
            }
        }
        if let Some(rest) = line.strip_prefix("search") {
            search = rest
                .split_whitespace()
                .map(|s| Value::String(s.to_string()))
                .collect();
        }
    }
    *res.get_mut("addresses").unwrap() = Value::Array(addresses);
    *res.get_mut("search").unwrap() = Value::Array(search);
    res
}

// ── DNS bytes → IP string ─────────────────────────────────────────────────────

fn bytes_to_ip(family: u64, bytes: &[u8]) -> Option<String> {
    match family {
        2 if bytes.len() == 4 => {
            let addr = Ipv4Addr::new(bytes[0], bytes[1], bytes[2], bytes[3]);
            Some(addr.to_string())
        }
        10 if bytes.len() == 16 => {
            let mut octets = [0u8; 16];
            octets.copy_from_slice(bytes);
            let addr = Ipv6Addr::from(octets);
            Some(addr.to_string())
        }
        _ => None,
    }
}

// ── Interface builder ─────────────────────────────────────────────────────────

#[allow(clippy::too_many_arguments)]
fn build_iface(
    ip: &Value,
    nd_data: &[Value],
    nm_data: &[Value],
    dns_addresses: &[(u64, u64, Vec<u8>)],
    dns_search: &[(u64, String)],
    routes4: &[Value],
    routes6: &[Value],
    runner: &impl CommandRunner,
) -> IfaceData {
    let idx = ip.get("ifindex").and_then(|v| v.as_u64()).unwrap_or(0);
    let name = ip
        .get("ifname")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .to_string();
    let flags: Vec<&str> = ip
        .get("flags")
        .and_then(|f| f.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str()).collect())
        .unwrap_or_default();
    let adminstate = if flags.contains(&"UP") { "UP" } else { "DOWN" };
    let operstate = ip
        .get("operstate")
        .and_then(|v| v.as_str())
        .unwrap_or("UNKNOWN")
        .to_uppercase();
    let macaddress = ip
        .get("address")
        .and_then(|v| v.as_str())
        .filter(|s| s.len() == 17)
        .map(|s| s.to_lowercase());
    let iproute_type = ip
        .get("linkinfo")
        .and_then(|li| li.get("info_kind"))
        .and_then(|v| v.as_str())
        .map(|s| s.trim().to_string());

    // Match networkd entry by index
    let nd = nd_data
        .iter()
        .find(|x| x.get("Index").and_then(|i| i.as_u64()) == Some(idx));
    let nd_type = nd
        .and_then(|x| x.get("Type"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_lowercase());
    let nd_kind = nd
        .and_then(|x| x.get("Kind"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_lowercase());
    let nd_setup_state = nd
        .and_then(|x| x.get("SetupState"))
        .and_then(|v| v.as_str())
        .map(String::from);
    let nd_network_file = nd
        .and_then(|x| x.get("NetworkFile"))
        .and_then(|v| v.as_str())
        .map(String::from);
    let nd_vendor = nd
        .and_then(|x| x.get("Vendor"))
        .and_then(|v| v.as_str())
        .map(String::from);

    // Match NM entry by device name
    let nm = nm_data
        .iter()
        .find(|x| x.get("device").and_then(|d| d.as_str()) == Some(&name));
    let nm_filename = nm
        .and_then(|x| x.get("filename"))
        .and_then(|v| v.as_str())
        .map(String::from);
    let nm_name = nm
        .and_then(|x| x.get("name"))
        .and_then(|v| v.as_str())
        .map(String::from);
    let nm_type = nm
        .and_then(|x| x.get("type"))
        .and_then(|v| v.as_str())
        .map(String::from);
    let nm_autoconnect = nm
        .and_then(|x| x.get("autoconnect"))
        .and_then(|v| v.as_str())
        .map(String::from);

    // DNS addresses for this interface
    let dns_addr_list: Option<Vec<String>> = if dns_addresses.is_empty() {
        None
    } else {
        let addrs: Vec<String> = dns_addresses
            .iter()
            .filter(|(ifidx, _, _)| *ifidx == idx)
            .filter_map(|(_, family, bytes)| bytes_to_ip(*family, bytes))
            .collect();
        Some(addrs)
    };

    let dns_search_list: Option<Vec<String>> = if dns_search.is_empty() {
        None
    } else {
        let srch: Vec<String> = dns_search
            .iter()
            .filter(|(ifidx, _)| *ifidx == idx)
            .map(|(_, domain)| domain.clone())
            .collect();
        Some(srch)
    };

    // Routes filtered to this dev
    let all_routes: Vec<&Value> = routes4.iter().chain(routes6.iter()).collect();
    let filtered_routes: Option<Vec<Map<String, Value>>> = if all_routes.is_empty() {
        None
    } else {
        let mut out = vec![];
        for r in all_routes {
            if r.get("dev").and_then(|d| d.as_str()) != Some(&name) {
                continue;
            }
            let mut m = Map::new();
            if let Some(v) = r.get("dst") {
                m.insert("to".into(), v.clone());
            }
            if let Some(v) = r.get("family") {
                m.insert("family".into(), v.clone());
            }
            if let Some(v) = r.get("gateway") {
                m.insert("via".into(), v.clone());
            }
            if let Some(v) = r.get("prefsrc") {
                m.insert("from".into(), v.clone());
            }
            if let Some(v) = r.get("metric") {
                m.insert("metric".into(), v.clone());
            }
            if let Some(v) = r.get("type") {
                m.insert("type".into(), v.clone());
            }
            if let Some(v) = r.get("scope") {
                m.insert("scope".into(), v.clone());
            }
            if let Some(v) = r.get("protocol") {
                m.insert("protocol".into(), v.clone());
            }
            if let Some(v) = r.get("table") {
                m.insert("table".into(), v.clone());
            }
            out.push(m);
        }
        Some(out)
    };

    // Addresses
    let addresses = build_addresses(ip, filtered_routes.as_deref());

    let networkctl_text = query_networkctl_text(&name, runner);

    IfaceData {
        idx,
        name,
        adminstate: adminstate.to_string(),
        operstate,
        iproute_type,
        macaddress,
        nd_type,
        nd_kind,
        nd_setup_state,
        nd_network_file,
        nd_vendor,
        networkctl_text,
        nm_filename,
        nm_name,
        nm_type,
        nm_autoconnect,
        dns_addresses: dns_addr_list,
        dns_search: dns_search_list,
        routes: filtered_routes,
        addresses,
        bridge: None,
        bond: None,
        vrf: None,
        members: vec![],
    }
}

fn build_addresses(ip: &Value, routes: Option<&[Map<String, Value>]>) -> Option<Vec<Value>> {
    let addr_info = match ip.get("addr_info").and_then(|a| a.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return None,
    };

    // Collect RA networks from routes (IPv6, family=10, not default, protocol=ra)
    let mut ra_networks: Vec<(Ipv6Addr, u32)> = vec![];
    if let Some(routes) = routes {
        for route in routes {
            let family = route.get("family").and_then(|v| v.as_u64()).unwrap_or(0);
            let protocol = route.get("protocol").and_then(|v| v.as_str()).unwrap_or("");
            let to = route.get("to").and_then(|v| v.as_str()).unwrap_or("");
            if family == 10 && protocol == "ra" && to != "default" {
                if let Some((net, prefix)) = parse_ipv6_cidr(to) {
                    ra_networks.push((net, prefix));
                }
            }
        }
    }

    let mut addresses = vec![];
    for addr in addr_info {
        let local = match addr.get("local").and_then(|v| v.as_str()) {
            Some(l) => l,
            None => continue,
        };
        let prefixlen = addr.get("prefixlen").and_then(|v| v.as_u64()).unwrap_or(0);
        let dynamic = addr
            .get("dynamic")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        let mut flags: Vec<&str> = vec![];

        // link-local detection
        if is_link_local(local) {
            flags.push("link");
        }
        if dynamic {
            flags.push("dynamic");
        }

        // RA detection for IPv6
        if let Ok(ip6) = local.parse::<Ipv6Addr>() {
            for (net, prefix) in &ra_networks {
                if ipv6_in_network(&ip6, net, *prefix) {
                    flags.push("ra");
                    break;
                }
            }
        }

        // DHCP detection from routes
        if let Some(routes) = routes {
            'outer: for route in routes {
                let from_addr = route.get("from").and_then(|v| v.as_str()).unwrap_or("");
                let protocol = route.get("protocol").and_then(|v| v.as_str()).unwrap_or("");
                if from_addr == local && protocol == "dhcp" && !flags.contains(&"dhcp") {
                    flags.push("dhcp");
                    break 'outer;
                }
            }
        }

        let ip_key = local.to_lowercase();
        let mut inner = Map::new();
        inner.insert("prefix".into(), Value::Number(prefixlen.into()));
        if !flags.is_empty() {
            inner.insert(
                "flags".into(),
                Value::Array(flags.iter().map(|s| Value::String(s.to_string())).collect()),
            );
        }
        let mut outer = Map::new();
        outer.insert(ip_key, Value::Object(inner));
        addresses.push(Value::Object(outer));
    }
    Some(addresses)
}

fn is_link_local(addr: &str) -> bool {
    if let Ok(ip4) = addr.parse::<Ipv4Addr>() {
        return ip4.is_link_local();
    }
    if let Ok(ip6) = addr.parse::<Ipv6Addr>() {
        let segs = ip6.segments();
        return segs[0] == 0xfe80;
    }
    false
}

fn parse_ipv6_cidr(cidr: &str) -> Option<(Ipv6Addr, u32)> {
    let parts: Vec<&str> = cidr.splitn(2, '/').collect();
    let addr: Ipv6Addr = parts[0].parse().ok()?;
    let prefix: u32 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(128);
    Some((addr, prefix))
}

fn ipv6_in_network(addr: &Ipv6Addr, net: &Ipv6Addr, prefix: u32) -> bool {
    if prefix == 0 {
        return true;
    }
    if prefix > 128 {
        return false;
    }
    let addr_bits = u128::from_be_bytes(addr.octets());
    let net_bits = u128::from_be_bytes(net.octets());
    let mask = if prefix == 128 {
        u128::MAX
    } else {
        !((1u128 << (128 - prefix)) - 1)
    };
    (addr_bits & mask) == (net_bits & mask)
}

// ── Correlate bridge/bond/vrf ─────────────────────────────────────────────────

fn correlate_members_and_uplinks(ifaces: &mut [IfaceData], runner: &impl CommandRunner) {
    let uplink_types = ["bond", "bridge", "vrf"];
    let mut members_to_uplink: HashMap<String, (String, &'static str)> = HashMap::new();
    let mut uplink_to_members: HashMap<String, Vec<String>> = HashMap::new();

    let uplinks: Vec<(String, &'static str)> = ifaces
        .iter()
        .filter_map(|iface| {
            if let Some(t) = iface.iface_type() {
                if uplink_types.contains(&t) {
                    return Some((iface.name.clone(), t));
                }
            }
            None
        })
        .collect();

    for (name, utype) in &uplinks {
        let members = query_members(name, runner);
        for member in &members {
            members_to_uplink.insert(member.clone(), (name.clone(), utype));
        }
        uplink_to_members.insert(name.clone(), members);
    }

    for iface in ifaces.iter_mut() {
        if let Some((uplink_name, uplink_type)) = members_to_uplink.get(&iface.name) {
            match *uplink_type {
                "bridge" => iface.bridge = Some(uplink_name.clone()),
                "bond" => iface.bond = Some(uplink_name.clone()),
                "vrf" => iface.vrf = Some(uplink_name.clone()),
                _ => {}
            }
        }
        if uplink_types.contains(&iface.iface_type().unwrap_or("")) {
            if let Some(members) = uplink_to_members.get(&iface.name) {
                iface.members = members.clone();
            }
        }
    }
}

// ── Online state ──────────────────────────────────────────────────────────────

fn query_online_state(ifaces: &[&IfaceData]) -> bool {
    for iface in ifaces {
        if !iface.is_up() {
            continue;
        }
        let has_addrs = iface
            .addresses
            .as_ref()
            .map(|a| !a.is_empty())
            .unwrap_or(false);
        let has_routes = iface
            .routes
            .as_ref()
            .map(|r| !r.is_empty())
            .unwrap_or(false);
        let has_dns = iface
            .dns_addresses
            .as_ref()
            .map(|d| !d.is_empty())
            .unwrap_or(false);
        if !has_addrs || !has_routes || !has_dns {
            continue;
        }

        // check non-link-local IPs
        let non_local: Vec<_> = iface
            .addresses
            .as_ref()
            .unwrap()
            .iter()
            .filter_map(|entry| {
                let obj = entry.as_object()?;
                let (ip, extra) = obj.iter().next()?;
                let flags = extra.get("flags")?.as_array()?;
                let is_link = flags.iter().any(|f| f.as_str() == Some("link"));
                if is_link {
                    None
                } else {
                    Some(ip.clone())
                }
            })
            .collect();

        let has_default = iface
            .routes
            .as_ref()
            .unwrap()
            .iter()
            .any(|r| r.get("to").and_then(|v| v.as_str()) == Some("default"));

        if !non_local.is_empty() && has_default {
            return true;
        }
    }
    false
}

// ── JSON serializer (Python-compatible) ───────────────────────────────────────

/// Escape a string for embedding in JSON output, matching the subset of
/// escapes produced by Python's `json.dumps` for ASCII control characters.
fn escape_json_string(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

fn python_json_dumps(v: &Value) -> String {
    match v {
        Value::Null => "null".to_string(),
        Value::Bool(b) => if *b { "true" } else { "false" }.to_string(),
        Value::Number(n) => n.to_string(),
        Value::String(s) => format!("\"{}\"", escape_json_string(s)),
        Value::Array(arr) => {
            let items: Vec<String> = arr.iter().map(python_json_dumps).collect();
            format!("[{}]", items.join(", "))
        }
        Value::Object(map) => {
            let items: Vec<String> = map
                .iter()
                .map(|(k, v)| format!("\"{}\": {}", escape_json_string(k), python_json_dumps(v)))
                .collect();
            format!("{{{}}}", items.join(", "))
        }
    }
}

// ── YAML serializer (Python yaml.dump-compatible: sorted keys, null/false) ────

fn to_yaml(v: &Value, indent: usize) -> String {
    use std::fmt::Write as _;
    match v {
        Value::Null => "null\n".to_string(),
        Value::Bool(b) => format!("{}\n", if *b { "true" } else { "false" }),
        Value::Number(n) => format!("{n}\n"),
        Value::String(s) => format!("{}\n", yaml_scalar(s)),
        Value::Array(arr) => {
            if arr.is_empty() {
                return "[]\n".to_string();
            }
            let pad = " ".repeat(indent);
            let mut out = "\n".to_string();
            for item in arr {
                let rendered = to_yaml(item, indent + 2);
                let trimmed = rendered.trim_end_matches('\n').trim_start();
                writeln!(out, "{pad}- {trimmed}").unwrap();
            }
            out
        }
        Value::Object(map) => {
            if map.is_empty() {
                return "{}\n".to_string();
            }
            let pad = " ".repeat(indent);
            let mut keys: Vec<&str> = map.keys().map(String::as_str).collect();
            keys.sort_unstable();
            let mut out = "\n".to_string();
            for key in keys {
                let val = &map[key];
                let rendered = to_yaml(val, indent + 2);
                if rendered.starts_with('\n') {
                    // nested block
                    write!(out, "{pad}{key}:{rendered}").unwrap();
                } else {
                    write!(out, "{pad}{key}: {rendered}").unwrap();
                }
            }
            out
        }
    }
}

fn yaml_scalar(s: &str) -> String {
    // Strings that need quoting: empty, contain ': ', start with special chars,
    // are YAML reserved words, or contain newlines
    let needs_quote = s.is_empty()
        || s == "true"
        || s == "false"
        || s == "null"
        || s == "yes"
        || s == "no"
        || s.contains(": ")
        || s.contains('\n')
        || s.starts_with('{')
        || s.starts_with('[')
        || s.starts_with('\'')
        || s.starts_with('"')
        || s.starts_with('*')
        || s.starts_with('&')
        || s.starts_with('!')
        || s.starts_with('#')
        || s.starts_with('%')
        || s.starts_with('@');

    if needs_quote {
        let escaped = s.replace('\\', "\\\\").replace('\'', "''");
        format!("'{}'", escaped)
    } else {
        s.to_string()
    }
}

fn render_yaml(data: &Map<String, Value>) -> String {
    use std::fmt::Write as _;
    let mut keys: Vec<&str> = data.keys().map(String::as_str).collect();
    keys.sort_unstable();
    let mut out = String::new();
    for key in keys {
        let val = &data[key];
        let rendered = to_yaml(val, 2);
        if rendered.starts_with('\n') {
            write!(out, "{key}:{rendered}").unwrap();
        } else {
            write!(out, "{key}: {rendered}").unwrap();
        }
    }
    out
}

// ── Tabular output ────────────────────────────────────────────────────────────

const PAD: usize = 18;

fn pline(title: &str, value: &str) {
    println!("{title:>PAD$} {value}");
}

fn pretty_print(
    data: &Map<String, Value>,
    total: usize,
    ifname_filter: Option<&str>,
    verbose: bool,
) {
    use std::io::IsTerminal;
    let use_color = std::io::stdout().is_terminal();

    // Global state
    let global = data.get("netplan-global-state").and_then(|v| v.as_object());
    if let Some(gs) = global {
        let online = gs.get("online").and_then(|v| v.as_bool()).unwrap_or(false);
        let state_str = if online {
            c_bold_green("online", use_color)
        } else {
            c_bold_red("offline", use_color)
        };
        pline("Online state:", &state_str);

        if let Some(ns) = gs.get("nameservers").and_then(|v| v.as_object()) {
            let addresses = ns
                .get("addresses")
                .and_then(|v| v.as_array())
                .map(|a| a.iter().filter_map(|v| v.as_str()).collect::<Vec<_>>())
                .unwrap_or_default();
            let mode = ns.get("mode").and_then(|v| v.as_str());
            let search = ns
                .get("search")
                .and_then(|v| v.as_array())
                .map(|a| a.iter().filter_map(|v| v.as_str()).collect::<Vec<_>>())
                .unwrap_or_default();

            for (i, addr) in addresses.iter().enumerate() {
                let title = if i == 0 { "DNS Addresses:" } else { "" };
                if let Some(m) = mode {
                    pline(
                        title,
                        &format!("{} {}", addr, c_dim(&format!("({})", m), use_color)),
                    );
                } else {
                    pline(title, addr);
                }
            }
            for (i, s) in search.iter().enumerate() {
                pline(if i == 0 { "DNS Search:" } else { "" }, s);
            }
        }
        println!();
    }

    // Per interface
    let interfaces: Vec<(&str, &Value)> = data
        .iter()
        .filter(|(k, _)| *k != "netplan-global-state")
        .map(|(k, v)| (k.as_str(), v))
        .collect();

    let total_shown = interfaces.len();
    for (idx, (ifname, ifconfig)) in interfaces.iter().enumerate() {
        if let Some(filter) = ifname_filter {
            if *ifname != filter {
                continue;
            }
        }

        let obj = match ifconfig.as_object() {
            Some(o) => o,
            None => continue,
        };

        // Interface header
        display_interface_header(ifname, obj, use_color);
        display_mac_address(obj, use_color);
        display_ip_addresses(obj, use_color);
        display_dns_addresses(obj);
        display_dns_search(obj);
        display_routes(obj, verbose, use_color);
        display_bridge(obj);
        display_bond(obj);
        display_vrf(obj);
        display_members(obj);
        display_activation_mode(obj);

        // newline separator between interfaces (not after the last one, unless more follow)
        if ifname_filter.is_none() && idx + 1 < total_shown {
            println!();
        }
    }

    let hidden = total.saturating_sub(total_shown);
    if hidden > 0 {
        println!();
        println!(
            "{} inactive interfaces hidden. Use \"--all\" to show all.",
            hidden
        );
    }
}

fn display_interface_header(ifname: &str, obj: &Map<String, Value>, use_color: bool) {
    let operstate = obj
        .get("operstate")
        .and_then(|v| v.as_str())
        .unwrap_or("UNKNOWN");
    let adminstate = obj
        .get("adminstate")
        .and_then(|v| v.as_str())
        .unwrap_or("UNKNOWN");

    let (bullet, state) = if operstate == "UP" && adminstate == "UP" {
        (c_bold_green("●", use_color), c_bold_green("UP", use_color))
    } else if operstate == "DOWN" && adminstate == "DOWN" {
        (c_bold_red("●", use_color), c_bold_red("DOWN", use_color))
    } else {
        let s = format!("{}/{}", operstate, adminstate);
        (c_bold_yellow("●", use_color), c_bold_yellow(&s, use_color))
    };

    let idx = obj.get("index").and_then(|v| v.as_u64()).unwrap_or(0);
    let full_type = {
        let t = obj.get("type").and_then(|v| v.as_str()).unwrap_or("other");
        let ssid = obj.get("ssid").and_then(|v| v.as_str());
        let tunnel_mode = obj.get("tunnel_mode").and_then(|v| v.as_str());
        if t == "wifi" {
            if let Some(ssid) = ssid {
                format!("{}/\"{}\"", t, ssid)
            } else {
                t.to_string()
            }
        } else if t == "tunnel" {
            if let Some(mode) = tunnel_mode {
                format!("{}/{}", t, mode)
            } else {
                t.to_string()
            }
        } else {
            t.to_string()
        }
    };

    let backend = obj
        .get("backend")
        .and_then(|v| v.as_str())
        .unwrap_or("unmanaged");
    let netdef = match obj.get("id").and_then(|v| v.as_str()) {
        Some(id) => format!("{}: {}", backend, c_bold(id, use_color)),
        None => backend.to_string(),
    };

    println!(
        "{} {:>2}: {} {} {} ({})",
        bullet, idx, ifname, full_type, state, netdef
    );
}

fn display_mac_address(obj: &Map<String, Value>, use_color: bool) {
    if let Some(mac) = obj.get("macaddress").and_then(|v| v.as_str()) {
        let vendor = obj.get("vendor").and_then(|v| v.as_str());
        if let Some(v) = vendor {
            pline(
                "MAC Address:",
                &format!("{} {}", mac, c_dim(&format!("({})", v), use_color)),
            );
        } else {
            pline("MAC Address:", mac);
        }
    }
}

fn display_ip_addresses(obj: &Map<String, Value>, use_color: bool) {
    let addrs = match obj.get("addresses").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return,
    };
    for (i, entry) in addrs.iter().enumerate() {
        let title = if i == 0 { "Addresses:" } else { "" };
        if let Some(map) = entry.as_object() {
            if let Some((ip, extra)) = map.iter().next() {
                let prefix = extra.get("prefix").and_then(|v| v.as_u64()).unwrap_or(0);
                let flags: Vec<&str> = extra
                    .get("flags")
                    .and_then(|v| v.as_array())
                    .map(|a| a.iter().filter_map(|v| v.as_str()).collect())
                    .unwrap_or_default();
                let addr_str = format!("{}/{}", ip, prefix);
                let should_highlight = flags.is_empty() || flags.contains(&"dhcp");
                let colored_addr = c_bold(&addr_str, use_color && should_highlight);
                if flags.is_empty() {
                    pline(title, &colored_addr);
                } else {
                    pline(
                        title,
                        &format!(
                            "{} {}",
                            colored_addr,
                            c_dim(&format!("({})", flags.join(", ")), use_color)
                        ),
                    );
                }
            }
        }
    }
}

fn display_dns_addresses(obj: &Map<String, Value>) {
    let addrs = match obj.get("dns_addresses").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return,
    };
    for (i, addr) in addrs.iter().enumerate() {
        if let Some(s) = addr.as_str() {
            pline(if i == 0 { "DNS Addresses:" } else { "" }, s);
        }
    }
}

fn display_dns_search(obj: &Map<String, Value>) {
    let search = match obj.get("dns_search").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return,
    };
    for (i, s) in search.iter().enumerate() {
        if let Some(domain) = s.as_str() {
            pline(if i == 0 { "DNS Search:" } else { "" }, domain);
        }
    }
}

fn display_routes(obj: &Map<String, Value>, verbose: bool, use_color: bool) {
    let routes = match obj.get("routes").and_then(|v| v.as_array()) {
        Some(r) if !r.is_empty() => r,
        _ => return,
    };
    let mut displayed = 0;
    for route in routes {
        let r = match route.as_object() {
            Some(r) => r,
            None => continue,
        };
        let table_id = r.get("table").and_then(|v| v.as_str()).unwrap_or("main");
        // non-verbose: only main table (table==254 or table=="main")
        if !verbose {
            let is_main = table_id == "main" || table_id == "254";
            if !is_main {
                continue;
            }
        }

        let to = r.get("to").and_then(|v| v.as_str()).unwrap_or("");
        let via = r.get("via").and_then(|v| v.as_str()).unwrap_or("");
        let from = r.get("from").and_then(|v| v.as_str()).unwrap_or("");
        let metric = r.get("metric").and_then(|v| v.as_u64());
        let protocol = r.get("protocol").and_then(|v| v.as_str()).unwrap_or("");
        let scope = r.get("scope").and_then(|v| v.as_str()).unwrap_or("");
        let rtype = r.get("type").and_then(|v| v.as_str()).unwrap_or("");

        let to_colored = c_bold(to, use_color && to == "default");
        let mut route_str = to_colored;
        if !via.is_empty() {
            route_str.push_str(&format!(" via {}", via));
        }
        if !from.is_empty() {
            route_str.push_str(&format!(" from {}", from));
        }
        if let Some(m) = metric {
            route_str.push_str(&format!(" metric {}", m));
        }
        if verbose {
            route_str.push_str(&format!(" table {}", table_id));
        }

        let mut extra = vec![];
        if !protocol.is_empty() && protocol != "kernel" {
            extra.push(protocol);
        }
        if !scope.is_empty() && scope != "global" {
            extra.push(scope);
        }
        if !rtype.is_empty() && rtype != "unicast" {
            extra.push(rtype);
        }

        let title = if displayed == 0 { "Routes:" } else { "" };
        if extra.is_empty() {
            pline(title, &route_str);
        } else {
            pline(
                title,
                &format!(
                    "{} {}",
                    route_str,
                    c_dim(&format!("({})", extra.join(", ")), use_color)
                ),
            );
        }
        displayed += 1;
    }
}

fn display_bridge(obj: &Map<String, Value>) {
    if let Some(b) = obj.get("bridge").and_then(|v| v.as_str()) {
        pline("Bridge:", b);
    }
}

fn display_bond(obj: &Map<String, Value>) {
    if let Some(b) = obj.get("bond").and_then(|v| v.as_str()) {
        pline("Bond:", b);
    }
}

fn display_vrf(obj: &Map<String, Value>) {
    if let Some(v) = obj.get("vrf").and_then(|v| v.as_str()) {
        pline("VRF:", v);
    }
}

fn display_members(obj: &Map<String, Value>) {
    let members = match obj.get("interfaces").and_then(|v| v.as_array()) {
        Some(m) if !m.is_empty() => m,
        _ => return,
    };
    for (i, m) in members.iter().enumerate() {
        if let Some(name) = m.as_str() {
            pline(if i == 0 { "Interfaces:" } else { "" }, name);
        }
    }
}

fn display_activation_mode(obj: &Map<String, Value>) {
    if let Some(mode) = obj.get("activation_mode").and_then(|v| v.as_str()) {
        pline("Activation Mode:", mode);
    }
}

// ── Diff data structures ──────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
struct DiffRoute {
    to: String,
    via: String,
    from_addr: String,
    metric: Option<u64>,
    table: Option<u64>,
    scope: String,
    route_type: String,
    protocol: String,
    family: u64,
}

impl DiffRoute {
    fn new() -> Self {
        DiffRoute {
            to: String::new(),
            via: String::new(),
            from_addr: String::new(),
            metric: None,
            table: None,
            scope: String::new(),
            route_type: String::new(),
            protocol: String::new(),
            family: 0,
        }
    }
}

#[derive(Debug, Clone)]
struct NetplanIface {
    id: String,
    iface_type: String,
    dhcp4: bool,
    dhcp6: bool,
    link_local_ipv4: bool,
    link_local_ipv6: bool,
    accept_ra: Option<bool>,
    addresses: Vec<String>,
    nameservers: Vec<String>,
    search_domains: Vec<String>,
    routes: Vec<DiffRoute>,
    gateway4: Option<String>,
    gateway6: Option<String>,
    macaddress: Option<String>,
    bridge: Option<String>,
    bond: Option<String>,
    vrf: Option<String>,
}

#[derive(Debug, Default)]
struct IfaceDiff {
    missing_addresses_system: Vec<String>,
    missing_addresses_netplan: Vec<String>,
    missing_dhcp4_address: bool,
    missing_dhcp6_address: bool,
    missing_nameservers_system: Vec<String>,
    missing_nameservers_netplan: Vec<String>,
    missing_search_system: Vec<String>,
    missing_search_netplan: Vec<String>,
    missing_macaddress_system: Option<String>,
    missing_macaddress_netplan: Option<String>,
    missing_routes_system: Vec<DiffRoute>,
    missing_routes_netplan: Vec<DiffRoute>,
    missing_bridge_system: Option<String>,
    missing_bridge_netplan: Option<String>,
    missing_bond_system: Option<String>,
    missing_bond_netplan: Option<String>,
    missing_vrf_system: Option<String>,
    missing_vrf_netplan: Option<String>,
    missing_interfaces_system: Vec<String>,
    missing_interfaces_netplan: Vec<String>,
}

#[derive(Debug, Default)]
struct DiffReport {
    interfaces: HashMap<String, (u64, IfaceDiff)>,
    missing_interfaces_system: Vec<(String, String)>,
    missing_interfaces_netplan: Vec<(String, u64, String)>,
}

// ── Diff helpers ──────────────────────────────────────────────────────────────

fn compress_ipv6(addr: &str) -> String {
    if let Some(slash) = addr.find('/') {
        let ip_part = &addr[..slash];
        let prefix = &addr[slash..];
        if let Ok(ip) = ip_part.parse::<Ipv6Addr>() {
            return format!("{}{}", ip, prefix);
        }
    } else if let Ok(ip) = addr.parse::<Ipv6Addr>() {
        return ip.to_string();
    }
    addr.to_string()
}

fn normalize_ip(addr: &str) -> String {
    compress_ipv6(addr)
}

#[allow(dead_code)]
fn ip_family(addr: &str) -> u64 {
    let ip_part = addr.split('/').next().unwrap_or(addr);
    if ip_part.parse::<Ipv4Addr>().is_ok() {
        2
    } else {
        10
    }
}

fn parse_table_name(table: &str) -> Option<u64> {
    match table {
        "main" => Some(254),
        "local" => Some(255),
        "default" => Some(253),
        "unspec" => Some(0),
        s => s.parse::<u64>().ok(),
    }
}

fn is_link_local_ip(addr: &str) -> bool {
    let ip_part = addr.split('/').next().unwrap_or(addr);
    if let Ok(ip4) = ip_part.parse::<Ipv4Addr>() {
        return ip4.is_link_local();
    }
    if let Ok(ip6) = ip_part.parse::<Ipv6Addr>() {
        return ip6.segments()[0] == 0xfe80;
    }
    false
}

fn is_valid_macaddress(mac: &str) -> bool {
    let parts: Vec<&str> = mac.split(':').collect();
    if parts.len() != 6 {
        return false;
    }
    parts
        .iter()
        .all(|p| p.len() == 2 && p.chars().all(|c| c.is_ascii_hexdigit()))
}

fn ipv6_net_contains(net_str: &str, addr_str: &str) -> bool {
    let ip_part = addr_str.split('/').next().unwrap_or(addr_str);
    let net_ip = net_str.split('/').next().unwrap_or(net_str);
    let prefix: u32 = net_str
        .split('/')
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(128);
    if let (Ok(net), Ok(addr)) = (net_ip.parse::<Ipv6Addr>(), ip_part.parse::<Ipv6Addr>()) {
        let addr_bits = u128::from_be_bytes(addr.octets());
        let net_bits = u128::from_be_bytes(net.octets());
        let mask = if prefix == 0 {
            0u128
        } else if prefix >= 128 {
            u128::MAX
        } else {
            !((1u128 << (128 - prefix)) - 1)
        };
        return (addr_bits & mask) == (net_bits & mask);
    }
    false
}

fn ip_network_str(cidr: &str) -> String {
    let parts: Vec<&str> = cidr.splitn(2, '/').collect();
    let prefix: u32 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(32);
    if let Ok(ip4) = parts[0].parse::<Ipv4Addr>() {
        if prefix == 0 {
            return format!("0.0.0.0/{}", prefix);
        }
        let mask = if prefix >= 32 {
            0xFFFFFFFFu32
        } else {
            !((1u32 << (32 - prefix)) - 1)
        };
        let net_bits = u32::from_be_bytes(ip4.octets()) & mask;
        let net = Ipv4Addr::from(net_bits);
        return format!("{}/{}", net, prefix);
    }
    if let Ok(ip6) = parts[0].parse::<Ipv6Addr>() {
        let prefix6: u32 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(128);
        let addr_bits = u128::from_be_bytes(ip6.octets());
        let mask = if prefix6 == 0 {
            0u128
        } else if prefix6 >= 128 {
            u128::MAX
        } else {
            !((1u128 << (128 - prefix6)) - 1)
        };
        let net_bits = addr_bits & mask;
        let net = Ipv6Addr::from(net_bits.to_be_bytes());
        return format!("{}/{}", net, prefix6);
    }
    cidr.to_string()
}

// ── Load netplan configuration from YAML dump ─────────────────────────────────

fn load_netplan_ifaces(rootdir: &str) -> HashMap<String, NetplanIface> {
    use crate::netplan as np;

    let state = match np::load_state(rootdir) {
        Ok(s) => s,
        Err(_) => return HashMap::new(),
    };
    let yaml_str = match state.dump_yaml() {
        Ok(s) => s,
        Err(_) => return HashMap::new(),
    };

    let yaml_val: Value = match crate::yaml::from_str(&yaml_str) {
        Ok(v) => v,
        Err(_) => return HashMap::new(),
    };
    let network = match yaml_val.get("network") {
        Some(v) => v,
        None => return HashMap::new(),
    };

    let section_type_map = [
        ("ethernets", "ethernet"),
        ("wifis", "wifi"),
        ("modems", "modem"),
        ("bridges", "bridge"),
        ("bonds", "bond"),
        ("vlans", "vlan"),
        ("tunnels", "tunnel"),
        ("vrfs", "vrf"),
        ("dummy-devices", "dummy-device"),
        ("virtual-ethernets", "virtual-ethernet"),
        ("nm-devices", "other"),
    ];

    let mut ifaces: HashMap<String, NetplanIface> = HashMap::new();

    for (section, iface_type) in &section_type_map {
        let section_val = match network.get(section) {
            Some(v) if v.is_object() => v,
            _ => continue,
        };
        for (id, cfg) in section_val.as_object().unwrap() {
            let cfg = match cfg {
                Value::Object(m) => m,
                _ => continue,
            };

            let mut iface = NetplanIface {
                id: id.clone(),
                iface_type: iface_type.to_string(),
                dhcp4: false,
                dhcp6: false,
                link_local_ipv4: false,
                link_local_ipv6: false,
                accept_ra: None,
                addresses: vec![],
                nameservers: vec![],
                search_domains: vec![],
                routes: vec![],
                gateway4: None,
                gateway6: None,
                macaddress: None,
                bridge: None,
                bond: None,
                vrf: None,
            };

            // Read YAML fields for fallback (actual values come from C API below)
            if let Some(v) = cfg.get("dhcp4") {
                iface.dhcp4 = v.as_bool().unwrap_or(false);
            }
            if let Some(v) = cfg.get("dhcp6") {
                iface.dhcp6 = v.as_bool().unwrap_or(false);
            }
            if let Some(ll) = cfg.get("link-local") {
                if let Some(arr) = ll.as_array() {
                    for item in arr {
                        if item.as_str() == Some("ipv4") {
                            iface.link_local_ipv4 = true;
                        }
                        if item.as_str() == Some("ipv6") {
                            iface.link_local_ipv6 = true;
                        }
                    }
                }
            }
            if let Some(v) = cfg.get("accept-ra") {
                iface.accept_ra = v.as_bool();
            }

            // Addresses
            if let Some(addrs) = cfg.get("addresses") {
                if let Some(arr) = addrs.as_array() {
                    for a in arr {
                        let addr_str = match a {
                            Value::String(s) => normalize_ip(s),
                            Value::Object(m) => {
                                m.keys().next().map(|k| normalize_ip(k)).unwrap_or_default()
                            }
                            _ => continue,
                        };
                        if !addr_str.is_empty() {
                            iface.addresses.push(addr_str);
                        }
                    }
                }
            }

            // Nameservers
            if let Some(ns) = cfg.get("nameservers") {
                if let Some(addrs) = ns.get("addresses").and_then(|v| v.as_array()) {
                    for a in addrs {
                        if let Some(s) = a.as_str() {
                            iface.nameservers.push(s.to_string());
                        }
                    }
                }
                if let Some(search) = ns.get("search").and_then(|v| v.as_array()) {
                    for s in search {
                        if let Some(s) = s.as_str() {
                            iface.search_domains.push(s.to_string());
                        }
                    }
                }
            }

            // Routes
            if let Some(routes) = cfg.get("routes").and_then(|v| v.as_array()) {
                for r in routes {
                    if let Some(dr) = parse_yaml_route(r) {
                        iface.routes.push(dr);
                    }
                }
            }

            // gateway4/gateway6
            if let Some(v) = cfg.get("gateway4").and_then(|v| v.as_str()) {
                iface.gateway4 = Some(v.to_string());
            }
            if let Some(v) = cfg.get("gateway6").and_then(|v| v.as_str()) {
                iface.gateway6 = Some(normalize_ip(v));
            }

            // macaddress
            if let Some(v) = cfg.get("macaddress").and_then(|v| v.as_str()) {
                iface.macaddress = Some(v.to_string());
            }

            // bridge-link, bond-link, vrf-link (from YAML)
            if let Some(v) = cfg.get("bridge-link").and_then(|v| v.as_str()) {
                iface.bridge = Some(v.to_string());
            }
            if let Some(v) = cfg.get("bond-link").and_then(|v| v.as_str()) {
                iface.bond = Some(v.to_string());
            }
            if let Some(v) = cfg.get("vrf-link").and_then(|v| v.as_str()) {
                iface.vrf = Some(v.to_string());
            }

            ifaces.insert(id.clone(), iface);
        }
    }

    // Override with C API values (more reliable for dhcp4/dhcp6/link_local/accept_ra/macaddress/links)
    for netdef in state.netdefs() {
        let Ok(id) = netdef.id() else { continue };
        if let Some(iface) = ifaces.get_mut(&id) {
            iface.dhcp4 = netdef.dhcp4();
            iface.dhcp6 = netdef.dhcp6();
            iface.link_local_ipv4 = netdef.link_local_ipv4();
            iface.link_local_ipv6 = netdef.link_local_ipv6();
            iface.accept_ra = netdef.accept_ra();
            if let Some(mac) = netdef.macaddress().ok().flatten() {
                iface.macaddress = Some(mac);
            }
            if let Some(b) = netdef.bridge_link_id().ok().flatten() {
                iface.bridge = Some(b);
            }
            if let Some(b) = netdef.bond_link_id().ok().flatten() {
                iface.bond = Some(b);
            }
            if let Some(v) = netdef.vrf_link_id().ok().flatten() {
                iface.vrf = Some(v);
            }
        }
    }

    ifaces
}

fn parse_yaml_route(r: &Value) -> Option<DiffRoute> {
    let m = r.as_object()?;
    let mut dr = DiffRoute::new();
    if let Some(to) = m.get("to").and_then(|v| v.as_str()) {
        dr.to = normalize_ip(to);
        // strip /32 and /128 suffixes
        if dr.to != "default" {
            let parts: Vec<&str> = dr.to.splitn(2, '/').collect();
            if parts.len() == 2 && (parts[1] == "32" || parts[1] == "128") {
                dr.to = parts[0].to_string();
            }
        }
    }
    if let Some(via) = m.get("via").and_then(|v| v.as_str()) {
        dr.via = normalize_ip(via);
    }
    if let Some(from) = m
        .get("on-link")
        .and_then(|v| v.as_str())
        .or_else(|| m.get("from").and_then(|v| v.as_str()))
    {
        dr.from_addr = normalize_ip(from);
    }
    if let Some(metric) = m.get("metric").and_then(|v| v.as_u64()) {
        dr.metric = Some(metric);
    }
    if let Some(table) = m.get("table") {
        let table_num = if let Some(n) = table.as_u64() {
            Some(n)
        } else if let Some(s) = table.as_str() {
            parse_table_name(s)
        } else {
            None
        };
        // UNSPEC (4294967295) maps to main (254)
        dr.table = match table_num {
            Some(n) if n == u64::MAX || n == 4294967295 => Some(254),
            other => other,
        };
    }
    if let Some(scope) = m.get("scope").and_then(|v| v.as_str()) {
        dr.scope = scope.to_string();
    }
    if let Some(t) = m.get("type").and_then(|v| v.as_str()) {
        dr.route_type = t.to_string();
    }
    if let Some(proto) = m.get("protocol").and_then(|v| v.as_str()) {
        dr.protocol = proto.to_string();
    }
    // derive family from "to"
    if dr.to == "default" {
        // Can't determine from "default" alone; leave as 0
    } else {
        let ip_part = dr.to.split('/').next().unwrap_or(&dr.to);
        if ip_part.parse::<Ipv4Addr>().is_ok() {
            dr.family = 2;
        } else if ip_part.parse::<Ipv6Addr>().is_ok() {
            dr.family = 10;
        }
    }
    Some(dr)
}

fn system_route_to_diff(r: &Map<String, Value>) -> DiffRoute {
    let mut dr = DiffRoute::new();
    if let Some(to) = r.get("to").and_then(|v| v.as_str()) {
        dr.to = normalize_ip(to);
    }
    if let Some(via) = r.get("via").and_then(|v| v.as_str()) {
        dr.via = normalize_ip(via);
    }
    if let Some(from) = r.get("from").and_then(|v| v.as_str()) {
        dr.from_addr = normalize_ip(from);
    }
    if let Some(m) = r.get("metric").and_then(|v| v.as_u64()) {
        dr.metric = Some(m);
    }
    if let Some(table) = r.get("table") {
        dr.table = if let Some(n) = table.as_u64() {
            Some(n)
        } else if let Some(s) = table.as_str() {
            parse_table_name(s)
        } else {
            None
        };
    }
    if let Some(scope) = r.get("scope").and_then(|v| v.as_str()) {
        dr.scope = scope.to_string();
    }
    if let Some(t) = r.get("type").and_then(|v| v.as_str()) {
        dr.route_type = t.to_string();
    }
    if let Some(proto) = r.get("protocol").and_then(|v| v.as_str()) {
        dr.protocol = proto.to_string();
    }
    if let Some(f) = r.get("family").and_then(|v| v.as_u64()) {
        dr.family = f;
    }
    dr
}

fn filter_system_routes(
    routes: &[Map<String, Value>],
    system_addresses: &[String],
    netplan: &NetplanIface,
) -> Vec<DiffRoute> {
    let local_networks: Vec<String> = system_addresses
        .iter()
        .filter_map(|addr| {
            let net = ip_network_str(addr);
            // exclude fe80::/64
            if net == "fe80::/64" {
                None
            } else {
                Some(net)
            }
        })
        .collect();
    let addresses: Vec<String> = system_addresses
        .iter()
        .map(|addr| addr.split('/').next().unwrap_or(addr).to_string())
        .collect();

    let link_local_ipv4 = netplan.link_local_ipv4;
    let link_local_ipv6 = netplan.link_local_ipv6;
    let accept_ra = netplan.accept_ra;

    let mut out = vec![];
    for r in routes {
        let dr = system_route_to_diff(r);

        // Filter link-scoped routes (but not link-local or default)
        if dr.scope == "link" && dr.to != "default" && !is_link_local_ip(&dr.to) {
            continue;
        }

        // Filter DHCP routes
        if dr.protocol == "dhcp" {
            continue;
        }

        // Filter RA routes if accept_ra is not false
        if dr.protocol == "ra" && accept_ra != Some(false) {
            continue;
        }

        // Filter link-local routes (if link_local is enabled)
        if dr.to != "default" && is_link_local_ip(&dr.to) {
            if dr.family == 10 && link_local_ipv6 {
                continue;
            }
            if dr.family == 2 && link_local_ipv4 {
                continue;
            }
        }

        // Filter host-scoped local routes
        if dr.scope == "host"
            && dr.route_type == "local"
            && (addresses.contains(&dr.to) || {
                let ip_part = dr.to.split('/').next().unwrap_or(&dr.to);
                ip_part.parse::<Ipv4Addr>().is_ok_and(|ip| ip.is_loopback())
                    || ip_part.parse::<Ipv6Addr>().is_ok_and(|ip| ip.is_loopback())
            })
        {
            continue;
        }

        // Filter IPv6 multicast ff00::/8
        if dr.family == 10 && dr.route_type == "multicast" && dr.to == "ff00::/8" {
            continue;
        }

        // Filter IPv6 local routes matching local networks or addresses
        if dr.family == 10 && dr.protocol != "ra" {
            if local_networks.contains(&dr.to) || addresses.contains(&dr.to) {
                continue;
            }
            // Also check if dr.to is contained in any local network
            if local_networks
                .iter()
                .any(|net| ipv6_net_contains(net, &dr.to))
            {
                continue;
            }
        }

        out.push(dr);
    }
    out
}

fn normalize_netplan_routes(routes: &[DiffRoute]) -> Vec<DiffRoute> {
    routes
        .iter()
        .map(|r| {
            let mut dr = r.clone();
            // UNSPEC table → main (254)
            if dr.table.is_none() {
                dr.table = Some(254);
            }
            dr.to = normalize_ip(&dr.to);
            dr.via = normalize_ip(&dr.via);
            dr.from_addr = normalize_ip(&dr.from_addr);
            // strip /32 and /128
            if dr.to != "default" {
                let parts: Vec<&str> = dr.to.splitn(2, '/').collect();
                if parts.len() == 2 && (parts[1] == "32" || parts[1] == "128") {
                    dr.to = parts[0].to_string();
                }
            }
            dr
        })
        .collect()
}

fn normalize_gateway_routes(
    np: &NetplanIface,
    system_routes: &[Map<String, Value>],
) -> Vec<DiffRoute> {
    let mut out = vec![];

    if let Some(gw4) = &np.gateway4 {
        let default_static: Vec<&Map<String, Value>> = system_routes
            .iter()
            .filter(|r| {
                r.get("to").and_then(|v| v.as_str()) == Some("default")
                    && r.get("family").and_then(|v| v.as_u64()) == Some(2)
                    && r.get("protocol").and_then(|v| v.as_str()) == Some("static")
            })
            .collect();
        let mut dr = DiffRoute::new();
        dr.to = "default".to_string();
        dr.via = gw4.clone();
        dr.family = 2;
        dr.protocol = "static".to_string();
        if default_static.len() == 1 {
            if let Some(m) = default_static[0].get("metric").and_then(|v| v.as_u64()) {
                dr.metric = Some(m);
            }
            if let Some(t) = default_static[0].get("table") {
                dr.table = if let Some(n) = t.as_u64() {
                    Some(n)
                } else if let Some(s) = t.as_str() {
                    parse_table_name(s)
                } else {
                    None
                };
            }
        }
        out.push(dr);
    }

    if let Some(gw6) = &np.gateway6 {
        let default_static: Vec<&Map<String, Value>> = system_routes
            .iter()
            .filter(|r| {
                r.get("to").and_then(|v| v.as_str()) == Some("default")
                    && r.get("family").and_then(|v| v.as_u64()) == Some(10)
                    && r.get("protocol").and_then(|v| v.as_str()) == Some("static")
            })
            .collect();
        let mut dr = DiffRoute::new();
        dr.to = "default".to_string();
        dr.via = normalize_ip(gw6);
        dr.family = 10;
        dr.protocol = "static".to_string();
        if default_static.len() == 1 {
            if let Some(m) = default_static[0].get("metric").and_then(|v| v.as_u64()) {
                dr.metric = Some(m);
            }
            if let Some(t) = default_static[0].get("table") {
                dr.table = if let Some(n) = t.as_u64() {
                    Some(n)
                } else if let Some(s) = t.as_str() {
                    parse_table_name(s)
                } else {
                    None
                };
            }
        }
        out.push(dr);
    }

    out
}

// ── Diff computation ──────────────────────────────────────────────────────────

fn compute_diff(
    system_state: &Map<String, Value>,
    netplan_ifaces: &HashMap<String, NetplanIface>,
    ifname_filter: Option<&str>,
) -> DiffReport {
    let mut report = DiffReport::default();

    // Collect system interfaces that have a netdef_id
    let system_netdef_ids: HashSet<String> = system_state
        .iter()
        .filter(|(k, _)| *k != "netplan-global-state")
        .filter_map(|(_, v)| v.get("id").and_then(|id| id.as_str()).map(String::from))
        .collect();

    // missing_interfaces_system: netplan-only netdefs (not wifi)
    let mut np_only: Vec<(String, String)> = netplan_ifaces
        .iter()
        .filter(|(id, np)| !system_netdef_ids.contains(*id) && np.iface_type != "wifi")
        .map(|(id, np)| (id.clone(), np.iface_type.clone()))
        .collect();
    np_only.sort_by(|a, b| a.0.cmp(&b.0));

    for (id, itype) in np_only {
        if let Some(filter) = ifname_filter {
            if id != filter {
                continue;
            }
        }
        report.missing_interfaces_system.push((id, itype));
    }

    // Build reverse map: system interface name → netplan iface (matching via netdef_id)
    // For each system interface, find the matching netplan iface
    let mut system_to_netplan: HashMap<String, &NetplanIface> = HashMap::new();
    for (ifname, sys_val) in system_state.iter() {
        if ifname == "netplan-global-state" {
            continue;
        }
        if let Some(netdef_id) = sys_val.get("id").and_then(|v| v.as_str()) {
            if let Some(np) = netplan_ifaces.get(netdef_id) {
                system_to_netplan.insert(ifname.clone(), np);
            }
        }
    }

    // missing_interfaces_netplan: system-only interfaces (no netplan match)
    let mut sys_only: Vec<(String, u64, String)> = system_state
        .iter()
        .filter(|(k, _)| *k != "netplan-global-state")
        .filter(|(k, _)| !system_to_netplan.contains_key(*k))
        .map(|(k, v)| {
            let idx = v.get("index").and_then(|i| i.as_u64()).unwrap_or(0);
            let t = v
                .get("type")
                .and_then(|t| t.as_str())
                .unwrap_or("other")
                .to_string();
            (k.clone(), idx, t)
        })
        .collect();
    sys_only.sort_by_key(|x| x.1);

    for (name, idx, itype) in sys_only {
        if let Some(filter) = ifname_filter {
            if name != filter {
                continue;
            }
        }
        report.missing_interfaces_netplan.push((name, idx, itype));
    }

    // Per-interface diff
    for (ifname, sys_val) in system_state.iter() {
        if ifname == "netplan-global-state" {
            continue;
        }
        let np = match system_to_netplan.get(ifname) {
            Some(n) => n,
            None => continue,
        };
        if let Some(filter) = ifname_filter {
            if ifname != filter {
                continue;
            }
        }

        let idx = sys_val.get("index").and_then(|v| v.as_u64()).unwrap_or(0);
        let mut diff = IfaceDiff::default();

        // addresses
        let sys_addr_map: HashMap<String, Vec<String>> = {
            let mut m = HashMap::new();
            if let Some(addrs) = sys_val.get("addresses").and_then(|v| v.as_array()) {
                for entry in addrs {
                    if let Some(obj) = entry.as_object() {
                        if let Some((ip, extra)) = obj.iter().next() {
                            let prefix = extra.get("prefix").and_then(|v| v.as_u64()).unwrap_or(0);
                            let full = format!("{}/{}", ip, prefix);
                            let flags: Vec<String> = extra
                                .get("flags")
                                .and_then(|v| v.as_array())
                                .map(|a| {
                                    a.iter()
                                        .filter_map(|v| v.as_str().map(String::from))
                                        .collect()
                                })
                                .unwrap_or_default();
                            m.insert(full, flags);
                        }
                    }
                }
            }
            m
        };

        let mut missing_dhcp4 = np.dhcp4;
        let mut missing_dhcp6 = np.dhcp6;

        let mut system_static_ips: HashSet<String> = HashSet::new();
        for (addr, flags) in &sys_addr_map {
            let ip_iface_obj = addr.parse::<std::net::IpAddr>().ok().map(|ip| {
                (
                    ip,
                    addr.split('/')
                        .nth(1)
                        .and_then(|p| p.parse::<u32>().ok())
                        .unwrap_or(32),
                )
            });

            let is_dhcp =
                flags.contains(&"dhcp".to_string()) || flags.contains(&"dynamic".to_string());
            let is_link = flags.contains(&"link".to_string());
            let is_ra = flags.contains(&"ra".to_string());
            let is_dynamic = is_dhcp || is_link || is_ra;

            // Static IPs
            if !is_dynamic {
                system_static_ips.insert(addr.clone());
            }

            // Link-local: if present but link-local not enabled in netplan → count as diff
            if is_link {
                if let Ok(ip) = addr
                    .split('/')
                    .next()
                    .unwrap_or("")
                    .parse::<std::net::IpAddr>()
                {
                    if ip.is_ipv4() && !np.link_local_ipv4 {
                        system_static_ips.insert(addr.clone());
                    }
                    if ip.is_ipv6() && !np.link_local_ipv6 {
                        system_static_ips.insert(addr.clone());
                    }
                }
            }

            // RA addresses: only a diff if accept_ra is false
            if is_ra && np.accept_ra == Some(false) {
                system_static_ips.insert(addr.clone());
            }

            // DHCP accounting
            if let Ok(ip) = addr
                .split('/')
                .next()
                .unwrap_or("")
                .parse::<std::net::IpAddr>()
            {
                if ip.is_ipv4() && is_dhcp {
                    missing_dhcp4 = false;
                }
                if ip.is_ipv6() && flags.contains(&"dhcp".to_string()) {
                    missing_dhcp6 = false;
                }
            }
            let _ = ip_iface_obj;
        }

        let np_ips: HashSet<String> = np.addresses.iter().map(|a| normalize_ip(a)).collect();

        let mut in_np_only: Vec<String> = np_ips.difference(&system_static_ips).cloned().collect();
        let mut in_sys_only: Vec<String> = system_static_ips.difference(&np_ips).cloned().collect();
        in_np_only.sort();
        in_sys_only.sort();

        if missing_dhcp4 {
            diff.missing_dhcp4_address = true;
        }
        if missing_dhcp6 {
            diff.missing_dhcp6_address = true;
        }
        diff.missing_addresses_system = in_np_only;
        diff.missing_addresses_netplan = in_sys_only;

        // nameservers
        let sys_ns: HashSet<String> = sys_val
            .get("dns_addresses")
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        let np_ns: HashSet<String> = np.nameservers.iter().cloned().collect();

        // Heuristic: if netplan has dhcp4/dhcp6 and no explicit nameservers, filter them
        let mut effective_sys_ns = sys_ns.clone();
        if np_ns.is_empty() {
            if np.dhcp4 {
                effective_sys_ns.retain(|ns| ns.parse::<Ipv4Addr>().is_err());
            }
            if np.dhcp6 {
                effective_sys_ns.retain(|ns| ns.parse::<Ipv6Addr>().is_err());
            }
        }

        let ns_np_only: HashSet<String> = np_ns.difference(&effective_sys_ns).cloned().collect();
        let ns_sys_only: HashSet<String> = effective_sys_ns.difference(&np_ns).cloned().collect();
        if !ns_sys_only.is_empty() {
            let mut v: Vec<String> = ns_sys_only.into_iter().collect();
            v.sort();
            diff.missing_nameservers_netplan = v;
        }
        if !ns_np_only.is_empty() {
            let mut v: Vec<String> = ns_np_only.into_iter().collect();
            v.sort();
            diff.missing_nameservers_system = v;
        }

        // search domains
        let sys_search: HashSet<String> = sys_val
            .get("dns_search")
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        let np_search: HashSet<String> = np.search_domains.iter().cloned().collect();
        let mut effective_sys_search = sys_search.clone();
        if np_search.is_empty() && (np.dhcp4 || np.dhcp6) {
            effective_sys_search.clear();
        }
        let search_np_only: HashSet<String> = np_search
            .difference(&effective_sys_search)
            .cloned()
            .collect();
        let search_sys_only: HashSet<String> = effective_sys_search
            .difference(&np_search)
            .cloned()
            .collect();
        if !search_sys_only.is_empty() {
            let mut v: Vec<String> = search_sys_only.into_iter().collect();
            v.sort();
            diff.missing_search_netplan = v;
        }
        if !search_np_only.is_empty() {
            let mut v: Vec<String> = search_np_only.into_iter().collect();
            v.sort();
            diff.missing_search_system = v;
        }

        // MAC address
        let sys_mac = sys_val
            .get("macaddress")
            .and_then(|v| v.as_str())
            .map(String::from);
        let np_mac = np.macaddress.clone();
        if let (Some(sm), Some(nm)) = (&sys_mac, &np_mac) {
            if is_valid_macaddress(nm) && sm != nm {
                diff.missing_macaddress_system = Some(nm.clone());
                diff.missing_macaddress_netplan = Some(sm.clone());
            }
        }

        // Routes
        let system_routes_raw: Vec<Map<String, Value>> = sys_val
            .get("routes")
            .and_then(|v| v.as_array())
            .map(|a| a.iter().filter_map(|v| v.as_object().cloned()).collect())
            .unwrap_or_default();

        let sys_addr_list: Vec<String> = sys_addr_map.keys().cloned().collect();
        let filtered_sys_routes: HashSet<DiffRoute> =
            filter_system_routes(&system_routes_raw, &sys_addr_list, np)
                .into_iter()
                .collect();

        let np_normalized: HashSet<DiffRoute> = {
            let mut routes = normalize_netplan_routes(&np.routes);
            routes.extend(normalize_gateway_routes(np, &system_routes_raw));
            routes.into_iter().collect()
        };

        let routes_np_only: Vec<DiffRoute> = {
            let mut v: Vec<DiffRoute> = np_normalized
                .difference(&filtered_sys_routes)
                .cloned()
                .collect();
            v.sort_by(|a, b| a.to.cmp(&b.to));
            v
        };
        let routes_sys_only: Vec<DiffRoute> = {
            let mut v: Vec<DiffRoute> = filtered_sys_routes
                .difference(&np_normalized)
                .cloned()
                .collect();
            v.sort_by(|a, b| a.to.cmp(&b.to));
            v
        };
        if !routes_sys_only.is_empty() {
            diff.missing_routes_netplan = routes_sys_only;
        }
        if !routes_np_only.is_empty() {
            diff.missing_routes_system = routes_np_only;
        }

        // Parent links
        let sys_bridge = sys_val
            .get("bridge")
            .and_then(|v| v.as_str())
            .map(String::from);
        let sys_bond = sys_val
            .get("bond")
            .and_then(|v| v.as_str())
            .map(String::from);
        let sys_vrf = sys_val
            .get("vrf")
            .and_then(|v| v.as_str())
            .map(String::from);
        let sys_members: Vec<String> = sys_val
            .get("interfaces")
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();

        if sys_bridge != np.bridge {
            if let Some(b) = &np.bridge {
                diff.missing_bridge_system = Some(b.clone());
            }
            if let Some(b) = &sys_bridge {
                diff.missing_bridge_netplan = Some(b.clone());
            }
        }
        if sys_bond != np.bond {
            if let Some(b) = &np.bond {
                diff.missing_bond_system = Some(b.clone());
            }
            if let Some(b) = &sys_bond {
                diff.missing_bond_netplan = Some(b.clone());
            }
        }
        if sys_vrf != np.vrf {
            if let Some(v) = &np.vrf {
                diff.missing_vrf_system = Some(v.clone());
            }
            if let Some(v) = &sys_vrf {
                diff.missing_vrf_netplan = Some(v.clone());
            }
        }

        // Compute netplan member list from all ifaces that point to this bridge/bond/vrf
        let np_members: HashSet<String> = netplan_ifaces
            .values()
            .filter(|ni| {
                ni.bridge.as_deref() == Some(ifname)
                    || ni.bond.as_deref() == Some(ifname)
                    || ni.vrf.as_deref() == Some(ifname)
            })
            .map(|ni| ni.id.clone())
            .collect();
        let sys_members_set: HashSet<String> = sys_members.into_iter().collect();
        if sys_members_set != np_members && (!sys_members_set.is_empty() || !np_members.is_empty())
        {
            let missing_sys: Vec<String> = {
                let mut v: Vec<String> = np_members.difference(&sys_members_set).cloned().collect();
                v.sort();
                v
            };
            let missing_np: Vec<String> = {
                let mut v: Vec<String> = sys_members_set.difference(&np_members).cloned().collect();
                v.sort();
                v
            };
            diff.missing_interfaces_system = missing_sys;
            diff.missing_interfaces_netplan = missing_np;
        }

        report.interfaces.insert(ifname.clone(), (idx, diff));
    }

    report
}

// ── Diff tabular output ───────────────────────────────────────────────────────

const PAD_DIFF: usize = 20;

// ANSI color helpers — no-ops when use_color is false
fn ansi(s: &str, code: u8) -> String {
    format!("\x1b[{}m{}\x1b[0m", code, s)
}
fn ansi2(s: &str, c1: u8, c2: u8) -> String {
    format!("\x1b[{};{}m{}\x1b[0m", c1, c2, s)
}
fn c_green(s: &str, on: bool) -> String {
    if on {
        ansi(s, 32)
    } else {
        s.to_string()
    }
}
fn c_red(s: &str, on: bool) -> String {
    if on {
        ansi(s, 31)
    } else {
        s.to_string()
    }
}
fn c_yellow(s: &str, on: bool) -> String {
    if on {
        ansi(s, 33)
    } else {
        s.to_string()
    }
}
fn c_dim(s: &str, on: bool) -> String {
    if on {
        ansi(s, 2)
    } else {
        s.to_string()
    }
}
fn c_bold(s: &str, on: bool) -> String {
    if on {
        ansi(s, 1)
    } else {
        s.to_string()
    }
}
fn c_bold_green(s: &str, on: bool) -> String {
    if on {
        ansi2(s, 1, 32)
    } else {
        s.to_string()
    }
}
fn c_bold_red(s: &str, on: bool) -> String {
    if on {
        ansi2(s, 1, 31)
    } else {
        s.to_string()
    }
}
fn c_bold_yellow(s: &str, on: bool) -> String {
    if on {
        ansi2(s, 1, 33)
    } else {
        s.to_string()
    }
}

fn sign_plus(on: bool) -> String {
    c_green("+", on)
}
fn sign_minus(on: bool) -> String {
    c_red("-", on)
}

// sign is already a rendered string (possibly ANSI-colored)
fn plined(sign: &str, title: &str, value: &str) {
    println!("{sign} {title:>PAD_DIFF$} {value}");
}

fn format_route_str_diff(dr: &DiffRoute, verbose: bool) -> String {
    let mut s = dr.to.clone();
    if !dr.via.is_empty() {
        s.push_str(&format!(" via {}", dr.via));
    }
    if !dr.from_addr.is_empty() {
        s.push_str(&format!(" from {}", dr.from_addr));
    }
    if let Some(m) = dr.metric {
        s.push_str(&format!(" metric {}", m));
    }
    if verbose {
        let table_name = match dr.table {
            Some(254) | None => "main".to_string(),
            Some(255) => "local".to_string(),
            Some(253) => "default".to_string(),
            Some(0) => "unspec".to_string(),
            Some(n) => n.to_string(),
        };
        s.push_str(&format!(" table {}", table_name));
    }
    let mut extra = vec![];
    if !dr.protocol.is_empty() && dr.protocol != "kernel" {
        extra.push(dr.protocol.as_str());
    }
    if !dr.scope.is_empty() && dr.scope != "global" {
        extra.push(dr.scope.as_str());
    }
    if !dr.route_type.is_empty() && dr.route_type != "unicast" {
        extra.push(dr.route_type.as_str());
    }
    if extra.is_empty() {
        s
    } else {
        format!("{} ({})", s, extra.join(", "))
    }
}

fn pretty_print_diff(
    state: &Map<String, Value>,
    report: &DiffReport,
    verbose: bool,
    diff_only: bool,
    ifname_filter: Option<&str>,
) {
    use std::io::IsTerminal;
    let use_color = std::io::stdout().is_terminal();

    // Sort all system interfaces by index — single pass preserves index order
    let mut all_ifaces: Vec<(&str, u64, &Value)> = state
        .iter()
        .filter(|(k, _)| *k != "netplan-global-state")
        .map(|(k, v)| {
            let idx = v.get("index").and_then(|i| i.as_u64()).unwrap_or(0);
            (k.as_str(), idx, v)
        })
        .collect();
    all_ifaces.sort_by_key(|(_, idx, _)| *idx);

    let iface_has_diff = |ifname: &str| -> bool {
        if report
            .missing_interfaces_netplan
            .iter()
            .any(|(n, _, _)| n == ifname)
        {
            return true;
        }
        if let Some((_, d)) = report.interfaces.get(ifname) {
            return !d.missing_addresses_system.is_empty()
                || !d.missing_addresses_netplan.is_empty()
                || d.missing_dhcp4_address
                || d.missing_dhcp6_address
                || !d.missing_nameservers_system.is_empty()
                || !d.missing_nameservers_netplan.is_empty()
                || !d.missing_search_system.is_empty()
                || !d.missing_search_netplan.is_empty()
                || d.missing_macaddress_system.is_some()
                || d.missing_macaddress_netplan.is_some()
                || !d.missing_routes_system.is_empty()
                || !d.missing_routes_netplan.is_empty()
                || d.missing_bridge_system.is_some()
                || d.missing_bridge_netplan.is_some()
                || d.missing_bond_system.is_some()
                || d.missing_bond_netplan.is_some()
                || d.missing_vrf_system.is_some()
                || d.missing_vrf_netplan.is_some()
                || !d.missing_interfaces_system.is_empty()
                || !d.missing_interfaces_netplan.is_empty();
        }
        false
    };

    let mut printed_any = false;
    let mut last_had_content = false;

    // Single loop over all system interfaces in index order
    for (ifname, idx, ifval) in &all_ifaces {
        if let Some(filter) = ifname_filter {
            if *ifname != filter {
                continue;
            }
        }

        let obj = match ifval.as_object() {
            Some(o) => o,
            None => continue,
        };

        let is_missing_netplan = report
            .missing_interfaces_netplan
            .iter()
            .any(|(n, _, _)| n == *ifname);

        let has_diff = is_missing_netplan || iface_has_diff(ifname);
        if diff_only && !has_diff {
            continue;
        }

        if last_had_content {
            println!();
        }

        if is_missing_netplan {
            // System-only: show with '+', all content in green
            display_diff_header_colored(&sign_plus(use_color), ifname, *idx, obj, use_color, true);
            display_diff_mac(obj, None, None, use_color, true);
            display_diff_addresses(obj, &[], &[], false, false, use_color, true);
            display_diff_dns_addresses(obj, &[], &[], use_color, true);
            display_diff_dns_search(obj, &[], &[], use_color, true);
            display_diff_routes(obj, verbose, &[], &[], use_color, true);
            display_diff_plain_links(obj, use_color, true);
        } else {
            let diff_opt = report.interfaces.get(*ifname).map(|(_, d)| d);
            let sign = " ";

            display_diff_header_colored(sign, ifname, *idx, obj, use_color, false);

            let missing_mac_sys = diff_opt.and_then(|d| d.missing_macaddress_system.as_deref());
            let missing_mac_np = diff_opt.and_then(|d| d.missing_macaddress_netplan.as_deref());
            display_diff_mac(obj, missing_mac_sys, missing_mac_np, use_color, false);

            let missing_addrs_sys = diff_opt
                .map(|d| d.missing_addresses_system.as_slice())
                .unwrap_or(&[]);
            let missing_addrs_np = diff_opt
                .map(|d| d.missing_addresses_netplan.as_slice())
                .unwrap_or(&[]);
            let dhcp4_missing = diff_opt.map(|d| d.missing_dhcp4_address).unwrap_or(false);
            let dhcp6_missing = diff_opt.map(|d| d.missing_dhcp6_address).unwrap_or(false);
            display_diff_addresses(
                obj,
                missing_addrs_sys,
                missing_addrs_np,
                dhcp4_missing,
                dhcp6_missing,
                use_color,
                false,
            );

            let missing_ns_sys = diff_opt
                .map(|d| d.missing_nameservers_system.as_slice())
                .unwrap_or(&[]);
            let missing_ns_np = diff_opt
                .map(|d| d.missing_nameservers_netplan.as_slice())
                .unwrap_or(&[]);
            display_diff_dns_addresses(obj, missing_ns_sys, missing_ns_np, use_color, false);

            let missing_srch_sys = diff_opt
                .map(|d| d.missing_search_system.as_slice())
                .unwrap_or(&[]);
            let missing_srch_np = diff_opt
                .map(|d| d.missing_search_netplan.as_slice())
                .unwrap_or(&[]);
            display_diff_dns_search(obj, missing_srch_sys, missing_srch_np, use_color, false);

            let missing_routes_sys = diff_opt
                .map(|d| d.missing_routes_system.as_slice())
                .unwrap_or(&[]);
            let missing_routes_np = diff_opt
                .map(|d| d.missing_routes_netplan.as_slice())
                .unwrap_or(&[]);
            display_diff_routes(
                obj,
                verbose,
                missing_routes_sys,
                missing_routes_np,
                use_color,
                false,
            );

            display_diff_plain_links(obj, use_color, false);
        }

        printed_any = true;
        last_had_content = true;
    }

    // Netplan-only interfaces (missing in system) shown with '-' at the end
    for (id, itype) in &report.missing_interfaces_system {
        if let Some(filter) = ifname_filter {
            if id != filter {
                continue;
            }
        }
        if last_had_content {
            println!();
        }
        let body = format!("●     {} {}", id, itype);
        println!("{} {}", sign_minus(use_color), c_red(&body, use_color));
        printed_any = true;
        last_had_content = true;
    }

    if printed_any && !diff_only {
        println!();
        let hint = format!(
            "Use {} to omit the information that is consistent between the system and Netplan.",
            c_yellow("\"--diff-only\"", use_color)
        );
        println!("{}", hint);
    }
}

fn display_diff_header_colored(
    sign: &str,
    ifname: &str,
    idx: u64,
    obj: &Map<String, Value>,
    use_color: bool,
    is_plus: bool,
) {
    let operstate = obj
        .get("operstate")
        .and_then(|v| v.as_str())
        .unwrap_or("UNKNOWN");
    let adminstate = obj
        .get("adminstate")
        .and_then(|v| v.as_str())
        .unwrap_or("UNKNOWN");
    let state = if operstate == "UP" && adminstate == "UP" {
        "UP".to_string()
    } else if operstate == "DOWN" && adminstate == "DOWN" {
        "DOWN".to_string()
    } else {
        format!("{}/{}", operstate, adminstate)
    };

    let t = obj.get("type").and_then(|v| v.as_str()).unwrap_or("other");
    let full_type = {
        let ssid = obj.get("ssid").and_then(|v| v.as_str());
        let tunnel_mode = obj.get("tunnel_mode").and_then(|v| v.as_str());
        if t == "wifi" {
            if let Some(s) = ssid {
                format!("{}/\"{}\"", t, s)
            } else {
                t.to_string()
            }
        } else if t == "tunnel" {
            if let Some(m) = tunnel_mode {
                format!("{}/{}", t, m)
            } else {
                t.to_string()
            }
        } else {
            t.to_string()
        }
    };

    let backend = obj
        .get("backend")
        .and_then(|v| v.as_str())
        .unwrap_or("unmanaged");
    let netdef = match obj.get("id").and_then(|v| v.as_str()) {
        Some(id) => format!("{}: {}", backend, id),
        None => backend.to_string(),
    };

    let body = format!(
        "● {:>2}: {} {} {} ({})",
        idx, ifname, full_type, state, netdef
    );
    let colored_body = if is_plus {
        c_green(&body, use_color)
    } else {
        c_dim(&body, use_color)
    };
    println!("{} {}", sign, colored_body);
}

fn display_diff_mac(
    obj: &Map<String, Value>,
    missing_sys: Option<&str>,
    missing_np: Option<&str>,
    use_color: bool,
    _all_green: bool,
) {
    let mac = obj.get("macaddress").and_then(|v| v.as_str());
    let vendor = obj.get("vendor").and_then(|v| v.as_str());
    let vendor_str = |m: &str| -> String {
        if let Some(v) = vendor {
            format!("{} ({})", m, v)
        } else {
            m.to_string()
        }
    };

    if missing_sys.is_none() && missing_np.is_none() {
        if let Some(mac) = mac {
            plined(" ", "MAC Address:", &c_dim(&vendor_str(mac), use_color));
        }
        return;
    }

    // Has diff — show existing mac with '+', missing mac with '-'
    if let Some(mac) = mac {
        plined(
            &sign_plus(use_color),
            "MAC Address:",
            &c_green(&vendor_str(mac), use_color),
        );
    }
    if let Some(missing) = missing_np {
        plined(
            &sign_minus(use_color),
            "",
            &c_red(&vendor_str(missing), use_color),
        );
    }
}

fn display_diff_addresses(
    obj: &Map<String, Value>,
    // missing_sys: in netplan but NOT in system → shown with '-'
    missing_sys: &[String],
    // missing_np: in system but NOT in netplan → annotated inline with '+'
    missing_np: &[String],
    dhcp4_missing: bool,
    dhcp6_missing: bool,
    use_color: bool,
    _all_green: bool,
) {
    let addrs = obj.get("addresses").and_then(|v| v.as_array());
    let addrs_slice = addrs.map(|a| a.as_slice()).unwrap_or(&[]);
    // System addresses that are extra vs netplan — highlight inline with '+'
    let missing_np_set: HashSet<&str> = missing_np.iter().map(String::as_str).collect();

    let mut first = true;
    let mut title = || {
        if first {
            first = false;
            "Addresses:"
        } else {
            ""
        }
    };

    for entry in addrs_slice {
        if let Some(map) = entry.as_object() {
            if let Some((ip, extra)) = map.iter().next() {
                let prefix = extra.get("prefix").and_then(|v| v.as_u64()).unwrap_or(0);
                let flags: Vec<&str> = extra
                    .get("flags")
                    .and_then(|v| v.as_array())
                    .map(|a| a.iter().filter_map(|v| v.as_str()).collect())
                    .unwrap_or_default();
                let full = format!("{}/{}", ip, prefix);
                let addr_str = if flags.is_empty() {
                    full.clone()
                } else {
                    format!("{} ({})", full, flags.join(", "))
                };
                // If address is in system but not netplan → '+'
                let is_extra_in_system = missing_np_set.contains(full.as_str());
                let (sign, val) = if is_extra_in_system {
                    (sign_plus(use_color), c_green(&addr_str, use_color))
                } else {
                    (" ".to_string(), c_dim(&addr_str, use_color))
                };
                plined(&sign, title(), &val);
            }
        }
    }
    // Addresses in netplan but missing from system → '-'
    for addr in missing_sys {
        plined(&sign_minus(use_color), title(), &c_red(addr, use_color));
    }
    // DHCP configured but no DHCP address obtained → '-'
    if dhcp4_missing {
        plined(
            &sign_minus(use_color),
            title(),
            &c_red("0.0.0.0/0 (dhcp)", use_color),
        );
    }
    if dhcp6_missing {
        plined(
            &sign_minus(use_color),
            title(),
            &c_red("::/0 (dhcp)", use_color),
        );
    }
}

fn display_diff_dns_addresses(
    obj: &Map<String, Value>,
    missing_sys: &[String],
    missing_np: &[String],
    use_color: bool,
    _all_green: bool,
) {
    let addrs = obj.get("dns_addresses").and_then(|v| v.as_array());
    let empty = vec![];
    let addrs = addrs.unwrap_or(&empty);
    // missing_np: in system, not netplan → '+' inline; missing_sys: in netplan, not system → '-'
    let missing_np_set: HashSet<&str> = missing_np.iter().map(String::as_str).collect();
    let mut first = true;
    let mut title = || {
        if first {
            first = false;
            "DNS Addresses:"
        } else {
            ""
        }
    };
    for addr in addrs {
        if let Some(s) = addr.as_str() {
            let is_extra = missing_np_set.contains(s);
            let (sign, val) = if is_extra {
                (sign_plus(use_color), c_green(s, use_color))
            } else {
                (" ".to_string(), c_dim(s, use_color))
            };
            plined(&sign, title(), &val);
        }
    }
    for addr in missing_sys {
        plined(&sign_minus(use_color), title(), &c_red(addr, use_color));
    }
}

fn display_diff_dns_search(
    obj: &Map<String, Value>,
    missing_sys: &[String],
    missing_np: &[String],
    use_color: bool,
    _all_green: bool,
) {
    let search = obj.get("dns_search").and_then(|v| v.as_array());
    let empty = vec![];
    let search = search.unwrap_or(&empty);
    // missing_np: in system, not netplan → '+' inline; missing_sys: in netplan, not system → '-'
    let missing_np_set: HashSet<&str> = missing_np.iter().map(String::as_str).collect();
    let mut first = true;
    let mut title = || {
        if first {
            first = false;
            "DNS Search:"
        } else {
            ""
        }
    };
    for s in search {
        if let Some(domain) = s.as_str() {
            let is_extra = missing_np_set.contains(domain);
            let (sign, val) = if is_extra {
                (sign_plus(use_color), c_green(domain, use_color))
            } else {
                (" ".to_string(), c_dim(domain, use_color))
            };
            plined(&sign, title(), &val);
        }
    }
    for s in missing_sys {
        plined(&sign_minus(use_color), title(), &c_red(s, use_color));
    }
}

fn display_diff_routes(
    obj: &Map<String, Value>,
    verbose: bool,
    missing_sys: &[DiffRoute],
    missing_np: &[DiffRoute],
    use_color: bool,
    _all_green: bool,
) {
    let routes = obj.get("routes").and_then(|v| v.as_array());
    let empty = vec![];
    let routes = routes.unwrap_or(&empty);
    let mut displayed = 0;
    let title = |n: usize| if n == 0 { "Routes:" } else { "" };

    for route in routes {
        let r = match route.as_object() {
            Some(r) => r,
            None => continue,
        };
        let table_id = r.get("table").and_then(|v| v.as_str()).unwrap_or("main");
        if !verbose {
            let is_main = table_id == "main" || table_id == "254";
            if !is_main {
                continue;
            }
        }
        let route_str = format_route_for_display(r, verbose);
        plined(" ", title(displayed), &c_dim(&route_str, use_color));
        displayed += 1;
    }
    // missing_np: in system, not netplan → '+'; missing_sys: in netplan, not system → '-'
    for dr in missing_np {
        let s = format_route_str_diff(dr, verbose);
        plined(
            &sign_plus(use_color),
            title(displayed),
            &c_green(&s, use_color),
        );
        displayed += 1;
    }
    for dr in missing_sys {
        let s = format_route_str_diff(dr, verbose);
        plined(
            &sign_minus(use_color),
            title(displayed),
            &c_red(&s, use_color),
        );
        displayed += 1;
    }
}

fn display_diff_plain_links(obj: &Map<String, Value>, use_color: bool, _all_green: bool) {
    let sign = " ";
    if let Some(b) = obj.get("bridge").and_then(|v| v.as_str()) {
        plined(sign, "Bridge:", &c_dim(b, use_color));
    }
    if let Some(b) = obj.get("bond").and_then(|v| v.as_str()) {
        plined(sign, "Bond:", &c_dim(b, use_color));
    }
    if let Some(v) = obj.get("vrf").and_then(|v| v.as_str()) {
        plined(sign, "VRF:", &c_dim(v, use_color));
    }
    let members = obj.get("interfaces").and_then(|v| v.as_array());
    if let Some(members) = members.filter(|m| !m.is_empty()) {
        for (i, m) in members.iter().enumerate() {
            if let Some(name) = m.as_str() {
                plined(
                    sign,
                    if i == 0 { "Interfaces:" } else { "" },
                    &c_dim(name, use_color),
                );
            }
        }
    }
}

fn format_route_for_display(r: &Map<String, Value>, verbose: bool) -> String {
    let to = r.get("to").and_then(|v| v.as_str()).unwrap_or("");
    let via = r.get("via").and_then(|v| v.as_str()).unwrap_or("");
    let from = r.get("from").and_then(|v| v.as_str()).unwrap_or("");
    let metric = r.get("metric").and_then(|v| v.as_u64());
    let protocol = r.get("protocol").and_then(|v| v.as_str()).unwrap_or("");
    let scope = r.get("scope").and_then(|v| v.as_str()).unwrap_or("");
    let rtype = r.get("type").and_then(|v| v.as_str()).unwrap_or("");
    let table_id = r.get("table").and_then(|v| v.as_str()).unwrap_or("main");

    let mut route_str = to.to_string();
    if !via.is_empty() {
        route_str.push_str(&format!(" via {}", via));
    }
    if !from.is_empty() {
        route_str.push_str(&format!(" from {}", from));
    }
    if let Some(m) = metric {
        route_str.push_str(&format!(" metric {}", m));
    }
    if verbose {
        route_str.push_str(&format!(" table {}", table_id));
    }

    let mut extra = vec![];
    if !protocol.is_empty() && protocol != "kernel" {
        extra.push(protocol);
    }
    if !scope.is_empty() && scope != "global" {
        extra.push(scope);
    }
    if !rtype.is_empty() && rtype != "unicast" {
        extra.push(rtype);
    }

    if extra.is_empty() {
        route_str
    } else {
        format!("{} ({})", route_str, extra.join(", "))
    }
}

// ── JSON/YAML output for diff mode ────────────────────────────────────────────

fn diff_to_json(report: &DiffReport) -> Value {
    let mut root = Map::new();
    let mut ifaces = Map::new();

    for (name, (idx, diff)) in &report.interfaces {
        let mut obj = Map::new();
        obj.insert("index".into(), Value::Number((*idx).into()));
        obj.insert("name".into(), Value::String(name.clone()));

        let mut sys_state = Map::new();
        let mut np_state = Map::new();

        if diff.missing_dhcp4_address {
            sys_state.insert("missing_dhcp4_address".into(), Value::Bool(true));
        }
        if diff.missing_dhcp6_address {
            sys_state.insert("missing_dhcp6_address".into(), Value::Bool(true));
        }
        if !diff.missing_addresses_system.is_empty() {
            sys_state.insert(
                "missing_addresses".into(),
                Value::Array(
                    diff.missing_addresses_system
                        .iter()
                        .map(|s| Value::String(s.clone()))
                        .collect(),
                ),
            );
        }
        if !diff.missing_addresses_netplan.is_empty() {
            np_state.insert(
                "missing_addresses".into(),
                Value::Array(
                    diff.missing_addresses_netplan
                        .iter()
                        .map(|s| Value::String(s.clone()))
                        .collect(),
                ),
            );
        }
        if let Some(mac) = &diff.missing_macaddress_system {
            sys_state.insert("missing_macaddress".into(), Value::String(mac.clone()));
        }
        if let Some(mac) = &diff.missing_macaddress_netplan {
            np_state.insert("missing_macaddress".into(), Value::String(mac.clone()));
        }
        if !diff.missing_routes_system.is_empty() {
            sys_state.insert(
                "missing_routes".into(),
                Value::Array(diff.missing_routes_system.iter().map(dr_to_json).collect()),
            );
        }
        if !diff.missing_routes_netplan.is_empty() {
            np_state.insert(
                "missing_routes".into(),
                Value::Array(diff.missing_routes_netplan.iter().map(dr_to_json).collect()),
            );
        }

        obj.insert("system_state".into(), Value::Object(sys_state));
        obj.insert("netplan_state".into(), Value::Object(np_state));
        ifaces.insert(name.clone(), Value::Object(obj));
    }

    root.insert("interfaces".into(), Value::Object(ifaces));

    let mut missing_sys = Map::new();
    for (id, itype) in &report.missing_interfaces_system {
        let mut m = Map::new();
        m.insert("type".into(), Value::String(itype.clone()));
        missing_sys.insert(id.clone(), Value::Object(m));
    }
    root.insert(
        "missing_interfaces_system".into(),
        Value::Object(missing_sys),
    );

    let mut missing_np = Map::new();
    for (name, idx, itype) in &report.missing_interfaces_netplan {
        let mut m = Map::new();
        m.insert("type".into(), Value::String(itype.clone()));
        m.insert("index".into(), Value::Number((*idx).into()));
        missing_np.insert(name.clone(), Value::Object(m));
    }
    root.insert(
        "missing_interfaces_netplan".into(),
        Value::Object(missing_np),
    );

    Value::Object(root)
}

fn dr_to_json(dr: &DiffRoute) -> Value {
    let mut m = Map::new();
    m.insert("to".into(), Value::String(dr.to.clone()));
    if !dr.via.is_empty() {
        m.insert("via".into(), Value::String(dr.via.clone()));
    }
    if !dr.from_addr.is_empty() {
        m.insert("from".into(), Value::String(dr.from_addr.clone()));
    }
    if let Some(metric) = dr.metric {
        m.insert("metric".into(), Value::Number(metric.into()));
    }
    if let Some(table) = dr.table {
        m.insert("table".into(), Value::Number(table.into()));
    }
    if !dr.scope.is_empty() {
        m.insert("scope".into(), Value::String(dr.scope.clone()));
    }
    if !dr.route_type.is_empty() {
        m.insert("type".into(), Value::String(dr.route_type.clone()));
    }
    if !dr.protocol.is_empty() {
        m.insert("protocol".into(), Value::String(dr.protocol.clone()));
    }
    m.insert("family".into(), Value::Number(dr.family.into()));
    Value::Object(m)
}
