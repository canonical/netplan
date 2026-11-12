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

//! Port of `netplan_cli/cli/utils.py`, plus the Python standard library
//! behaviour it depends on (`glob`, `fnmatch`, `os.path.realpath`).
//!
//! Functions keep the Python names and semantics: subprocess failures raise
//! the same exceptions (see [`sub`]), and helpers that swallow errors in
//! Python swallow the same errors here.

pub mod process;
pub mod sub;

use std::path::{Path, PathBuf};

use anyhow::Result;

use crate::py;
use sub::Io;

// ── Paths ─────────────────────────────────────────────────────────────────────

pub const GENERATOR_LATE_DIR: &str = "/run/systemd/generator.late/";
/// Relative to a root dir.
pub const TRY_READY_STAMP: &str = "run/netplan/netplan-try.ready";

pub const NM_SERVICE_NAME: &str = "NetworkManager.service";
pub const NM_SNAP_SERVICE_NAME: &str = "snap.network-manager.networkmanager.service";

pub fn get_generator_path() -> String {
    std::env::var("NETPLAN_GENERATE_PATH")
        .unwrap_or_else(|_| "/usr/libexec/netplan/generate".into())
}

pub fn get_configure_path() -> String {
    std::env::var("NETPLAN_CONFIGURE_PATH")
        .unwrap_or_else(|_| "/usr/libexec/netplan/configure".into())
}

/// `shutil.which(name)`
pub fn which(name: &str) -> Option<PathBuf> {
    use std::os::unix::fs::PermissionsExt;
    let path = std::env::var("PATH").unwrap_or_else(|_| "/bin:/usr/bin".to_string());
    path.split(':')
        .map(|dir| Path::new(if dir.is_empty() { "." } else { dir }).join(name))
        .find(|p| {
            p.metadata()
                .map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
                .unwrap_or(false)
        })
}

// ── NetworkManager ────────────────────────────────────────────────────────────

pub fn is_nm_snap_enabled() -> Result<bool> {
    Ok(sub::call_with(
        &["systemctl", "--quiet", "is-enabled", NM_SNAP_SERVICE_NAME],
        Io::Inherit,
        Io::Null,
    )? == 0)
}

pub fn nmcli(args: &[&str]) -> Result<()> {
    let argv: Vec<&str> = std::iter::once("nmcli")
        .chain(args.iter().copied())
        .collect();
    sub::check_call_with(&argv, Io::Null, Io::Null)
}

pub fn nmcli_out(args: &[&str]) -> Result<String> {
    let argv: Vec<&str> = std::iter::once("nmcli")
        .chain(args.iter().copied())
        .collect();
    sub::check_output(&argv)
}

/// Check if NetworkManager is running
pub fn nm_running() -> Result<bool> {
    match nmcli(&["general"]) {
        Ok(()) => Ok(true),
        Err(e) if sub::is_exception(&e, &["OSError", "subprocess.SubprocessError"]) => Ok(false),
        Err(e) => Err(e),
    }
}

/// Interfaces named by `interface-name=` in the given NM connection files,
/// expanded against `devices`. A Python set: callers must not rely on order.
pub fn nm_interfaces(paths: &[String], devices: &[String]) -> Result<Vec<String>> {
    let mut interfaces: Vec<String> = vec![];
    for path in paths {
        let content = read_text(path)?;
        for line in content.split_inclusive('\n') {
            // re.match('^interface-name=(.*)$', line): '.' stops at '\n'
            if let Some(rest) = line.strip_prefix("interface-name=") {
                let pattern = rest.strip_suffix('\n').unwrap_or(rest);
                if pattern.contains('\n') {
                    continue;
                }
                for d in devices.iter().filter(|d| fnmatch(d, pattern)) {
                    if !interfaces.contains(d) {
                        interfaces.push(d.clone());
                    }
                }
                break;
            }
        }
    }
    Ok(interfaces)
}

pub fn nm_get_connection_for_interface(interface: &str) -> Result<String> {
    let output = nmcli_out(&[
        "-m",
        "tabular",
        "-f",
        "GENERAL.CONNECTION",
        "device",
        "show",
        interface,
    ])?;
    let lines: Vec<&str> = output.trim().split('\n').collect();
    let Some(connection) = lines.get(1) else {
        return Err(py::Exception::err("IndexError", "list index out of range"));
    };
    Ok(if *connection != "--" {
        connection.to_string()
    } else {
        String::new()
    })
}

