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

//! Minimal YAML parser producing [`serde_json::Value`].
//!
//! `libnetplan`'s `netplan_state_dump_yaml` always emits block-style
//! mappings and sequences (`YAML_BLOCK_MAPPING_STYLE` /
//! `YAML_BLOCK_SEQUENCE_STYLE`) with scalars in either plain or
//! double-quoted style (see `src/yaml-helpers.h`). This parser only needs
//! to understand that constrained subset of YAML, so a small hand-written
//! parser is preferable to pulling in the (deprecated) `serde_yaml` crate.

use anyhow::Result;
use serde_json::{Map, Value};

/// Parse a YAML document (as produced by `netplan_state_dump_yaml`) into a
/// [`serde_json::Value`].
pub fn from_str(input: &str) -> Result<Value> {
    let lines = preprocess(input);
    let mut parser = Parser { lines, pos: 0 };
    if parser.lines.is_empty() {
        return Ok(Value::Null);
    }
    Ok(parser.parse_node(0))
}

/// A non-empty, comment-stripped source line: `(indentation, content)`.
struct Line<'a> {
    indent: usize,
    content: &'a str,
}

/// Strip comments/blank lines/document markers and record each remaining
/// line's indentation.
fn preprocess(input: &str) -> Vec<Line<'_>> {
    let mut lines = Vec::new();
    for raw in input.lines() {
        let indent = raw.len() - raw.trim_start_matches(' ').len();
        let content = strip_comment(raw[indent..].trim_end());
        if content.is_empty() || content == "---" || content == "..." {
            continue;
        }
        lines.push(Line { indent, content });
    }
    lines
}

/// Strip a trailing ` #...` comment that isn't inside a quoted scalar.
fn strip_comment(line: &str) -> &str {
    if line.starts_with('#') {
        return "";
    }
    let mut in_single = false;
    let mut in_double = false;
    let bytes = line.as_bytes();
    for (i, &b) in bytes.iter().enumerate() {
        match b {
            b'\'' if !in_double => in_single = !in_single,
            b'"' if !in_single => in_double = !in_double,
            b'#' if !in_single && !in_double && i > 0 && bytes[i - 1] == b' ' => {
                return line[..i].trim_end();
            }
            _ => {}
        }
    }
    line
}

