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

//! PyYAML's `yaml.dump(data)` with default arguments (`sort_keys=True`,
//! `default_flow_style=False`, `allow_unicode=False`, `width=80`,
//! `indent=2`) for JSON-like data. A port of the parts of
//! `yaml/representer.py`, `yaml/resolver.py` and `yaml/emitter.py` such
//! data goes through; anchors/aliases are never needed (no shared objects).

use serde_json::Value;

use crate::pyjson;

enum Node {
    /// (value, implicit[0] i.e. "plain resolves back to the same tag")
    Scalar(String, bool),
    Seq(Vec<Node>),
    Map(Vec<(Node, Node)>),
}

/// `Resolver.resolve(ScalarNode, value, (True, False))` returns the
/// implicit tag for a plain scalar; this tells whether it is `str`.
fn resolves_to_str(v: &str) -> bool {
    !(is_bool(v)
        || is_float(v)
        || is_int(v)
        || v == "<<"
        || is_null(v)
        || is_timestamp(v)
        || v == "=")
}

/// Python `re.match(pattern + '$')`: `$` also matches before a final "\n".
fn strip_final_nl(v: &str) -> &str {
    v.strip_suffix('\n').unwrap_or(v)
}

fn is_bool(v: &str) -> bool {
    matches!(
        strip_final_nl(v),
        "yes"
            | "Yes"
            | "YES"
            | "no"
            | "No"
            | "NO"
            | "true"
            | "True"
            | "TRUE"
            | "false"
            | "False"
            | "FALSE"
            | "on"
            | "On"
            | "ON"
            | "off"
            | "Off"
            | "OFF"
    )
}

fn is_null(v: &str) -> bool {
    matches!(strip_final_nl(v), "~" | "null" | "Null" | "NULL" | "")
}

/// A tiny matcher over a char slice for the resolver's regular expressions.
struct M<'a> {
    s: &'a [char],
    i: usize,
}

impl M<'_> {
    fn eat(&mut self, f: impl Fn(char) -> bool) -> bool {
        if self.i < self.s.len() && f(self.s[self.i]) {
            self.i += 1;
            true
        } else {
            false
        }
    }
    fn eat_while(&mut self, f: impl Fn(char) -> bool) -> usize {
        let start = self.i;
        while self.eat(&f) {}
        self.i - start
    }
    fn end(&self) -> bool {
        self.i == self.s.len()
    }
}

fn chars(v: &str) -> Vec<char> {
    strip_final_nl(v).chars().collect()
}

fn digit(c: char) -> bool {
    c.is_ascii_digit()
}

fn digit_(c: char) -> bool {
    c.is_ascii_digit() || c == '_'
}

/// `(?::[0-5]?[0-9])+` from position `m.i`, greedy, must reach the end
fn sexagesimal_tail(m: &mut M) -> bool {
    let mut any = false;
    while m.eat(|c| c == ':') {
        let start = m.i;
        let n = m.eat_while(digit);
        if n == 0 || n > 2 || (n == 2 && m.s[start] > '5') {
            return false;
        }
        any = true;
    }
    any
}

fn is_int(v: &str) -> bool {
    let s = chars(v);
    let alts: [&dyn Fn(&mut M) -> bool; 5] = [
        &|m| {
            m.eat(|c| c == '+' || c == '-');
            m.eat(|c| c == '0')
                && m.eat(|c| c == 'b')
                && m.eat_while(|c| c == '0' || c == '1' || c == '_') > 0
        },
        &|m| {
            m.eat(|c| c == '+' || c == '-');
            m.eat(|c| c == '0') && m.eat_while(|c| ('0'..='7').contains(&c) || c == '_') > 0
        },
        &|m| {
            m.eat(|c| c == '+' || c == '-');
            if m.eat(|c| c == '0') {
                return true;
            }
            m.eat(|c| ('1'..='9').contains(&c)) && {
                m.eat_while(digit_);
                true
            }
        },
        &|m| {
            m.eat(|c| c == '+' || c == '-');
            m.eat(|c| c == '0')
                && m.eat(|c| c == 'x')
                && m.eat_while(|c| c.is_ascii_hexdigit() || c == '_') > 0
        },
        &|m| {
            m.eat(|c| c == '+' || c == '-');
            m.eat(|c| ('1'..='9').contains(&c)) && {
                // [0-9_]* is greedy but may give back digits to the tail;
                // digits before the first ':' all belong to it.
                m.eat_while(digit_);
                sexagesimal_tail(m)
            }
        },
    ];
    alts.iter().any(|f| {
        let mut m = M { s: &s, i: 0 };
        f(&mut m) && m.end()
    })
}

