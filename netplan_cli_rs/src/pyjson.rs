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

//! Python's `json.loads()` / `json.dumps()` (default arguments) over
//! [`serde_json::Value`]: same accepted syntax, the same `JSONDecodeError`
//! messages and the same output formatting (`", "`/`": "` separators,
//! `ensure_ascii`, float `repr()`).

use serde_json::{Map, Number, Value};

/// `str(json.JSONDecodeError)`, e.g. "Expecting value: line 1 column 1 (char 0)"
fn decode_error(msg: &str, s: &[char], pos: usize) -> String {
    let lineno = s[..pos].iter().filter(|&&c| c == '\n').count() + 1;
    let colno = match s[..pos].iter().rposition(|&c| c == '\n') {
        Some(i) => pos - i,
        None => pos + 1,
    };
    format!("{msg}: line {lineno} column {colno} (char {pos})")
}

/// `json.loads(s)`; the error is `str(JSONDecodeError)`.
pub fn loads(s: &str) -> Result<Value, String> {
    let s: Vec<char> = s.chars().collect();
    if s.first() == Some(&'\u{feff}') {
        return Err(decode_error(
            "Unexpected UTF-8 BOM (decode using utf-8-sig)",
            &s,
            0,
        ));
    }
    let mut d = Decoder { s: &s };
    let idx = d.skip_ws(0);
    let (value, end) = match d.scan_once(idx)? {
        Some(r) => r,
        None => return Err(decode_error("Expecting value", &s, idx)),
    };
    let end = d.skip_ws(end);
    if end != s.len() {
        return Err(decode_error("Extra data", &s, end));
    }
    Ok(value)
}

struct Decoder<'a> {
    s: &'a [char],
}

type Scan = Result<Option<(Value, usize)>, String>;

