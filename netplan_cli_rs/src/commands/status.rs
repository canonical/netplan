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

//! `netplan status`: port of `netplan_cli/cli/commands/status.py`.
//!
//! The data comes from [`crate::state`] / [`crate::state_diff`]; the
//! tabular output goes through [`crate::rich`] (python3-rich's Console).

use anyhow::Result;
use serde_json::{Map, Value};

use crate::argparse::{Arg, Nargs};
use crate::cli;
use crate::pyjson;
use crate::pyyaml;
use crate::rich::Console;
use crate::state::{self, pv, NetplanConfigState, RouteTables, SystemConfigState};
use crate::state_diff::{DiffVal, IfaceDiff, NetplanDiffState, NetplanRoute, Report};

pub struct NetplanStatus {
    pub ifname: Option<String>,
    pub all: bool,
    pub verbose: bool,
    pub format: String,
    pub diff: bool,
    pub diff_only: bool,
    pub root_dir: Option<String>,
    state_diff: Option<Report>,
    route_lookup_table_names: RouteTables,
    pprint: Option<Console>,
    plus: &'static str,
    minus: &'static str,
    pad: usize,
}

/// `netplan status [ifname] [-a] [-v] [-f FORMAT] [--diff] [--diff-only] [--root-dir DIR]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
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
    let mut status = NetplanStatus {
        ifname: ns.str("ifname"),
        all: ns.bool("all"),
        verbose: ns.bool("verbose"),
        format: ns.str("format").unwrap_or_default(),
        diff: ns.bool("diff"),
        diff_only: ns.bool("diff_only"),
        root_dir: ns.str("root_dir"),
        state_diff: None,
        route_lookup_table_names: RouteTables::default(),
        pprint: None,
        plus: "[green]+[/green]",
        minus: "[red]-[/red]",
        pad: 18,
    };
    status.command()?;
    Ok(0)
}

/// `'{:>2}'.format(value)`
fn fmt_idx(v: &Value) -> String {
    format!("{:>2}", pv::to_str(v))
}

impl NetplanStatus {
    fn ifname(&self) -> Option<&str> {
        self.ifname.as_deref().filter(|n| !n.is_empty())
    }

    fn pprint(&self, line: &str) -> Result<()> {
        match &self.pprint {
            Some(c) => c.print(line),
            None => Ok(()),
        }
    }

    fn pprint_empty(&self) {
        if let Some(c) = &self.pprint {
            c.print_empty();
        }
    }

    fn t(&self, title: &str) -> String {
        format!("{:>w$}", title, w = self.pad)
    }

    fn diff_for(&self, ifname: &str) -> Option<&IfaceDiff> {
        self.state_diff.as_ref().and_then(|d| d.interface(ifname))
    }

    fn get_interface_diff(&self, ifname: &str) -> Option<&IfaceDiff> {
        self.diff_for(ifname)
            .filter(|d| !d.system_state.is_empty() || !d.netplan_state.is_empty())
    }

    fn is_interface_missing_in_netplan(&self, ifname: &str) -> bool {
        self.state_diff.as_ref().is_some_and(|d| {
            d.missing_interfaces_netplan
                .iter()
                .any(|(k, _)| k == ifname)
        })
    }

    fn side(&self, ifname: &str, state: &str, property: &str) -> Option<&DiffVal> {
        let d = self.diff_for(ifname)?;
        let side = if state == "system_state" {
            &d.system_state
        } else {
            &d.netplan_state
        };
        side.get(property)
    }

    fn missing_list(&self, ifname: &str, state: &str, property: &str) -> Vec<Value> {
        match self.side(ifname, state, property) {
            Some(DiffVal::List(l)) => l.clone(),
            _ => vec![],
        }
    }

    fn missing_str(&self, ifname: &str, state: &str, property: &str) -> String {
        match self.side(ifname, state, property) {
            Some(DiffVal::Str(s)) => s.clone(),
            _ => String::new(),
        }
    }

    fn missing_routes(&self, ifname: &str, state: &str) -> Vec<NetplanRoute> {
        match self.side(ifname, state, "missing_routes") {
            Some(DiffVal::Routes(r)) => r.clone(),
            _ => vec![],
        }
    }

    fn missing_bool(&self, ifname: &str, state: &str, property: &str) -> bool {
        matches!(
            self.side(ifname, state, property),
            Some(DiffVal::Bool(true))
        )
    }

