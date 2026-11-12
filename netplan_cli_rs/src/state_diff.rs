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

//! Port of `netplan_cli/cli/state_diff.py`: compares the system's state with
//! Netplan's configuration.
//!
//! Python sets are kept as insertion-ordered vectors: where Python turns a
//! set of several elements into a list its order is arbitrary anyway.

use std::cell::RefCell;
use std::rc::Rc;

use anyhow::Result;
use serde_json::{Map, Value};

use crate::ipaddress;
use crate::py::Exception;
use crate::state::{self, pv, NetplanConfigState, RouteTables, SystemConfigState};
use crate::utils;

const METRIC_UNSPEC: i64 = u32::MAX as i64;
const TABLE_UNSPEC: i64 = 0;

/// `netplan.netdef.NetplanRoute`
#[derive(Clone, Debug)]
pub struct NetplanRoute {
    pub to: Option<String>,
    pub via: Option<String>,
    pub from_addr: Option<String>,
    pub type_: Option<String>,
    pub scope: Option<String>,
    pub protocol: Option<String>,
    pub table: i64,
    pub family: i64,
    pub metric: i64,
}

impl Default for NetplanRoute {
    fn default() -> Self {
        NetplanRoute {
            to: None,
            via: None,
            from_addr: None,
            type_: Some("unicast".into()),
            scope: Some("global".into()),
            protocol: None,
            table: TABLE_UNSPEC,
            family: -1,
            metric: METRIC_UNSPEC,
        }
    }
}

impl PartialEq for NetplanRoute {
    fn eq(&self, r: &Self) -> bool {
        self.to == r.to
            && self.via == r.via
            && self.from_addr == r.from_addr
            && self.table == r.table
            && self.family == r.family
            && self.metric == r.metric
            && self.type_ == r.type_
            && self.scope == r.scope
    }
}

impl NetplanRoute {
    pub fn metric_unspec() -> i64 {
        METRIC_UNSPEC
    }

    /// `NetplanRoute.to_dict()` (via `DiffJSONEncoder`)
    pub fn to_dict(&self) -> Value {
        let mut route = Map::new();
        if self.family >= 0 {
            route.insert("family".into(), self.family.into());
        }
        if let Some(to) = self.to.as_ref().filter(|s| !s.is_empty()) {
            route.insert("to".into(), to.clone().into());
        }
        if let Some(via) = self.via.as_ref().filter(|s| !s.is_empty()) {
            route.insert("via".into(), via.clone().into());
        }
        if let Some(from) = self.from_addr.as_ref().filter(|s| !s.is_empty()) {
            route.insert("from".into(), from.clone().into());
        }
        if self.metric < METRIC_UNSPEC {
            route.insert("metric".into(), self.metric.into());
        }
        if self.table > TABLE_UNSPEC {
            route.insert("table".into(), self.table.into());
        }
        route.insert(
            "type".into(),
            self.type_.clone().map_or(Value::Null, Value::from),
        );
        Value::Object(route)
    }
}

/// A value in the per-interface `system_state` / `netplan_state` reports
#[derive(Clone)]
pub enum DiffVal {
    Bool(bool),
    Str(String),
    List(Vec<Value>),
    Routes(Vec<NetplanRoute>),
}

impl DiffVal {
    fn to_json(&self) -> Value {
        match self {
            DiffVal::Bool(b) => Value::Bool(*b),
            DiffVal::Str(s) => Value::String(s.clone()),
            DiffVal::List(l) => Value::Array(l.clone()),
            DiffVal::Routes(r) => Value::Array(r.iter().map(NetplanRoute::to_dict).collect()),
        }
    }
}

/// An ordered dict of report entries
#[derive(Clone, Default)]
pub struct Side(pub Vec<(String, DiffVal)>);

impl Side {
    fn set(&mut self, key: &str, val: DiffVal) {
        match self.0.iter_mut().find(|(k, _)| k == key) {
            Some(e) => e.1 = val,
            None => self.0.push((key.to_string(), val)),
        }
    }

    pub fn get(&self, key: &str) -> Option<&DiffVal> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    fn to_json(&self) -> Value {
        let mut m = Map::new();
        for (k, v) in &self.0 {
            m.insert(k.clone(), v.to_json());
        }
        Value::Object(m)
    }
}

pub struct IfaceDiff {
    pub index: Value,
    pub name: String,
    pub id: Value,
    pub system_state: Side,
    pub netplan_state: Side,
}

/// The report returned by `get_diff()`
#[derive(Default)]
pub struct Report {
    pub interfaces: Vec<(String, IfaceDiff)>,
    pub missing_interfaces_system: Vec<(String, String)>,
    /// name -> (type, index)
    pub missing_interfaces_netplan: Vec<(String, (Value, Value))>,
}

impl Report {
    pub fn interface(&self, name: &str) -> Option<&IfaceDiff> {
        self.interfaces
            .iter()
            .find(|(k, _)| k == name)
            .map(|(_, v)| v)
    }