struct Parser<'a> {
    lines: Vec<Line<'a>>,
    pos: usize,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<&Line<'a>> {
        self.lines.get(self.pos)
    }

    /// Parse the block (mapping, sequence, or single scalar) starting at the
    /// current position, provided its indentation is at least `min_indent`.
    fn parse_node(&mut self, min_indent: usize) -> Value {
        let Some(line) = self.peek() else {
            return Value::Null;
        };
        if line.indent < min_indent {
            return Value::Null;
        }
        let indent = line.indent;
        if is_sequence_item(line.content) {
            self.parse_sequence(indent)
        } else {
            self.parse_mapping(indent)
        }
    }

    fn parse_sequence(&mut self, indent: usize) -> Value {
        let mut items = Vec::new();
        while let Some(line) = self.peek() {
            if line.indent != indent || !is_sequence_item(line.content) {
                break;
            }
            let content = line.content;
            let rest = if content.len() == 1 {
                ""
            } else {
                content[1..].trim_start()
            };
            if rest.is_empty() {
                self.pos += 1;
                items.push(self.parse_node(indent + 1));
            } else if let Some((key, value)) = split_mapping_entry(rest) {
                // Inline mapping, e.g. `- to: 0.0.0.0/0`. The mapping
                // continues on following lines indented to match where
                // `rest` starts on this line.
                let inline_indent = indent + (content.len() - rest.len());
                self.pos += 1;
                items.push(self.parse_mapping_inline(inline_indent, key, value));
            } else {
                self.pos += 1;
                items.push(parse_scalar(rest));
            }
        }
        Value::Array(items)
    }

    fn parse_mapping(&mut self, indent: usize) -> Value {
        let mut map = Map::new();
        while let Some(line) = self.peek() {
            if line.indent != indent || is_sequence_item(line.content) {
                break;
            }
            let Some((key, value)) = split_mapping_entry(line.content) else {
                break;
            };
            self.pos += 1;
            map.insert(unquote(key), self.parse_entry_value(indent, value));
        }
        Value::Object(map)
    }

    /// Parse a mapping whose first key/value pair (`first_key`/`first_value`)
    /// was already extracted from a `- key: value` sequence item line.
    fn parse_mapping_inline(&mut self, indent: usize, first_key: &str, first_value: &str) -> Value {
        let mut map = Map::new();
        map.insert(
            unquote(first_key),
            self.parse_entry_value(indent, first_value),
        );
        while let Some(line) = self.peek() {
            if line.indent != indent || is_sequence_item(line.content) {
                break;
            }
            let Some((key, value)) = split_mapping_entry(line.content) else {
                break;
            };
            self.pos += 1;
            map.insert(unquote(key), self.parse_entry_value(indent, value));
        }
        Value::Object(map)
    }

    /// Parse the value half of a `key: value` mapping entry, recursing into
    /// a nested block when `value` is empty (i.e. the value is on following
    /// lines).
    ///
    /// Block sequence items may be indented to the same column as their
    /// parent key (this is how `libyaml`'s block-sequence style is
    /// emitted), so a sequence at `key_indent` is also accepted as this
    /// entry's value.
    fn parse_entry_value(&mut self, key_indent: usize, value: &str) -> Value {
        if !value.is_empty() {
            return parse_scalar(value);
        }
        match self.peek() {
            Some(line) if line.indent == key_indent && is_sequence_item(line.content) => {
                self.parse_sequence(key_indent)
            }
            Some(line) if line.indent > key_indent => self.parse_node(key_indent + 1),
            _ => Value::Null,
        }
    }
}

fn is_sequence_item(content: &str) -> bool {
    content == "-" || content.starts_with("- ")
}

/// Split a `key: value` (or `key:`) mapping entry at the first unquoted
/// `": "`, or at a trailing unquoted `:`. Returns `None` if `line` is not a
/// mapping entry (e.g. a plain scalar sequence item).
fn split_mapping_entry(line: &str) -> Option<(&str, &str)> {
    let mut in_single = false;
    let mut in_double = false;
    let bytes = line.as_bytes();
    for (i, &b) in bytes.iter().enumerate() {
        match b {
            b'\'' if !in_double => in_single = !in_single,
            b'"' if !in_single => in_double = !in_double,
            b':' if !in_single && !in_double => {
                if bytes.get(i + 1) == Some(&b' ') {
                    return Some((line[..i].trim_end(), line[i + 1..].trim_start()));
                }
                if i + 1 == bytes.len() {
                    return Some((line[..i].trim_end(), ""));
                }
            }
            _ => {}
        }
    }
    None
}

/// Remove surrounding quotes from a scalar used as a mapping key.
fn unquote(s: &str) -> String {
    match parse_scalar(s) {
        Value::String(s) => s,
        other => other.to_string(),
    }
}

/// Parse a single scalar token (plain or double-quoted) into a JSON value.
fn parse_scalar(s: &str) -> Value {
    if let Some(inner) = s.strip_prefix('"').and_then(|s| s.strip_suffix('"')) {
        return Value::String(unescape_double_quoted(inner));
    }
    if let Some(inner) = s.strip_prefix('\'').and_then(|s| s.strip_suffix('\'')) {
        return Value::String(inner.replace("''", "'"));
    }
    match s {
        "~" | "null" | "Null" | "NULL" | "" => return Value::Null,
        "true" | "True" | "TRUE" => return Value::Bool(true),
        "false" | "False" | "FALSE" => return Value::Bool(false),
        "[]" => return Value::Array(Vec::new()),
        "{}" => return Value::Object(Map::new()),
        _ => {}
    }
    if let Ok(n) = s.parse::<u64>() {
        return Value::Number(n.into());
    }
    if let Ok(n) = s.parse::<i64>() {
        return Value::Number(n.into());
    }
    Value::String(s.to_string())
}

