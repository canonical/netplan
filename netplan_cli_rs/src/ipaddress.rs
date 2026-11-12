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

//! The parts of Python's `ipaddress` module that `netplan status` uses:
//! `ip_address()`, `ip_interface()` (also from packed bytes), their string
//! forms, `.network`, `.with_prefixlen`, `.is_link_local`, `.is_loopback`.
//! Parsing follows CPython's rules (no leading zeros in IPv4 octets, at most
//! one "::", optional "%scope" for IPv6, IPv4 netmask prefixes).

use std::fmt;

use anyhow::Result;

use crate::py::Exception;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Address {
    V4(u32),
    V6(u128, Option<String>),
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Network {
    v6: bool,
    addr: u128,
    prefixlen: u32,
}

#[derive(Clone, Debug)]
pub struct Interface {
    pub ip: Address,
    pub prefixlen: u32,
}

fn value_error(msg: String) -> anyhow::Error {
    Exception::err("ValueError", msg)
}

fn parse_v4(s: &str) -> Option<u32> {
    let parts: Vec<&str> = s.split('.').collect();
    if parts.len() != 4 {
        return None;
    }
    let mut out = 0u32;
    for p in parts {
        if p.is_empty() || p.len() > 3 || !p.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        if p.len() > 1 && p.starts_with('0') {
            return None;
        }
        let v: u32 = p.parse().ok()?;
        if v > 255 {
            return None;
        }
        out = (out << 8) | v;
    }
    Some(out)
}

fn parse_hextet(h: &str) -> Option<u128> {
    if h.is_empty() || h.len() > 4 || !h.bytes().all(|b| b.is_ascii_hexdigit()) {
        return None;
    }
    u128::from_str_radix(h, 16).ok()
}

/// `_BaseV6._ip_int_from_string`
fn parse_v6_int(s: &str) -> Option<u128> {
    if s.is_empty() {
        return None;
    }
    let mut parts: Vec<String> = s.split(':').map(String::from).collect();
    if parts.len() < 3 {
        return None;
    }
    if parts.last().is_some_and(|p| p.contains('.')) {
        let v4 = parse_v4(&parts.pop()?)?;
        parts.push(format!("{:x}", (v4 >> 16) & 0xffff));
        parts.push(format!("{:x}", v4 & 0xffff));
    }
    if parts.len() > 9 {
        return None;
    }
    let mut skip_index = None;
    for (i, p) in parts.iter().enumerate().take(parts.len() - 1).skip(1) {
        if p.is_empty() {
            if skip_index.is_some() {
                return None;
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
                return None;
            }
        }
        if parts[parts.len() - 1].is_empty() {
            lo -= 1;
            if lo != 0 {
                return None;
            }
        }
        let skipped = 8i32 - (hi + lo) as i32;
        if skipped < 1 {
            return None;
        }
        (parts_hi, parts_lo, parts_skipped) = (hi, lo, skipped as u32);
    } else {
        if parts.len() != 8 || parts[0].is_empty() || parts[7].is_empty() {
            return None;
        }
        (parts_hi, parts_lo, parts_skipped) = (parts.len(), 0, 0);
    }
    let mut ip: u128 = 0;
    for p in &parts[..parts_hi] {
        ip = (ip << 16) | parse_hextet(p)?;
    }
    if parts_skipped > 0 {
        ip = ip.checked_shl(16 * parts_skipped).unwrap_or(0);
    }
    for p in &parts[parts.len() - parts_lo..] {
        ip = (ip << 16) | parse_hextet(p)?;
    }
    Some(ip)
}

fn parse_v6(s: &str) -> Option<(u128, Option<String>)> {
    let (addr, scope) = match s.split_once('%') {
        None => (s, None),
        Some((a, sc)) => {
            if sc.is_empty() || sc.contains('%') {
                return None;
            }
            (a, Some(sc.to_string()))
        }
    };
    Some((parse_v6_int(addr)?, scope))
}

/// `_BaseV6._string_from_ip_int`
fn v6_hex_string(ip: u128) -> String {
    let hextets: Vec<String> = (0..8)
        .map(|i| format!("{:x}", (ip >> (112 - 16 * i)) & 0xffff))
        .collect();
    let (mut best_start, mut best_len) = (None, 0);
    let (mut start, mut len) = (None, 0);
    for (i, h) in hextets.iter().enumerate() {
        if h == "0" {
            len += 1;
            if start.is_none() {
                start = Some(i);
            }
            if len > best_len {
                best_len = len;
                best_start = start;
            }
        } else {
            len = 0;
            start = None;
        }
    }
    if best_len > 1 {
        let s = best_start.unwrap_or(0);
        let e = s + best_len;
        let mut out: Vec<String> = hextets[..s].to_vec();
        out.push(String::new());
        out.extend_from_slice(&hextets[e..]);
        if e == 8 {
            out.push(String::new());
        }
        if s == 0 {
            out.insert(0, String::new());
        }
        out.join(":")
    } else {
        hextets.join(":")
    }
}

fn v4_string(ip: u32) -> String {
    let b = ip.to_be_bytes();
    format!("{}.{}.{}.{}", b[0], b[1], b[2], b[3])
}

impl fmt::Display for Address {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Address::V4(ip) => f.write_str(&v4_string(*ip)),
            Address::V6(ip, scope) => {
                let s = if (ip >> 32) == 0xffff {
                    format!("{}:{}", v6_hex_string(ip >> 32), v4_string(*ip as u32))
                } else {
                    v6_hex_string(*ip)
                };
                match scope {
                    Some(sc) => write!(f, "{s}%{sc}"),
                    None => f.write_str(&s),
                }
            }
        }
    }
}

