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

//! Port of `netplan_cli/cli/state.py`: collects the system's network state
//! (iproute2, systemd-networkd, NetworkManager, systemd-resolved,
//! /etc/resolv.conf) and Netplan's configuration state.
//!
//! The data gathered from external tools is kept as JSON values and handled
//! with Python's semantics (truthiness, `dict.get()`, `in`), see [`pv`].

use std::collections::HashMap;

use anyhow::Result;
use serde_json::{Map, Value};

use crate::ipaddress;
use crate::netplan;
use crate::py::{self, Exception};
use crate::pyjson;
use crate::utils::{self, sub};

/// Python value helpers over [`serde_json::Value`].
pub mod pv {
    use anyhow::Result;
    use serde_json::{Map, Value};

    use crate::py::Exception;

    /// `type(v).__name__`
    pub fn type_name(v: &Value) -> &'static str {
        match v {
            Value::Null => "NoneType",
            Value::Bool(_) => "bool",
            Value::Number(n) if n.is_f64() => "float",
            Value::Number(_) => "int",
            Value::String(_) => "str",
            Value::Array(_) => "list",
            Value::Object(_) => "dict",
        }
    }

    /// `bool(v)`
    pub fn truthy(v: &Value) -> bool {
        match v {
            Value::Null => false,
            Value::Bool(b) => *b,
            Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
            Value::String(s) => !s.is_empty(),
            Value::Array(a) => !a.is_empty(),
            Value::Object(o) => !o.is_empty(),
        }
    }

    pub fn opt_truthy(v: Option<&Value>) -> bool {
        v.is_some_and(truthy)
    }

    /// `v.get(key)` on something that must be a dict
    pub fn get<'a>(v: &'a Value, key: &str) -> Result<Option<&'a Value>> {
        match v {
            Value::Object(m) => Ok(m.get(key)),
            _ => Err(Exception::err(
                "AttributeError",
                format!("'{}' object has no attribute 'get'", type_name(v)),
            )),
        }
    }

    /// `v[key]` on something that must be a dict
    pub fn index<'a>(v: &'a Value, key: &str) -> Result<&'a Value> {
        match v {
            Value::Object(m) => m
                .get(key)
                .ok_or_else(|| Exception::err("KeyError", crate::utils::py_repr_str(key))),
            Value::Array(_) => Err(Exception::err(
                "TypeError",
                "list indices must be integers or slices, not str",
            )),
            Value::String(_) => Err(Exception::err(
                "TypeError",
                "string indices must be integers, not 'str'",
            )),
            _ => Err(Exception::err(
                "TypeError",
                format!("'{}' object is not subscriptable", type_name(v)),
            )),
        }
    }

    /// `str(v)`
    pub fn to_str(v: &Value) -> String {
        match v {
            Value::Null => "None".into(),
            Value::Bool(true) => "True".into(),
            Value::Bool(false) => "False".into(),
            Value::String(s) => match crate::pyjson::nonfinite(v) {
                Some(f) => f.to_string(),
                None => s.clone(),
            },
            Value::Number(n) => match (n.as_i64(), n.as_u64(), n.as_f64()) {
                (Some(i), _, _) => i.to_string(),
                (_, Some(u), _) => u.to_string(),
                (_, _, Some(f)) => crate::pyjson::py_float_repr(f),
                _ => String::new(),
            },
            Value::Array(items) => format!(
                "[{}]",
                items.iter().map(repr).collect::<Vec<_>>().join(", ")
            ),
            Value::Object(m) => format!(
                "{{{}}}",
                m.iter()
                    .map(|(k, v)| format!("{}: {}", crate::utils::py_repr_str(k), repr(v)))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        }
    }

    /// `repr(v)`
    pub fn repr(v: &Value) -> String {
        match v {
            Value::String(s) if crate::pyjson::nonfinite(v).is_none() => {
                crate::utils::py_repr_str(s)
            }
            _ => to_str(v),
        }
    }

    /// `a == b` for JSON-derived values
    pub fn eq(a: &Value, b: &Value) -> bool {
        let num = |v: &Value| match v {
            Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
            Value::Number(n) => n.as_f64(),
            _ => None,
        };
        match (a, b) {
            (Value::Number(x), Value::Number(y)) => match (x.as_i64(), y.as_i64()) {
                (Some(i), Some(j)) => i == j,
                _ => num(a) == num(b),
            },
            (Value::Bool(_) | Value::Number(_), Value::Bool(_) | Value::Number(_)) => {
                num(a) == num(b)
            }
            (Value::Array(x), Value::Array(y)) => {
                x.len() == y.len() && x.iter().zip(y).all(|(p, q)| eq(p, q))
            }
            (Value::Object(x), Value::Object(y)) => {
                x.len() == y.len() && x.iter().all(|(k, v)| y.get(k).is_some_and(|w| eq(v, w)))
            }
            _ => a == b,
        }
    }

    pub fn eq_str(a: Option<&Value>, s: &str) -> bool {
        matches!(a, Some(Value::String(x)) if x == s)
    }

    /// `needle in container`
    pub fn contains(container: &Value, needle: &str) -> Result<bool> {
        match container {
            Value::String(s) => Ok(s.contains(needle)),
            Value::Array(items) => Ok(items.iter().any(|i| eq_str(Some(i), needle))),
            Value::Object(m) => Ok(m.contains_key(needle)),
            v => Err(Exception::err(
                "TypeError",
                format!("argument of type '{}' is not iterable", type_name(v)),
            )),
        }
    }

    /// `iter(v)` as a list of values
    pub fn iterate(v: &Value) -> Result<Vec<Value>> {
        match v {
            Value::Array(items) => Ok(items.clone()),
            Value::Object(m) => Ok(m.keys().map(|k| Value::String(k.clone())).collect()),
            Value::String(s) => Ok(s.chars().map(|c| Value::String(c.to_string())).collect()),
            v => Err(Exception::err(
                "TypeError",
                format!("'{}' object is not iterable", type_name(v)),
            )),
        }
    }

    /// `int(v)`
    pub fn to_int(v: &Value) -> Result<i64> {
        match v {
            Value::Bool(b) => Ok(*b as i64),
            Value::Number(n) => match n.as_i64() {
                Some(i) => Ok(i),
                None => Ok(n.as_f64().unwrap_or(0.0).trunc() as i64),
            },
            Value::String(s) => s.trim().parse().map_err(|_| {
                Exception::err(
                    "ValueError",
                    format!("invalid literal for int() with base 10: {}", crate::utils::py_repr_str(s)),
                )
            }),
            v => Err(Exception::err(
                "TypeError",
                format!(
                    "int() argument must be a string, a bytes-like object or a real number, not '{}'",
                    type_name(v)
                ),
            )),
        }
    }

    /// `v.strip()` / `v.upper()` etc. need a str
    pub fn as_str<'a>(v: &'a Value, method: &str) -> Result<&'a str> {
        match v {
            Value::String(s) => Ok(s),
            _ => Err(Exception::err(
                "AttributeError",
                format!("'{}' object has no attribute '{}'", type_name(v), method),
            )),
        }
    }

    pub fn obj(pairs: Vec<(&str, Value)>) -> Value {
        let mut m = Map::new();
        for (k, v) in pairs {
            m.insert(k.to_string(), v);
        }
        Value::Object(m)
    }
}