/// Decode YAML double-quoted scalar escape sequences.
fn unescape_double_quoted(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        match chars.next() {
            Some('n') => out.push('\n'),
            Some('t') => out.push('\t'),
            Some('r') => out.push('\r'),
            Some('0') => out.push('\0'),
            Some('"') => out.push('"'),
            Some('\\') => out.push('\\'),
            Some('u') => {
                let hex: String = chars.by_ref().take(4).collect();
                if let Some(c) = u32::from_str_radix(&hex, 16).ok().and_then(char::from_u32) {
                    out.push(c);
                }
            }
            Some(other) => out.push(other),
            None => out.push('\\'),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_scalars() {
        assert_eq!(parse_scalar("true"), Value::Bool(true));
        assert_eq!(parse_scalar("false"), Value::Bool(false));
        assert_eq!(parse_scalar("123"), Value::Number(123.into()));
        assert_eq!(
            parse_scalar("192.168.1.1"),
            Value::String("192.168.1.1".into())
        );
        assert_eq!(parse_scalar("\"quoted\""), Value::String("quoted".into()));
        assert_eq!(parse_scalar("~"), Value::Null);
    }

    #[test]
    fn parses_simple_mapping() {
        let v = from_str("network:\n  ethernets:\n    eth0:\n      dhcp4: true\n").unwrap();
        assert_eq!(
            v["network"]["ethernets"]["eth0"]["dhcp4"],
            Value::Bool(true)
        );
    }

    #[test]
    fn parses_sequence_of_scalars() {
        let v = from_str("addresses:\n  - 10.0.0.1/24\n  - 10.0.0.2/24\n").unwrap();
        assert_eq!(
            v["addresses"],
            Value::Array(vec![
                Value::String("10.0.0.1/24".into()),
                Value::String("10.0.0.2/24".into()),
            ])
        );
    }

    #[test]
    fn parses_sequence_of_mappings() {
        let v =
            from_str("routes:\n  - to: default\n    via: 2001:db8::1\n    metric: 100\n").unwrap();
        let route = &v["routes"][0];
        assert_eq!(route["to"], Value::String("default".into()));
        assert_eq!(route["via"], Value::String("2001:db8::1".into()));
        assert_eq!(route["metric"], Value::Number(100.into()));
    }

    #[test]
    fn parses_ipv6_key_with_nested_mapping() {
        let v = from_str("addresses:\n  - 2001:db8::1/64:\n      label: foo\n").unwrap();
        assert_eq!(
            v["addresses"][0]["2001:db8::1/64"]["label"],
            Value::String("foo".into())
        );
    }

    /// `netplan_state_dump_yaml` indents block-sequence items to the *same*
    /// column as the mapping key they're the value of, e.g.:
    /// ```yaml
    /// routes:
    /// - table: 101
    ///   to: "192.168.3.0/24"
    /// ```
    #[test]
    fn parses_real_dump_yaml_output() {
        let input = "\
network:
  version: 2
  renderer: networkd
  ethernets:
    ens3:
      addresses:
      - \"192.168.3.30/24\"
      dhcp4: false
      routes:
      - table: 101
        to: \"192.168.3.0/24\"
        via: \"192.168.3.1\"
      routing-policy:
      - table: 101
        from: \"192.168.3.0/24\"
";
        let v = from_str(input).unwrap();
        let ens3 = &v["network"]["ethernets"]["ens3"];
        assert_eq!(ens3["dhcp4"], Value::Bool(false));
        assert_eq!(
            ens3["addresses"],
            Value::Array(vec![Value::String("192.168.3.30/24".into())])
        );
        let route = &ens3["routes"][0];
        assert_eq!(route["table"], Value::Number(101.into()));
        assert_eq!(route["to"], Value::String("192.168.3.0/24".into()));
        assert_eq!(route["via"], Value::String("192.168.3.1".into()));
        assert_eq!(
            ens3["routing-policy"][0]["table"],
            Value::Number(101.into())
        );
    }
}