pub fn nm_bring_interface_up(connection: &str) -> Result<()> {
    match nmcli(&["connection", "up", connection]) {
        Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => Ok(()),
        other => other,
    }
}

pub fn systemctl_network_manager(action: &str, sync: bool) -> Result<()> {
    // If the network-manager snap is installed use its service
    // name rather than the one of the deb packaged NetworkManager
    if is_nm_snap_enabled()? {
        return systemctl(action, &[NM_SNAP_SERVICE_NAME], sync);
    }
    systemctl(action, &[NM_SERVICE_NAME], sync)
}

// ── systemd ───────────────────────────────────────────────────────────────────

pub fn systemctl<S: AsRef<str>>(action: &str, services: &[S], sync: bool) -> Result<()> {
    if services.is_empty() {
        return Ok(());
    }
    let mut command = vec!["systemctl", action];
    if !sync {
        command.push("--no-block");
    }
    command.extend(services.iter().map(AsRef::as_ref));
    sub::check_call(&command)
}

/// networkd-managed interface indices. A Python set: unordered.
pub fn networkd_interfaces() -> Result<Vec<String>> {
    let out = sub::check_output(&["networkctl", "--no-pager", "--no-legend"])?;
    let mut interfaces: Vec<String> = vec![];
    for line in py_splitlines(&out) {
        let s: Vec<&str> = line.trim().split(' ').collect();
        let first = s[0];
        let last = s[s.len() - 1];
        if !first.is_empty()
            && first.chars().all(char::is_numeric)
            && !["unmanaged", "linger"].contains(&last)
            && !interfaces.iter().any(|i| i == first)
        {
            interfaces.push(first.to_string());
        }
    }
    Ok(interfaces)
}

pub fn networkctl_reload() -> Result<()> {
    sub::check_call(&["networkctl", "reload"])
}

pub fn networkctl_reconfigure(interfaces: &[String]) -> Result<()> {
    if interfaces.is_empty() {
        return Ok(());
    }
    let mut argv = vec!["networkctl", "reconfigure"];
    argv.extend(interfaces.iter().map(String::as_str));
    sub::check_call(&argv)
}

/// Return True if at least one matching unit is running
#[allow(dead_code)] // used by `netplan status` (port pending)
pub fn systemctl_is_active(unit_pattern: &str) -> Result<bool> {
    Ok(sub::call(&["systemctl", "--quiet", "is-active", unit_pattern])? == 0)
}

/// Return True if output is "masked" or "masked-runtime"
#[allow(dead_code)] // used by `netplan status` (port pending)
pub fn systemctl_is_masked(unit_pattern: &str) -> Result<bool> {
    let res = sub::run(
        &["systemctl", "is-enabled", unit_pattern],
        Io::Pipe,
        Io::Pipe,
    )?;
    Ok(res.returncode > 0 && res.stdout.contains("masked"))
}

/// Return True if returncode is other than "not-found" (4)
#[allow(dead_code)] // used by `netplan status` (port pending)
pub fn systemctl_is_installed(unit_pattern: &str) -> Result<bool> {
    let res = sub::run(&["systemctl", "status", unit_pattern], Io::Pipe, Io::Pipe)?;
    Ok(res.returncode != 4)
}

/// Reload systemd unit files from disk and re-calculate its dependencies
pub fn systemctl_daemon_reload() -> Result<i32> {
    sub::call(&["systemctl", "daemon-reload", "--no-ask-password"])
}

/// Flush all IP addresses of a given interface via iproute2
pub fn ip_addr_flush(iface: &str) -> Result<()> {
    sub::check_call_with(&["ip", "addr", "flush", iface], Io::Null, Io::Null)
}

// ── interfaces ────────────────────────────────────────────────────────────────