impl Decoder<'_> {
    fn err(&self, msg: &str, pos: usize) -> String {
        decode_error(msg, self.s, pos)
    }

    fn at(&self, i: usize) -> Option<char> {
        self.s.get(i).copied()
    }

    fn skip_ws(&self, mut i: usize) -> usize {
        while matches!(self.at(i), Some(' ' | '\t' | '\n' | '\r')) {
            i += 1;
        }
        i
    }

    fn starts_with(&self, i: usize, word: &str) -> bool {
        let w: Vec<char> = word.chars().collect();
        self.s.len() >= i + w.len() && self.s[i..i + w.len()] == w[..]
    }

    /// The C scanner's `scan_once_unicode`: `None` is StopIteration.
    fn scan_once(&mut self, idx: usize) -> Scan {
        let Some(c) = self.at(idx) else {
            return Ok(None);
        };
        match c {
            '"' => {
                let (s, end) = self.scanstring(idx + 1)?;
                Ok(Some((Value::String(s), end)))
            }
            '{' => self.parse_object(idx + 1).map(Some),
            '[' => self.parse_array(idx + 1).map(Some),
            'n' if self.starts_with(idx, "null") => Ok(Some((Value::Null, idx + 4))),
            't' if self.starts_with(idx, "true") => Ok(Some((Value::Bool(true), idx + 4))),
            'f' if self.starts_with(idx, "false") => Ok(Some((Value::Bool(false), idx + 5))),
            'N' if self.starts_with(idx, "NaN") => Ok(Some((float(f64::NAN), idx + 3))),
            'I' if self.starts_with(idx, "Infinity") => Ok(Some((float(f64::INFINITY), idx + 8))),
            '-' if self.starts_with(idx, "-Infinity") => {
                Ok(Some((float(f64::NEG_INFINITY), idx + 9)))
            }
            _ => Ok(self.match_number(idx)),
        }
    }

    fn match_number(&self, start: usize) -> Option<(Value, usize)> {
        let digit = |i: usize| self.at(i).is_some_and(|c| c.is_ascii_digit());
        let mut i = start;
        if self.at(i) == Some('-') {
            i += 1;
        }
        if self.at(i) == Some('0') {
            i += 1;
        } else if self.at(i).is_some_and(|c| ('1'..='9').contains(&c)) {
            while digit(i) {
                i += 1;
            }
        } else {
            return None;
        }
        let mut is_float = false;
        if self.at(i) == Some('.') && digit(i + 1) {
            i += 1;
            while digit(i) {
                i += 1;
            }
            is_float = true;
        }
        if matches!(self.at(i), Some('e' | 'E')) {
            let mut j = i + 1;
            if matches!(self.at(j), Some('+' | '-')) {
                j += 1;
            }
            if digit(j) {
                while digit(j) {
                    j += 1;
                }
                i = j;
                is_float = true;
            }
        }
        let text: String = self.s[start..i].iter().collect();
        let value = if is_float {
            float(text.parse::<f64>().unwrap_or(f64::NAN))
        } else if let Ok(n) = text.parse::<i64>() {
            Value::Number(n.into())
        } else if let Ok(n) = text.parse::<u64>() {
            Value::Number(n.into())
        } else {
            // beyond 64 bits: Python keeps an exact int, we degrade to float
            float(text.parse::<f64>().unwrap_or(f64::NAN))
        };
        Some((value, i))
    }

    /// `scanstring_unicode(s, end, strict=True)`; `end` is the index after
    /// the opening quote.
    fn scanstring(&self, end: usize) -> Result<(String, usize), String> {
        let begin = end - 1;
        let mut out = String::new();
        let mut i = end;
        loop {
            let Some(c) = self.at(i) else {
                return Err(self.err("Unterminated string starting at", begin));
            };
            match c {
                '"' => return Ok((out, i + 1)),
                '\\' => {
                    let Some(e) = self.at(i + 1) else {
                        return Err(self.err("Unterminated string starting at", begin));
                    };
                    if e != 'u' {
                        let r = match e {
                            '"' => '"',
                            '\\' => '\\',
                            '/' => '/',
                            'b' => '\u{8}',
                            'f' => '\u{c}',
                            'n' => '\n',
                            'r' => '\r',
                            't' => '\t',
                            _ => return Err(self.err("Invalid \\escape", i)),
                        };
                        out.push(r);
                        i += 2;
                        continue;
                    }
                    let hex = |at: usize| -> Option<u32> {
                        if at + 4 > self.s.len() {
                            return None;
                        }
                        let h: String = self.s[at..at + 4].iter().collect();
                        if h.chars().all(|c| c.is_ascii_hexdigit()) {
                            u32::from_str_radix(&h, 16).ok()
                        } else {
                            None
                        }
                    };
                    let Some(mut u) = hex(i + 2) else {
                        return Err(self.err("Invalid \\uXXXX escape", i + 1));
                    };
                    i += 6;
                    if (0xd800..=0xdbff).contains(&u)
                        && self.at(i) == Some('\\')
                        && self.at(i + 1) == Some('u')
                    {
                        if let Some(u2) = hex(i + 2) {
                            if (0xdc00..=0xdfff).contains(&u2) {
                                u = 0x10000 + (((u - 0xd800) << 10) | (u2 - 0xdc00));
                                i += 6;
                            }
                        }
                    }
                    // A lone surrogate is a valid Python str but not a Rust one.
                    out.push(char::from_u32(u).unwrap_or('\u{fffd}'));
                }
                c if (c as u32) < 0x20 => {
                    return Err(self.err("Invalid control character at", i));
                }
                c => {
                    out.push(c);
                    i += 1;
                }
            }
        }
    }

    fn parse_object(&mut self, start: usize) -> Result<(Value, usize), String> {
        let mut map = Map::new();
        let mut idx = self.skip_ws(start);
        if self.at(idx) == Some('}') {
            return Ok((Value::Object(map), idx + 1));
        }
        loop {
            if self.at(idx) != Some('"') {
                return Err(self.err("Expecting property name enclosed in double quotes", idx));
            }
            let (key, end) = self.scanstring(idx + 1)?;
            idx = self.skip_ws(end);
            if self.at(idx) != Some(':') {
                return Err(self.err("Expecting ':' delimiter", idx));
            }
            idx = self.skip_ws(idx + 1);
            let Some((val, end)) = self.scan_once(idx)? else {
                return Err(self.err("Expecting value", idx));
            };
            map.insert(key, val);
            idx = self.skip_ws(end);
            match self.at(idx) {
                Some('}') => return Ok((Value::Object(map), idx + 1)),
                Some(',') => {}
                _ => return Err(self.err("Expecting ',' delimiter", idx)),
            }
            let comma = idx;
            idx = self.skip_ws(idx + 1);
            if self.at(idx) == Some('}') {
                return Err(self.err("Illegal trailing comma before end of object", comma));
            }
        }
    }

    fn parse_array(&mut self, start: usize) -> Result<(Value, usize), String> {
        let mut list = vec![];
        let mut idx = self.skip_ws(start);
        if self.at(idx) == Some(']') {
            return Ok((Value::Array(list), idx + 1));
        }
        loop {
            let Some((val, end)) = self.scan_once(idx)? else {
                return Err(self.err("Expecting value", idx));
            };
            list.push(val);
            idx = self.skip_ws(end);
            match self.at(idx) {
                Some(']') => return Ok((Value::Array(list), idx + 1)),
                Some(',') => {}
                _ => return Err(self.err("Expecting ',' delimiter", idx)),
            }
            let comma = idx;
            idx = self.skip_ws(idx + 1);
            if self.at(idx) == Some(']') {
                return Err(self.err("Illegal trailing comma before end of array", comma));
            }
        }
    }
}

