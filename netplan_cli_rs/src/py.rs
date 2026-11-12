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

//! Runtime behaviour of the Python netplan CLI that the Rust CLI must
//! reproduce: how it exits, how errors surface, how it logs and how its
//! stdout is buffered.
//!
//! - [`Exit`] is `sys.exit(code)`.
//! - [`NetplanError`] is a libnetplan error, classified like the Python
//!   bindings' exception hierarchy (`python-cffi/netplan/_utils.py`), which
//!   `netplan_cli/cli/core.py` reports as `Command failed: ...` (exit 1).
//! - [`Exception`] is any other Python exception. Uncaught, Python prints a
//!   traceback and exits 1; only the exit code and the stderr written before
//!   the traceback are part of the compatibility contract.
//! - Logging mirrors `logging.basicConfig()` as set up in `core.py`:
//!   `%(message)s` at INFO, or `%(levelname)s:%(message)s` at DEBUG.
//! - stdout mirrors `sys.stdout`: line-buffered on a terminal, otherwise
//!   block-buffered, so output interleaves with child processes as it does
//!   in Python.

use std::fmt;
use std::io::Write;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

// ── Exit / exceptions ─────────────────────────────────────────────────────────

/// `sys.exit(code)`.
#[derive(Debug)]
pub struct Exit(pub i32);

impl fmt::Display for Exit {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "exit {}", self.0)
    }
}

impl std::error::Error for Exit {}

/// A Python exception other than a libnetplan one, e.g. `RuntimeError` or
/// `subprocess.CalledProcessError`.
#[derive(Debug)]
pub struct Exception {
    pub kind: &'static str,
    pub message: String,
}

impl Exception {
    pub fn err(kind: &'static str, message: impl Into<String>) -> anyhow::Error {
        Exception {
            kind,
            message: message.into(),
        }
        .into()
    }

    /// `subprocess.CalledProcessError` as raised by `check_call()` / `check_output()`.
    pub fn called_process_error(argv: &[&str], code: i32) -> anyhow::Error {
        let cmd = crate::utils::py_repr_list(argv);
        Self::err(
            "subprocess.CalledProcessError",
            format!("Command '{cmd}' returned non-zero exit status {code}."),
        )
    }
}

impl fmt::Display for Exception {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for Exception {}

// ── libnetplan errors ─────────────────────────────────────────────────────────

const PARSER_ERROR: u64 = 1;
const VALIDATION_ERROR: u64 = 2;
const PARSER_INVALID_YAML: u64 = 0;
const PARSER_INVALID_CONFIG: u64 = 1;
const VALIDATION_CONFIG_VALIDATION: u64 = 1;

/// Which Python exception class libnetplan's error maps to.
#[derive(Debug, Clone, PartialEq)]
pub enum NetplanErrorKind {
    /// `NetplanParserException`: "file:line:col: message"
    Parser {
        filename: String,
        line: String,
        column: String,
    },
    /// `NetplanValidationException`: "file.yaml: message" (first line only)
    Validation { filename: String },
    /// Any other `NetplanException` subclass
    Other,
}

/// A libnetplan error, as the Python bindings present it.
#[derive(Debug, Clone)]
pub struct NetplanError {
    pub kind: NetplanErrorKind,
    /// `str(exception)`: for parser and validation errors this is the
    /// message without the location prefix.
    pub message: String,
}

impl NetplanError {
    /// Classify an error the way `_checked_lib_call()` does. Returns the
    /// `ValueError` the Python bindings raise when a parser or validation
    /// message does not have the expected format.
    pub fn from_lib(domain_code: u64, raw: String) -> anyhow::Error {
        let domain = domain_code >> 32;
        let code = domain_code & 0xffff_ffff;
        if domain == PARSER_ERROR && (code == PARSER_INVALID_YAML || code == PARSER_INVALID_CONFIG)
        {
            // r'(?P<file_path>.*):(?P<error_line>\d+):(?P<error_col>\d+): (?P<message>(\s|.)*)'
            match split_parser_message(&raw) {
                Some((filename, line, column, message)) => NetplanError {
                    kind: NetplanErrorKind::Parser {
                        filename,
                        line,
                        column,
                    },
                    message,
                }
                .into(),
                None => Exception::err(
                    "ValueError",
                    format!("The parser error message does not have the expected format: {raw}"),
                ),
            }
        } else if domain == VALIDATION_ERROR && code == VALIDATION_CONFIG_VALIDATION {
            // r'(?P<file_path>.*\.yaml): (?P<message>.*)' -- '.' stops at a newline
            let first_line = raw.split('\n').next().unwrap_or("");
            match first_line.rfind(".yaml: ") {
                Some(i) => NetplanError {
                    kind: NetplanErrorKind::Validation {
                        filename: first_line[..i + 5].to_string(),
                    },
                    message: first_line[i + 7..].to_string(),
                }
                .into(),
                None => Exception::err(
                    "ValueError",
                    format!(
                        "The validation error message does not have the expected format: {raw}"
                    ),
                ),
            }
        } else {
            NetplanError {
                kind: NetplanErrorKind::Other,
                message: raw,
            }
            .into()
        }
    }