    /// `json.loads(json.dumps(report, cls=DiffJSONEncoder))`
    pub fn to_json(&self) -> Value {
        let mut interfaces = Map::new();
        for (name, d) in &self.interfaces {
            interfaces.insert(
                name.clone(),
                pv::obj(vec![
                    ("index", d.index.clone()),
                    ("name", d.name.clone().into()),
                    ("id", d.id.clone()),
                    ("system_state", d.system_state.to_json()),
                    ("netplan_state", d.netplan_state.to_json()),
                ]),
            );
        }
        let mut missing_system = Map::new();
        for (name, t) in &self.missing_interfaces_system {
            missing_system.insert(name.clone(), pv::obj(vec![("type", t.clone().into())]));
        }
        let mut missing_netplan = Map::new();
        for (name, (t, index)) in &self.missing_interfaces_netplan {
            missing_netplan.insert(
                name.clone(),
                pv::obj(vec![("type", t.clone()), ("index", index.clone())]),
            );
        }
        pv::obj(vec![
            ("interfaces", Value::Object(interfaces)),
            ("missing_interfaces_system", Value::Object(missing_system)),
            ("missing_interfaces_netplan", Value::Object(missing_netplan)),
        ])
    }
}

/// `_get_system_interfaces()` entry
#[derive(Default)]
struct SysState {
    id: Option<String>,
    index: Option<Value>,
    addresses: Option<Vec<(String, Vec<Value>)>>,
    nameservers_addresses: Option<Vec<Value>>,
    nameservers_search: Option<Vec<Value>>,
    routes: Option<Vec<NetplanRoute>>,
    macaddress: Option<String>,
    interfaces: Option<Vec<Value>>,
    bond: Option<String>,
    bridge: Option<String>,
    vrf: Option<String>,
}

/// `_get_netplan_interfaces()` entry (shared between interfaces matching
/// the same netdef, like the Python dict object)
#[derive(Default)]
struct NpState {
    id: String,
    dhcp4: bool,
    dhcp6: bool,
    link_local: Vec<String>,
    accept_ra: Option<bool>,
    addresses: Option<Vec<String>>,
    nameservers_addresses: Option<Vec<String>>,
    nameservers_search: Option<Vec<String>>,
    routes: Option<Vec<Rc<RefCell<NetplanRoute>>>>,
    gateway4: Option<String>,
    gateway6: Option<String>,
    macaddress: Option<String>,
    bridge: Option<String>,
    bond: Option<String>,
    vrf: Option<String>,
    interfaces: Option<Vec<Value>>,
}

#[derive(Default)]
struct FullIface {
    system_state: Option<SysState>,
    netplan_state: Option<Rc<RefCell<NpState>>>,
    data_sources: Option<Map<String, Value>>,
}

fn index_error() -> anyhow::Error {
    Exception::err("IndexError", "list index out of range")
}

fn push_unique<T: PartialEq>(v: &mut Vec<T>, item: T) {
    if !v.contains(&item) {
        v.push(item);
    }
}

/// `set(a) - set(b)` (in the order of `a`)
fn difference<T: PartialEq + Clone>(a: &[T], b: &[T]) -> Vec<T> {
    let mut out = vec![];
    for x in a {
        if !b.contains(x) {
            push_unique(&mut out, x.clone());
        }
    }
    out
}

pub struct NetplanDiffState<'a> {
    system_state: Option<&'a SystemConfigState>,
    netplan_state: Option<&'a NetplanConfigState>,
    route_lookup_table_names: RouteTables,
}

impl<'a> NetplanDiffState<'a> {
    pub fn new(
        system_state: Option<&'a SystemConfigState>,
        netplan_state: Option<&'a NetplanConfigState>,
    ) -> Self {
        NetplanDiffState {
            system_state,
            netplan_state,
            route_lookup_table_names: RouteTables::default(),
        }
    }