pub fn get_interface_driver_name(interface: &str, only_down: bool) -> Option<String> {
    let devdir = Path::new("/sys/class/net").join(interface);
    if only_down {
        match std::fs::read_to_string(devdir.join("operstate")) {
            Ok(s) => {
                let state = s.trim();
                if state != "down" {
                    py::debug(&format!(
                        "device {interface} operstate is {state}, not changing"
                    ));
                    return None;
                }
            }
            Err(e) => {
                py::error(&format!(
                    "Cannot determine operstate of {interface}: {}",
                    py_oserror_str(&e, &devdir.join("operstate"))
                ));
                return None;
            }
        }
    }
    let driver = realpath(&devdir.join("device").join("driver"));
    Some(
        driver
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default(),
    )
}

fn get_permanent_macaddress(interface: &str) -> Option<String> {
    let out = sub::check_output(&["ethtool", "-P", interface]).ok()?;
    let split: Vec<&str> = out.split(": ").collect();
    if split.len() == 2 && is_valid_macaddress(split[1].trim()) {
        return Some(split[1].trim().to_string());
    }
    None
}

fn get_macaddress(interface: &str) -> Option<String> {
    std::fs::read_to_string(format!("/sys/class/net/{interface}/address"))
        .ok()
        .map(|s| s.trim().to_string())
}

/// Interface names from `ip --json link`, or `[]` on any error.
pub fn get_interfaces() -> Vec<String> {
    let Ok(out) = sub::check_output(&["ip", "--json", "link"]) else {
        return vec![];
    };
    let Ok(serde_json::Value::Array(links)) = serde_json::from_str::<serde_json::Value>(&out)
    else {
        return vec![];
    };
    let mut names = vec![];
    for link in links {
        match link.get("ifname") {
            Some(serde_json::Value::String(n)) => names.push(n.clone()),
            // a KeyError/TypeError aborts the whole list comprehension
            _ => return vec![],
        }
    }
    names
}

pub fn get_interface_macaddress(interface: &str) -> Option<String> {
    get_permanent_macaddress(interface).or_else(|| get_macaddress(interface))
}

pub fn find_matching_iface(
    interfaces: &[String],
    netdef: &crate::netplan::NetDef,
) -> Option<String> {
    let matches: Vec<&String> = interfaces
        .iter()
        .filter(|itf| {
            let driver = get_interface_driver_name(itf, false);
            let mac = get_interface_macaddress(itf);
            // empty strings are passed to libnetplan as NULL
            netdef.matches_interface(
                itf,
                mac.as_deref().filter(|m| !m.is_empty()),
                driver.as_deref().filter(|d| !d.is_empty()),
            )
        })
        .collect();
    // Return current name of unique matched interface, if available
    if matches.len() != 1 {
        py::info(&py_repr_list(&matches));
        return None;
    }
    Some(matches[0].clone())
}

pub fn is_valid_macaddress(macaddress: &str) -> bool {
    // '^[a-fA-F0-9][a-fA-F0-9](:[a-fA-F0-9][a-fA-F0-9]){5}((:[a-fA-F0-9][a-fA-F0-9]){14})?$'
    let s = macaddress.strip_suffix('\n').unwrap_or(macaddress);
    let groups: Vec<&str> = s.split(':').collect();
    (groups.len() == 6 || groups.len() == 20)
        && groups
            .iter()
            .all(|g| g.len() == 2 && g.bytes().all(|b| b.is_ascii_hexdigit()))
}

// ── Python standard library helpers ───────────────────────────────────────────

/// `open(path).read()` in text mode (universal newlines).
pub fn read_text(path: &str) -> Result<String> {
    match std::fs::read(path) {
        Ok(bytes) => Ok(String::from_utf8_lossy(&bytes)
            .replace("\r\n", "\n")
            .replace('\r', "\n")),
        Err(e) => Err(oserror(&e, Path::new(path))),
    }
}

/// The OSError subclass Python raises for an I/O error on `path`.
pub fn oserror(e: &std::io::Error, path: &Path) -> anyhow::Error {
    let kind = match e.raw_os_error() {
        Some(2) => "FileNotFoundError",
        Some(13) | Some(1) => "PermissionError",
        Some(21) => "IsADirectoryError",
        Some(20) => "NotADirectoryError",
        Some(17) => "FileExistsError",
        _ => "OSError",
    };
    py::Exception::err(kind, py_oserror_str(e, path))
}

