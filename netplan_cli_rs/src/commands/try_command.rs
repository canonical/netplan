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

//! `netplan try` – apply config with automatic rollback on timeout or rejection.
//!
//! Port of `netplan_cli/cli/commands/try_command.py` and `netplan_cli/terminal.py`.
//!
//! Signals: SIGUSR1 accepts and, once the configuration has been changed,
//! SIGINT rejects (both sent by netplan-dbus). SIGTERM keeps its default
//! action. Python raises the resulting exception wherever it happens to be;
//! here it takes effect at the next step boundary or confirmation tick.

use std::os::fd::{AsFd, BorrowedFd};
use std::path::Path;
use std::sync::atomic::{AtomicI32, Ordering};

use anyhow::Result;
use nix::fcntl::{fcntl, FcntlArg, OFlag};
use nix::sys::signal::{self, SigHandler, Signal};
use nix::sys::termios::{self, LocalFlags, SetArg, Termios};

use crate::argparse::{Arg, Type, Value};
use crate::commands::apply::NetplanApply;
use crate::configmanager::{self, ConfigManager, CONFIG_ERRORS};
use crate::utils::{self, sub};
use crate::{cli, py};

// Keep a timeout long enough to allow the network to converge, 60 seconds may
// be slightly short given some complex configs, i.e. if STP must reconverge.
const DEFAULT_INPUT_TIMEOUT: i64 = 120;

/// `os.EX_CONFIG`
const EX_CONFIG: i32 = 78;

/// `netplan try [--config-file FILE] [--timeout SECONDS] [--state DIR]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "try", cli::description("try"));
    p.add(
        Arg::new(&["--config-file"])
            .help("Apply the config file in argument in addition to current configuration."),
    );
    p.add(
        Arg::new(&["--timeout"])
            .typ(Type::Int)
            .default(Value::Int(DEFAULT_INPUT_TIMEOUT))
            .help("Maximum number of seconds to wait for the user's confirmation"),
    );
    p.add(Arg::new(&["--state"]).help("Directory containing previous YAML configuration"));
    let ns = cli::parse_leaf(&p, args)?;
    let rootdir = std::env::var("DBUS_TEST_NETPLAN_ROOT").unwrap_or_else(|_| "/".into());
    let mut t = NetplanTry {
        config_file: ns.str("config_file"),
        timeout: ns.int("timeout").unwrap_or(DEFAULT_INPUT_TIMEOUT),
        state: ns.str("state"),
        stamp: Path::new(&rootdir)
            .join(utils::TRY_READY_STAMP)
            .to_string_lossy()
            .into_owned(),
        config_manager: ConfigManager::new(&rootdir),
        rootdir,
    };
    t.command_try()
}

struct NetplanTry {
    config_file: Option<String>,
    timeout: i64,
    state: Option<String>,
    rootdir: String,
    stamp: String,
    config_manager: ConfigManager,
}

/// How the confirmation (or a signal) ended the try.
enum Outcome {
    Accepted,
    Rejected,
}

// ── signals ───────────────────────────────────────────────────────────────────

static PENDING_SIGNAL: AtomicI32 = AtomicI32::new(0);
static CONFIGURATION_CHANGED: AtomicI32 = AtomicI32::new(0);

extern "C" fn signal_handler(sig: i32) {
    // SIGINT before the configuration was changed is ignored
    if sig == Signal::SIGUSR1 as i32 || CONFIGURATION_CHANGED.load(Ordering::SeqCst) != 0 {
        PENDING_SIGNAL.store(sig, Ordering::SeqCst);
    }
}

/// The exception a received signal raises, if any.
fn pending_outcome() -> Option<Outcome> {
    match PENDING_SIGNAL.swap(0, Ordering::SeqCst) {
        0 => None,
        s if s == Signal::SIGUSR1 as i32 => Some(Outcome::Accepted),
        _ => Some(Outcome::Rejected),
    }
}