/// `str.strip()` (Python whitespace)
pub fn py_strip(s: &str) -> &str {
    s.trim_matches(crate::rich::py_isspace)
}

/// `str.split()` (no arguments)
pub fn py_split(s: &str) -> Vec<&str> {
    s.split(crate::rich::py_isspace)
        .filter(|p| !p.is_empty())
        .collect()
}

/// `DEVICE_TYPES.get(key)`
pub fn device_type(key: &str) -> Option<&'static str> {
    Some(match key {
        "bond" => "bond",
        "bridge" => "bridge",
        "dummy" => "dummy-device",
        "erspan" => "tunnel",
        "ether" => "ethernet",
        "gretap" => "tunnel",
        "ipgre" => "tunnel",
        "ip6gre" => "tunnel",
        "loopback" => "ethernet",
        "sit" => "tunnel",
        "tunnel" => "tunnel",
        "tun" => "tunnel",
        "tunnel6" => "tunnel",
        "wireguard" => "tunnel",
        "wlan" => "wifi",
        "wwan" => "modem",
        "veth" => "virtual-ethernet",
        "vlan" => "vlan",
        "vrf" => "vrf",
        "vxlan" => "tunnel",
        "ieee80211_radiotap" => "wifi",
        "wifis" => "wifi",
        "ethernets" => "ethernet",
        "bridges" => "bridge",
        "bonds" => "bond",
        "nm-devices" => "nm-device",
        "dummy-devices" => "dummy-device",
        "modems" => "modem",
        "vlans" => "vlan",
        "vrfs" => "vrf",
        _ => return None,
    })
}

/// `str(exception)` for an error caught by `except Exception`
pub fn exc_str(e: &anyhow::Error) -> String {
    match e.downcast_ref::<Exception>() {
        Some(ex) => ex.message.clone(),
        None => format!("{e:#}"),
    }
}

/// One NetworkManager connection as returned by `process_nm()`
#[derive(Clone)]
pub struct NmConnection {
    pub device: String,
    pub name: String,
    #[allow(dead_code)] // parsed like Python does, but unused
    pub uuid: String,
    pub filename: String,
    pub type_: String,
    pub autoconnect: String,
}

pub struct Interface {
    pub idx: Value,
    pub name: Value,
    pub adminstate: String,
    pub operstate: String,
    pub macaddress: Option<String>,
    pub bridge: Option<String>,
    pub bond: Option<String>,
    pub vrf: Option<String>,
    pub members: Vec<Value>,
    pub data_sources: Map<String, Value>,
    nd: Option<Value>,
    nm: Option<NmConnection>,
    pub dns_addresses: Option<Vec<String>>,
    pub dns_search: Option<Vec<String>>,
    pub routes: Option<Vec<Map<String, Value>>>,
    pub addresses: Option<Vec<Value>>,
    iproute_type: Option<String>,
    networkctl: String,
}

impl Interface {
    /// `self.name` as a str (interface names from iproute2 are strings)
    pub fn name_str(&self) -> String {
        pv::to_str(&self.name)
    }

    fn extract_mac(ip: &Value) -> Result<Option<String>> {
        let address = pv::get(ip, "address")?
            .cloned()
            .unwrap_or(Value::String(String::new()));
        let len = match &address {
            Value::String(s) => s.chars().count(),
            Value::Array(a) => a.len(),
            Value::Object(o) => o.len(),
            v => {
                return Err(Exception::err(
                    "TypeError",
                    format!("object of type '{}' has no len()", pv::type_name(v)),
                ))
            }
        };
        if len == 17 {
            return Ok(Some(pv::as_str(&address, "lower")?.to_lowercase()));
        }
        Ok(None)
    }

    pub fn new(
        ip: &Value,
        nd_data: &Value,
        nm_data: &[NmConnection],
        resolved_data: (&Option<Value>, &Option<Value>),
        route_data: (&Option<Value>, &Option<Value>),
    ) -> Result<Interface> {
        let idx = pv::get(ip, "ifindex")?.cloned().unwrap_or(Value::from(-1));
        let name = pv::get(ip, "ifname")?
            .cloned()
            .unwrap_or(Value::String("unknown".into()));
        let flags = pv::get(ip, "flags")?
            .cloned()
            .unwrap_or(Value::Array(vec![]));
        let adminstate = if pv::contains(&flags, "UP")? {
            "UP"
        } else {
            "DOWN"
        }
        .to_string();
        let operstate = match pv::get(ip, "operstate")? {
            None => "UNKNOWN".to_string(),
            Some(v) => pv::as_str(v, "upper")?.to_uppercase(),
        };
        let macaddress = Self::extract_mac(ip)?;

        // Filter networkd/NetworkManager data
        let mut nd = None;
        for x in pv::iterate(nd_data)? {
            if pv::eq(pv::index(&x, "Index")?, &idx) {
                nd = Some(x);
                break;
            }
        }
        let nm = nm_data
            .iter()
            .find(|x| matches!(&name, Value::String(n) if *n == x.device))
            .cloned();

        let mut itf = Interface {
            idx,
            name,
            adminstate,
            operstate,
            macaddress,
            bridge: None,
            bond: None,
            vrf: None,
            members: vec![],
            data_sources: Map::new(),
            nd,
            nm,
            dns_addresses: None,
            dns_search: None,
            routes: None,
            addresses: None,
            iproute_type: None,
            networkctl: String::new(),
        };

        // Map networkd data (such as IP addresses and nameservers)
        // to their sources (such as dhcp4, dhcp6, etc)
        if let Some(nd) = &itf.nd {
            if pv::truthy(nd) {
                itf.data_sources = Self::find_data_sources(nd)?;
            }
        }

        // Filter resolved's DNS data
        if let Some(addresses) = resolved_data.0 {
            if pv::truthy(addresses) {
                let mut dns = vec![];
                for itr in pv::iterate(addresses)? {
                    let item = pv::iterate(&itr)?;
                    let get = |i: usize| {
                        item.get(i)
                            .ok_or_else(|| Exception::err("IndexError", "list index out of range"))
                    };
                    if pv::to_int(get(0)?)? == pv::to_int(&itf.idx)? {
                        let family = pv::to_int(get(1)?)?;
                        let mut bytes = vec![];
                        for v in pv::iterate(get(2)?)? {
                            let b = pv::to_int(&v)?;
                            if !(0..=255).contains(&b) {
                                return Err(Exception::err(
                                    "OverflowError",
                                    "int too big to convert",
                                ));
                            }
                            bytes.push(b as u8);
                        }
                        dns.push(ipaddress::inet_ntop(family, &bytes)?);
                    }
                }
                itf.dns_addresses = Some(dns);
            }
        }
        if let Some(search) = resolved_data.1 {
            if pv::truthy(search) {
                let mut out = vec![];
                for v in pv::iterate(search)? {
                    let item = pv::iterate(&v)?;
                    let get = |i: usize| {
                        item.get(i)
                            .ok_or_else(|| Exception::err("IndexError", "list index out of range"))
                    };
                    if pv::to_int(get(0)?)? == pv::to_int(&itf.idx)? {
                        out.push(pv::to_str(get(1)?));
                    }
                }
                itf.dns_search = Some(out);
            }
        }

        // Filter route data
        let mut routes_in: Vec<Value> = vec![];
        if let Some(r) = route_data.0 {
            if pv::truthy(r) {
                routes_in.extend(pv::iterate(r)?);
            }
        }
        if let Some(r) = route_data.1 {
            if pv::truthy(r) {
                routes_in.extend(pv::iterate(r)?);
            }
        }
        if !routes_in.is_empty() {
            let mut routes = vec![];
            for obj in &routes_in {
                let dev = pv::get(obj, "dev")?;
                if dev.is_some_and(|d| pv::eq(d, &itf.name)) {
                    let mut elem = Map::new();
                    elem.insert(
                        "to".into(),
                        pv::get(obj, "dst")?.cloned().unwrap_or(Value::Null),
                    );
                    for (src, dst) in [
                        ("family", "family"),
                        ("gateway", "via"),
                        ("prefsrc", "from"),
                        ("metric", "metric"),
                        ("type", "type"),
                        ("scope", "scope"),
                        ("protocol", "protocol"),
                        ("table", "table"),
                    ] {
                        if let Some(val) = pv::get(obj, src)? {
                            if pv::truthy(val) {
                                elem.insert(dst.into(), val.clone());
                            }
                        }
                    }
                    routes.push(elem);
                }
            }
            itf.routes = Some(routes);
        }

        if let Some(addr_info) = pv::get(ip, "addr_info")? {
            if pv::truthy(addr_info) {
                itf.addresses = Some(itf.parse_addresses(addr_info)?);
            }
        }

        if let Some(linkinfo) = pv::get(ip, "linkinfo")? {
            if let Some(kind) = pv::get(linkinfo, "info_kind")? {
                if pv::truthy(kind) {
                    itf.iproute_type = Some(py_strip(pv::as_str(kind, "strip")?).to_string());
                }
            }
        }

        // workaround: query some data which is not available via networkctl's JSON output
        itf.networkctl = Self::query_networkctl(&itf.name).unwrap_or_default();
        Ok(itf)
    }