/// `str(OSError)`: "[Errno 2] No such file or directory: '/path'"
pub fn py_oserror_str(e: &std::io::Error, path: &Path) -> String {
    let errno = e.raw_os_error().unwrap_or(0);
    let msg = nix::errno::Errno::from_raw(errno).desc();
    format!("[Errno {errno}] {msg}: '{}'", path.display())
}

/// `str.splitlines()`
pub fn py_splitlines(s: &str) -> Vec<&str> {
    let mut out = vec![];
    let mut start = 0;
    let mut chars = s.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        let is_break = matches!(
            c,
            '\n' | '\r'
                | '\x0b'
                | '\x0c'
                | '\x1c'
                | '\x1d'
                | '\x1e'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        );
        if is_break {
            out.push(&s[start..i]);
            let mut next = i + c.len_utf8();
            if c == '\r' {
                if let Some(&(j, '\n')) = chars.peek() {
                    chars.next();
                    next = j + 1;
                }
            }
            start = next;
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

/// `repr()` of a Python list of strings.
pub fn py_repr_list<S: AsRef<str>>(items: &[S]) -> String {
    let parts: Vec<String> = items.iter().map(|s| py_repr_str(s.as_ref())).collect();
    format!("[{}]", parts.join(", "))
}

/// `repr()` of a Python str.
pub fn py_repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::from(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                out.push_str(&format!("\\x{:02x}", c as u32))
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `os.path.realpath(path)` (non-strict): resolve symlinks as far as the
/// path exists, keep the remaining components as they are.
pub fn realpath(path: &Path) -> PathBuf {
    let mut resolved = PathBuf::from("/");
    let mut pending: Vec<std::ffi::OsString> = path
        .components()
        .rev()
        .filter_map(|c| match c {
            std::path::Component::Normal(n) => Some(n.to_os_string()),
            std::path::Component::ParentDir => Some("..".into()),
            _ => None,
        })
        .collect();
    let mut hops = 0;
    while let Some(part) = pending.pop() {
        if part == ".." {
            resolved.pop();
            continue;
        }
        let candidate = resolved.join(&part);
        match std::fs::read_link(&candidate) {
            Ok(target) if hops < 40 => {
                hops += 1;
                if target.is_absolute() {
                    resolved = PathBuf::from("/");
                }
                for c in target.components().rev() {
                    match c {
                        std::path::Component::Normal(n) => pending.push(n.to_os_string()),
                        std::path::Component::ParentDir => pending.push("..".into()),
                        _ => {}
                    }
                }
            }
            _ => resolved = candidate,
        }
    }
    resolved
}

/// `fnmatch.fnmatch(name, pattern)` (case-sensitive, as on POSIX).
pub fn fnmatch(name: &str, pattern: &str) -> bool {
    let tokens = fnmatch_translate(pattern);
    let name: Vec<char> = name.chars().collect();
    match_tokens(&tokens, &name)
}

enum Tok {
    Star,
    Any,
    Lit(char),
    /// `[...]`: negated, ranges; an empty, non-negated set never matches
    Class(bool, Vec<(char, char)>),
}

fn fnmatch_translate(pat: &str) -> Vec<Tok> {
    let p: Vec<char> = pat.chars().collect();
    let mut out = vec![];
    let mut i = 0;
    while i < p.len() {
        let c = p[i];
        i += 1;
        match c {
            '*' => {
                if !matches!(out.last(), Some(Tok::Star)) {
                    out.push(Tok::Star);
                }
            }
            '?' => out.push(Tok::Any),
            '[' => {
                let mut j = i;
                if j < p.len() && p[j] == '!' {
                    j += 1;
                }
                if j < p.len() && p[j] == ']' {
                    j += 1;
                }
                while j < p.len() && p[j] != ']' {
                    j += 1;
                }
                if j >= p.len() {
                    out.push(Tok::Lit('['));
                    continue;
                }
                let mut stuff: &[char] = &p[i..j];
                i = j + 1;
                let negate = stuff.first() == Some(&'!');
                if negate {
                    stuff = &stuff[1..];
                }
                let mut ranges = vec![];
                let mut k = 0;
                while k < stuff.len() {
                    if k + 2 < stuff.len() && stuff[k + 1] == '-' {
                        if stuff[k] <= stuff[k + 2] {
                            ranges.push((stuff[k], stuff[k + 2]));
                        }
                        k += 3;
                    } else {
                        ranges.push((stuff[k], stuff[k]));
                        k += 1;
                    }
                }
                out.push(Tok::Class(negate, ranges));
            }
            c => out.push(Tok::Lit(c)),
        }
    }
    out
}

fn match_tokens(toks: &[Tok], s: &[char]) -> bool {
    match toks.first() {
        None => s.is_empty(),
        Some(Tok::Star) => (0..=s.len()).any(|k| match_tokens(&toks[1..], &s[k..])),
        Some(t) => {
            let Some(&c) = s.first() else { return false };
            let ok = match t {
                Tok::Any => true,
                Tok::Lit(l) => *l == c,
                Tok::Class(neg, ranges) => ranges.iter().any(|(a, b)| *a <= c && c <= *b) != *neg,
                Tok::Star => unreachable!(),
            };
            ok && match_tokens(&toks[1..], &s[1..])
        }
    }
}

fn has_magic(s: &str) -> bool {
    s.contains(['*', '?', '['])
}

/// `glob.glob(pattern)`: results in directory (readdir) order, hidden
/// names only matched by patterns starting with '.'.
pub fn glob_paths(pattern: &str) -> Vec<String> {
    let (dirname, basename) = match pattern.rfind('/') {
        Some(i) => (&pattern[..=i], &pattern[i + 1..]),
        None => ("", pattern),
    };
    let dirname = if dirname.len() > 1 {
        dirname.trim_end_matches('/')
    } else {
        dirname
    };
    if !has_magic(pattern) {
        return if Path::new(pattern).symlink_metadata().is_ok() {
            vec![pattern.to_string()]
        } else {
            vec![]
        };
    }
    let dirs: Vec<String> = if dirname.is_empty() {
        vec![String::new()]
    } else if has_magic(dirname) {
        glob_paths(dirname)
    } else {
        vec![dirname.to_string()]
    };
    let mut out = vec![];
    for dir in dirs {
        let names: Vec<String> = if has_magic(basename) {
            let lookup = if dir.is_empty() { "." } else { dir.as_str() };
            let Ok(entries) = std::fs::read_dir(lookup) else {
                continue;
            };
            entries
                .flatten()
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .filter(|n| basename.starts_with('.') || !n.starts_with('.'))
                .filter(|n| fnmatch(n, basename))
                .collect()
        } else if basename.is_empty() {
            if Path::new(&dir).is_dir() {
                vec![String::new()]
            } else {
                vec![]
            }
        } else if Path::new(&dir).join(basename).symlink_metadata().is_ok() {
            vec![basename.to_string()]
        } else {
            vec![]
        };
        for n in names {
            out.push(if dir.is_empty() {
                n
            } else if dir.ends_with('/') {
                format!("{dir}{n}")
            } else {
                format!("{dir}/{n}")
            });
        }
    }
    out
}

// ── Dotted key paths ─────────────────────────────────────────────────────────

/// Split a dotted key path on `.` but not on `\.`.
/// Each part has `\.` sequences replaced with `.`.
///
/// Equivalent to:
/// ```python
/// [s.replace(r'\.', '.') for s in re.split(r'(?<!\\)\.', key)]
/// ```
pub fn split_dotted_path(key: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut chars = key.chars().peekable();

    while let Some(c) = chars.next() {
        match c {
            '\\' if chars.peek() == Some(&'.') => {
                chars.next(); // consume the escaped dot
                current.push('.');
            }
            '.' => parts.push(std::mem::take(&mut current)),
            _ => current.push(c),
        }
    }
    parts.push(current);
    parts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fnmatch_semantics() {
        assert!(fnmatch("eth0", "eth*"));
        assert!(fnmatch("eth0", "eth[0-9]"));
        assert!(!fnmatch("eth0", "eth[!0-9]"));
        assert!(fnmatch("a[b", "a[b"));
        assert!(!fnmatch("eth0", "Eth*"));
    }

    #[test]
    fn repr() {
        assert_eq!(py_repr_list(&["a", "b'c"]), "['a', \"b'c\"]");
        assert_eq!(py_repr_list::<&str>(&[]), "[]");
    }

    #[test]
    fn splitlines() {
        assert_eq!(py_splitlines("a\r\nb\rc\n"), vec!["a", "b", "c"]);
    }
}