impl Address {
    pub fn is_v4(&self) -> bool {
        matches!(self, Address::V4(_))
    }

    fn ipv4_mapped(&self) -> Option<u32> {
        match self {
            Address::V6(ip, _) if (ip >> 32) == 0xffff => Some(*ip as u32),
            _ => None,
        }
    }

    pub fn is_link_local(&self) -> bool {
        if let Some(v4) = self.ipv4_mapped() {
            return Address::V4(v4).is_link_local();
        }
        match self {
            Address::V4(ip) => ip >> 16 == 0xa9fe,
            Address::V6(ip, _) => ip >> 118 == 0xfe80 >> 6,
        }
    }

    pub fn is_loopback(&self) -> bool {
        if let Some(v4) = self.ipv4_mapped() {
            return Address::V4(v4).is_loopback();
        }
        match self {
            Address::V4(ip) => ip >> 24 == 127,
            Address::V6(ip, _) => *ip == 1,
        }
    }

    /// Value comparison as `==` between two address objects (the scope id
    /// counts for IPv6).
    pub fn eq_py(&self, other: &Address) -> bool {
        self == other
    }
}

/// `ipaddress.ip_address(s)`
pub fn ip_address(s: &str) -> Result<Address> {
    if let Some(v4) = parse_v4(s) {
        return Ok(Address::V4(v4));
    }
    if let Some((v6, scope)) = parse_v6(s) {
        return Ok(Address::V6(v6, scope));
    }
    Err(value_error(format!(
        "{} does not appear to be an IPv4 or IPv6 address",
        crate::utils::py_repr_str(s)
    )))
}

fn v4_prefix(p: &str) -> Option<u32> {
    if p.is_ascii() && !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()) {
        let n: u32 = p.parse().ok()?;
        return (n <= 32).then_some(n);
    }
    // netmask or hostmask
    let ip = parse_v4(p)?;
    let check = |m: u32| {
        let n = m.leading_ones();
        (m.checked_shl(n).unwrap_or(0) == 0).then_some(n)
    };
    check(ip).or_else(|| check(!ip))
}

fn v6_prefix(p: &str) -> Option<u32> {
    if p.is_ascii() && !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()) {
        let n: u32 = p.parse().ok()?;
        return (n <= 128).then_some(n);
    }
    None
}