    fn sys(&self) -> &'a SystemConfigState {
        self.system_state.expect("system state")
    }

    fn np(&self) -> &'a NetplanConfigState {
        self.netplan_state.expect("netplan state")
    }

    /// Return the states of both the system and Netplan in a common
    /// representation that makes it easier to compare them.
    fn get_full_state(&mut self) -> Result<Vec<(String, FullIface)>> {
        let system_interfaces = self.get_system_interfaces()?;
        let netplan_interfaces = self.get_netplan_interfaces()?;

        // Merge all the interfaces in the same data structure
        let mut full: Vec<(String, FullIface)> = vec![];
        for name in system_interfaces
            .iter()
            .map(|(k, _)| k)
            .chain(netplan_interfaces.iter().map(|(k, _)| k))
        {
            if !full.iter().any(|(k, _)| k == name) {
                full.push((name.clone(), FullIface::default()));
            }
        }
        for (name, config) in system_interfaces {
            if let Some(e) = full.iter_mut().find(|(k, _)| *k == name) {
                e.1.system_state = Some(config);
            }
        }
        for (name, config) in netplan_interfaces {
            if let Some(e) = full.iter_mut().find(|(k, _)| *k == name) {
                e.1.netplan_state = Some(config);
            }
        }
        for interface in &self.sys().interface_list {
            let name = interface.name_str();
            match full.iter_mut().find(|(k, _)| *k == name) {
                Some(e) => e.1.data_sources = Some(interface.data_sources.clone()),
                None => return Err(Exception::err("KeyError", utils::py_repr_str(&name))),
            }
        }
        Ok(full)
    }

    /// Compare the configuration of interfaces currently found in the system
    /// against Netplan configuration.
    pub fn get_diff(&mut self, interface: Option<&str>) -> Result<Report> {
        let full_state = self.get_full_state()?;
        let mut interfaces: Vec<(String, FullIface)> = full_state
            .into_iter()
            .filter(|(_, c)| c.system_state.is_some() && c.netplan_state.is_some())
            .filter(|(_, c)| c.system_state.as_ref().is_some_and(|s| s.id.is_some()))
            .collect();

        let interface = interface.filter(|i| !i.is_empty());
        if let Some(name) = interface {
            interfaces.retain(|(k, _)| k == name);
        }

        let mut report = Report::default();
        self.analyze_missing_interfaces(&mut report, interface)?;

        for (name, config) in &interfaces {
            let sys = config.system_state.as_ref().expect("filtered");
            let mut iface = IfaceDiff {
                index: sys.index.clone().unwrap_or(Value::Null),
                name: name.clone(),
                id: sys.id.clone().map_or(Value::Null, Value::from),
                system_state: Side::default(),
                netplan_state: Side::default(),
            };
            self.analyze_ip_addresses(config, &mut iface)?;
            self.analyze_nameservers(config, &mut iface)?;
            self.analyze_search_domains(config, &mut iface);
            self.analyze_mac_addresses(config, &mut iface);
            self.analyze_routes(config, &mut iface)?;
            self.analyze_parent_links(config, &mut iface);
            match report.interfaces.iter_mut().find(|(k, _)| k == name) {
                Some(e) => e.1 = iface,
                None => report.interfaces.push((name.clone(), iface)),
            }
        }

        // Sort the list of interfaces according to their indices.
        if report.interfaces.len() > 1 {
            for (_, d) in &report.interfaces {
                if !matches!(d.index, Value::Number(_) | Value::Bool(_)) {
                    return Err(Exception::err(
                        "TypeError",
                        format!(
                            "'<' not supported between instances of '{}' and 'int'",
                            pv::type_name(&d.index)
                        ),
                    ));
                }
            }
            report.interfaces.sort_by(|a, b| {
                let f = |v: &Value| match v {
                    Value::Bool(b) => *b as i64 as f64,
                    v => v.as_f64().unwrap_or(0.0),
                };
                f(&a.1.index)
                    .partial_cmp(&f(&b.1.index))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
        }
        Ok(report)
    }

    fn analyze_ip_addresses(&self, config: &FullIface, iface: &mut IfaceDiff) -> Result<()> {
        let np = config.netplan_state.as_ref().expect("filtered").borrow();
        let sys = config.system_state.as_ref().expect("filtered");
        let mut netplan_ips: Vec<String> = vec![];
        for ip in np.addresses.iter().flatten() {
            push_unique(&mut netplan_ips, ip.clone());
        }
        let netplan_ips = normalize_ip_addresses(&netplan_ips);

        let mut missing_dhcp4_address = np.dhcp4;
        let mut missing_dhcp6_address = np.dhcp6;
        let link_local = &np.link_local;
        let mut system_ips: Vec<String> = vec![];
        let has = |flags: &Vec<Value>, f: &str| flags.iter().any(|x| pv::eq_str(Some(x), f));
        for (addr, flags) in sys.addresses.iter().flatten() {
            let ip = ipaddress::ip_interface(addr)?;

            // Select only static IPs
            if !["dhcp", "dynamic", "link", "ra"]
                .iter()
                .any(|f| has(flags, f))
            {
                push_unique(&mut system_ips, addr.clone());
            }

            // Handle the link local address
            if has(flags, "link") && ip.is_link_local() {
                if ip.ip.is_v4() && !link_local.iter().any(|l| l == "ipv4") {
                    push_unique(&mut system_ips, addr.clone());
                }
                if !ip.ip.is_v4() && !link_local.iter().any(|l| l == "ipv6") {
                    push_unique(&mut system_ips, addr.clone());
                }
            }

            if ip.ip.is_v4() {
                if has(flags, "dhcp") || has(flags, "dynamic") {
                    missing_dhcp4_address = false;
                }
            } else if has(flags, "dhcp") {
                missing_dhcp6_address = false;
            }

            // Handle RA addresses
            if has(flags, "ra") && np.accept_ra == Some(false) {
                push_unique(&mut system_ips, addr.clone());
            }
        }

        let mut present_only_in_netplan = difference(&netplan_ips, &system_ips);
        let mut present_only_in_system = difference(&system_ips, &netplan_ips);

        if missing_dhcp4_address {
            iface
                .system_state
                .set("missing_dhcp4_address", DiffVal::Bool(true));
        }
        if missing_dhcp6_address {
            iface
                .system_state
                .set("missing_dhcp6_address", DiffVal::Bool(true));
        }
        if !present_only_in_system.is_empty() {
            present_only_in_system.sort();
            iface.netplan_state.set(
                "missing_addresses",
                DiffVal::List(
                    present_only_in_system
                        .into_iter()
                        .map(Value::from)
                        .collect(),
                ),
            );
        }
        if !present_only_in_netplan.is_empty() {
            present_only_in_netplan.sort();
            iface.system_state.set(
                "missing_addresses",
                DiffVal::List(
                    present_only_in_netplan
                        .into_iter()
                        .map(Value::from)
                        .collect(),
                ),
            );
        }
        Ok(())
    }

    fn analyze_nameservers(&self, config: &FullIface, iface: &mut IfaceDiff) -> Result<()> {
        let np = config.netplan_state.as_ref().expect("filtered").borrow();
        let sys = config.system_state.as_ref().expect("filtered");
        let empty = Map::new();
        let data_sources = config
            .data_sources
            .as_ref()
            .and_then(|d| d.get("dns"))
            .and_then(Value::as_object)
            .unwrap_or(&empty);

        let mut netplan_nameservers: Vec<Value> = vec![];
        for ns in np.nameservers_addresses.iter().flatten() {
            push_unique(&mut netplan_nameservers, Value::from(ns.clone()));
        }
        let mut system_nameservers: Vec<Value> = vec![];
        for ns in sys.nameservers_addresses.iter().flatten() {
            push_unique(&mut system_nameservers, ns.clone());
        }

        let by_source = |src: &str| -> Vec<Value> {
            data_sources
                .iter()
                .filter(|(_, v)| pv::eq_str(Some(v), src))
                .map(|(k, _)| Value::from(k.clone()))
                .collect()
        };
        let dhcp4_ns = by_source("DHCPv4");
        let dhcp6_ns = by_source("DHCPv6");
        let ndisc_ns = by_source("NDisc");

        // Filter out dynamically assigned DNS data
        let accept_ra_enabled = np.accept_ra != Some(false);
        let link_local_enabled = np.link_local.iter().any(|l| l == "ipv6");

        if !dhcp4_ns.is_empty() || !dhcp6_ns.is_empty() || !ndisc_ns.is_empty() {
            if np.dhcp4 {
                system_nameservers = difference(&system_nameservers, &dhcp4_ns);
            }
            // networkd will enable DHCPv6 if RA is enabled even if DHCPv6 is set to false
            if accept_ra_enabled {
                system_nameservers = difference(&system_nameservers, &dhcp6_ns);
            }
            let link_local_ns: Vec<Value> = system_nameservers
                .iter()
                .filter(|ns| ndisc_ns.contains(ns))
                .cloned()
                .collect();
            if link_local_enabled && accept_ra_enabled {
                system_nameservers = difference(&system_nameservers, &link_local_ns);
            }
        } else if netplan_nameservers.is_empty() {
            // Heuristic used when we don't have data sources for DNS information
            if np.dhcp4 {
                let mut keep = vec![];
                for ns in &system_nameservers {
                    if !ipaddress::ip_address(&pv::to_str(ns))?.is_v4() {
                        keep.push(ns.clone());
                    }
                }
                system_nameservers = keep;
            }
            if np.dhcp6 {
                let mut keep = vec![];
                for ns in &system_nameservers {
                    if ipaddress::ip_address(&pv::to_str(ns))?.is_v4() {
                        keep.push(ns.clone());
                    }
                }
                system_nameservers = keep;
            }
        }

        let present_only_in_netplan = difference(&netplan_nameservers, &system_nameservers);
        let present_only_in_system = difference(&system_nameservers, &netplan_nameservers);
        if !present_only_in_system.is_empty() {
            iface.netplan_state.set(
                "missing_nameservers_addresses",
                DiffVal::List(present_only_in_system),
            );
        }
        if !present_only_in_netplan.is_empty() {
            iface.system_state.set(
                "missing_nameservers_addresses",
                DiffVal::List(present_only_in_netplan),
            );
        }
        Ok(())
    }

    fn analyze_search_domains(&self, config: &FullIface, iface: &mut IfaceDiff) {
        let np = config.netplan_state.as_ref().expect("filtered").borrow();
        let sys = config.system_state.as_ref().expect("filtered");
        let mut netplan_search: Vec<Value> = vec![];
        for s in np.nameservers_search.iter().flatten() {
            push_unique(&mut netplan_search, Value::from(s.clone()));
        }
        let mut system_search: Vec<Value> = vec![];
        for s in sys.nameservers_search.iter().flatten() {
            push_unique(&mut system_search, s.clone());
        }
        let empty = Map::new();
        let data_sources = config
            .data_sources
            .as_ref()
            .and_then(|d| d.get("search"))
            .and_then(Value::as_object)
            .unwrap_or(&empty);
        let by_source = |src: &str| -> Vec<Value> {
            data_sources
                .iter()
                .filter(|(_, v)| pv::eq_str(Some(v), src))
                .map(|(k, _)| Value::from(k.clone()))
                .collect()
        };
        let dhcp4_search = by_source("DHCPv4");
        let dhcp6_search = by_source("DHCPv6");

        if !dhcp4_search.is_empty() || !dhcp6_search.is_empty() {
            if np.dhcp4 {
                system_search = difference(&system_search, &dhcp4_search);
            }
            if np.accept_ra != Some(false) {
                system_search = difference(&system_search, &dhcp6_search);
            }
        } else if netplan_search.is_empty() && (np.dhcp4 || np.dhcp6) {
            system_search = vec![];
        }

        let present_only_in_netplan = difference(&netplan_search, &system_search);
        let present_only_in_system = difference(&system_search, &netplan_search);
        if !present_only_in_system.is_empty() {
            iface.netplan_state.set(
                "missing_nameservers_search",
                DiffVal::List(present_only_in_system),
            );
        }
        if !present_only_in_netplan.is_empty() {
            iface.system_state.set(
                "missing_nameservers_search",
                DiffVal::List(present_only_in_netplan),
            );
        }
    }

    fn analyze_mac_addresses(&self, config: &FullIface, iface: &mut IfaceDiff) {
        let np = config.netplan_state.as_ref().expect("filtered").borrow();
        let sys = config.system_state.as_ref().expect("filtered");
        let system_macaddress = sys.macaddress.as_ref().filter(|m| !m.is_empty());
        let netplan_macaddress = np.macaddress.as_ref().filter(|m| !m.is_empty());

        // if the macaddress in netplan is an special option (such as 'random')
        // don't try to diff it against the system MAC address
        if let Some(m) = netplan_macaddress {
            if !utils::is_valid_macaddress(m) {
                return;
            }
        }
        if let (Some(s), Some(n)) = (system_macaddress, netplan_macaddress) {
            if s != n {
                iface
                    .system_state
                    .set("missing_macaddress", DiffVal::Str(n.clone()));
                iface
                    .netplan_state
                    .set("missing_macaddress", DiffVal::Str(s.clone()));
            }
        }
    }

    fn analyze_routes(&mut self, config: &FullIface, iface: &mut IfaceDiff) -> Result<()> {
        let np_rc = config.netplan_state.as_ref().expect("filtered");
        let sys = config.system_state.as_ref().expect("filtered");
        // set(config['netplan_state']['routes']): the (shared) route objects
        let mut netplan_route_objs: Vec<Rc<RefCell<NetplanRoute>>> = vec![];
        for r in np_rc.borrow().routes.iter().flatten() {
            if !netplan_route_objs
                .iter()
                .any(|x| *x.borrow() == *r.borrow())
            {
                netplan_route_objs.push(r.clone());
            }
        }
        let mut system_routes: Vec<NetplanRoute> = vec![];
        for r in sys.routes.iter().flatten() {
            push_unique(&mut system_routes, r.clone());
        }
        let mut netplan_routes = self.normalize_routes(&netplan_route_objs)?;

        // If gateway4 and/or gateway6 is present, merge them in the routes set
        let gateways = self.normalize_gateways(&np_rc.borrow());
        for g in gateways {
            push_unique(&mut netplan_routes, g);
        }

        // Filter out some routes that are expected to be added automatically
        let system_addresses: Vec<String> = sys
            .addresses
            .iter()
            .flatten()
            .map(|(a, _)| a.clone())
            .collect();
        let system_routes =
            filter_system_routes(&system_routes, &system_addresses, &np_rc.borrow())?;

        let mut present_only_in_netplan = difference(&netplan_routes, &system_routes);
        let mut present_only_in_system = difference(&system_routes, &netplan_routes);

        let sort = |v: &mut Vec<NetplanRoute>| -> Result<()> {
            if v.len() > 1 && v.iter().any(|r| r.to.is_none()) {
                return Err(Exception::err(
                    "TypeError",
                    "'<' not supported between instances of 'NoneType' and 'str'",
                ));
            }
            v.sort_by(|a, b| a.to.cmp(&b.to));
            Ok(())
        };
        if !present_only_in_system.is_empty() {
            sort(&mut present_only_in_system)?;
            iface
                .netplan_state
                .set("missing_routes", DiffVal::Routes(present_only_in_system));
        }
        if !present_only_in_netplan.is_empty() {
            sort(&mut present_only_in_netplan)?;
            iface
                .system_state
                .set("missing_routes", DiffVal::Routes(present_only_in_netplan));
        }
        Ok(())
    }

    fn analyze_missing_interfaces(
        &self,
        report: &mut Report,
        interface: Option<&str>,
    ) -> Result<()> {
        let netplan_interfaces: Vec<&String> = self.np().netdefs.iter().map(|(k, _)| k).collect();
        let mut system_interfaces_netdef_ids: Vec<String> = vec![];
        for iface in &self.sys().interface_list {
            if iface.netdef_id()?.is_some_and(|i| !i.is_empty()) {
                if let Some(id) = iface.netdef_id()? {
                    push_unique(&mut system_interfaces_netdef_ids, id);
                }
            }
        }

        // Filtering out disconnected wifi netdefs
        let mut netplan_only: Vec<String> = netplan_interfaces
            .iter()
            .filter(|i| !system_interfaces_netdef_ids.contains(i))
            .filter(|i| self.np().get(i).is_some_and(|nd| nd.type_ != "wifis"))
            .map(|i| i.to_string())
            .collect();

        let mut system_only: Vec<String> = vec![];
        for iface in &self.sys().interface_list {
            let id = iface.netdef_id()?;
            if !id.is_some_and(|id| netplan_interfaces.iter().any(|n| **n == id)) {
                system_only.push(iface.name_str());
            }
        }

        netplan_only.sort();
        system_only.sort();

        if let Some(name) = interface {
            netplan_only.retain(|i| i == name);
            system_only.retain(|i| i == name);
        }

        let system_state = self.sys().get_data();

        for iface in netplan_only {
            let iface_type = self.np().get(&iface).map(|nd| nd.type_).unwrap_or("");
            let t = state::device_type(iface_type)
                .unwrap_or("other")
                .to_string();
            match report
                .missing_interfaces_system
                .iter_mut()
                .find(|(k, _)| *k == iface)
            {
                Some(e) => e.1 = t,
                None => report.missing_interfaces_system.push((iface, t)),
            }
        }

        for iface in system_only {
            let Some(data) = system_state.get(&iface) else {
                return Err(Exception::err(
                    "AttributeError",
                    "'NoneType' object has no attribute 'get'",
                ));
            };
            let t = data.get("type").cloned().unwrap_or_else(|| "other".into());
            let index = data.get("index").cloned().unwrap_or(Value::Null);
            match report
                .missing_interfaces_netplan
                .iter_mut()
                .find(|(k, _)| *k == iface)
            {
                Some(e) => e.1 = (t, index),
                None => report.missing_interfaces_netplan.push((iface, (t, index))),
            }
        }
        Ok(())
    }

    /// Analyse if interfaces such as bonds, bridges and VRFs are correctly
    /// attached to their members and vice versa.
    fn analyze_parent_links(&self, config: &FullIface, iface: &mut IfaceDiff) {
        let np = config.netplan_state.as_ref().expect("filtered").borrow();
        let sys = config.system_state.as_ref().expect("filtered");
        for (key, s, n) in [
            ("bond", &sys.bond, &np.bond),
            ("bridge", &sys.bridge, &np.bridge),
            ("vrf", &sys.vrf, &np.vrf),
        ] {
            if (s.is_some() || n.is_some()) && s != n {
                let k = format!("missing_{key}_link");
                if let Some(s) = s.as_ref().filter(|s| !s.is_empty()) {
                    iface.netplan_state.set(&k, DiffVal::Str(s.clone()));
                }
                if let Some(n) = n.as_ref().filter(|n| !n.is_empty()) {
                    iface.system_state.set(&k, DiffVal::Str(n.clone()));
                }
            }
        }

        let system = sys.interfaces.clone().unwrap_or_default();
        let netplan = np.interfaces.clone().unwrap_or_default();
        if !system.is_empty() || !netplan.is_empty() {
            let missing_system = difference(&netplan, &system);
            let missing_netplan = difference(&system, &netplan);
            if !missing_system.is_empty() {
                iface
                    .system_state
                    .set("missing_interfaces", DiffVal::List(missing_system));
            }
            if !missing_netplan.is_empty() {
                iface
                    .netplan_state
                    .set("missing_interfaces", DiffVal::List(missing_netplan));
            }
        }
    }

    /// Apply some transformations to Netplan routes so their representation
    /// will match the system's (mutating the shared route objects).
    fn normalize_routes(
        &mut self,
        routes: &[Rc<RefCell<NetplanRoute>>],
    ) -> Result<Vec<NetplanRoute>> {
        let mut new_routes = vec![];
        for route in routes {
            let mut r = route.borrow_mut();
            // If the table is unspecified we set it to main
            if r.table == TABLE_UNSPEC {
                r.table = self.default_route_tables_name_to_number("main");
            }
            // If the addresses are IPv6, compress them so it will match the system representation
            r.to = r.to.as_deref().map(compress_ipv6_address);
            r.from_addr = r.from_addr.as_deref().map(compress_ipv6_address);
            r.via = r.via.as_deref().map(compress_ipv6_address);

            // If the route.to prefix is either /32 and /128 we remove it
            if r.to.as_deref() != Some("default") {
                let to = r.to.clone().ok_or_else(|| {
                    Exception::err(
                        "AttributeError",
                        "'NoneType' object has no attribute 'split'",
                    )
                })?;
                let ip_prefix: Vec<&str> = to.split('/').collect();
                let prefix = ip_prefix.get(1).ok_or_else(index_error)?;
                if *prefix == "32" || *prefix == "128" {
                    r.to = Some(ip_prefix[0].to_string());
                }
            }
            push_unique(&mut new_routes, r.clone());
        }
        Ok(new_routes)
    }

    /// Convert the gateway4 and gateway6 properties to NetplanRoutes.
    fn normalize_gateways(&mut self, config: &NpState) -> Vec<NetplanRoute> {
        let mut routes_set = vec![];
        let system_interfaces = self.sys().get_data();
        let interface = &config.id;
        let routes: Vec<&Map<String, Value>> = system_interfaces
            .values()
            .filter(|iface| pv::eq_str(iface.get("id"), interface))
            .filter_map(|iface| iface.get("routes").and_then(Value::as_array))
            .flatten()
            .filter_map(Value::as_object)
            .collect();

        for (gateway, family) in [(&config.gateway4, 2), (&config.gateway6, 10)] {
            let Some(gateway) = gateway.as_ref().filter(|g| !g.is_empty()) else {
                continue;
            };
            let default_routes: Vec<&&Map<String, Value>> = routes
                .iter()
                .filter(|r| {
                    pv::eq_str(r.get("to"), "default")
                        && r.get("family")
                            .is_some_and(|f| pv::eq(f, &Value::from(family)))
                        && pv::eq_str(r.get("protocol"), "static")
                })
                .collect();
            let via = if family == 10 {
                compress_ipv6_address(gateway)
            } else {
                gateway.clone()
            };
            let mut route = NetplanRoute {
                to: Some("default".into()),
                via: Some(via),
                family,
                protocol: Some("static".into()),
                ..Default::default()
            };
            if default_routes.len() == 1 {
                if let Some(metric) = default_routes[0].get("metric").filter(|m| pv::truthy(m)) {
                    route.metric = pv::to_int(metric).unwrap_or(METRIC_UNSPEC);
                }
                if let Some(table) = default_routes[0].get("table").filter(|t| pv::truthy(t)) {
                    route.table = self.default_route_tables_name_to_number(&pv::to_str(table));
                }
            }
            push_unique(&mut routes_set, route);
        }
        routes_set
    }

    fn get_netplan_interfaces(&mut self) -> Result<Vec<(String, Rc<RefCell<NpState>>)>> {
        let system_interfaces = self.sys().get_data();
        let mut interfaces: Vec<(String, Rc<RefCell<NpState>>)> = vec![];
        let insert = |interfaces: &mut Vec<(String, Rc<RefCell<NpState>>)>,
                      k: &str,
                      v: Rc<RefCell<NpState>>| {
            match interfaces.iter_mut().find(|(key, _)| key == k) {
                Some(e) => e.1 = v,
                None => interfaces.push((k.to_string(), v)),
            }
        };
        for (interface, config) in &self.np().netdefs {
            let mut addresses = None;
            if !config.addresses.is_empty() {
                let mut a = vec![];
                for addr in &config.addresses {
                    push_unique(
                        &mut a,
                        addr.address.clone().unwrap_or_else(|| "None".into()),
                    );
                }
                addresses = Some(a);
            }
            let routes: Vec<Rc<RefCell<NetplanRoute>>> = config
                .routes
                .iter()
                .map(|r| {
                    Rc::new(RefCell::new(NetplanRoute {
                        to: r.to.clone(),
                        via: r.via.clone(),
                        from_addr: r.from_addr.clone(),
                        type_: r.type_.clone(),
                        scope: r.scope.clone(),
                        protocol: None,
                        table: r.table,
                        family: r.family,
                        metric: r.metric,
                    }))
                })
                .collect();
            let np = NpState {
                id: interface.clone(),
                dhcp4: config.dhcp4,
                dhcp6: config.dhcp6,
                link_local: config.link_local.clone(),
                accept_ra: config.accept_ra,
                addresses,
                nameservers_addresses: Some(config.nameserver_addresses.clone())
                    .filter(|v| !v.is_empty()),
                nameservers_search: Some(config.nameserver_search.clone())
                    .filter(|v| !v.is_empty()),
                routes: Some(routes).filter(|v| !v.is_empty()),
                gateway4: config.gateway4.clone().filter(|g| !g.is_empty()),
                gateway6: config.gateway6.clone().filter(|g| !g.is_empty()),
                macaddress: config.macaddress.clone().filter(|m| !m.is_empty()),
                bridge: config.bridge.clone(),
                bond: config.bond.clone(),
                vrf: config.vrf.clone(),
                interfaces: None,
            };
            let np = Rc::new(RefCell::new(np));

            if !system_interfaces.contains_key(interface) {
                // The netdef ID might be associated with multiple system
                // interfaces (match, or NM connection UUIDs): add one netdef
                // entry per device pointing to it.
                let mut found_some = false;
                for (key, value) in system_interfaces {
                    if let Some(netdef_id) = value.get("id").filter(|v| pv::truthy(v)) {
                        if pv::eq_str(Some(netdef_id), interface) {
                            found_some = true;
                            insert(&mut interfaces, key, np.clone());
                        }
                    }
                }
                if !found_some {
                    insert(&mut interfaces, interface, np);
                }
            } else {
                insert(&mut interfaces, interface, np);
            }
        }
        self.netplan_state_find_parents(&interfaces)?;
        Ok(interfaces)
    }

    /// Associates interfaces with their parents
    fn netplan_state_find_parents(
        &self,
        interfaces: &[(String, Rc<RefCell<NpState>>)],
    ) -> Result<()> {
        let mut parents: Vec<(String, Vec<Value>)> = vec![];
        for (interface, config) in interfaces {
            let c = config.borrow();
            for link in [&c.bridge, &c.bond, &c.vrf].into_iter().flatten() {
                if link.is_empty() {
                    continue;
                }
                match parents.iter_mut().find(|(k, _)| k == link) {
                    Some(e) => push_unique(&mut e.1, Value::from(interface.clone())),
                    None => parents.push((link.clone(), vec![Value::from(interface.clone())])),
                }
            }
        }
        for (interface, members) in parents {
            match interfaces.iter().find(|(k, _)| *k == interface) {
                Some((_, config)) => config.borrow_mut().interfaces = Some(members),
                None => return Err(Exception::err("KeyError", utils::py_repr_str(&interface))),
            }
        }
        Ok(())
    }

    fn get_system_interfaces(&mut self) -> Result<Vec<(String, SysState)>> {
        let mut interfaces = vec![];
        let data = self.sys().get_data();
        for (interface, config) in data {
            if interface == "netplan-global-state" {
                continue;
            }
            let mut s = SysState::default();
            if let Some(id) = config.get("id").filter(|v| pv::truthy(v)) {
                s.id = Some(pv::to_str(id));
            }
            if let Some(index) = config.get("index").filter(|v| pv::truthy(v)) {
                s.index = Some(index.clone());
            }
            let mut addresses: Vec<(String, Vec<Value>)> = vec![];
            for addr in config
                .get("addresses")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                let Some((ip, extra)) = addr.as_object().and_then(|m| m.iter().next()) else {
                    continue;
                };
                let prefix = extra.get("prefix").cloned().unwrap_or(Value::Null);
                let full_addr = format!("{}/{}", ip, pv::to_str(&prefix));
                let flags = extra
                    .get("flags")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                match addresses.iter_mut().find(|(k, _)| *k == full_addr) {
                    Some(e) => e.1 = flags,
                    None => addresses.push((full_addr, flags)),
                }
            }
            if !addresses.is_empty() {
                s.addresses = Some(addresses);
            }
            s.nameservers_addresses = config
                .get("dns_addresses")
                .and_then(Value::as_array)
                .filter(|a| !a.is_empty())
                .cloned();
            s.nameservers_search = config
                .get("dns_search")
                .and_then(Value::as_array)
                .filter(|a| !a.is_empty())
                .cloned();
            if let Some(routes) = config
                .get("routes")
                .and_then(Value::as_array)
                .filter(|r| !r.is_empty())
            {
                let mut out = vec![];
                for route in routes {
                    if let Some(r) = route.as_object() {
                        out.push(system_route_to_netplan(
                            r,
                            &mut self.route_lookup_table_names,
                        ));
                    }
                }
                s.routes = Some(out);
            }
            s.macaddress = config
                .get("macaddress")
                .filter(|v| pv::truthy(v))
                .map(pv::to_str);
            s.interfaces = config
                .get("interfaces")
                .and_then(Value::as_array)
                .filter(|a| !a.is_empty())
                .cloned();
            s.bond = config.get("bond").filter(|v| pv::truthy(v)).map(pv::to_str);
            s.bridge = config
                .get("bridge")
                .filter(|v| pv::truthy(v))
                .map(pv::to_str);
            s.vrf = config.get("vrf").filter(|v| pv::truthy(v)).map(pv::to_str);
            interfaces.push((interface.clone(), s));
        }
        Ok(interfaces)
    }

    fn default_route_tables_name_to_number(&mut self, name: &str) -> i64 {
        default_route_tables_name_to_number(name, &mut self.route_lookup_table_names)
    }
}