    fn has_diff(&self, ifname: &str) -> bool {
        self.is_interface_missing_in_netplan(ifname) || self.get_interface_diff(ifname).is_some()
    }

    fn display_global_state(&self, data: &Map<String, Value>) -> Result<()> {
        let empty = Value::Object(Map::new());
        let global_state = data.get("netplan-global-state").unwrap_or(&empty);
        let online = global_state.get("online").is_some_and(pv::truthy);
        self.pprint(&format!(
            "{} {}",
            self.t("Online state:"),
            if online {
                "[online]online[/online]"
            } else {
                "[offline]offline[/offline]"
            }
        ))?;
        let ns = global_state.get("nameservers").unwrap_or(&empty);
        let list = |k: &str| {
            ns.get(k)
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
        };
        let dns_addr = list("addresses");
        let dns_mode = ns.get("mode").filter(|m| pv::truthy(m));
        let dns_search = list("search");
        for (i, val) in dns_addr.iter().enumerate() {
            self.pprint(&format!(
                "{} {}[muted]{}[/muted]",
                self.t(if i == 0 { "DNS Addresses:" } else { "" }),
                pv::to_str(val),
                dns_mode.map_or(String::new(), |m| format!(" ({})", pv::to_str(m)))
            ))?;
        }
        for (i, val) in dns_search.iter().enumerate() {
            self.pprint(&format!(
                "{} {}",
                self.t(if i == 0 { "DNS Search:" } else { "" }),
                pv::to_str(val)
            ))?;
        }
        self.pprint_empty();
        Ok(())
    }

    fn display_interface_header(&self, ifname: &str, data: &Map<String, Value>) -> Result<()> {
        let get_str = |k: &str, default: &str| data.get(k).map_or(default.to_string(), pv::to_str);
        let mut state = format!(
            "{}/{}",
            get_str("operstate", "UNKNOWN"),
            get_str("adminstate", "UNKNOWN")
        );
        let mut scolor = "unknown";
        if state == "UP/UP" {
            state = "UP".into();
            scolor = "online";
        } else if state == "DOWN/DOWN" {
            state = "DOWN".into();
            scolor = "offline";
        }
        let mut full_type = get_str("type", "other");
        let ssid = data.get("ssid").filter(|v| pv::truthy(v));
        let tunnel_mode = data.get("tunnel_mode").filter(|v| pv::truthy(v));
        if full_type == "wifi" && ssid.is_some() {
            full_type += &format!("/\"{}\"", pv::to_str(ssid.unwrap_or(&Value::Null)));
        } else if full_type == "tunnel" && tunnel_mode.is_some() {
            full_type += &format!("/{}", pv::to_str(tunnel_mode.unwrap_or(&Value::Null)));
        }

        let id = data.get("id").filter(|v| pv::truthy(v));
        let idx = fmt_idx(data.get("index").unwrap_or(&Value::String("?".into())));
        let backend = get_str("backend", "unmanaged");
        let col = scolor;
        let mut netdef = id.map_or(String::new(), |id| {
            format!(": [highlight]{}[/highlight]", pv::to_str(id))
        });
        let mut line = format!("[{col}]●[/{col}] {idx}: {ifname} {full_type} [{col}]{state}[/{col}] ({backend}{netdef})");
        if self.diff {
            if self.is_interface_missing_in_netplan(ifname) {
                let sign = self.plus;
                line = format!(
                    "{sign} [{col}]●[/{col}] {idx}: [green][highlight]{ifname} {full_type} [{col}]{state}[/{col}] ({backend}{netdef})[/highlight][/green]"
                );
            } else {
                netdef = id.map_or(String::new(), |id| format!(": {}", pv::to_str(id)));
                line = format!(
                    "  [muted]● {idx}: {ifname} {full_type} {state} ({backend}{netdef})[/muted]"
                );
            }
        }
        if !self.diff_only || self.has_diff(ifname) {
            self.pprint(&line)?;
        }
        Ok(())
    }