    fn parse_addresses(&self, addr_info: &Value) -> Result<Vec<Value>> {
        let mut ra_networks = vec![];
        if let Some(routes) = &self.routes {
            for route in routes {
                if pv::eq_str(route.get("protocol"), "ra")
                    && !pv::eq_str(route.get("to"), "default")
                    && route
                        .get("family")
                        .is_some_and(|f| pv::eq(f, &Value::from(10)))
                {
                    let to = pv::index(&Value::Object(route.clone()), "to")?.clone();
                    ra_networks.push(ipaddress::ip_interface(&pv::to_str(&to))?.network());
                }
            }
        }
        let ds_addresses = self.data_sources.get("addresses");
        let ds_get = |key: &str| {
            ds_addresses
                .and_then(|m| m.get(key))
                .filter(|v| pv::truthy(v))
        };

        let mut addresses = vec![];
        for addr in pv::iterate(addr_info)? {
            let mut flags: Vec<Value> = vec![];
            let local = pv::index(&addr, "local")?;
            let local_str = pv::to_str(local);
            if ipaddress::ip_address(&local_str)?.is_link_local() {
                flags.push("link".into());
            }
            if pv::opt_truthy(pv::get(&addr, "dynamic")?) {
                flags.push("dynamic".into());
            }

            // Try to determine if the address was received via RA/DHCPv6
            let prefixlen = pv::index(&addr, "prefixlen")?;
            let ip_addr =
                ipaddress::ip_interface(&format!("{}/{}", local_str, pv::to_str(prefixlen)))?;
            let ip_addr_str = ip_addr.to_string();
            if !ip_addr.ip.is_v4() {
                if ra_networks.contains(&ip_addr.network()) {
                    flags.push("ra".into());
                }
                if let Some(ds) = ds_get(&ip_addr_str) {
                    if pv::eq_str(Some(ds), "DHCPv6") {
                        flags.push("dhcp".into());
                    }
                }
            }
            let has_dhcp = |flags: &Vec<Value>| flags.iter().any(|f| pv::eq_str(Some(f), "dhcp"));
            if let Some(ds) = ds_get(&ip_addr_str) {
                if pv::eq_str(Some(ds), "DHCPv4") && !has_dhcp(&flags) {
                    flags.push("dhcp".into());
                }
            }

            if let Some(routes) = &self.routes {
                if !routes.is_empty() && !has_dhcp(&flags) {
                    for route in routes {
                        if let Some(from) = route.get("from") {
                            let a = ipaddress::ip_address(&pv::to_str(from))?;
                            let b = ipaddress::ip_address(&local_str)?;
                            if a.eq_py(&b) {
                                let route_v = Value::Object(route.clone());
                                let proto = pv::index(&route_v, "protocol")?;
                                if pv::eq_str(Some(proto), "dhcp") && !has_dhcp(&flags) {
                                    flags.push("dhcp".into());
                                    break;
                                }
                            }
                        }
                    }
                }
            }
            let ip = pv::as_str(local, "lower")?.to_lowercase();
            let mut extra = Map::new();
            extra.insert("prefix".into(), prefixlen.clone());
            if !flags.is_empty() {
                extra.insert("flags".into(), Value::Array(flags));
            }
            let mut elem = Map::new();
            elem.insert(ip, Value::Object(extra));
            addresses.push(Value::Object(elem));
        }
        Ok(addresses)
    }

    pub fn query_nm_ssid(con_name: &str) -> Option<String> {
        match utils::nmcli_out(&[
            "--get-values",
            "802-11-wireless.ssid",
            "con",
            "show",
            "id",
            con_name,
        ]) {
            Ok(ssid) => Some(py_strip(&ssid).to_string()),
            Err(e) => {
                py::warning(&format!(
                    "Cannot query NetworkManager SSID for {}: {}",
                    con_name,
                    exc_str(&e)
                ));
                None
            }
        }
    }

    fn query_networkctl(ifname: &Value) -> Option<String> {
        let name = match ifname {
            Value::String(s) => s.clone(),
            v => {
                py::warning(&format!(
                    "Cannot query networkctl for {}: expected str, bytes or os.PathLike object, not {}",
                    pv::to_str(v),
                    pv::type_name(v)
                ));
                return None;
            }
        };
        match sub::check_output(&["networkctl", "status", "--", &name]) {
            Ok(out) => Some(out),
            Err(e) => {
                py::warning(&format!(
                    "Cannot query networkctl for {}: {}",
                    name,
                    exc_str(&e)
                ));
                None
            }
        }
    }

