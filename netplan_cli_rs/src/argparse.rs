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

//! A port of the parts of Python 3.14's `argparse` that the netplan CLI
//! uses, so that command lines are interpreted exactly as the Python CLI
//! interprets them: `parse_known_args()` semantics (unknown options and
//! surplus positionals are returned, not rejected), unique-prefix
//! abbreviation of long options, `--opt=value`, clustered short options,
//! `--` handling, mutually exclusive groups and subparsers.
//!
//! The parsing algorithm follows `ArgumentParser._parse_known_args()`
//! closely; help text is only an approximation of argparse's formatter.

use std::collections::HashMap;

/// A parsed attribute value.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    None,
    Bool(bool),
    Str(String),
    Int(i64),
    List(Vec<String>),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Nargs {
    /// `nargs=None`: exactly one
    Single,
    /// `nargs='?'`
    Optional,
    /// `nargs='*'`
    ZeroOrMore,
    /// `nargs=PARSER` (subparsers)
    Parser,
    /// options taking no argument (store_true, store_const, help)
    Zero,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Type {
    Str,
    Int,
}

#[derive(Debug, Clone)]
enum Kind {
    Store,
    StoreConst(Value),
    StoreTrue,
    Help,
    SubParsers,
}

#[derive(Debug, Clone)]
struct Action {
    option_strings: Vec<String>,
    dest: String,
    nargs: Nargs,
    kind: Kind,
    default: Value,
    typ: Type,
    required: bool,
    help: Option<String>,
}

/// The result of parsing: attribute name -> value.
#[derive(Debug, Clone, Default)]
pub struct Namespace(HashMap<String, Value>);

impl Namespace {
    pub fn get(&self, dest: &str) -> &Value {
        self.0.get(dest).unwrap_or(&Value::None)
    }

    pub fn str(&self, dest: &str) -> Option<String> {
        match self.get(dest) {
            Value::Str(s) => Some(s.clone()),
            _ => None,
        }
    }

    pub fn bool(&self, dest: &str) -> bool {
        matches!(self.get(dest), Value::Bool(true))
    }

    pub fn int(&self, dest: &str) -> Option<i64> {
        match self.get(dest) {
            Value::Int(i) => Some(*i),
            _ => None,
        }
    }

    #[allow(dead_code)] // used by `netplan rebind` (port pending)
    pub fn list(&self, dest: &str) -> Vec<String> {
        match self.get(dest) {
            Value::List(l) => l.clone(),
            _ => vec![],
        }
    }

    fn set(&mut self, dest: &str, value: Value) {
        self.0.insert(dest.to_string(), value);
    }
}

/// Why parsing stopped early. Mirrors `parser.error()` (exit 2, usage and
/// message on stderr) and the help action (exit 0, help on stdout).
#[derive(Debug)]
pub enum ParseExit {
    Error { usage: String, message: String },
    Help(String),
}

impl ParseExit {
    /// Print what argparse prints and return the exit code.
    pub fn report(&self) -> i32 {
        match self {
            ParseExit::Error { usage, message } => {
                crate::py::flush_stdout();
                eprintln!("{usage}{message}");
                2
            }
            ParseExit::Help(text) => {
                crate::py::write_stdout(text);
                0
            }
        }
    }
}

#[derive(Debug, Clone)]
pub struct ArgParser {
    prog: String,
    description: String,
    actions: Vec<Action>,
    mutex_groups: Vec<Vec<usize>>,
    subparsers: Vec<(String, ArgParser, Option<String>)>,
}

/// Argument definition builder, see [`ArgParser::add`].
pub struct Arg {
    action: Action,
}

impl Arg {
    /// An option (`--name`, `-n`) or positional (`name`) storing one value.
    pub fn new(names: &[&str]) -> Self {
        let option_strings: Vec<String> = names
            .iter()
            .filter(|n| n.starts_with('-'))
            .map(|n| n.to_string())
            .collect();
        let dest = if option_strings.is_empty() {
            names[0].to_string()
        } else {
            // first long option string, else first short one, minus prefix
            let long = option_strings.iter().find(|s| s.starts_with("--"));
            long.unwrap_or(&option_strings[0])
                .trim_start_matches('-')
                .replace('-', "_")
        };
        let positional = option_strings.is_empty();
        Arg {
            action: Action {
                option_strings,
                dest,
                nargs: Nargs::Single,
                kind: Kind::Store,
                default: Value::None,
                typ: Type::Str,
                required: positional,
                help: None,
            },
        }
    }

    pub fn store_true(mut self) -> Self {
        self.action.kind = Kind::StoreTrue;
        self.action.nargs = Nargs::Zero;
        self.action.default = Value::Bool(false);
        self
    }

    pub fn store_const(mut self, dest: &str, value: &str) -> Self {
        self.action.kind = Kind::StoreConst(Value::Str(value.to_string()));
        self.action.nargs = Nargs::Zero;
        self.action.dest = dest.to_string();
        self
    }

    pub fn nargs(mut self, nargs: Nargs) -> Self {
        self.action.nargs = nargs;
        if !self.action.option_strings.is_empty() {
            return self;
        }
        // _get_positional_kwargs(): '?' and '*' positionals are not required
        self.action.required = !matches!(nargs, Nargs::Optional | Nargs::ZeroOrMore);
        self
    }

    pub fn default(mut self, value: Value) -> Self {
        self.action.default = value;
        self
    }

    pub fn default_str(self, value: &str) -> Self {
        self.default(Value::Str(value.to_string()))
    }

    pub fn typ(mut self, typ: Type) -> Self {
        self.action.typ = typ;
        self
    }

    pub fn help(mut self, help: &str) -> Self {
        self.action.help = Some(help.to_string());
        self
    }

    /// `help=argparse.SUPPRESS`
    pub fn hidden(mut self) -> Self {
        self.action.help = None;
        self
    }
}

impl ArgParser {
    /// `ArgumentParser(prog=prog, description=description, add_help=add_help)`
    pub fn new(prog: &str, description: &str, add_help: bool) -> Self {
        let mut p = ArgParser {
            prog: prog.to_string(),
            description: description.to_string(),
            actions: vec![],
            mutex_groups: vec![],
            subparsers: vec![],
        };
        if add_help {
            p.actions.push(Action {
                option_strings: vec!["-h".into(), "--help".into()],
                dest: "help".into(),
                nargs: Nargs::Zero,
                kind: Kind::Help,
                default: Value::None,
                typ: Type::Str,
                required: false,
                help: Some("show this help message and exit".into()),
            });
        }
        p
    }

    pub fn add(&mut self, arg: Arg) -> &mut Self {
        self.actions.push(arg.action);
        self
    }

    /// `add_mutually_exclusive_group(required=False)` with these arguments.
    pub fn add_mutually_exclusive(&mut self, args: Vec<Arg>) -> &mut Self {
        let mut group = vec![];
        for arg in args {
            group.push(self.actions.len());
            self.actions.push(arg.action);
        }
        self.mutex_groups.push(group);
        self
    }

    /// `add_subparsers(title=..., metavar='', dest=dest)`
    pub fn add_subparsers(&mut self, dest: &str) -> &mut Self {
        self.actions.push(Action {
            option_strings: vec![],
            dest: dest.to_string(),
            nargs: Nargs::Parser,
            kind: Kind::SubParsers,
            default: Value::None,
            typ: Type::Str,
            required: false,
            help: None,
        });
        self
    }

    /// `subparsers.add_parser(name, help=help, add_help=add_help)`
    pub fn add_parser(&mut self, name: &str, help: Option<&str>, add_help: bool) -> &mut Self {
        let prog = format!("{} {}", self.prog, name);
        self.subparsers.push((
            name.to_string(),
            ArgParser::new(&prog, help.unwrap_or(""), add_help),
            help.map(str::to_string),
        ));
        self
    }

    /// `parse_known_args(args)`: returns the namespace and the arguments
    /// that were not consumed, in order.
    pub fn parse_known_args(&self, args: &[String]) -> Result<(Namespace, Vec<String>), ParseExit> {
        let mut ns = Namespace::default();
        for a in &self.actions {
            if !matches!(a.kind, Kind::Help) {
                ns.set(&a.dest, a.default.clone());
            }
        }
        let mut unrecognized = vec![];
        let mut extras = self.parse_inner(args, &mut ns, &mut unrecognized)?;
        extras.extend(unrecognized);
        Ok((ns, extras))
    }

    fn error(&self, message: &str) -> ParseExit {
        ParseExit::Error {
            usage: self.format_usage(),
            message: format!("{}: error: {}", self.prog, message),
        }
    }

    // ── option string lookup ─────────────────────────────────────────────────

    fn option_string_actions(&self) -> Vec<(&str, usize)> {
        let mut out = vec![];
        for (i, a) in self.actions.iter().enumerate() {
            for s in &a.option_strings {
                out.push((s.as_str(), i));
            }
        }
        out
    }

    fn lookup(&self, option_string: &str) -> Option<usize> {
        self.option_string_actions()
            .into_iter()
            .find(|(s, _)| *s == option_string)
            .map(|(_, i)| i)
    }

    /// `_parse_optional()`: None for a positional, else candidate matches.
    fn parse_optional(&self, arg: &str) -> Option<Vec<OptTuple>> {
        if arg.is_empty() || !arg.starts_with('-') {
            return None;
        }
        if let Some(i) = self.lookup(arg) {
            return Some(vec![OptTuple::new(Some(i), arg, None, None)]);
        }
        if arg.chars().count() == 1 {
            return None;
        }
        if let Some((opt, explicit)) = arg.split_once('=') {
            if let Some(i) = self.lookup(opt) {
                return Some(vec![OptTuple::new(Some(i), opt, Some("="), Some(explicit))]);
            }
        }
        let tuples = self.get_option_tuples(arg);
        if !tuples.is_empty() {
            return Some(tuples);
        }
        // negative numbers are positionals (no option looks like one)
        let b = arg.as_bytes();
        let negative = b.len() >= 2
            && (b[1].is_ascii_digit() || (b[1] == b'.' && b.len() >= 3 && b[2].is_ascii_digit()));
        if negative || arg.contains(' ') {
            return None;
        }
        Some(vec![OptTuple::new(None, arg, None, None)])
    }

    /// `_get_option_tuples()`: abbreviation matches.
    fn get_option_tuples(&self, option_string: &str) -> Vec<OptTuple> {
        let mut result = vec![];
        let second_is_prefix = option_string.chars().nth(1) == Some('-');
        let (prefix, sep, explicit) = match option_string.split_once('=') {
            Some((p, e)) => (p, Some("="), Some(e)),
            None => (option_string, None, None),
        };
        if second_is_prefix {
            for (s, i) in self.option_string_actions() {
                if s.starts_with(prefix) {
                    result.push(OptTuple::new(Some(i), s, sep, explicit));
                }
            }
        } else {
            let split = option_string
                .char_indices()
                .nth(2)
                .map(|(i, _)| i)
                .unwrap_or(option_string.len());
            let (short_prefix, short_explicit) = option_string.split_at(split);
            for (s, i) in self.option_string_actions() {
                if s == short_prefix {
                    result.push(OptTuple::new(Some(i), s, Some(""), Some(short_explicit)));
                } else if s.starts_with(prefix) {
                    result.push(OptTuple::new(Some(i), s, sep, explicit));
                }
            }
        }
        result
    }

    // ── the main parsing loop (_parse_known_args) ────────────────────────────

    fn parse_inner(
        &self,
        arg_strings: &[String],
        ns: &mut Namespace,
        unrecognized: &mut Vec<String>,
    ) -> Result<Vec<String>, ParseExit> {
        let mut conflicts: HashMap<usize, Vec<usize>> = HashMap::new();
        for group in &self.mutex_groups {
            for (i, &a) in group.iter().enumerate() {
                let c = conflicts.entry(a).or_default();
                c.extend(group[..i].iter().copied());
                c.extend(group[i + 1..].iter().copied());
            }
        }

        // arg_strings_pattern: 'O' option, 'A' argument, '-' for '--'
        let mut option_indices: HashMap<usize, Vec<OptTuple>> = HashMap::new();
        let mut pattern = String::new();
        let mut iter = arg_strings.iter().enumerate();
        while let Some((i, arg)) = iter.next() {
            if arg == "--" {
                pattern.push('-');
                for _ in iter.by_ref() {
                    pattern.push('A');
                }
                break;
            }
            match self.parse_optional(arg) {
                None => pattern.push('A'),
                Some(t) => {
                    option_indices.insert(i, t);
                    pattern.push('O');
                }
            }
        }
        let pattern = pattern.into_bytes();

        let mut st = State {
            seen: vec![false; self.actions.len()],
            seen_non_default: vec![false; self.actions.len()],
            extras: vec![],
            positionals: self
                .actions
                .iter()
                .enumerate()
                .filter(|(_, a)| a.option_strings.is_empty())
                .map(|(i, _)| i)
                .collect(),
        };

        let max_option_index = option_indices
            .keys()
            .max()
            .map(|&m| m as isize)
            .unwrap_or(-1);
        let mut start = 0usize;
        while (start as isize) <= max_option_index {
            let mut next_option = start;
            while (next_option as isize) <= max_option_index {
                if option_indices.contains_key(&next_option) {
                    break;
                }
                next_option += 1;
            }
            if start != next_option {
                let end = self.consume_positionals(
                    start,
                    arg_strings,
                    &pattern,
                    &mut st,
                    &conflicts,
                    ns,
                    unrecognized,
                )?;
                if end > start {
                    start = end;
                    continue;
                }
                start = end;
            }
            if !option_indices.contains_key(&start) {
                st.extras
                    .extend(arg_strings[start..next_option].iter().cloned());
                start = next_option;
            }
            start = self.consume_optional(
                start,
                arg_strings,
                &pattern,
                &option_indices,
                &mut st,
                &conflicts,
                ns,
                unrecognized,
            )?;
        }
        let stop = self.consume_positionals(
            start,
            arg_strings,
            &pattern,
            &mut st,
            &conflicts,
            ns,
            unrecognized,
        )?;
        st.extras.extend(arg_strings[stop..].iter().cloned());

        let missing: Vec<String> = self
            .actions
            .iter()
            .enumerate()
            .filter(|(i, a)| !st.seen[*i] && a.required)
            .map(|(_, a)| action_name(a))
            .collect();
        if !missing.is_empty() {
            return Err(self.error(&format!(
                "the following arguments are required: {}",
                missing.join(", ")
            )));
        }
        Ok(st.extras)
    }

    #[allow(clippy::too_many_arguments)]
    fn consume_optional(
        &self,
        start: usize,
        arg_strings: &[String],
        pattern: &[u8],
        option_indices: &HashMap<usize, Vec<OptTuple>>,
        st: &mut State,
        conflicts: &HashMap<usize, Vec<usize>>,
        ns: &mut Namespace,
        unrecognized: &mut Vec<String>,
    ) -> Result<usize, ParseExit> {
        let tuples = &option_indices[&start];
        if tuples.len() > 1 {
            let options: Vec<&str> = tuples.iter().map(|t| t.option_string.as_str()).collect();
            return Err(self.error(&format!(
                "ambiguous option: {} could match {}",
                arg_strings[start],
                options.join(", ")
            )));
        }
        let t = tuples[0].clone();
        let (mut action, mut option_string, mut sep, mut explicit) =
            (t.action, t.option_string, t.sep, t.explicit_arg);
        let mut action_tuples: Vec<(usize, Vec<String>, String)> = vec![];
        let stop;
        loop {
            let Some(a) = action else {
                st.extras.push(arg_strings[start].clone());
                return Ok(start + 1);
            };
            if let Some(exp) = explicit.clone() {
                let arg_count =
                    match_argument(&self.actions[a], b"A").map_err(|m| self.error(&m))?;
                let second = option_string.chars().nth(1);
                if arg_count == 0 && second != Some('-') && !exp.is_empty() {
                    if sep.as_deref().is_some_and(|s| !s.is_empty()) || exp.starts_with('-') {
                        return Err(self.error(&format!(
                            "argument {}: ignored explicit argument '{}'",
                            action_name(&self.actions[a]),
                            exp
                        )));
                    }
                    action_tuples.push((a, vec![], option_string.clone()));
                    let first = exp.chars().next().unwrap();
                    let candidate = format!("-{first}");
                    if let Some(next) = self.lookup(&candidate) {
                        action = Some(next);
                        option_string = candidate;
                        let rest: String = exp.chars().skip(1).collect();
                        if rest.is_empty() {
                            sep = None;
                            explicit = None;
                        } else if let Some(r) = rest.strip_prefix('=') {
                            sep = Some("=".into());
                            explicit = Some(r.to_string());
                        } else {
                            sep = Some(String::new());
                            explicit = Some(rest);
                        }
                    } else {
                        st.extras.push(format!("-{exp}"));
                        stop = start + 1;
                        break;
                    }
                } else if arg_count == 1 {
                    stop = start + 1;
                    action_tuples.push((a, vec![exp], option_string.clone()));
                    break;
                } else {
                    return Err(self.error(&format!(
                        "argument {}: ignored explicit argument '{}'",
                        action_name(&self.actions[a]),
                        exp
                    )));
                }
            } else {
                let begin = start + 1;
                let arg_count = match_argument(&self.actions[a], &pattern[begin..])
                    .map_err(|m| self.error(&m))?;
                stop = begin + arg_count;
                action_tuples.push((a, arg_strings[begin..stop].to_vec(), option_string.clone()));
                break;
            }
        }
        for (a, args, opt) in action_tuples {
            self.take_action(a, &args, Some(&opt), st, conflicts, ns, unrecognized)?;
        }
        Ok(stop)
    }

    #[allow(clippy::too_many_arguments)]
    fn consume_positionals(
        &self,
        mut start: usize,
        arg_strings: &[String],
        pattern: &[u8],
        st: &mut State,
        conflicts: &HashMap<usize, Vec<usize>>,
        ns: &mut Namespace,
        unrecognized: &mut Vec<String>,
    ) -> Result<usize, ParseExit> {
        let positionals: Vec<usize> = st.positionals.clone();
        let counts = self.match_arguments_partial(&positionals, &pattern[start..]);
        for (&a, &count) in positionals.iter().zip(counts.iter()) {
            let mut args: Vec<String> = arg_strings[start..start + count].to_vec();
            if self.actions[a].nargs == Nargs::Parser {
                if pattern.get(start) == Some(&b'-') {
                    if let Some(p) = args.iter().position(|s| s == "--") {
                        args.remove(p);
                    }
                }
            } else if pattern[start..start + count].contains(&b'-') {
                if let Some(p) = args.iter().position(|s| s == "--") {
                    args.remove(p);
                }
            }
            start += count;
            self.take_action(a, &args, None, st, conflicts, ns, unrecognized)?;
        }
        st.positionals.drain(..counts.len());
        Ok(start)
    }

    #[allow(clippy::too_many_arguments)]
    fn take_action(
        &self,
        a: usize,
        args: &[String],
        option_string: Option<&str>,
        st: &mut State,
        conflicts: &HashMap<usize, Vec<usize>>,
        ns: &mut Namespace,
        unrecognized: &mut Vec<String>,
    ) -> Result<(), ParseExit> {
        st.seen[a] = true;
        let action = &self.actions[a];
        let value = self.get_values(action, args)?;
        if option_string.is_some() || !args.is_empty() {
            st.seen_non_default[a] = true;
            for &c in conflicts.get(&a).map(Vec::as_slice).unwrap_or(&[]) {
                if st.seen_non_default[c] {
                    return Err(self.error(&format!(
                        "argument {}: not allowed with argument {}",
                        action_name(action),
                        action_name(&self.actions[c])
                    )));
                }
            }
        }
        match &action.kind {
            Kind::Store => ns.set(&action.dest, value),
            Kind::StoreConst(v) => ns.set(&action.dest, v.clone()),
            Kind::StoreTrue => ns.set(&action.dest, Value::Bool(true)),
            Kind::Help => return Err(ParseExit::Help(self.format_help())),
            Kind::SubParsers => {
                let Value::List(values) = value else {
                    unreachable!()
                };
                let name = &values[0];
                ns.set(&action.dest, Value::Str(name.clone()));
                let (_, sub, _) = self
                    .subparsers
                    .iter()
                    .find(|(n, _, _)| n == name)
                    .expect("choice checked in get_values");
                let (sub_ns, sub_extras) = sub.parse_known_args(&values[1..])?;
                for (k, v) in sub_ns.0 {
                    ns.set(&k, v);
                }
                unrecognized.extend(sub_extras);
            }
        }
        Ok(())
    }

    /// `_get_values()`
    fn get_values(&self, action: &Action, args: &[String]) -> Result<Value, ParseExit> {
        if args.is_empty() && action.nargs == Nargs::Optional {
            return Ok(if action.option_strings.is_empty() {
                action.default.clone()
            } else {
                Value::None
            });
        }
        if args.is_empty() && action.nargs == Nargs::ZeroOrMore && action.option_strings.is_empty()
        {
            return Ok(match &action.default {
                Value::None => Value::List(vec![]),
                v => v.clone(),
            });
        }
        if args.len() == 1 && matches!(action.nargs, Nargs::Single | Nargs::Optional) {
            return convert(action, &args[0]).map_err(|m| self.error(&m));
        }
        match action.nargs {
            Nargs::Parser => {
                let name = &args[0];
                if !self.subparsers.iter().any(|(n, _, _)| n == name) {
                    let choices: Vec<&str> =
                        self.subparsers.iter().map(|(n, _, _)| n.as_str()).collect();
                    return Err(self.error(&format!(
                        "argument {}: invalid choice: '{}' (choose from {})",
                        action_name(action),
                        name,
                        choices.join(", ")
                    )));
                }
                Ok(Value::List(args.to_vec()))
            }
            Nargs::Zero => Ok(Value::None),
            _ => {
                for a in args {
                    convert(action, a).map_err(|m| self.error(&m))?;
                }
                Ok(Value::List(args.to_vec()))
            }
        }
    }

    /// `_match_arguments_partial()`
    fn match_arguments_partial(&self, actions: &[usize], pattern: &[u8]) -> Vec<usize> {
        for i in (1..=actions.len()).rev() {
            let groups: Vec<Vec<Elem>> = actions[..i]
                .iter()
                .map(|&a| nargs_pattern(&self.actions[a]))
                .collect();
            if let Some(mut counts) = match_groups(&groups, pattern) {
                let end: usize = counts.iter().sum();
                if end < pattern.len() && pattern[end] == b'O' {
                    while counts.last() == Some(&0) {
                        counts.pop();
                    }
                }
                return counts;
            }
        }
        vec![]
    }

    // ── help ─────────────────────────────────────────────────────────────────

    pub fn format_usage(&self) -> String {
        let mut parts = vec![format!("usage: {}", self.prog)];
        for a in &self.actions {
            if a.help.is_none() && !a.option_strings.is_empty() {
                continue;
            }
            if let Some(o) = a.option_strings.first() {
                let metavar = match a.nargs {
                    Nargs::Zero => String::new(),
                    _ => format!(" {}", a.dest.to_uppercase()),
                };
                parts.push(format!("[{o}{metavar}]"));
            } else if matches!(a.kind, Kind::SubParsers) {
                parts.push(" ...".into());
            } else {
                parts.push(match a.nargs {
                    Nargs::Optional => format!("[{}]", a.dest),
                    Nargs::ZeroOrMore => format!("[{} ...]", a.dest),
                    _ => a.dest.clone(),
                });
            }
        }
        parts.join(" ") + "\n"
    }

    pub fn format_help(&self) -> String {
        let mut out = self.format_usage();
        if !self.description.is_empty() {
            out += &format!("\n{}\n", self.description);
        }
        let positionals: Vec<&Action> = self
            .actions
            .iter()
            .filter(|a| a.option_strings.is_empty() && !matches!(a.kind, Kind::SubParsers))
            .collect();
        if !positionals.is_empty() {
            out += "\npositional arguments:\n";
            for a in positionals {
                out += &format!("  {:<22}{}\n", a.dest, a.help.as_deref().unwrap_or(""));
            }
        }
        out += "\noptions:\n";
        for a in self
            .actions
            .iter()
            .filter(|a| !a.option_strings.is_empty() && a.help.is_some())
        {
            let mut names = a.option_strings.join(", ");
            if a.nargs != Nargs::Zero {
                names += &format!(" {}", a.dest.to_uppercase());
            }
            out += &format!("  {:<22}{}\n", names, a.help.as_deref().unwrap_or(""));
        }
        if !self.subparsers.is_empty() {
            out += "\nAvailable commands:\n";
            for (name, _, help) in &self.subparsers {
                if let Some(h) = help {
                    out += &format!("    {name:<20}{h}\n");
                }
            }
        }
        out
    }
}

impl ArgParser {
    /// Alias of [`parse_known_args`](Self::parse_known_args).
    pub fn parse(&self, args: &[String]) -> Result<(Namespace, Vec<String>), ParseExit> {
        self.parse_known_args(args)
    }
}

#[derive(Debug, Clone)]
struct OptTuple {
    action: Option<usize>,
    option_string: String,
    sep: Option<String>,
    explicit_arg: Option<String>,
}

impl OptTuple {
    fn new(
        action: Option<usize>,
        option_string: &str,
        sep: Option<&str>,
        explicit: Option<&str>,
    ) -> Self {
        OptTuple {
            action,
            option_string: option_string.to_string(),
            sep: sep.map(str::to_string),
            explicit_arg: explicit.map(str::to_string),
        }
    }
}

struct State {
    seen: Vec<bool>,
    seen_non_default: Vec<bool>,
    extras: Vec<String>,
    positionals: Vec<usize>,
}

/// `_get_action_name()`
fn action_name(a: &Action) -> String {
    if a.option_strings.is_empty() {
        a.dest.clone()
    } else {
        a.option_strings.join("/")
    }
}

/// `_get_value()` + `_check_value()` for the types netplan uses.
fn convert(action: &Action, s: &str) -> Result<Value, String> {
    match action.typ {
        Type::Str => Ok(Value::Str(s.to_string())),
        Type::Int => python_int(s).map(Value::Int).ok_or_else(|| {
            format!(
                "argument {}: invalid int value: '{}'",
                action_name(action),
                s
            )
        }),
    }
}

/// Python's `int(str)` for base-10 strings: surrounding whitespace, an
/// optional sign and digits with single underscores between them.
pub fn python_int(s: &str) -> Option<i64> {
    let t = s.trim();
    let (neg, digits) = match t.as_bytes().first() {
        Some(b'-') => (true, &t[1..]),
        Some(b'+') => (false, &t[1..]),
        _ => (false, t),
    };
    if digits.is_empty()
        || digits.starts_with('_')
        || digits.ends_with('_')
        || digits.contains("__")
    {
        return None;
    }
    let mut value: i64 = 0;
    for c in digits.chars() {
        if c == '_' {
            continue;
        }
        let d = c.to_digit(10)? as i64;
        value = value.checked_mul(10)?.checked_add(d)?;
    }
    Some(if neg { -value } else { value })
}

// ── nargs patterns ────────────────────────────────────────────────────────────

/// One `[chars]{min,max}` element of an nargs regex (always greedy).
#[derive(Clone, Copy)]
struct Elem {
    chars: &'static [u8],
    min: usize,
    max: usize,
}

const INF: usize = usize::MAX;

fn e(chars: &'static [u8], min: usize, max: usize) -> Elem {
    Elem { chars, min, max }
}

/// `_get_nargs_pattern()`, as a sequence of elements.
fn nargs_pattern(a: &Action) -> Vec<Elem> {
    let option = !a.option_strings.is_empty();
    match (a.nargs, option) {
        (Nargs::Single, true) => vec![e(b"A", 1, 1)],
        (Nargs::Single, false) => vec![e(b"-", 0, INF), e(b"A", 1, 1), e(b"-", 0, INF)],
        (Nargs::Optional, true) => vec![e(b"A", 0, 1)],
        (Nargs::Optional, false) => vec![e(b"-", 0, INF), e(b"A", 0, 1), e(b"-", 0, INF)],
        (Nargs::ZeroOrMore, true) => vec![e(b"A", 0, INF)],
        (Nargs::ZeroOrMore, false) => vec![e(b"-", 0, INF), e(b"A-", 0, INF)],
        (Nargs::Parser, true) => vec![e(b"A", 1, 1), e(b"AO", 0, INF)],
        (Nargs::Parser, false) => vec![e(b"-", 0, INF), e(b"A", 1, 1), e(b"-AO", 0, INF)],
        (Nargs::Zero, _) => vec![],
    }
}

/// `_match_argument()`
fn match_argument(a: &Action, pattern: &[u8]) -> Result<usize, String> {
    match match_groups(&[nargs_pattern(a)], pattern) {
        Some(counts) => Ok(counts[0]),
        None => Err(format!(
            "argument {}: {}",
            action_name(a),
            match a.nargs {
                Nargs::Single => "expected one argument",
                Nargs::Optional => "expected at most one argument",
                _ => "expected at least one argument",
            }
        )),
    }
}

/// Match the concatenation of `groups` at the start of `s` the way Python's
/// backtracking regex engine would (each element greedy), returning the
/// length matched by each group.
fn match_groups(groups: &[Vec<Elem>], s: &[u8]) -> Option<Vec<usize>> {
    let flat: Vec<(usize, Elem)> = groups
        .iter()
        .enumerate()
        .flat_map(|(g, elems)| elems.iter().map(move |el| (g, *el)))
        .collect();
    let mut lens = vec![0usize; flat.len()];
    if !match_from(&flat, 0, s, 0, &mut lens) {
        return None;
    }
    let mut counts = vec![0usize; groups.len()];
    for ((g, _), len) in flat.iter().zip(lens) {
        counts[*g] += len;
    }
    Some(counts)
}

fn match_from(flat: &[(usize, Elem)], i: usize, s: &[u8], pos: usize, lens: &mut [usize]) -> bool {
    if i == flat.len() {
        return true;
    }
    let el = flat[i].1;
    let mut n = 0;
    while n < el.max && pos + n < s.len() && el.chars.contains(&s[pos + n]) {
        n += 1;
    }
    loop {
        if n < el.min {
            return false;
        }
        lens[i] = n;
        if match_from(flat, i + 1, s, pos + n, lens) {
            return true;
        }
        if n == 0 {
            return false;
        }
        n -= 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    fn get_parser() -> ArgParser {
        let mut p = ArgParser::new("netplan get", "", true);
        p.add(
            Arg::new(&["--debug"])
                .store_true()
                .help("Enable debug messages"),
        );
        p.add(Arg::new(&["--breakpoint"]).store_true().hidden());
        p.add(Arg::new(&["key"]).nargs(Nargs::Optional).default_str("all"));
        p.add(Arg::new(&["--root-dir"]).default_str("/"));
        p
    }

    #[test]
    fn known_args_and_extras() {
        let p = get_parser();
        let (ns, extra) = p
            .parse(&args(&["--bogus", "--root", "/x", "ethernets", "more"]))
            .unwrap();
        assert_eq!(ns.str("root_dir").unwrap(), "/x");
        assert_eq!(ns.str("key").unwrap(), "ethernets");
        assert_eq!(extra, args(&["--bogus", "more"]));
        let (ns, _) = p.parse(&args(&["--root-dir=/y"])).unwrap();
        assert_eq!(ns.str("root_dir").unwrap(), "/y");
        assert_eq!(ns.str("key").unwrap(), "all");
    }

    #[test]
    fn ambiguous_and_help() {
        let mut p = get_parser();
        p.add(Arg::new(&["--diff"]).store_true());
        p.add(Arg::new(&["--diff-only"]).store_true());
        assert!(matches!(
            p.parse(&args(&["--dif"])),
            Err(ParseExit::Error { .. })
        ));
        assert!(matches!(p.parse(&args(&["-h"])), Err(ParseExit::Help(_))));
        assert!(matches!(
            p.parse(&args(&["--debug=1"])),
            Err(ParseExit::Error { .. })
        ));
    }

    #[test]
    fn subparsers() {
        let mut p = ArgParser::new("netplan ", "", true);
        p.add(Arg::new(&["--debug"]).store_true());
        p.add_subparsers("subcommand");
        p.add_parser("help", Some("Show this help message"), true);
        p.add_parser("get", Some("Get"), false);
        let (ns, extra) = p
            .parse(&args(&["--deb", "get", "--root-dir", "/x", "--debug"]))
            .unwrap();
        assert!(ns.bool("debug"));
        assert_eq!(ns.str("subcommand").unwrap(), "get");
        assert_eq!(extra, args(&["--root-dir", "/x", "--debug"]));
        let (ns, extra) = p.parse(&args(&["--", "get"])).unwrap();
        assert_eq!(ns.str("subcommand").unwrap(), "get");
        assert!(extra.is_empty());
        let (ns, extra) = p.parse(&args(&["--bogus"])).unwrap();
        assert_eq!(ns.get("subcommand"), &Value::None);
        assert_eq!(extra, args(&["--bogus"]));
        assert!(matches!(
            p.parse(&args(&["nope"])),
            Err(ParseExit::Error { .. })
        ));
        assert!(matches!(
            p.parse(&args(&["help", "-h"])),
            Err(ParseExit::Help(_))
        ));
    }

    #[test]
    fn ints() {
        assert_eq!(python_int(" +1_0 "), Some(10));
        assert_eq!(python_int("-5"), Some(-5));
        assert_eq!(python_int("1__0"), None);
        assert_eq!(python_int("x"), None);
    }
}