    fn display_mac_address(&self, ifname: &str, data: &Map<String, Value>) -> Result<()> {
        let Some(macaddress) = data.get("macaddress").filter(|v| pv::truthy(v)) else {
            return Ok(());
        };
        let mac = pv::to_str(macaddress);
        let mut hide_macaddress = false;
        let missing_system_macaddress =
            self.missing_str(ifname, "system_state", "missing_macaddress");
        let vendor = data
            .get("vendor")
            .filter(|v| pv::truthy(v))
            .map_or(String::new(), |v| format!(" ({})", pv::to_str(v)));
        let title = self.t("MAC Address:");
        let mut line = format!("{title} {mac}[muted]{vendor}[/muted]");
        if self.diff && missing_system_macaddress.is_empty() {
            line = format!("  [muted]{title} {mac}{vendor}[/muted]");
            if self.diff_only {
                hide_macaddress = true;
            }
        } else if self.diff && !missing_system_macaddress.is_empty() {
            line = format!(
                "{} {title} [green][highlight]{mac}{vendor}[/highlight][/green]",
                self.plus
            );
        }
        if !hide_macaddress {
            self.pprint(&line)?;
            if self.diff && !missing_system_macaddress.is_empty() {
                self.pprint(&format!(
                    "{} {} [red][highlight]{missing_system_macaddress}{vendor}[/highlight][/red]",
                    self.minus,
                    self.t("")
                ))?;
            }
        }
        Ok(())
    }

    fn display_ip_addresses(&self, ifname: &str, data: &Map<String, Value>) -> Result<()> {
        let lst = data
            .get("addresses")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let mut addresses_displayed = 0;
        if !lst.is_empty() {
            let missing_netplan_addresses =
                self.missing_list(ifname, "netplan_state", "missing_addresses");
            for obj in &lst {
                let Some((ip, extra)) = obj.as_object().and_then(|m| m.iter().next()) else {
                    continue;
                };
                let prefix = extra.get("prefix").map_or(String::new(), pv::to_str);
                let flags: Vec<String> = extra
                    .get("flags")
                    .filter(|f| pv::truthy(f))
                    .and_then(Value::as_array)
                    .map(|a| a.iter().map(pv::to_str).collect())
                    .unwrap_or_default();
                let (mut start, mut end) = ("", "");
                if flags.is_empty() || flags.iter().any(|f| f == "dhcp") {
                    start = "[highlight]";
                    end = "[/highlight]";
                }
                let address = format!("{ip}/{prefix}");
                let missing = missing_netplan_addresses
                    .iter()
                    .any(|a| pv::eq_str(Some(a), &address));
                let extra_s = if flags.is_empty() {
                    String::new()
                } else {
                    format!(" ({})", flags.join(", "))
                };
                let title = self.t(if addresses_displayed == 0 {
                    "Addresses:"
                } else {
                    ""
                });
                let mut hide_address = false;
                let line = if self.diff && !missing {
                    if self.diff_only {
                        hide_address = true;
                    }
                    format!("  [muted]{title} {ip}/{prefix}{extra_s}[/muted]")
                } else if self.diff && missing {
                    format!(
                        "{} {title} [green][highlight]{ip}/{prefix}{extra_s}[/highlight][/green]",
                        self.plus
                    )
                } else {
                    format!("{title} {start}{ip}/{prefix}{end}[muted]{extra_s}[/muted]")
                };
                if !hide_address {
                    self.pprint(&line)?;
                    addresses_displayed += 1;
                }
            }
        }

        if let Some(diff) = self.get_interface_diff(ifname) {
            let sign = self.minus;
            if let Some(DiffVal::List(missing_addresses)) =
                diff.system_state.get("missing_addresses")
            {
                for ip in missing_addresses {
                    self.pprint(&format!(
                        "{sign} {} [highlight][red]{}[/red][/highlight]",
                        self.t(if addresses_displayed == 0 {
                            "Addresses:"
                        } else {
                            ""
                        }),
                        pv::to_str(ip)
                    ))?;
                    addresses_displayed += 1;
                }
            }
            if self.missing_bool(ifname, "system_state", "missing_dhcp4_address") {
                self.pprint(&format!(
                    "{sign} {} [highlight][red]0.0.0.0/0 (dhcp)[/red][/highlight]",
                    self.t(if addresses_displayed == 0 {
                        "Addresses:"
                    } else {
                        ""
                    })
                ))?;
                addresses_displayed += 1;
            }
            if self.missing_bool(ifname, "system_state", "missing_dhcp6_address") {
                self.pprint(&format!(
                    "{sign} {} [highlight][red]::/0 (dhcp)[/red][/highlight]",
                    self.t(if addresses_displayed == 0 {
                        "Addresses:"
                    } else {
                        ""
                    })
                ))?;
            }
        }
        Ok(())
    }