/// A float `Value`. serde_json cannot hold NaN/inf, so those are kept as
/// strings tagged with a private prefix (see [`float_of`]).
fn float(f: f64) -> Value {
    match Number::from_f64(f) {
        Some(n) => Value::Number(n),
        None => Value::String(format!("{NONFINITE}{}", py_float_repr(f))),
    }
}

const NONFINITE: &str = "\u{0}pyfloat:";

/// The non-finite float a `Value` stands for, if any.
pub fn nonfinite(v: &Value) -> Option<&str> {
    match v {
        Value::String(s) => s.strip_prefix(NONFINITE),
        _ => None,
    }
}

/// `repr(float)`
pub fn py_float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if f == 0.0 {
        return if f.is_sign_negative() {
            "-0.0".into()
        } else {
            "0.0".into()
        };
    }
    // Shortest round-trip digits and decimal exponent.
    let sci = format!("{:e}", f.abs());
    let (mant, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let digits: String = mant.chars().filter(|c| *c != '.').collect();
    let sign = if f < 0.0 { "-" } else { "" };
    if !(-4..16).contains(&exp) {
        let m = if digits.len() > 1 {
            format!("{}.{}", &digits[..1], &digits[1..])
        } else {
            digits.clone()
        };
        let esign = if exp < 0 { "-" } else { "+" };
        return format!("{sign}{m}e{esign}{:02}", exp.abs());
    }
    let n = digits.len() as i32;
    let body = if exp < 0 {
        format!("0.{}{}", "0".repeat((-exp - 1) as usize), digits)
    } else if exp + 1 >= n {
        format!("{}{}.0", digits, "0".repeat((exp + 1 - n) as usize))
    } else {
        let p = (exp + 1) as usize;
        format!("{}.{}", &digits[..p], &digits[p..])
    };
    format!("{sign}{body}")
}

fn dump_str(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            c => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", u));
                }
            }
        }
    }
    out.push('"');
}

fn dump_into(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => match (n.as_i64(), n.as_u64(), n.as_f64()) {
            (Some(i), _, _) => out.push_str(&i.to_string()),
            (_, Some(u), _) => out.push_str(&u.to_string()),
            (_, _, Some(f)) => out.push_str(&py_float_repr(f)),
            _ => out.push_str("null"),
        },
        Value::String(s) => match nonfinite(v) {
            Some("nan") => out.push_str("NaN"),
            Some("inf") => out.push_str("Infinity"),
            Some("-inf") => out.push_str("-Infinity"),
            _ => dump_str(s, out),
        },
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                dump_into(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            out.push('{');
            for (i, (k, item)) in map.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                dump_str(k, out);
                out.push_str(": ");
                dump_into(item, out);
            }
            out.push('}');
        }
    }
}

/// `json.dumps(v)`
pub fn dumps(v: &Value) -> String {
    let mut out = String::new();
    dump_into(v, &mut out);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn errors_match_python() {
        let cases = [
            ("", "Expecting value: line 1 column 1 (char 0)"),
            (
                "{\"a\":1,}",
                "Illegal trailing comma before end of object: line 1 column 7 (char 6)",
            ),
            (
                "[1,\n 2,]",
                "Illegal trailing comma before end of array: line 2 column 3 (char 6)",
            ),
            ("\"a\\x\"", "Invalid \\escape: line 1 column 3 (char 2)"),
            (
                "\"a\\u12\"",
                "Invalid \\uXXXX escape: line 1 column 4 (char 3)",
            ),
            (
                "{\"a\" 1}",
                "Expecting ':' delimiter: line 1 column 6 (char 5)",
            ),
            ("1.", "Extra data: line 1 column 2 (char 1)"),
            ("-", "Expecting value: line 1 column 1 (char 0)"),
            (
                "{\"a\":1,,}",
                "Expecting property name enclosed in double quotes: line 1 column 8 (char 7)",
            ),
        ];
        for (input, msg) in cases {
            assert_eq!(loads(input).unwrap_err(), msg, "{input:?}");
        }
    }

    #[test]
    fn dumps_matches_python() {
        let v = loads("{\"a\": [1, 2.5, 1e16, 1e-5, 0.1, -0.0, \"\\u00e9\\u2028\\u007f\\ud83d\\ude00\", null, true, {}], \"b\": -0}").unwrap();
        assert_eq!(
            dumps(&v),
            "{\"a\": [1, 2.5, 1e+16, 1e-05, 0.1, -0.0, \"\\u00e9\\u2028\\u007f\\ud83d\\ude00\", null, true, {}], \"b\": 0}"
        );
    }
}