    pub fn json(&self) -> Result<(String, Map<String, Value>)> {
        let mut json = Map::new();
        json.insert("index".into(), self.idx.clone());
        json.insert("adminstate".into(), self.adminstate.clone().into());
        json.insert("operstate".into(), self.operstate.clone().into());
        if self.type_()?.is_some() {
            json.insert("type".into(), self.type_()?.into());
        }
        if self.ssid()?.is_some_and(|s| !s.is_empty()) {
            json.insert("ssid".into(), self.ssid()?.into());
        }
        if self.tunnel_mode()?.is_some_and(|s| !s.is_empty()) {
            json.insert("tunnel_mode".into(), self.tunnel_mode()?.into());
        }
        if self.backend()?.is_some() {
            json.insert("backend".into(), self.backend()?.into());
        }
        if self.netdef_id()?.is_some_and(|s| !s.is_empty()) {
            json.insert("id".into(), self.netdef_id()?.into());
        }
        if let Some(mac) = &self.macaddress {
            if !mac.is_empty() {
                json.insert("macaddress".into(), mac.clone().into());
            }
        }
        if let Some(vendor) = self.vendor()? {
            if !vendor.is_empty() {
                json.insert("vendor".into(), self.vendor()?.into());
            }
        }
        if let Some(a) = self.addresses.as_ref().filter(|a| !a.is_empty()) {
            json.insert("addresses".into(), Value::Array(a.clone()));
        }
        if let Some(a) = self.dns_addresses.as_ref().filter(|a| !a.is_empty()) {
            json.insert("dns_addresses".into(), a.clone().into());
        }
        if let Some(a) = self.dns_search.as_ref().filter(|a| !a.is_empty()) {
            json.insert("dns_search".into(), a.clone().into());
        }
        if let Some(r) = self.routes.as_ref().filter(|r| !r.is_empty()) {
            json.insert(
                "routes".into(),
                Value::Array(r.iter().map(|m| Value::Object(m.clone())).collect()),
            );
        }
        if self.activation_mode()?.is_some_and(|s| !s.is_empty()) {
            json.insert("activation_mode".into(), self.activation_mode()?.into());
        }
        for (key, val) in [
            ("bridge", &self.bridge),
            ("bond", &self.bond),
            ("vrf", &self.vrf),
        ] {
            if let Some(v) = val.as_ref().filter(|v| !v.is_empty()) {
                json.insert(key.into(), v.clone().into());
            }
        }
        if !self.members.is_empty() {
            json.insert("interfaces".into(), Value::Array(self.members.clone()));
        }
        Ok((self.name_str(), json))
    }

    pub fn up(&self) -> bool {
        self.adminstate == "UP" && self.operstate == "UP"
    }

    #[allow(dead_code)]
    pub fn down(&self) -> bool {
        self.adminstate == "DOWN" && self.operstate == "DOWN"
    }

    fn nd_get(&self, key: &str) -> Option<&Value> {
        self.nd.as_ref().and_then(|nd| nd.get(key))
    }