    /// `_display_dns_addresses`, `_display_dns_search` and `_display_members`
    fn display_list(
        &self,
        ifname: &str,
        data: &Map<String, Value>,
        key: &str,
        title_text: &str,
        missing_key: &str,
    ) -> Result<()> {
        let lst = data
            .get(key)
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let mut displayed = 0;
        if !lst.is_empty() {
            let missing_netplan = self.missing_list(ifname, "netplan_state", missing_key);
            for val in &lst {
                let value = pv::to_str(val);
                let missing = missing_netplan.iter().any(|m| pv::eq(m, val));
                let title = self.t(if displayed == 0 { title_text } else { "" });
                let mut hide = false;
                let line = if self.diff && !missing {
                    if self.diff_only {
                        hide = true;
                    }
                    format!("  [muted]{title} {value}[/muted]")
                } else if self.diff && missing {
                    format!(
                        "{} {title} [green][highlight]{value}[/highlight][/green]",
                        self.plus
                    )
                } else {
                    format!("{title} {value}")
                };
                if !hide {
                    self.pprint(&line)?;
                    displayed += 1;
                }
            }
        }

        if self.has_diff(ifname) {
            let missing_system = self.missing_list(ifname, "system_state", missing_key);
            for v in &missing_system {
                self.pprint(&format!(
                    "{} {} [red][highlight]{}[/highlight][/red]",
                    self.minus,
                    self.t(if displayed == 0 { title_text } else { "" }),
                    pv::to_str(v)
                ))?;
                displayed += 1;
            }
        }
        Ok(())
    }

    fn route_parts(&self, route: &NetplanRoute) -> (String, String, String, String, String) {
        let to = route.to.clone().unwrap_or_else(|| "None".into());
        let via = route
            .via
            .as_ref()
            .filter(|v| !v.is_empty())
            .map_or(String::new(), |v| format!(" via {v}"));
        let src = route
            .from_addr
            .as_ref()
            .filter(|v| !v.is_empty())
            .map_or(String::new(), |v| format!(" from {v}"));
        let metric = if route.metric < NetplanRoute::metric_unspec() {
            format!(" metric {}", route.metric)
        } else {
            String::new()
        };
        let table = if self.verbose && route.table > 0 {
            let name = self
                .route_lookup_table_names
                .by_num
                .get(&route.table)
                .cloned()
                .unwrap_or_else(|| route.table.to_string());
            format!(" table {name}")
        } else {
            String::new()
        };
        (to, via, src, metric, table)
    }

    fn display_routes(&mut self, ifname: &str, data: &Map<String, Value>) -> Result<()> {
        let lst = data
            .get("routes")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let missing_netplan_routes = self.missing_routes(ifname, "netplan_state");
        let missing_system_routes = self.missing_routes(ifname, "system_state");
        let mut routes_displayed = 0;
        if !lst.is_empty() {
            if self.route_lookup_table_names.is_empty() {
                self.route_lookup_table_names = state::route_table_lookup();
            }
            // NetplanDiffState(None, None)._system_route_to_netplan(route)
            let mut cache = RouteTables::default();
            let mut routes: Vec<NetplanRoute> = lst
                .iter()
                .filter_map(Value::as_object)
                .map(|r| crate::state_diff::system_route_to_netplan(r, &mut cache))
                .collect();
            if !self.verbose {
                // filter out routes that are not in the main route table
                routes.retain(|r| r.table == 254);
            }
            for route in &routes {
                let mut hide_route = false;
                let (mut start, mut end) = ("", "");
                if route.to.as_deref() == Some("default") {
                    start = "[highlight]";
                    end = "[/highlight]";
                }
                let (to, via, src, metric, table) = self.route_parts(route);
                let mut extra = vec![];
                if let Some(p) = route
                    .protocol
                    .as_ref()
                    .filter(|p| !p.is_empty() && *p != "kernel")
                {
                    extra.push(p.clone());
                }
                if let Some(s) = route
                    .scope
                    .as_ref()
                    .filter(|s| !s.is_empty() && *s != "global")
                {
                    extra.push(s.clone());
                }
                if let Some(t) = route
                    .type_
                    .as_ref()
                    .filter(|t| !t.is_empty() && *t != "unicast")
                {
                    extra.push(t.clone());
                }
                let extra = if extra.is_empty() {
                    String::new()
                } else {
                    format!(" ({})", extra.join(", "))
                };
                let title = self.t(if routes_displayed == 0 { "Routes:" } else { "" });
                let missing = missing_netplan_routes.contains(route);
                let line = if self.diff && !missing {
                    if self.diff_only {
                        hide_route = true;
                    }
                    format!("  [muted]{title} {to}{via}{src}{metric}{table}{extra}[/muted]")
                } else if self.diff && missing {
                    format!(
                        "{} {title} [green][highlight]{start}{to}{via}{src}{metric}{table}{end}{extra}[/highlight][/green]",
                        self.plus
                    )
                } else {
                    format!(
                        "{title} {start}{to}{via}{src}{metric}{table}{end}[muted]{extra}[/muted]"
                    )
                };
                if !hide_route {
                    self.pprint(&line)?;
                    routes_displayed += 1;
                }
            }
        }

        if self.diff {
            for route in &missing_system_routes {
                let (to, via, src, metric, table) = self.route_parts(route);
                let mut extra = vec![];
                if let Some(s) = route
                    .scope
                    .as_ref()
                    .filter(|s| !s.is_empty() && *s != "global")
                {
                    extra.push(s.clone());
                }
                if let Some(t) = route
                    .type_
                    .as_ref()
                    .filter(|t| !t.is_empty() && *t != "unicast")
                {
                    extra.push(t.clone());
                }
                let extra = if extra.is_empty() {
                    String::new()
                } else {
                    format!(" ({})", extra.join(", "))
                };
                self.pprint(&format!(
                    "{} {} [highlight][red]{to}{via}{src}{metric}{table}{extra}[/red][/highlight]",
                    self.minus,
                    self.t(if routes_displayed == 0 { "Routes:" } else { "" })
                ))?;
                routes_displayed += 1;
            }
        }
        Ok(())
    }