impl NetplanTry {
    fn clear_ready_stamp(&self) -> Result<bool> {
        if Path::new(&self.stamp).is_file() {
            std::fs::remove_file(&self.stamp)
                .map_err(|e| utils::oserror(&e, Path::new(&self.stamp)))?;
            return Ok(true);
        }
        Ok(false)
    }

    fn touch_ready_stamp(&self) -> Result<()> {
        let dir = format!("{}/run/netplan", self.rootdir);
        std::fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&dir)
            .map_err(|e| utils::oserror(&e, Path::new(&dir)))?;
        std::fs::File::create(&self.stamp)
            .map_err(|e| utils::oserror(&e, Path::new(&self.stamp)))?;
        Ok(())
    }

    fn safe_revert(&mut self, reason: Option<&str>) -> Result<i32> {
        if let Some(r) = reason {
            crate::pyprintln!("\n{r}");
        }
        crate::pyprintln!("\nReverting.");
        match self.revert() {
            Ok(()) => Ok(0),
            Err(e) if sub::is_exception(&e, &["Exception"]) => {
                crate::pyprintln!("\nAn error occurred while reverting: {e}");
                crate::pyprintln!("\nPlease check the configuration state");
                Ok(1)
            }
            Err(e) => Err(e),
        }
    }

    fn command_try(&mut self) -> Result<i32> {
        if !self.is_revertable()? {
            return py::exit(EX_CONFIG);
        }

        let stdin = std::io::stdin();
        let fd = stdin.as_fd();
        let mut terminal: Option<Terminal> = None;
        let result = (|| -> Result<Outcome> {
            terminal = Some(Terminal::new(fd)?);

            // we really don't want to be interrupted while doing backup/revert operations
            // SAFETY: the handler only stores into atomics.
            unsafe {
                signal::signal(Signal::SIGINT, SigHandler::Handler(signal_handler))?;
                signal::signal(Signal::SIGUSR1, SigHandler::Handler(signal_handler))?;
            }

            self.config_manager.backup(self.config_file.is_some())?;
            if let Some(o) = pending_outcome() {
                return Ok(o);
            }
            self.setup()?;
            if let Some(o) = pending_outcome() {
                return Ok(o);
            }

            let mut apply = NetplanApply::default();
            apply.command_apply(true, true, false, self.state.as_deref())?;
            if let Some(o) = pending_outcome() {
                return Ok(o);
            }

            // Touch stamp file, it is the signal (for netplan-dbus) that we're
            // ready to accept any Accept/Reject input (like SIGUSR1 or SIGTERM)
            self.touch_ready_stamp()?;
            terminal
                .as_ref()
                .unwrap()
                .get_confirmation_input(self.timeout)
        })();

        let mut exit_code = 0;
        let outcome = match result {
            Ok(Outcome::Rejected) => self.safe_revert(None),
            Ok(Outcome::Accepted) => {
                crate::pyprintln!("\nConfiguration accepted.");
                Ok(0)
            }
            Err(e) if sub::is_exception(&e, &["Exception"]) => {
                self.safe_revert(Some(&format!("An error occurred: {e}")))
            }
            Err(e) => Err(e),
        };
        // finally:
        if let Some(t) = &terminal {
            t.reset(&t.orig)?;
        }
        self.config_manager.cleanup()?;
        self.clear_ready_stamp()?;
        exit_code = outcome.map(|c| c.max(exit_code))?;
        py::exit(exit_code)
    }

    fn setup(&mut self) -> Result<()> {
        if let Some(cf) = &self.config_file {
            let base = Path::new(cf)
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default();
            // str.rstrip('.yaml') strips any trailing '.', 'y', 'a', 'm', 'l'
            let dest_name = base.trim_end_matches(['.', 'y', 'a', 'm', 'l']);
            let dest_path = format!("/etc/netplan/{dest_name}.{}.yaml", py_time());
            self.config_manager.add(&[(cf.clone(), dest_path)])?;
        }
        CONFIGURATION_CHANGED.store(1, Ordering::SeqCst);
        Ok(())
    }

    fn revert(&mut self) -> Result<()> {
        let tempdir = configmanager::mkdtemp("tmp")?;
        let result = (|| -> Result<()> {
            // backup the state we just tried to apply
            let confdir = tempdir.join("etc").join("netplan");
            std::fs::create_dir_all(&confdir).map_err(|e| utils::oserror(&e, &confdir))?;
            configmanager::copy_tree(Path::new("/etc/netplan"), &confdir, false, true)?;
            // restore previous state
            self.config_manager.revert()?;
            let mut apply = NetplanApply::default();
            apply.command_apply(false, true, false, Some(&tempdir.to_string_lossy()))
        })();
        if let Err(e) = std::fs::remove_dir_all(&tempdir) {
            py::warning(&format!(
                "Failed to remove temporary directory {}: {}",
                tempdir.display(),
                utils::py_oserror_str(&e, &tempdir)
            ));
        }
        result
    }

    /// Check if the configuration is revertable: bridges and bonds with
    /// custom parameters cannot be reliably reverted by the backends.
    fn is_revertable(&mut self) -> Result<bool> {
        let extra: Vec<String> = self.config_file.iter().cloned().collect();
        match self.config_manager.parse(&extra) {
            Ok(_) => {}
            Err(e) if sub::is_exception(&e, CONFIG_ERRORS) => {
                py::error(&e.to_string());
                return py::exit(EX_CONFIG);
            }
            Err(e) => return Err(e),
        }
        let state = self.config_manager.np_state.as_ref().unwrap();

        let mut multi_iface: Vec<(String, bool)> = vec![];
        for t in ["bridges", "bonds"] {
            for nd in state.netdefs_of_type(t) {
                let id = nd.id().unwrap_or_default();
                let trivial = nd.is_trivial_compound_itf();
                match multi_iface.iter_mut().find(|(k, _)| *k == id) {
                    Some(e) => e.1 = trivial,
                    None => multi_iface.push((id, trivial)),
                }
            }
        }
        let reason = "reverting custom parameters for bridges and bonds is not supported";
        let unsupported: Vec<&String> = multi_iface
            .iter()
            .filter(|(_, t)| !t)
            .map(|(id, _)| id)
            .collect();
        if !unsupported.is_empty() {
            for ifname in unsupported {
                crate::pyprintln!("{ifname}: {reason}");
            }
            crate::pyprintln!(
                "\nPlease carefully review the configuration and use 'netplan apply' directly."
            );
            return Ok(false);
        }
        Ok(true)
    }
}

