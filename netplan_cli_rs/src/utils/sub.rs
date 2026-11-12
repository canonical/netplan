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

//! Python `subprocess` semantics: `call()` returns the exit status
//! (negative signal number if killed), `check_call()`/`check_output()` raise
//! `CalledProcessError` on a non-zero status, and a program that cannot be
//! started raises `FileNotFoundError`/`PermissionError`.

use std::process::{Command, Stdio};

use anyhow::Result;

use crate::py::Exception;

/// Where a child's stdout/stderr goes.
#[derive(Clone, Copy, PartialEq)]
pub enum Io {
    /// inherited from this process (the default)
    Inherit,
    /// `subprocess.DEVNULL`
    Null,
    /// `subprocess.PIPE`
    Pipe,
    /// `stderr=subprocess.STDOUT` (merged into a piped stdout)
    Stdout,
}

fn stdio(io: Io) -> Stdio {
    match io {
        Io::Inherit => Stdio::inherit(),
        Io::Null => Stdio::null(),
        Io::Pipe | Io::Stdout => Stdio::piped(),
    }
}

/// The OSError Python raises when `argv[0]` cannot be executed.
fn spawn_error(argv0: &str, e: std::io::Error) -> anyhow::Error {
    match e.kind() {
        std::io::ErrorKind::NotFound => Exception::err(
            "FileNotFoundError",
            format!("[Errno 2] No such file or directory: '{argv0}'"),
        ),
        std::io::ErrorKind::PermissionDenied => Exception::err(
            "PermissionError",
            format!("[Errno 13] Permission denied: '{argv0}'"),
        ),
        _ => Exception::err("OSError", format!("{e}: '{argv0}'")),
    }
}

/// Exit status as Python's `Popen.returncode`.
fn returncode(status: std::process::ExitStatus) -> i32 {
    use std::os::unix::process::ExitStatusExt;
    status
        .code()
        .unwrap_or_else(|| -status.signal().unwrap_or(0))
}

/// The result of a finished child process.
pub struct Completed {
    pub returncode: i32,
    pub stdout: String,
    #[allow(dead_code)] // used by `netplan status` (port pending)
    pub stderr: String,
}

/// `subprocess.run(argv, stdout=..., stderr=...)`
pub fn run(argv: &[&str], stdout: Io, stderr: Io) -> Result<Completed> {
    let mut cmd = Command::new(argv[0]);
    cmd.args(&argv[1..]).stdout(stdio(stdout));
    if stderr == Io::Stdout {
        // Share one pipe for both streams.
        let (reader, writer) = std::io::pipe().map_err(|e| spawn_error(argv[0], e))?;
        let writer2 = writer.try_clone().map_err(|e| spawn_error(argv[0], e))?;
        cmd.stdout(writer).stderr(writer2);
        let mut child = cmd.spawn().map_err(|e| spawn_error(argv[0], e))?;
        drop(cmd);
        let mut out = Vec::new();
        let mut reader = reader;
        std::io::Read::read_to_end(&mut reader, &mut out).ok();
        let status = child.wait().map_err(|e| spawn_error(argv[0], e))?;
        return Ok(Completed {
            returncode: returncode(status),
            stdout: String::from_utf8_lossy(&out).into_owned(),
            stderr: String::new(),
        });
    }
    cmd.stderr(stdio(stderr));
    let out = cmd.output().map_err(|e| spawn_error(argv[0], e))?;
    Ok(Completed {
        returncode: returncode(out.status),
        stdout: String::from_utf8_lossy(&out.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
    })
}

/// `subprocess.call(argv)`
pub fn call(argv: &[&str]) -> Result<i32> {
    call_with(argv, Io::Inherit, Io::Inherit)
}

/// `subprocess.call(argv, stdout=..., stderr=...)`
pub fn call_with(argv: &[&str], stdout: Io, stderr: Io) -> Result<i32> {
    Ok(run(argv, stdout, stderr)?.returncode)
}

/// `subprocess.check_call(argv)`
pub fn check_call(argv: &[&str]) -> Result<()> {
    check_call_with(argv, Io::Inherit, Io::Inherit)
}

/// `subprocess.check_call(argv, stdout=..., stderr=...)`
pub fn check_call_with(argv: &[&str], stdout: Io, stderr: Io) -> Result<()> {
    let rc = call_with(argv, stdout, stderr)?;
    if rc != 0 {
        return Err(Exception::called_process_error(argv, rc));
    }
    Ok(())
}

/// `subprocess.check_output(argv)` (stderr inherited), decoded as text.
pub fn check_output(argv: &[&str]) -> Result<String> {
    let c = run(argv, Io::Pipe, Io::Inherit)?;
    if c.returncode != 0 {
        return Err(Exception::called_process_error(argv, c.returncode));
    }
    Ok(c.stdout)
}

/// Whether `err` is one of the given Python exception classes, honouring
/// the parts of the class hierarchy netplan relies on (`OSError` covers
/// `FileNotFoundError`/`PermissionError`, `SubprocessError` covers
/// `CalledProcessError`, `Exception` covers everything but `SystemExit`).
pub fn is_exception(err: &anyhow::Error, classes: &[&str]) -> bool {
    if err.downcast_ref::<crate::py::Exit>().is_some() {
        return false;
    }
    let kind = match err.downcast_ref::<Exception>() {
        Some(e) => e.kind,
        None if err.downcast_ref::<crate::py::NetplanError>().is_some() => "NetplanException",
        None => "RuntimeError",
    };
    classes.iter().any(|&c| {
        c == kind
            || c == "Exception"
            || (c == "OSError"
                && matches!(
                    kind,
                    "FileNotFoundError"
                        | "PermissionError"
                        | "IsADirectoryError"
                        | "NotADirectoryError"
                ))
            || (c == "subprocess.SubprocessError" && kind == "subprocess.CalledProcessError")
    })
}