    /// `_display_bridge`, `_display_bond` and `_display_vrf`
    fn display_link(
        &self,
        ifname: &str,
        data: &Map<String, Value>,
        key: &str,
        title: &str,
    ) -> Result<()> {
        let missing_key = format!("missing_{key}_link");
        if let Some(val) = data.get(key).filter(|v| pv::truthy(v)) {
            let mut val = pv::to_str(val);
            let missing_netplan_link = self.missing_str(ifname, "netplan_state", &missing_key);
            let t = self.t(title);
            let mut line = format!("{t} {val}");
            let mut hide = false;
            if self.diff && missing_netplan_link.is_empty() {
                line = format!("  [muted]{t} {val}[/muted]");
                if self.diff_only {
                    hide = true;
                }
            } else if self.diff && !missing_netplan_link.is_empty() {
                val = missing_netplan_link;
                line = format!(
                    "{} {t} [highlight][green]{val}[/green][/highlight]",
                    self.plus
                );
            }
            if !hide {
                self.pprint(&line)?;
            }
        }
        let missing_system_link = self.missing_str(ifname, "system_state", &missing_key);
        if !missing_system_link.is_empty() {
            self.pprint(&format!(
                "{} {} [highlight][red]{missing_system_link}[/red][/highlight]",
                self.minus,
                self.t(title)
            ))?;
        }
        Ok(())
    }

    fn display_activation_mode(&self, data: &Map<String, Value>) -> Result<()> {
        if let Some(val) = data.get("activation_mode").filter(|v| pv::truthy(v)) {
            self.pprint(&format!(
                "{} {}",
                self.t("Activation Mode:"),
                pv::to_str(val)
            ))?;
        }
        Ok(())
    }

    fn display_missing_interfaces(&self) -> Result<()> {
        let missing: Vec<(String, String)> = self
            .state_diff
            .as_ref()
            .map(|d| d.missing_interfaces_system.clone())
            .unwrap_or_default();
        let sign = self.minus;
        for (index, (interface, itype)) in missing.iter().enumerate() {
            // If we called netplan status for a single interface, ignore the rest
            if self.ifname().is_some_and(|n| n != interface) {
                continue;
            }
            self.pprint(&format!(
                "{sign} [red]● {:>2}  {interface} {itype}[/red]",
                ""
            ))?;
            if index + 1 != missing.len() && self.ifname().is_none() {
                // linebreak only if it's not the last interfaces or the only one
                self.pprint_empty();
            }
        }
        Ok(())
    }