/// `str(time.time())`
fn py_time() -> String {
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    let s = format!("{t}");
    if s.contains('.') {
        s
    } else {
        s + ".0"
    }
}

// ── Terminal (netplan_cli/terminal.py) ────────────────────────────────────────

/// Saved terminal attributes and file status flags.
#[derive(Clone)]
struct Settings {
    flags: OFlag,
    term: Option<Termios>,
}

/// Minimal terminal mangling to prompt users for input.
struct Terminal<'a> {
    fd: BorrowedFd<'a>,
    orig: Settings,
}

impl<'a> Terminal<'a> {
    fn new(fd: BorrowedFd<'a>) -> Result<Self> {
        let orig = Self::save(fd)?;
        Ok(Terminal { fd, orig })
    }

    fn save(fd: BorrowedFd<'_>) -> Result<Settings> {
        let flags = OFlag::from_bits_retain(fcntl(fd, FcntlArg::F_GETFL).map_err(errno_error)?);
        let term = if nix::unistd::isatty(fd).unwrap_or(false) {
            Some(termios::tcgetattr(fd).map_err(errno_error)?)
        } else {
            None
        };
        Ok(Settings { flags, term })
    }

    /// Reset the terminal to the given attributes and flags.
    fn reset(&self, settings: &Settings) -> Result<()> {
        if nix::unistd::isatty(self.fd).unwrap_or(false) {
            if let Some(t) = &settings.term {
                termios::tcsetattr(self.fd, SetArg::TCSAFLUSH, t).map_err(errno_error)?;
            }
        }
        fcntl(self.fd, FcntlArg::F_SETFL(settings.flags)).map_err(errno_error)?;
        Ok(())
    }