fn is_float(v: &str) -> bool {
    let s = chars(v);
    let exp = |m: &mut M| {
        // (?:[eE][-+][0-9]+)?
        let save = m.i;
        if m.eat(|c| c == 'e' || c == 'E')
            && m.eat(|c| c == '-' || c == '+')
            && m.eat_while(digit) > 0
        {
            return;
        }
        m.i = save;
    };
    let alts: [&dyn Fn(&mut M) -> bool; 5] = [
        &|m| {
            m.eat(|c| c == '+' || c == '-');
            m.eat(digit)
                && {
                    m.eat_while(digit_);
                    m.eat(|c| c == '.')
                }
                && {
                    m.eat_while(digit_);
                    exp(m);
                    true
                }
        },
        &|m| {
            m.eat(|c| c == '.') && m.eat(digit) && {
                m.eat_while(digit_);
                exp(m);
                true
            }
        },
        &|m| {
            m.eat(|c| c == '+' || c == '-');
            m.eat(digit)
                && {
                    m.eat_while(digit_);
                    sexagesimal_tail(m)
                }
                && m.eat(|c| c == '.')
                && {
                    m.eat_while(digit_);
                    true
                }
        },
        &|m| {
            m.eat(|c| c == '+' || c == '-');
            let rest: String = m.s[m.i..].iter().collect();
            matches!(rest.as_str(), ".inf" | ".Inf" | ".INF") && {
                m.i = m.s.len();
                true
            }
        },
        &|m| {
            let rest: String = m.s[m.i..].iter().collect();
            matches!(rest.as_str(), ".nan" | ".NaN" | ".NAN") && {
                m.i = m.s.len();
                true
            }
        },
    ];
    alts.iter().any(|f| {
        let mut m = M { s: &s, i: 0 };
        f(&mut m) && m.end()
    })
}

fn is_timestamp(v: &str) -> bool {
    let s = chars(v);
    let mut m = M { s: &s, i: 0 };
    // [0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?
    let date = |m: &mut M| {
        (0..4).all(|_| m.eat(digit))
            && m.eat(|c| c == '-')
            && m.eat(digit)
            && {
                m.eat(digit);
                m.eat(|c| c == '-')
            }
            && m.eat(digit)
            && {
                m.eat(digit);
                true
            }
    };
    if !date(&mut m) {
        return false;
    }
    if m.end() {
        return true;
    }
    // (?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?
    // (?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?
    if !(m.eat(|c| c == 'T' || c == 't') || m.eat_while(|c| c == ' ' || c == '\t') > 0) {
        return false;
    }
    if !(m.eat(digit)
        && {
            m.eat(digit);
            m.eat(|c| c == ':')
        }
        && m.eat(digit)
        && m.eat(digit)
        && m.eat(|c| c == ':')
        && m.eat(digit)
        && m.eat(digit))
    {
        return false;
    }
    if m.eat(|c| c == '.') {
        m.eat_while(digit);
    }
    if m.end() {
        return true;
    }
    m.eat_while(|c| c == ' ' || c == '\t');
    if m.eat(|c| c == 'Z') {
        return m.end();
    }
    if m.eat(|c| c == '-' || c == '+') && m.eat(digit) {
        m.eat(digit);
        let save = m.i;
        if !(m.eat(|c| c == ':') && m.eat(digit) && m.eat(digit)) {
            m.i = save;
        }
        return m.end();
    }
    false
}

/// `SafeRepresenter.represent_float`
fn represent_float(f: f64) -> String {
    if f.is_nan() {
        return ".nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 {
            ".inf".into()
        } else {
            "-.inf".into()
        };
    }
    let value = pyjson::py_float_repr(f).to_lowercase();
    if !value.contains('.') && value.contains('e') {
        value.replacen('e', ".0e", 1)
    } else {
        value
    }
}

/// `Representer.represent_data` (with `sort_keys=True`)
fn represent(v: &Value) -> Node {
    match v {
        Value::Null => Node::Scalar("null".into(), true),
        Value::Bool(b) => Node::Scalar(if *b { "true" } else { "false" }.into(), true),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Node::Scalar(i.to_string(), true)
            } else if let Some(u) = n.as_u64() {
                Node::Scalar(u.to_string(), true)
            } else {
                Node::Scalar(represent_float(n.as_f64().unwrap_or(f64::NAN)), true)
            }
        }
        Value::String(s) => match pyjson::nonfinite(v) {
            Some("nan") => Node::Scalar(".nan".into(), true),
            Some("inf") => Node::Scalar(".inf".into(), true),
            Some("-inf") => Node::Scalar("-.inf".into(), true),
            _ => Node::Scalar(s.clone(), resolves_to_str(s)),
        },
        Value::Array(items) => Node::Seq(items.iter().map(represent).collect()),
        Value::Object(map) => {
            let mut items: Vec<(&String, &Value)> = map.iter().collect();
            items.sort_by(|a, b| a.0.cmp(b.0));
            Node::Map(
                items
                    .into_iter()
                    .map(|(k, v)| (Node::Scalar(k.clone(), resolves_to_str(k)), represent(v)))
                    .collect(),
            )
        }
    }
}