    fn pretty_print(&mut self, data: &Map<String, Value>, total: usize) -> Result<()> {
        self.pprint = Some(Console::new(self.diff));
        self.plus = "[green]+[/green]";
        self.minus = "[red]-[/red]";
        self.pad = 18;
        if self.diff {
            // In diff mode we shift the text 2 columns to the right so we can display
            // + and - and maintain the alignment consistency
            self.pad = 20;
        }

        // Global state
        if !self.diff {
            self.display_global_state(data)?;
        }

        // Per interface
        let mut interfaces: Vec<(&String, &Value)> = data
            .iter()
            .filter(|(k, _)| *k != "netplan-global-state")
            .collect();
        if self.diff_only {
            // in diff-only mode we filter out interfaces that don't have any diff
            interfaces.retain(|(k, _)| self.has_diff(k));
        }

        let missing_interfaces = self
            .state_diff
            .as_ref()
            .map_or(0, |d| d.missing_interfaces_system.len());
        let count = interfaces.len();
        let empty = Map::new();
        for (index, (ifname, ifconfig)) in interfaces.iter().enumerate() {
            // If we called netplan status for a single interface, ignore the rest
            if self.ifname().is_some_and(|n| n != ifname.as_str()) {
                continue;
            }
            let ifconfig = ifconfig.as_object().unwrap_or(&empty);
            self.display_interface_header(ifname, ifconfig)?;
            self.display_mac_address(ifname, ifconfig)?;
            self.display_ip_addresses(ifname, ifconfig)?;
            self.display_list(
                ifname,
                ifconfig,
                "dns_addresses",
                "DNS Addresses:",
                "missing_nameservers_addresses",
            )?;
            self.display_list(
                ifname,
                ifconfig,
                "dns_search",
                "DNS Search:",
                "missing_nameservers_search",
            )?;
            self.display_routes(ifname, ifconfig)?;
            self.display_link(ifname, ifconfig, "bridge", "Bridge:")?;
            self.display_link(ifname, ifconfig, "bond", "Bond:")?;
            self.display_link(ifname, ifconfig, "vrf", "VRF:")?;
            self.display_list(
                ifname,
                ifconfig,
                "interfaces",
                "Interfaces:",
                "missing_interfaces",
            )?;
            self.display_activation_mode(ifconfig)?;

            if (!self.diff_only || self.has_diff(ifname))
                && (index + 1 != count || missing_interfaces > 0)
                && self.ifname().is_none()
            {
                // we only break to a new line if we still have data to display
                self.pprint_empty();
            }
        }

        if self.diff {
            self.display_missing_interfaces()?;
        }

        let hidden = total as i64 - count as i64;
        if hidden > 0 && !self.diff {
            self.pprint(&format!(
                "\n{hidden} inactive interfaces hidden. Use \"--all\" to show all."
            ))?;
        }

        if self.diff && !self.diff_only {
            self.pprint(
                "\nUse [yellow]\"--diff-only\"[/yellow] to omit the information that is consistent between the system and Netplan.",
            )?;
        }
        Ok(())
    }

    pub fn command(&mut self) -> Result<()> {
        // --diff-only implies --diff
        if self.diff_only {
            self.diff = true;
        }
        // --diff needs data from all interfaces to work
        if self.diff {
            self.all = true;
        }

        let system_state = SystemConfigState::new(self.ifname.as_deref(), self.all)?;

        let output_format = self.format.to_lowercase();

        if self.diff {
            let netplan_state = NetplanConfigState::new(self.root_dir.as_deref())?;
            let mut diff_state = NetplanDiffState::new(Some(&system_state), Some(&netplan_state));
            let report = diff_state.get_diff(self.ifname.as_deref())?;
            if output_format == "json" {
                crate::pyprintln!("{}", pyjson::dumps(&report.to_json()));
                return Ok(());
            } else if output_format == "yaml" {
                crate::pyprintln!("{}", pyyaml::dump(&report.to_json()));
                return Ok(());
            }
            self.state_diff = Some(report);
        }

        let data = system_state.get_data();
        if output_format == "json" {
            // structural JSON output
            crate::pyprintln!("{}", pyjson::dumps(&Value::Object(data.clone())));
        } else if output_format == "yaml" {
            // stuctural YAML output
            crate::pyprintln!("{}", pyyaml::dump(&Value::Object(data.clone())));
        } else {
            // pretty print, human readable output
            self.pretty_print(data, system_state.number_of_interfaces())?;
        }
        Ok(())
    }
}