/// `NetplanDiffState._default_route_tables_name_to_number`
fn default_route_tables_name_to_number(name: &str, cache: &mut RouteTables) -> i64 {
    if !name.is_empty() && name.chars().all(|c| c.is_ascii_digit()) {
        return name.parse().unwrap_or(0);
    }
    if cache.is_empty() {
        *cache = state::route_table_lookup();
    }
    cache.by_name.get(name).copied().unwrap_or(0)
}

/// `NetplanDiffState._system_route_to_netplan`
pub fn system_route_to_netplan(
    system_route: &Map<String, Value>,
    cache: &mut RouteTables,
) -> NetplanRoute {
    let get = |k: &str| system_route.get(k).filter(|v| pv::truthy(v));
    let s = |v: &Value| pv::to_str(v);
    let mut route = NetplanRoute::default();
    if let Some(family) = get("family") {
        route.family = pv::to_int(family).unwrap_or(-1);
    }
    if let Some(to) = get("to") {
        route.to = Some(s(to));
    }
    if let Some(via) = get("via") {
        route.via = Some(s(via));
    }
    if let Some(from) = get("from") {
        route.from_addr = Some(s(from));
    }
    if let Some(metric) = get("metric") {
        route.metric = pv::to_int(metric).unwrap_or(METRIC_UNSPEC);
    }
    if let Some(scope) = get("scope") {
        route.scope = Some(s(scope));
    }
    if let Some(t) = get("type") {
        route.type_ = Some(s(t));
    }
    if let Some(protocol) = get("protocol") {
        route.protocol = Some(s(protocol));
    }
    if let Some(table) = get("table") {
        route.table = default_route_tables_name_to_number(&s(table), cache);
    }
    route
}