struct Analysis {
    empty: bool,
    multiline: bool,
    allow_flow_plain: bool,
    allow_block_plain: bool,
    allow_single_quoted: bool,
}

fn is_break(c: char) -> bool {
    matches!(c, '\n' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

fn is_ws0(c: char) -> bool {
    matches!(c, '\0' | ' ' | '\t' | '\r') || is_break(c)
}

/// `Emitter.analyze_scalar` (allow_unicode=False)
fn analyze_scalar(scalar: &str) -> Analysis {
    let s: Vec<char> = scalar.chars().collect();
    if s.is_empty() {
        return Analysis {
            empty: true,
            multiline: false,
            allow_flow_plain: false,
            allow_block_plain: true,
            allow_single_quoted: true,
        };
    }
    let mut block_indicators = false;
    let mut flow_indicators = false;
    let mut line_breaks = false;
    let mut special_characters = false;
    let mut leading_space = false;
    let mut leading_break = false;
    let mut trailing_space = false;
    let mut trailing_break = false;
    let mut break_space = false;
    let mut space_break = false;
    if scalar.starts_with("---") || scalar.starts_with("...") {
        block_indicators = true;
        flow_indicators = true;
    }
    let mut preceded_by_whitespace = true;
    let mut followed_by_whitespace = s.len() == 1 || is_ws0(s[1]);
    let mut previous_space = false;
    let mut previous_break = false;
    let mut index = 0;
    while index < s.len() {
        let ch = s[index];
        if index == 0 {
            if "#,[]{}&*!|>'\"%@`".contains(ch) {
                flow_indicators = true;
                block_indicators = true;
            }
            if ch == '?' || ch == ':' {
                flow_indicators = true;
                if followed_by_whitespace {
                    block_indicators = true;
                }
            }
            if ch == '-' && followed_by_whitespace {
                flow_indicators = true;
                block_indicators = true;
            }
        } else {
            if ",?[]{}".contains(ch) {
                flow_indicators = true;
            }
            if ch == ':' {
                flow_indicators = true;
                if followed_by_whitespace {
                    block_indicators = true;
                }
            }
            if ch == '#' && preceded_by_whitespace {
                flow_indicators = true;
                block_indicators = true;
            }
        }
        if is_break(ch) {
            line_breaks = true;
        }
        if !(ch == '\n' || ('\x20'..='\x7e').contains(&ch)) {
            // with allow_unicode=False every other character is special
            special_characters = true;
        }
        if ch == ' ' {
            if index == 0 {
                leading_space = true;
            }
            if index == s.len() - 1 {
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
            if index == s.len() - 1 {
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
        index += 1;
        preceded_by_whitespace = is_ws0(ch);
        followed_by_whitespace = index + 1 >= s.len() || is_ws0(s[index + 1]);
    }
    let mut allow_flow_plain = true;
    let mut allow_block_plain = true;
    let mut allow_single_quoted = true;
    if leading_space || leading_break || trailing_space || trailing_break {
        allow_flow_plain = false;
        allow_block_plain = false;
    }
    if break_space {
        allow_flow_plain = false;
        allow_block_plain = false;
        allow_single_quoted = false;
    }
    if space_break || special_characters {
        allow_flow_plain = false;
        allow_block_plain = false;
        allow_single_quoted = false;
    }
    if line_breaks {
        allow_flow_plain = false;
        allow_block_plain = false;
    }
    if flow_indicators {
        allow_flow_plain = false;
    }
    if block_indicators {
        allow_block_plain = false;
    }
    Analysis {
        empty: false,
        multiline: line_breaks,
        allow_flow_plain,
        allow_block_plain,
        allow_single_quoted,
    }
}

struct Emitter {
    out: String,
    indent: Option<usize>,
    indents: Vec<Option<usize>>,
    flow_level: usize,
    column: usize,
    whitespace: bool,
    indention: bool,
    mapping_context: bool,
    simple_key_context: bool,
}

const BEST_INDENT: usize = 2;
const BEST_WIDTH: usize = 80;

impl Emitter {
    fn increase_indent(&mut self, flow: bool, indentless: bool) {
        self.indents.push(self.indent);
        match self.indent {
            None => self.indent = Some(if flow { BEST_INDENT } else { 0 }),
            Some(i) if !indentless => self.indent = Some(i + BEST_INDENT),
            _ => {}
        }
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
            let data = " ".repeat(indent - self.column);
            self.write(&data);
        }
    }

    fn write_line_break(&mut self, data: Option<char>) {
        self.whitespace = true;
        self.indention = true;
        self.column = 0;
        self.out.push(data.unwrap_or('\n'));
    }

    fn expect_node(&mut self, node: &Node, sequence: bool, mapping: bool, simple_key: bool) {
        let _ = sequence;
        self.mapping_context = mapping;
        self.simple_key_context = simple_key;
        match node {
            Node::Scalar(value, implicit) => {
                self.increase_indent(true, false);
                self.process_scalar(value, *implicit);
                self.indent = self.indents.pop().unwrap_or(None);
            }
            Node::Seq(items) => {
                if self.flow_level > 0 || items.is_empty() {
                    self.write_indicator("[", true, true, false);
                    self.flow_level += 1;
                    self.increase_indent(true, false);
                    // only empty sequences are emitted in flow style
                    self.indent = self.indents.pop().unwrap_or(None);
                    self.flow_level -= 1;
                    self.write_indicator("]", false, false, false);
                } else {
                    let indentless = self.mapping_context && !self.indention;
                    self.increase_indent(false, indentless);
                    for item in items {
                        self.write_indent();
                        self.write_indicator("-", true, false, true);
                        self.expect_node(item, true, false, false);
                    }
                    self.indent = self.indents.pop().unwrap_or(None);
                }
            }
            Node::Map(items) => {
                if self.flow_level > 0 || items.is_empty() {
                    self.write_indicator("{", true, true, false);
                    self.flow_level += 1;
                    self.increase_indent(true, false);
                    self.indent = self.indents.pop().unwrap_or(None);
                    self.flow_level -= 1;
                    self.write_indicator("}", false, false, false);
                } else {
                    self.increase_indent(false, false);
                    for (k, v) in items {
                        self.write_indent();
                        if check_simple_key(k) {
                            self.expect_node(k, false, true, true);
                            self.write_indicator(":", false, false, false);
                            self.expect_node(v, false, true, false);
                        } else {
                            self.write_indicator("?", true, false, true);
                            self.expect_node(k, false, true, false);
                            self.write_indent();
                            self.write_indicator(":", true, false, true);
                            self.expect_node(v, false, true, false);
                        }
                    }
                    self.indent = self.indents.pop().unwrap_or(None);
                }
            }
        }
    }

    /// `choose_scalar_style` for events with style=None
    fn choose_scalar_style(&self, a: &Analysis, implicit: bool) -> char {
        if implicit
            && !(self.simple_key_context && (a.empty || a.multiline))
            && ((self.flow_level > 0 && a.allow_flow_plain)
                || (self.flow_level == 0 && a.allow_block_plain))
        {
            return ' ';
        }
        if a.allow_single_quoted && !(self.simple_key_context && a.multiline) {
            return '\'';
        }
        '"'
    }

    fn process_scalar(&mut self, value: &str, implicit: bool) {
        let a = analyze_scalar(value);
        let style = self.choose_scalar_style(&a, implicit);
        let split = !self.simple_key_context;
        match style {
            '"' => self.write_double_quoted(value, split),
            '\'' => self.write_single_quoted(value, split),
            _ => self.write_plain(value, split),
        }
    }

    fn write_plain(&mut self, text: &str, split: bool) {
        if text.is_empty() {
            return;
        }
        if !self.whitespace {
            self.write(" ");
        }
        self.whitespace = false;
        self.indention = false;
        let t: Vec<char> = text.chars().collect();
        let mut spaces = false;
        let mut breaks = false;
        let (mut start, mut end) = (0, 0);
        while end <= t.len() {
            let ch = t.get(end).copied();
            if spaces {
                if ch != Some(' ') {
                    if start + 1 == end && self.column > BEST_WIDTH && split {
                        self.write_indent();
                        self.whitespace = false;
                        self.indention = false;
                    } else {
                        let data: String = t[start..end].iter().collect();
                        self.write(&data);
                    }
                    start = end;
                }
            } else if breaks {
                if !ch.is_some_and(is_break) {
                    if t[start] == '\n' {
                        self.write_line_break(None);
                    }
                    for &br in &t[start..end] {
                        if br == '\n' {
                            self.write_line_break(None);
                        } else {
                            self.write_line_break(Some(br));
                        }
                    }
                    self.write_indent();
                    self.whitespace = false;
                    self.indention = false;
                    start = end;
                }
            } else if ch.is_none_or(|c| c == ' ' || is_break(c)) {
                let data: String = t[start..end].iter().collect();
                self.write(&data);
                start = end;
            }
            if let Some(c) = ch {
                spaces = c == ' ';
                breaks = is_break(c);
            }
            end += 1;
        }
    }

    fn write_single_quoted(&mut self, text: &str, split: bool) {
        self.write_indicator("'", true, false, false);
        let t: Vec<char> = text.chars().collect();
        let mut spaces = false;
        let mut breaks = false;
        let (mut start, mut end) = (0, 0);
        while end <= t.len() {
            let ch = t.get(end).copied();
            if spaces {
                if ch != Some(' ') {
                    if start + 1 == end
                        && self.column > BEST_WIDTH
                        && split
                        && start != 0
                        && end != t.len()
                    {
                        self.write_indent();
                    } else {
                        let data: String = t[start..end].iter().collect();
                        self.write(&data);
                    }
                    start = end;
                }
            } else if breaks {
                if !ch.is_some_and(is_break) {
                    if t[start] == '\n' {
                        self.write_line_break(None);
                    }
                    for &br in &t[start..end] {
                        if br == '\n' {
                            self.write_line_break(None);
                        } else {
                            self.write_line_break(Some(br));
                        }
                    }
                    self.write_indent();
                    start = end;
                }
            } else if ch.is_none_or(|c| c == ' ' || is_break(c) || c == '\'') && start < end {
                let data: String = t[start..end].iter().collect();
                self.write(&data);
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

    fn write_double_quoted(&mut self, text: &str, split: bool) {
        self.write_indicator("\"", true, false, false);
        let t: Vec<char> = text.chars().collect();
        let (mut start, mut end) = (0, 0);
        while end <= t.len() {
            let ch = t.get(end).copied();
            let special = match ch {
                None => true,
                Some(c) => {
                    "\"\\\u{85}\u{2028}\u{2029}\u{feff}".contains(c) || !(' '..='~').contains(&c)
                }
            };
            if special {
                if start < end {
                    let data: String = t[start..end].iter().collect();
                    self.write(&data);
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
                && end + 1 < t.len()
                && (ch == Some(' ') || start >= end)
                && self.column as isize + (end as isize - start as isize) > BEST_WIDTH as isize
                && split
            {
                let mut data: String = if start < end {
                    t[start..end].iter().collect()
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
                if t.get(start) == Some(&' ') {
                    self.write("\\");
                }
            }
            end += 1;
        }
        self.write_indicator("\"", false, false, false);
    }
}

/// `Emitter.check_simple_key` for a key node
fn check_simple_key(node: &Node) -> bool {
    match node {
        Node::Scalar(v, _) => {
            let a = analyze_scalar(v);
            v.chars().count() < 128 && !a.empty && !a.multiline
        }
        Node::Seq(items) => items.is_empty(),
        Node::Map(items) => items.is_empty(),
    }
}

/// `yaml.dump(data)`
pub fn dump(v: &Value) -> String {
    let node = represent(v);
    let mut e = Emitter {
        out: String::new(),
        indent: None,
        indents: vec![],
        flow_level: 0,
        column: 0,
        whitespace: true,
        indention: true,
        mapping_context: false,
        simple_key_context: false,
    };
    e.expect_node(&node, false, false, false);
    // expect_document_end
    e.write_indent();
    // (A plain root scalar would leave the stream "open ended" and add a
    // "..." line; `netplan status` always dumps a mapping.)
    e.out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolver() {
        assert!(!resolves_to_str("52:54:00:12:34:56"));
        assert!(resolves_to_str("1c:4d:70:e4:e4:0e"));
        assert!(!resolves_to_str("1.5"));
        assert!(!resolves_to_str("yes"));
        assert!(!resolves_to_str(""));
        assert!(resolves_to_str("10.0.0.1"));
        assert!(!resolves_to_str("2024-01-01"));
        assert!(resolves_to_str("fe80::1"));
    }

    #[test]
    fn dump_matches_pyyaml() {
        let v = crate::pyjson::loads(
            r#"{"b": {"x": [], "y": {}, "l": ["a", {"k": 1, "j": null}], "s": "", "t": "yes"}, "a": true}"#,
        )
        .unwrap();
        assert_eq!(
            dump(&v),
            "a: true\nb:\n  l:\n  - a\n  - j: null\n    k: 1\n  s: ''\n  t: 'yes'\n  x: []\n  y: {}\n"
        );
    }
}