    /// `Interface.type` (logs a warning for unknown types on every call)
    pub fn type_(&self) -> Result<Option<&'static str>> {
        let nd_truthy = self.nd.as_ref().is_some_and(pv::truthy);
        let mut nd_type: Value = if nd_truthy {
            self.nd_get("Type").cloned().unwrap_or(Value::Null)
        } else {
            Value::Null
        };
        if pv::eq_str(Some(&nd_type), "none") {
            // If the Type is reported as 'none' by networkd, the interface still might have a Kind.
            nd_type = self.nd_get("Kind").cloned().unwrap_or(Value::Null);
        }
        if pv::eq_str(Some(&nd_type), "ether") {
            // There are different kinds of 'ether' devices, such as VRFs, veth and dummies
            if let Some(kind) = self.nd_get("Kind").filter(|k| pv::truthy(k)) {
                nd_type = kind.clone();
            }
        }
        if matches!(nd_type, Value::Array(_) | Value::Object(_)) {
            return Err(Exception::err(
                "TypeError",
                format!("unhashable type: '{}'", pv::type_name(&nd_type)),
            ));
        }
        if let Value::String(t) = &nd_type {
            if let Some(device_type) = device_type(t) {
                return Ok(Some(device_type));
            }
        }
        py::warning(&format!("Unknown device type: {}", pv::to_str(&nd_type)));
        Ok(None)
    }

    pub fn tunnel_mode(&self) -> Result<Option<String>> {
        if self.type_()? == Some("tunnel") {
            if let Some(t) = self.iproute_type.as_ref().filter(|t| !t.is_empty()) {
                return Ok(Some(t.clone()));
            }
        }
        Ok(None)
    }

    pub fn backend(&self) -> Result<Option<&'static str>> {
        if let Some(nd) = self.nd.as_ref().filter(|nd| pv::truthy(nd)) {
            let setup = pv::get(nd, "SetupState")?
                .cloned()
                .unwrap_or(Value::String(String::new()));
            if !pv::contains(&setup, "unmanaged")? {
                let file = pv::get(nd, "NetworkFile")?
                    .cloned()
                    .unwrap_or(Value::String(String::new()));
                if pv::contains(&file, "run/systemd/network/10-netplan-")? {
                    return Ok(Some("networkd"));
                }
            }
        }
        if let Some(nm) = &self.nm {
            if nm
                .filename
                .contains("run/NetworkManager/system-connections/netplan-")
            {
                return Ok(Some("NetworkManager"));
            }
        }
        Ok(None)
    }

    pub fn netdef_id(&self) -> Result<Option<String>> {
        match self.backend()? {
            Some("networkd") => {
                let file = self
                    .nd_get("NetworkFile")
                    .cloned()
                    .unwrap_or(Value::String(String::new()));
                let file = pv::as_str(&file, "split")?;
                let tail = file
                    .split("run/systemd/network/10-netplan-")
                    .nth(1)
                    .unwrap_or("");
                Ok(Some(
                    tail.split(".network").next().unwrap_or("").to_string(),
                ))
            }
            Some(_) => {
                let Some(nm) = &self.nm else { return Ok(None) };
                let tail = nm
                    .filename
                    .split("run/NetworkManager/system-connections/netplan-")
                    .nth(1)
                    .unwrap_or("");
                let mut netdef = tail.split(".nmconnection").next().unwrap_or("").to_string();
                if nm.type_ == "802-11-wireless" {
                    let Some(mut ssid) = Self::query_nm_ssid(&nm.name) else {
                        return Err(Exception::err(
                            "TypeError",
                            "'in <string>' requires string as left operand, not NoneType",
                        ));
                    };
                    if !netdef.contains(&ssid) {
                        // Transform the SSID to the same format used by Network Manager
                        // and escape it like g_uri_escape_string() in src/nm.c
                        // (urllib.parse.quote: ';' becomes %3B).
                        let parts: Vec<String> =
                            ssid.as_bytes().iter().map(|b| b.to_string()).collect();
                        ssid = format!("{};", parts.join(";")).replace(';', "%3B");
                    }
                    if !ssid.is_empty() {
                        netdef = netdef
                            .split(&format!("-{ssid}"))
                            .next()
                            .unwrap_or("")
                            .to_string();
                    }
                }
                Ok(Some(netdef))
            }
            None => Ok(None),
        }
    }

    pub fn vendor(&self) -> Result<Option<String>> {
        if let Some(v) = self.nd_get("Vendor") {
            if self.nd.as_ref().is_some_and(pv::truthy) && pv::truthy(v) {
                return Ok(Some(py_strip(pv::as_str(v, "strip")?).to_string()));
            }
        }
        Ok(None)
    }

    pub fn ssid(&self) -> Result<Option<String>> {
        if self.type_()? == Some("wifi") {
            if self.backend()? == Some("NetworkManager") {
                let name = self.nm.as_ref().map(|n| n.name.clone()).unwrap_or_default();
                return Ok(Self::query_nm_ssid(&name));
            }
            for line in utils::py_splitlines(&self.networkctl) {
                let line = py_strip(line);
                if let Some(ssid) = match_wifi_ap(line) {
                    let ssid = decode_networkctl_ssid(&ssid)?;
                    return Ok(if ssid.is_empty() { None } else { Some(ssid) });
                }
            }
        }
        Ok(None)
    }

    pub fn activation_mode(&self) -> Result<Option<String>> {
        match self.backend()? {
            Some("networkd") => {
                for line in utils::py_splitlines(&self.networkctl) {
                    let line = py_strip(line);
                    if let Some(rest) = line.strip_prefix("Activation Policy: ") {
                        let mode = py_strip(rest);
                        return Ok(if mode != "up" {
                            Some(mode.to_string())
                        } else {
                            None
                        });
                    }
                }
                Ok(None)
            }
            Some(_) => {
                let manual = self.nm.as_ref().is_some_and(|nm| nm.autoconnect == "no");
                Ok(if manual { Some("manual".into()) } else { None })
            }
            None => Ok(None),
        }
    }

    fn find_data_sources(data: &Value) -> Result<Map<String, Value>> {
        let mut sources = Map::new();
        let packed = |v: &Value| -> Result<ipaddress::Interface> {
            let mut bytes = vec![];
            for b in pv::iterate(v)? {
                let b = pv::to_int(&b)?;
                if !(0..=255).contains(&b) {
                    return Err(Exception::err(
                        "ValueError",
                        "bytes must be in range(0, 256)",
                    ));
                }
                bytes.push(b as u8);
            }
            ipaddress::ip_interface_packed(&bytes)
        };

        // DNS nameservers
        if let Some(addresses) = pv::get(data, "DNS")?.filter(|v| pv::truthy(v)) {
            let mut dns = Map::new();
            for item in pv::iterate(addresses)? {
                let addr = packed(pv::index(&item, "Address")?)?;
                let source = pv::index(&item, "ConfigSource")?.clone();
                dns.insert(addr.ip().to_string(), source);
            }
            sources.insert("dns".into(), Value::Object(dns));
        }

        // DNS search domains
        if let Some(domains) = pv::get(data, "SearchDomains")?.filter(|v| pv::truthy(v)) {
            let mut search = Map::new();
            for item in pv::iterate(domains)? {
                let domain = pv::to_str(pv::index(&item, "Domain")?);
                let source = pv::index(&item, "ConfigSource")?.clone();
                search.insert(domain, source);
            }
            sources.insert("search".into(), Value::Object(search));
        }

        // IP addresses
        if let Some(addresses) = pv::get(data, "Addresses")?.filter(|v| pv::truthy(v)) {
            let mut addrs = Map::new();
            for item in pv::iterate(addresses)? {
                let addr = packed(pv::index(&item, "Address")?)?;
                let prefix = pv::to_str(pv::index(&item, "PrefixLength")?);
                let full = ipaddress::ip_interface(&format!("{}/{}", addr.ip(), prefix))?;
                let source = pv::index(&item, "ConfigSource")?.clone();
                addrs.insert(full.to_string(), source);
            }
            sources.insert("addresses".into(), Value::Object(addrs));
        }
        Ok(sources)
    }
}

/// `re.match(r'^Wi-?Fi access point: (.*) \(.*\)', line).group(1)`
fn match_wifi_ap(line: &str) -> Option<String> {
    let rest = line
        .strip_prefix("WiFi access point: ")
        .or_else(|| line.strip_prefix("Wi-Fi access point: "))?;
    let chars: Vec<char> = rest.chars().collect();
    // greedy (.*): the last " (" that is followed by a ")" somewhere after it
    (0..chars.len().saturating_sub(1))
        .rev()
        .find(|&i| chars[i] == ' ' && chars[i + 1] == '(' && chars[i + 2..].contains(&')'))
        .map(|i| chars[..i].iter().collect())
}

/// `ssid.encode('latin1').decode('unicode-escape').encode('latin1').decode('utf-8')`
fn decode_networkctl_ssid(ssid: &str) -> Result<String> {
    let codec = |what: &str| Exception::err("UnicodeError", format!("cannot {what} SSID"));
    let mut bytes = vec![];
    for c in ssid.chars() {
        if (c as u32) > 0xff {
            return Err(codec("latin1-encode"));
        }
        bytes.push(c as u8);
    }
    // unicode-escape decoding (latin-1 for the non-escaped bytes)
    let mut out: Vec<char> = vec![];
    let mut i = 0;
    while i < bytes.len() {
        let b = bytes[i];
        if b != b'\\' {
            out.push(b as char);
            i += 1;
            continue;
        }
        let Some(&e) = bytes.get(i + 1) else {
            return Err(codec("unicode-escape decode"));
        };
        i += 2;
        let hex = |n: usize, i: usize| -> Option<u32> {
            let s = std::str::from_utf8(bytes.get(i..i + n)?).ok()?;
            if s.chars().all(|c| c.is_ascii_hexdigit()) {
                u32::from_str_radix(s, 16).ok()
            } else {
                None
            }
        };
        match e {
            b'\n' => {}
            b'\\' => out.push('\\'),
            b'\'' => out.push('\''),
            b'"' => out.push('"'),
            b'a' => out.push('\x07'),
            b'b' => out.push('\x08'),
            b'f' => out.push('\x0c'),
            b'n' => out.push('\n'),
            b'r' => out.push('\r'),
            b't' => out.push('\t'),
            b'v' => out.push('\x0b'),
            b'0'..=b'7' => {
                let mut v = (e - b'0') as u32;
                for _ in 0..2 {
                    match bytes.get(i) {
                        Some(&d @ b'0'..=b'7') => {
                            v = v * 8 + (d - b'0') as u32;
                            i += 1;
                        }
                        _ => break,
                    }
                }
                out.push(char::from_u32(v).ok_or_else(|| codec("unicode-escape decode"))?);
            }
            b'x' | b'u' | b'U' => {
                let n = match e {
                    b'x' => 2,
                    b'u' => 4,
                    _ => 8,
                };
                let v = hex(n, i).ok_or_else(|| codec("unicode-escape decode"))?;
                i += n;
                out.push(char::from_u32(v).ok_or_else(|| codec("unicode-escape decode"))?);
            }
            other => {
                out.push('\\');
                out.push(other as char);
            }
        }
    }
    let mut latin1 = vec![];
    for c in out {
        if (c as u32) > 0xff {
            return Err(codec("latin1-encode"));
        }
        latin1.push(c as u8);
    }
    String::from_utf8(latin1).map_err(|_| codec("utf-8 decode"))
}