    /// The message `core.py` prints after "Command failed: ".
    pub fn command_failed_message(&self) -> String {
        match &self.kind {
            NetplanErrorKind::Parser {
                filename,
                line,
                column,
            } => format!("{filename}:{line}:{column}: {}", self.message),
            NetplanErrorKind::Validation { filename } => format!("{filename}: {}", self.message),
            NetplanErrorKind::Other => self.message.clone(),
        }
    }
}

/// Greedy match of `(.*):(\d+):(\d+): ((\s|.)*)` against the whole message,
/// where `.*` cannot span a newline: the location is the last
/// "path:line:col: " on the first line.
fn split_parser_message(raw: &str) -> Option<(String, String, String, String)> {
    let first_line_end = raw.find('\n').unwrap_or(raw.len());
    let mut search_end = first_line_end;
    while let Some(sep) = raw[..search_end].rfind(": ") {
        // `sep` must be preceded by ":<digits>:<digits>"
        let head = &raw[..sep];
        if let Some((rest, col)) = head.rsplit_once(':') {
            if let Some((file, line)) = rest.rsplit_once(':') {
                let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
                if digits(col) && digits(line) {
                    return Some((
                        file.to_string(),
                        line.to_string(),
                        col.to_string(),
                        raw[sep + 2..].to_string(),
                    ));
                }
            }
        }
        if sep == 0 {
            break;
        }
        search_end = sep;
    }
    None
}

impl fmt::Display for NetplanError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for NetplanError {}

/// Report an error that escaped a command the way `core.py` / the Python
/// interpreter would, and return the process exit code.
pub fn report_uncaught(err: &anyhow::Error) -> i32 {
    if let Some(Exit(code)) = err.downcast_ref::<Exit>() {
        return *code;
    }
    if let Some(e) = err.downcast_ref::<NetplanError>() {
        warning(&format!("Command failed: {}", e.command_failed_message()));
        return 1;
    }
    flush_stdout();
    let (kind, message) = match err.downcast_ref::<Exception>() {
        Some(e) => (e.kind, e.message.clone()),
        None => ("RuntimeError", format!("{err:#}")),
    };
    eprintln!("Traceback (most recent call last):\n  (netplan Rust CLI)\n{kind}: {message}");
    1
}

/// Shorthand for `Err(Exit(code))`.
pub fn exit<T>(code: i32) -> anyhow::Result<T> {
    Err(Exit(code).into())
}

// ── Logging ───────────────────────────────────────────────────────────────────

static DEBUG: AtomicBool = AtomicBool::new(false);

/// `logging.basicConfig(level=DEBUG, format='%(levelname)s:%(message)s')`
pub fn enable_debug_logging() {
    DEBUG.store(true, Ordering::Relaxed);
}

pub fn debug_enabled() -> bool {
    DEBUG.load(Ordering::Relaxed)
}

fn log(level: &str, msg: &str) {
    let mut err = std::io::stderr().lock();
    if debug_enabled() {
        let _ = writeln!(err, "{level}:{msg}");
    } else {
        let _ = writeln!(err, "{msg}");
    }
}

pub fn debug(msg: &str) {
    if debug_enabled() {
        log("DEBUG", msg);
    }
}

pub fn info(msg: &str) {
    log("INFO", msg);
}

pub fn warning(msg: &str) {
    log("WARNING", msg);
}

pub fn error(msg: &str) {
    log("ERROR", msg);
}

pub fn critical(msg: &str) {
    log("CRITICAL", msg);
}

// ── stdout ────────────────────────────────────────────────────────────────────

const STDOUT_BUFFER_SIZE: usize = 8192;

struct Stdout {
    buf: Vec<u8>,
    line_buffered: Option<bool>,
}

static STDOUT: Mutex<Stdout> = Mutex::new(Stdout {
    buf: Vec::new(),
    line_buffered: None,
});

impl Stdout {
    fn write_out(&mut self) {
        let mut out = std::io::stdout().lock();
        let _ = out.write_all(&self.buf);
        let _ = out.flush();
        self.buf.clear();
    }
}

/// Write to stdout with `sys.stdout`'s buffering.
pub fn write_stdout(text: &str) {
    let mut s = STDOUT.lock().unwrap_or_else(|e| e.into_inner());
    let line_buffered = *s
        .line_buffered
        .get_or_insert_with(|| nix::unistd::isatty(std::io::stdout()).unwrap_or(false));
    s.buf.extend_from_slice(text.as_bytes());
    if (line_buffered && (text.contains('\n') || text.contains('\r')))
        || s.buf.len() >= STDOUT_BUFFER_SIZE
    {
        s.write_out();
    }
}

/// `sys.stdout.flush()`; also done at exit.
pub fn flush_stdout() {
    let mut s = STDOUT.lock().unwrap_or_else(|e| e.into_inner());
    if !s.buf.is_empty() {
        s.write_out();
    }
}

/// `print(...)` with Python's stdout buffering.
#[macro_export]
macro_rules! pyprint {
    () => { $crate::py::write_stdout("\n") };
    ($($arg:tt)*) => { $crate::py::write_stdout(&format!($($arg)*)) };
}

/// `print(...)` with Python's stdout buffering, ending in a newline.
#[macro_export]
macro_rules! pyprintln {
    () => { $crate::py::write_stdout("\n") };
    ($($arg:tt)*) => { $crate::py::write_stdout(&(format!($($arg)*) + "\n")) };
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parser_message_split() {
        let (f, l, c, m) =
            split_parser_message("/etc/netplan/a.yaml:4:14: Error in network definition: x\n  y")
                .unwrap();
        assert_eq!(
            (f.as_str(), l.as_str(), c.as_str()),
            ("/etc/netplan/a.yaml", "4", "14")
        );
        assert_eq!(m, "Error in network definition: x\n  y");
        assert!(split_parser_message("no location here").is_none());
    }
}