/// `ipaddress.ip_interface(s)`
pub fn ip_interface(s: &str) -> Result<Interface> {
    let parts: Vec<&str> = s.split('/').collect();
    if parts.len() <= 2 {
        if let Some(v4) = parse_v4(parts[0]) {
            let prefix = match parts.get(1) {
                None => Some(32),
                Some(p) => v4_prefix(p),
            };
            if let Some(prefixlen) = prefix {
                return Ok(Interface {
                    ip: Address::V4(v4),
                    prefixlen,
                });
            }
        }
        if let Some((v6, scope)) = parse_v6(parts[0]) {
            let prefix = match parts.get(1) {
                None => Some(128),
                Some(p) => v6_prefix(p),
            };
            if let Some(prefixlen) = prefix {
                return Ok(Interface {
                    ip: Address::V6(v6, scope),
                    prefixlen,
                });
            }
        }
    }
    Err(value_error(format!(
        "{} does not appear to be an IPv4 or IPv6 interface",
        crate::utils::py_repr_str(s)
    )))
}

/// `ipaddress.ip_interface(bytes(data))`
pub fn ip_interface_packed(data: &[u8]) -> Result<Interface> {
    match data.len() {
        4 => Ok(Interface {
            ip: Address::V4(u32::from_be_bytes(data.try_into().unwrap_or_default())),
            prefixlen: 32,
        }),
        16 => Ok(Interface {
            ip: Address::V6(
                u128::from_be_bytes(data.try_into().unwrap_or_default()),
                None,
            ),
            prefixlen: 128,
        }),
        _ => Err(value_error(format!(
            "{:?} does not appear to be an IPv4 or IPv6 interface",
            data
        ))),
    }
}

impl Interface {
    /// `.ip`: the address without the scope id
    pub fn ip(&self) -> Address {
        match &self.ip {
            Address::V4(ip) => Address::V4(*ip),
            Address::V6(ip, _) => Address::V6(*ip, None),
        }
    }

    pub fn network(&self) -> Network {
        match self.ip {
            Address::V4(ip) => {
                let mask = u32::MAX.checked_shl(32 - self.prefixlen).unwrap_or(0);
                Network {
                    v6: false,
                    addr: (ip & mask) as u128,
                    prefixlen: self.prefixlen,
                }
            }
            Address::V6(ip, _) => {
                let mask = u128::MAX.checked_shl(128 - self.prefixlen).unwrap_or(0);
                Network {
                    v6: true,
                    addr: ip & mask,
                    prefixlen: self.prefixlen,
                }
            }
        }
    }

    /// `.with_prefixlen`
    pub fn with_prefixlen(&self) -> String {
        match self.ip {
            Address::V4(ip) => format!("{}/{}", v4_string(ip), self.prefixlen),
            Address::V6(ip, _) => format!("{}/{}", v6_hex_string(ip), self.prefixlen),
        }
    }

    pub fn is_link_local(&self) -> bool {
        self.ip.is_link_local()
    }

    /// `IPv4Interface.is_loopback` is the address's; `IPv6Interface`'s also
    /// requires the network to be loopback (i.e. ::1/128).
    pub fn is_loopback(&self) -> bool {
        match self.ip {
            Address::V4(_) => self.ip.is_loopback(),
            Address::V6(..) => self.ip.is_loopback() && self.prefixlen == 128,
        }
    }
}

impl fmt::Display for Interface {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}/{}", self.ip, self.prefixlen)
    }
}

impl fmt::Display for Network {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let addr = if self.v6 {
            Address::V6(self.addr, None)
        } else {
            Address::V4(self.addr as u32)
        };
        write!(f, "{}/{}", addr, self.prefixlen)
    }
}