/// Route table names, as `utils.route_table_lookup()` returns them.
#[derive(Clone, Default)]
pub struct RouteTables {
    pub by_num: HashMap<i64, String>,
    pub by_name: HashMap<String, i64>,
}

impl RouteTables {
    pub fn is_empty(&self) -> bool {
        self.by_num.is_empty() && self.by_name.is_empty()
    }
}

/// `utils.route_table_lookup()`
pub fn route_table_lookup() -> RouteTables {
    const NEW: &str = "/usr/share/iproute2/rt_tables";
    const OLD: &str = "/etc/iproute2/rt_tables";
    let path = if std::path::Path::new(NEW).exists() {
        NEW
    } else {
        OLD
    };
    let mut t = RouteTables::default();
    match utils::read_text(path) {
        Ok(content) => {
            for line in content.split_inclusive('\n') {
                let split = py_split(line);
                if split.len() == 2
                    && split[0].chars().all(|c| c.is_ascii_digit())
                    && !split[0].is_empty()
                {
                    if let Ok(n) = split[0].parse::<i64>() {
                        t.by_num.insert(n, split[1].to_string());
                        t.by_name.insert(split[1].to_string(), n);
                    }
                }
            }
            t
        }
        Err(_) => {
            py::debug(&format!("Cannot open '{path}' for reading"));
            // defaults to the standard content found in the file
            for (n, name) in [
                (0, "unspec"),
                (253, "default"),
                (254, "main"),
                (255, "local"),
            ] {
                t.by_num.insert(n, name.into());
                t.by_name.insert(name.into(), n);
            }
            t
        }
    }
}

pub struct SystemConfigState {
    pub interface_list: Vec<Interface>,
    state: Map<String, Value>,
}

impl SystemConfigState {
    pub fn new(ifname: Option<&str>, all: bool) -> Result<SystemConfigState> {
        // Make sure sd-networkd is running, as we need the data it provides.
        if !utils::systemctl_is_active("systemd-networkd.service")? {
            if utils::systemctl_is_masked("systemd-networkd.service")? {
                py::error(
                    "'netplan status' depends on networkd, but systemd-networkd.service is masked. Please start it.",
                );
                return py::exit(1);
            }
            if !utils::systemctl_is_installed("systemd-networkd.service")? {
                py::error("systemd-networkd is required for 'netplan status' functionality");
                return py::exit(1);
            }
            py::debug("systemd-networkd.service is not active. Starting...");
            utils::systemctl("start", &["systemd-networkd.service"], true)?;
        }

        // required data: iproute2 and sd-networkd can be expected to exist,
        // due to hard package dependencies
        let iproute2 = Self::query_iproute2();
        let networkd = Self::query_networkd();
        if !iproute2.as_ref().is_some_and(pv::truthy) || !networkd.as_ref().is_some_and(pv::truthy)
        {
            py::error("Could not query iproute2 or systemd-networkd");
            return py::exit(1);
        }
        let (iproute2, networkd) = (
            iproute2.unwrap_or(Value::Null),
            networkd.unwrap_or(Value::Null),
        );

        // optional data
        let nmcli = Self::query_nm().unwrap_or_default();
        let (route4, route6) = Self::query_routes()?;
        let (dns_addresses, dns_search) = Self::query_resolved();

        let mut interface_list = vec![];
        for itf in pv::iterate(&iproute2)? {
            interface_list.push(Interface::new(
                &itf,
                &networkd,
                &nmcli,
                (&dns_addresses, &dns_search),
                (&route4, &route6),
            )?);
        }

        // get bridge/bond/vrf data
        Self::correlate_members_and_uplink(&mut interface_list)?;

        // show only active interfaces by default
        let mut filtered: Vec<usize> = (0..interface_list.len())
            .filter(|&i| interface_list[i].operstate != "DOWN")
            .collect();
        // down interfaces do not contribute anything to the online state
        let online_state = Self::query_online_state(filtered.iter().map(|&i| &interface_list[i]));
        // show only a single interface, if requested
        let ifname = ifname.filter(|n| !n.is_empty());
        if let Some(name) = ifname {
            filtered = interface_list
                .iter()
                .position(|itf| matches!(&itf.name, Value::String(n) if n == name))
                .into_iter()
                .collect();
            if filtered.is_empty() {
                py::error(&format!("Could not find interface {name}"));
                return py::exit(1);
            }
        }

        // Global state
        let mut state = Map::new();
        state.insert(
            "netplan-global-state".into(),
            pv::obj(vec![
                ("online", Value::Bool(online_state)),
                ("nameservers", Self::resolvconf_json()),
            ]),
        );
        // Per interface
        let itf_iter: Vec<usize> = if all {
            (0..interface_list.len()).collect()
        } else {
            filtered
        };
        for i in itf_iter {
            let (name, obj) = interface_list[i].json()?;
            state.insert(name, Value::Object(obj));
        }
        Ok(SystemConfigState {
            interface_list,
            state,
        })
    }

    pub fn resolvconf_json() -> Value {
        let mut addresses: Vec<Value> = vec![];
        let mut search: Vec<Value> = vec![];
        let mut mode = Value::Null;
        match std::fs::read("/etc/resolv.conf") {
            Err(e) => py::warning(&format!(
                "Cannot parse /etc/resolv.conf: {}",
                utils::py_oserror_str(&e, std::path::Path::new("/etc/resolv.conf"))
            )),
            Ok(bytes) => match String::from_utf8(bytes) {
                Err(e) => {
                    let pos = e.utf8_error().valid_up_to();
                    let byte = e.as_bytes()[pos];
                    py::warning(&format!(
                        "Cannot parse /etc/resolv.conf: 'utf-8' codec can't decode byte 0x{byte:02x} in position {pos}: invalid start byte"
                    ));
                }
                Ok(content) => {
                    let content = content.replace("\r\n", "\n").replace('\r', "\n");
                    let lines: Vec<&str> = content.split_inclusive('\n').collect();
                    // check first line for systemd-resolved stub or compat modes
                    let firstline = lines.first().copied().unwrap_or("");
                    if firstline.contains("# This is /run/systemd/resolve/stub-resolv.conf") {
                        mode = "stub".into();
                    } else if firstline.contains("# This is /run/systemd/resolve/resolv.conf") {
                        mode = "compat".into();
                    }
                    for line in lines {
                        if line.starts_with("nameserver") {
                            addresses.extend(py_split(line).into_iter().skip(1).map(Value::from));
                        }
                        if line.starts_with("search") {
                            search = py_split(line)
                                .into_iter()
                                .skip(1)
                                .map(Value::from)
                                .collect();
                        }
                    }
                }
            },
        }
        pv::obj(vec![
            ("addresses", Value::Array(addresses)),
            ("search", Value::Array(search)),
            ("mode", mode),
        ])
    }