    fn disable_echo(&self) -> Result<()> {
        if nix::unistd::isatty(self.fd).unwrap_or(false) {
            let mut attrs = termios::tcgetattr(self.fd).map_err(errno_error)?;
            attrs
                .local_flags
                .remove(LocalFlags::ICANON | LocalFlags::ECHO);
            termios::tcsetattr(self.fd, SetArg::TCSANOW, &attrs).map_err(errno_error)?;
        }
        Ok(())
    }

    fn enable_nonblocking_io(&self) -> Result<()> {
        let flags =
            OFlag::from_bits_retain(fcntl(self.fd, FcntlArg::F_GETFL).map_err(errno_error)?);
        fcntl(self.fd, FcntlArg::F_SETFL(flags | OFlag::O_NONBLOCK)).map_err(errno_error)?;
        Ok(())
    }

    /// Get a "confirmation" input from the user, for at most `timeout`
    /// seconds: accepted only if a one-second poll reads exactly "\n".
    fn get_confirmation_input(&self, timeout: i64) -> Result<Outcome> {
        crate::pyprintln!("Do you want to keep these settings?\n\n");

        let settings = Self::save(self.fd)?;
        self.disable_echo()?;
        self.enable_nonblocking_io()?;

        let message = "accept the new configuration";
        crate::pyprintln!("Press ENTER before the timeout to {message}\n\n");
        let width = timeout.to_string().len();
        let mut timeout_now = timeout;
        while timeout_now > 0 {
            crate::pyprint!("Changes will revert in {timeout_now:>width$} seconds\r");

            // wait at most 1 second for usable input from stdin
            let mut fds = [nix::poll::PollFd::new(
                self.fd,
                nix::poll::PollFlags::POLLIN,
            )];
            let _ = nix::poll::poll(&mut fds, nix::poll::PollTimeout::from(1000u16));
            if let Some(o) = pending_outcome() {
                self.reset(&settings)?;
                return Ok(o);
            }
            // retrieve any input from the terminal. poll() either has
            // timed out with no input, or found something we can retrieve.
            if read_available(self.fd).as_deref() == Some("\n") {
                self.reset(&settings)?;
                // Yay, user has accepted the changes!
                return Ok(Outcome::Accepted);
            }
            timeout_now -= 1;
        }

        // We reached the timeout for our loop, now revert our change for
        // non-blocking I/O and signal the caller the changes were essentially
        // rejected.
        self.reset(&settings)?;
        Ok(Outcome::Rejected)
    }
}

/// A non-blocking text `read()` of everything available: `None` when
/// nothing is available yet, `""` at end of file.
fn read_available(fd: BorrowedFd<'_>) -> Option<String> {
    let mut data = Vec::new();
    let mut buf = [0u8; 4096];
    loop {
        match nix::unistd::read(fd, &mut buf) {
            Ok(0) => break,
            Ok(n) => data.extend_from_slice(&buf[..n]),
            Err(nix::errno::Errno::EINTR) => continue,
            Err(_) if data.is_empty() => return None,
            Err(_) => break,
        }
    }
    // universal newlines
    Some(
        String::from_utf8_lossy(&data)
            .replace("\r\n", "\n")
            .replace('\r', "\n"),
    )
}

fn errno_error(e: nix::errno::Errno) -> anyhow::Error {
    py::Exception::err("OSError", format!("[Errno {}] {}", e as i32, e.desc()))
}

use std::os::unix::fs::DirBuilderExt;