/// Apply some transformations to IP addresses so their representation
/// will match the system's.
fn normalize_ip_addresses(addresses: &[String]) -> Vec<String> {
    let mut out = vec![];
    for ip in addresses {
        push_unique(&mut out, compress_ipv6_address(ip));
    }
    out
}

/// Compress IPv6 addresses to match the system representation; return the
/// original value if it is not an IP address/interface.
fn compress_ipv6_address(address: &str) -> String {
    match ipaddress::ip_interface(address) {
        Ok(addr) => {
            if address.contains('/') {
                addr.with_prefixlen()
            } else {
                addr.ip().to_string()
            }
        }
        Err(_) => address.to_string(),
    }
}

/// Some routes found in the system are installed automatically/dynamically
/// without being configured in Netplan: remove them before comparing.
fn filter_system_routes(
    system_routes: &[NetplanRoute],
    system_addresses: &[String],
    config: &NpState,
) -> Result<Vec<NetplanRoute>> {
    let mut local_networks = vec![];
    let mut addresses = vec![];
    for ip in system_addresses {
        let i = ipaddress::ip_interface(ip)?;
        let net = i.network().to_string();
        // filter out the local link network as we give special treatment to it
        if net != "fe80::/64" {
            local_networks.push(net);
        }
    }
    for ip in system_addresses {
        addresses.push(ipaddress::ip_interface(ip)?.ip().to_string());
    }
    let link_local = &config.link_local;
    let iface = |to: &Option<String>| -> Result<ipaddress::Interface> {
        ipaddress::ip_interface(to.as_deref().unwrap_or("None"))
    };
    let mut routes = vec![];
    for route in system_routes {
        let to_default = route.to.as_deref() == Some("default");
        // Filter out link routes (but not link local as we handle them differently)
        if route.scope.as_deref() == Some("link")
            && !to_default
            && !iface(&route.to)?.is_link_local()
        {
            continue;
        }
        // Filter out routes installed by DHCP
        if route.protocol.as_deref() == Some("dhcp") {
            continue;
        }
        // Filter out routes installed by RA if accept_ra is not false
        if route.protocol.as_deref() == Some("ra") && config.accept_ra != Some(false) {
            continue;
        }
        // Filter out Link Local routes
        if !to_default && iface(&route.to)?.is_link_local() {
            if route.family == 10 && link_local.iter().any(|l| l == "ipv6") {
                continue;
            }
            if route.family == 2 && link_local.iter().any(|l| l == "ipv4") {
                continue;
            }
        }
        // Filter out host scoped routes
        if route.scope.as_deref() == Some("host") && route.type_.as_deref() == Some("local") {
            let in_addresses = route.to.as_ref().is_some_and(|t| addresses.contains(t));
            if in_addresses || iface(&route.to)?.is_loopback() {
                continue;
            }
        }
        // Filter out the default IPv6 multicast route
        if route.family == 10
            && route.type_.as_deref() == Some("multicast")
            && route.to.as_deref() == Some("ff00::/8")
        {
            continue;
        }
        // Filter IPv6 local routes
        if route.family == 10
            && route.protocol.as_deref() != Some("ra")
            && route
                .to
                .as_ref()
                .is_some_and(|t| local_networks.contains(t) || addresses.contains(t))
        {
            continue;
        }
        push_unique(&mut routes, route.clone());
    }
    Ok(routes)
}