/// `socket.inet_ntop(family, packed)` (glibc formatting)
pub fn inet_ntop(family: i64, data: &[u8]) -> Result<String> {
    match family {
        2 => {
            if data.len() != 4 {
                return Err(value_error(
                    "invalid length of packed IP address string".into(),
                ));
            }
            Ok(format!("{}.{}.{}.{}", data[0], data[1], data[2], data[3]))
        }
        10 => {
            if data.len() != 16 {
                return Err(value_error(
                    "invalid length of packed IP address string".into(),
                ));
            }
            let words: Vec<u16> = (0..8)
                .map(|i| u16::from_be_bytes([data[2 * i], data[2 * i + 1]]))
                .collect();
            // longest run (>= 2) of zero words, first one wins
            // (start, length) of zero runs
            let mut best: Option<(usize, usize)> = None;
            let mut cur: Option<(usize, usize)> = None;
            for (i, w) in words.iter().enumerate() {
                if *w == 0 {
                    cur = Some(match cur {
                        None => (i, 1),
                        Some((b, l)) => (b, l + 1),
                    });
                } else if let Some(c) = cur.take() {
                    if best.is_none_or(|b| c.1 > b.1) {
                        best = Some(c);
                    }
                }
            }
            if let Some(c) = cur {
                if best.is_none_or(|b| c.1 > b.1) {
                    best = Some(c);
                }
            }
            if best.is_some_and(|b| b.1 < 2) {
                best = None;
            }
            let mut out = String::new();
            let mut i = 0;
            while i < 8 {
                if let Some((b, l)) = best {
                    if i >= b && i < b + l {
                        if i == b {
                            out.push(':');
                        }
                        i += 1;
                        continue;
                    }
                }
                if i != 0 {
                    out.push(':');
                }
                // encapsulated IPv4?
                if i == 6
                    && best.is_some_and(|(b, l)| {
                        b == 0
                            && (l == 6
                                || (l == 7 && words[7] != 1)
                                || (l == 5 && words[5] == 0xffff))
                    })
                {
                    out.push_str(&format!(
                        "{}.{}.{}.{}",
                        data[12], data[13], data[14], data[15]
                    ));
                    break;
                }
                out.push_str(&format!("{:x}", words[i]));
                i += 1;
            }
            if let Some((b, l)) = best {
                if b + l == 8 {
                    out.push(':');
                }
            }
            Ok(out)
        }
        f => Err(Exception::err(
            "ValueError",
            format!("unknown address family {f}"),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formatting() {
        assert_eq!(
            ip_address("2001:db8:0:0:1:0:0:1").unwrap().to_string(),
            "2001:db8::1:0:0:1"
        );
        assert_eq!(
            ip_address("::ffff:1.2.3.4").unwrap().to_string(),
            "::ffff:1.2.3.4"
        );
        assert_eq!(
            ip_interface("::ffff:1.2.3.4/120").unwrap().with_prefixlen(),
            "::ffff:102:304/120"
        );
        assert_eq!(
            ip_interface("10.1.2.3/255.255.0.0")
                .unwrap()
                .network()
                .to_string(),
            "10.1.0.0/16"
        );
        assert_eq!(
            ip_interface("fe80::1/64").unwrap().network().to_string(),
            "fe80::/64"
        );
        assert!(ip_address("01.2.3.4").is_err());
        assert!(ip_address("1::2::3").is_err());
        assert!(ip_interface("default").is_err());
        let fd = [
            0xfd, 0, 0, 0, 0, 0, 0, 0, 0xce, 0xce, 0x1e, 0xff, 0xfe, 0x3d, 0xc7, 0x37,
        ];
        assert_eq!(inet_ntop(10, &fd).unwrap(), "fd00::cece:1eff:fe3d:c737");
        let mut two = [0u8; 16];
        two[15] = 2;
        assert_eq!(inet_ntop(10, &two).unwrap(), "::2");
        let mut v4c = [0u8; 16];
        v4c[12..].copy_from_slice(&[1, 2, 3, 4]);
        assert_eq!(inet_ntop(10, &v4c).unwrap(), "::1.2.3.4");
        let mut alt = [0u8; 16];
        alt[1] = 1;
        alt[5] = 1;
        alt[11] = 1;
        assert_eq!(inet_ntop(10, &alt).unwrap(), "1:0:1::1:0:0");
        two[15] = 1;
        assert_eq!(inet_ntop(10, &two).unwrap(), "::1");
        assert_eq!(inet_ntop(10, &[0u8; 16]).unwrap(), "::");
    }
}