    fn query_online_state<'a>(interfaces: impl Iterator<Item = &'a Interface>) -> bool {
        // TODO: fully implement network-online.target specification (FO020):
        // https://discourse.ubuntu.com/t/spec-definition-of-an-online-system/27838
        for itf in interfaces {
            let (Some(addresses), Some(routes), Some(dns)) =
                (&itf.addresses, &itf.routes, &itf.dns_addresses)
            else {
                continue;
            };
            if itf.up() && !addresses.is_empty() && !routes.is_empty() && !dns.is_empty() {
                let mut non_local_ips = 0;
                for addr in addresses {
                    if let Some((_, extra)) = addr.as_object().and_then(|m| m.iter().next()) {
                        let link = extra
                            .get("flags")
                            .is_some_and(|f| pv::contains(f, "link").unwrap_or(false));
                        if !link {
                            non_local_ips += 1;
                        }
                    }
                }
                let default_routes = routes
                    .iter()
                    .filter(|x| pv::eq_str(x.get("to"), "default"))
                    .count();
                if non_local_ips > 0 && default_routes > 0 {
                    return true;
                }
            }
        }
        false
    }

    fn query_iproute2() -> Option<Value> {
        let res = sub::check_output(&["ip", "-d", "-j", "addr"]).and_then(|out| {
            pyjson::loads(&out).map_err(|m| Exception::err("json.JSONDecodeError", m))
        });
        match res {
            Ok(v) => Some(v),
            Err(e) => {
                py::critical(&format!(
                    "Cannot query iproute2 interface data: {}",
                    exc_str(&e)
                ));
                None
            }
        }
    }

    fn query_networkd() -> Option<Value> {
        let res = sub::check_output(&["networkctl", "--json=short"])
            .and_then(|out| {
                pyjson::loads(&out).map_err(|m| Exception::err("json.JSONDecodeError", m))
            })
            .and_then(|v| pv::index(&v, "Interfaces").cloned());
        match res {
            Ok(v) => Some(v),
            Err(e) => {
                py::critical(&format!(
                    "Cannot query networkd interface data: {}",
                    exc_str(&e)
                ));
                None
            }
        }
    }

    fn process_nm(output: &str) -> Result<Vec<NmConnection>> {
        let mut data = vec![];
        for line in utils::py_splitlines(output) {
            let split: Vec<&str> = line.split(':').collect();
            if !split[0].is_empty() {
                // ignore inactive connection profiles
                let get = |i: usize| -> Result<String> {
                    split
                        .get(i)
                        .map(|s| s.to_string())
                        .ok_or_else(|| Exception::err("IndexError", "list index out of range"))
                };
                data.push(NmConnection {
                    device: get(0)?,
                    name: get(1)?,
                    uuid: get(2)?,
                    filename: get(3)?,
                    type_: get(4)?,
                    autoconnect: get(5)?,
                });
            }
        }
        Ok(data)
    }

    fn query_nm() -> Option<Vec<NmConnection>> {
        let res = utils::nmcli_out(&[
            "-t",
            "-f",
            "DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT",
            "con",
            "show",
        ])
        .and_then(|out| Self::process_nm(&out));
        match res {
            Ok(v) => Some(v),
            Err(e) => {
                py::debug(&format!(
                    "Cannot query NetworkManager interface data: {}",
                    exc_str(&e)
                ));
                None
            }
        }
    }

    fn query_routes() -> Result<(Option<Value>, Option<Value>)> {
        let mut data4 = None;
        let mut data6 = None;
        let res = (|| -> Result<()> {
            let out4 =
                sub::check_output(&["ip", "-d", "-j", "-4", "route", "show", "table", "all"])?;
            data4 =
                Some(pyjson::loads(&out4).map_err(|m| Exception::err("json.JSONDecodeError", m))?);
            let out6 =
                sub::check_output(&["ip", "-d", "-j", "-6", "route", "show", "table", "all"])?;
            data6 =
                Some(pyjson::loads(&out6).map_err(|m| Exception::err("json.JSONDecodeError", m))?);
            Ok(())
        })();
        if let Err(e) = res {
            py::debug(&format!(
                "Cannot query iproute2 route data: {}",
                exc_str(&e)
            ));
        }

        // Add the address family to the data
        // IPv4: 2, IPv6: 10
        for (data, family) in [(&mut data4, 2), (&mut data6, 10)] {
            if let Some(d) = data.as_mut().filter(|d| pv::truthy(d)) {
                match d {
                    Value::Array(routes) => {
                        for route in routes.iter_mut() {
                            match route {
                                Value::Object(m) => {
                                    m.insert("family".into(), Value::from(family));
                                }
                                v => {
                                    return Err(Exception::err(
                                        "AttributeError",
                                        format!(
                                            "'{}' object has no attribute 'update'",
                                            pv::type_name(v)
                                        ),
                                    ))
                                }
                            }
                        }
                    }
                    Value::Object(_) | Value::String(_) => {
                        return Err(Exception::err(
                            "AttributeError",
                            "'str' object has no attribute 'update'",
                        ))
                    }
                    v => {
                        return Err(Exception::err(
                            "TypeError",
                            format!("'{}' object is not iterable", pv::type_name(v)),
                        ))
                    }
                }
            }
        }
        Ok((data4, data6))
    }

    fn query_resolved() -> (Option<Value>, Option<Value>) {
        let mut addresses = None;
        let mut search = None;
        let res = (|| -> Result<()> {
            let Some(busctl) = utils::which("busctl") else {
                return Err(Exception::err("RuntimeError", "missing busctl utility"));
            };
            let busctl = busctl.to_string_lossy().into_owned();
            let json_out = sub::check_output(&[
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
            ])?;
            let res =
                pyjson::loads(&json_out).map_err(|m| Exception::err("json.JSONDecodeError", m))?;
            let data_list = pv::get(&res, "data")?
                .cloned()
                .unwrap_or(Value::Array(vec![pv::obj(vec![])]));
            let data = match &data_list {
                Value::Array(items) => items
                    .first()
                    .cloned()
                    .ok_or_else(|| Exception::err("IndexError", "list index out of range"))?,
                Value::Object(_) => return Err(Exception::err("KeyError", "0")),
                v => {
                    return Err(Exception::err(
                        "TypeError",
                        format!("'{}' object is not subscriptable", pv::type_name(v)),
                    ))
                }
            };
            let empty = pv::obj(vec![]);
            let dns = pv::get(&data, "DNS")?.unwrap_or(&empty);
            // make sure the type doesn't change. We expect an array of two
            // intergers and an array of bytes (IP address)
            if !pv::eq_str(pv::get(dns, "type")?, "a(iiay)") {
                return Err(Exception::err(
                    "AssertionError",
                    "DNS address type doesn't match",
                ));
            }
            addresses = pv::get(dns, "data")?.cloned();
            let domains = pv::get(&data, "Domains")?.unwrap_or(&empty);
            // make sure the type dosn't change. We expect an array of an integer
            // a string (DNS search domain) and a boolean
            if !pv::eq_str(pv::get(domains, "type")?, "a(isb)") {
                return Err(Exception::err(
                    "AssertionError",
                    "DNS search type doesn't match",
                ));
            }
            search = pv::get(domains, "data")?.cloned();
            Ok(())
        })();
        if let Err(e) = res {
            py::debug(&format!("Cannot query resolved DNS data: {}", exc_str(&e)));
        }
        (addresses, search)
    }

    /// Return a list containing the interfaces that are members of a bond/bridge/vrf
    fn query_members(ifname: &str) -> Result<Vec<Value>> {
        let output = match sub::check_output(&["ip", "-d", "-j", "link", "show", "master", ifname])
        {
            Ok(o) => o,
            Err(e) => {
                py::warning(&format!("Cannot query bridge: {}", exc_str(&e)));
                return Ok(vec![]);
            }
        };
        let output_json = pyjson::loads(&output)
            .map_err(|m| Exception::err("json.decoder.JSONDecodeError", m))?;
        let mut members = vec![];
        for member in pv::iterate(&output_json)? {
            members.push(pv::get(&member, "ifname")?.cloned().unwrap_or(Value::Null));
        }
        Ok(members)
    }

    /// Associate interfaces with their members and parent interfaces.
    fn correlate_members_and_uplink(interfaces: &mut [Interface]) -> Result<()> {
        const UPLINK_TYPES: [&str; 3] = ["bond", "bridge", "vrf"];
        let is_uplink = |t: Option<&str>| t.is_some_and(|t| UPLINK_TYPES.contains(&t));
        let mut members_to_uplink: Vec<(Value, (Value, Option<&'static str>))> = vec![];
        let mut uplink_to_members: Vec<(Value, Vec<Value>)> = vec![];
        for interface in interfaces.iter() {
            let t = interface.type_()?;
            if !is_uplink(t) {
                continue;
            }
            let members = match &interface.name {
                Value::String(n) => Self::query_members(n)?,
                v => Self::query_members(&pv::to_str(v))?,
            };
            for member in &members {
                let entry = (interface.name.clone(), t);
                match members_to_uplink.iter_mut().find(|(k, _)| k == member) {
                    Some(e) => e.1 = entry,
                    None => members_to_uplink.push((member.clone(), entry)),
                }
            }
            match uplink_to_members
                .iter_mut()
                .find(|(k, _)| *k == interface.name)
            {
                Some(e) => e.1 = members,
                None => uplink_to_members.push((interface.name.clone(), members)),
            }
        }

        for interface in interfaces.iter_mut() {
            if let Some((_, (uplink_name, uplink_type))) =
                members_to_uplink.iter().find(|(k, _)| *k == interface.name)
            {
                let name = Some(pv::to_str(uplink_name));
                match *uplink_type {
                    Some("bridge") => interface.bridge = name,
                    Some("bond") => interface.bond = name,
                    Some("vrf") => interface.vrf = name,
                    _ => {}
                }
            }
            if is_uplink(interface.type_()?) {
                if let Some((_, members)) =
                    uplink_to_members.iter().find(|(k, _)| *k == interface.name)
                {
                    if !members.is_empty() {
                        interface.members = members.clone();
                    }
                }
            }
        }
        Ok(())
    }

    pub fn number_of_interfaces(&self) -> usize {
        self.interface_list.len()
    }

    pub fn get_data(&self) -> &Map<String, Value> {
        &self.state
    }
}

/// The parts of a `netplan.NetDefinition` that the diff uses.
pub struct NetdefInfo {
    pub type_: &'static str,
    pub dhcp4: bool,
    pub dhcp6: bool,
    pub link_local: Vec<String>,
    pub accept_ra: Option<bool>,
    pub addresses: Vec<netplan::NetplanAddress>,
    pub nameserver_addresses: Vec<String>,
    pub nameserver_search: Vec<String>,
    pub routes: Vec<netplan::RawRoute>,
    pub gateway4: Option<String>,
    pub gateway6: Option<String>,
    pub macaddress: Option<String>,
    pub bridge: Option<String>,
    pub bond: Option<String>,
    pub vrf: Option<String>,
}

/// Collects the Netplan's network configuration
pub struct NetplanConfigState {
    pub netdefs: Vec<(String, NetdefInfo)>,
}

impl NetplanConfigState {
    pub fn new(rootdir: Option<&str>) -> Result<NetplanConfigState> {
        let mut parser = netplan::Parser::new()?;
        parser.load_yaml_hierarchy(rootdir.filter(|r| !r.is_empty()).unwrap_or("/"))?;
        let mut np_state = netplan::State::new()?;
        np_state.import_parser_results(&mut parser)?;
        let mut netdefs: Vec<(String, NetdefInfo)> = vec![];
        for nd in np_state.netdefs() {
            let mut link_local = vec![];
            if nd.link_local_ipv4() {
                link_local.push("ipv4".to_string());
            }
            if nd.link_local_ipv6() {
                link_local.push("ipv6".to_string());
            }
            let info = NetdefInfo {
                type_: nd.type_name(),
                dhcp4: nd.dhcp4(),
                dhcp6: nd.dhcp6(),
                link_local,
                accept_ra: nd.accept_ra(),
                addresses: nd.addresses(),
                nameserver_addresses: nd.nameserver_addresses(),
                nameserver_search: nd.nameserver_search(),
                routes: nd.routes(),
                gateway4: nd.gateway4()?,
                gateway6: nd.gateway6()?,
                macaddress: nd.macaddress()?,
                bridge: nd.bridge_link_id()?,
                bond: nd.bond_link_id()?,
                vrf: nd.vrf_link_id()?,
            };
            let id = nd.id()?;
            match netdefs.iter_mut().find(|(k, _)| *k == id) {
                Some(e) => e.1 = info,
                None => netdefs.push((id, info)),
            }
        }
        // np_state._dump_yaml(output_file=self.state)
        np_state.dump_yaml()?;
        Ok(NetplanConfigState { netdefs })
    }

    pub fn get(&self, id: &str) -> Option<&NetdefInfo> {
        self.netdefs.iter().find(|(k, _)| k == id).map(|(_, v)| v)
    }
}
