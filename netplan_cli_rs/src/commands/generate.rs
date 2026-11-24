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

//! `netplan generate` – produce backend-specific config from YAML sources.
//!
//! Port of `netplan_cli/cli/commands/generate.py`.

use std::path::Path;

use anyhow::Result;

use crate::argparse::Arg;
use crate::utils::{self, sub};
use crate::{cli, py};

/// `netplan generate [--root-dir DIR] [--mapping IFACE]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "generate", cli::description("generate"));
    p.add(
        Arg::new(&["--root-dir"]).help(
            "Search for and generate configuration files in this root directory instead of /",
        ),
    );
    p.add(
        Arg::new(&["--mapping"])
            .help("Display the netplan device ID/backend/interface name mapping and exit."),
    );
    let ns = cli::parse_leaf(&p, args)?;
    // `if self.root_dir:` / `if self.mapping:` -- empty strings count as unset
    let root_dir = ns.str("root_dir").filter(|s| !s.is_empty());
    let mapping = ns.str("mapping").filter(|s| !s.is_empty());
    command_generate(root_dir.as_deref(), mapping.as_deref())
}

fn command_generate(root_dir: Option<&str>, mapping: Option<&str>) -> Result<i32> {
    // if we are inside a snap, then call dbus to run netplan apply instead
    if std::env::var_os("SNAP").is_some() {
        let Some(busctl) = utils::which("busctl") else {
            return Err(py::Exception::err("RuntimeError", "missing busctl utility"));
        };
        let busctl = busctl.to_string_lossy().into_owned();
        let res = sub::call(&[
            &busctl,
            "call",
            "--quiet",
            "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Generate",
        ])?;
        if res != 0 {
            if res == 130 {
                return Err(py::Exception::err(
                    "PermissionError",
                    "PermissionError: failed to communicate with dbus service",
                ));
            }
            return Err(py::Exception::err(
                "RuntimeError",
                format!("RuntimeError: failed to communicate with dbus service: error {res}"),
            ));
        }
        return Ok(0);
    }

    let mut argv = vec![utils::get_configure_path()];
    let mut rootdir = "/";
    if let Some(rd) = root_dir {
        argv.extend(["--root-dir".to_string(), rd.to_string()]);
        rootdir = rd;
    }
    if let Some(m) = mapping {
        argv.extend(["--mapping".to_string(), m.to_string()]);
    }

    let try_stamp = Path::new(rootdir).join(utils::TRY_READY_STAMP);
    let res;
    if mapping.is_some() {
        // XXX: get rid of the legacy "--mapping" option
        argv[0] = utils::get_generator_path();
        res = call(&argv)?;
    } else if try_stamp.is_file() {
        // Avoid calling the Netplan generator if 'netplan try' is restoring
        // a previous configuration. See https://github.com/canonical/netplan/pull/548
        py::debug(&format!(
            "Skipping daemon-reload... 'netplan try' is restoring configuration, remove {} to force re-run.",
            try_stamp.display()
        ));
        res = 1;
    } else {
        py::debug("executing Netplan systemd-generator via daemon-reload");
        if let Some(rd) = root_dir {
            // for testing purposes
            let sd_generator = Path::new(rd).join("usr/lib/systemd/system-generators/netplan");
            let generator_dir = Path::new(rd).join("run/systemd/generator");
            let generator_early_dir = Path::new(rd).join("run/systemd/generator.early");
            let generator_late_dir = Path::new(rd).join("run/systemd/generator.late");
            // Ensure necessary directories exist
            for d in [
                sd_generator.parent().unwrap(),
                &generator_dir,
                &generator_early_dir,
                &generator_late_dir,
            ] {
                if let Err(e) = std::fs::create_dir_all(d) {
                    py::debug(&format!(
                        "Could not create directory {}: {}",
                        d.display(),
                        utils::py_oserror_str(&e, d)
                    ));
                }
            }
            // Ensure sd_generator exists and points to the real generator
            let real_generator = utils::get_generator_path();
            if !sd_generator.exists() {
                if let Err(e) = std::os::unix::fs::symlink(&real_generator, &sd_generator) {
                    py::debug(&format!(
                        "Could not symlink {} -> {real_generator}: {}",
                        sd_generator.display(),
                        utils::py_oserror_str(&e, &sd_generator)
                    ));
                }
            }
            let s = |p: &Path| p.to_string_lossy().into_owned();
            sub::check_call(&[
                &s(&sd_generator),
                "--root-dir",
                rd,
                &s(&generator_dir),
                &s(&generator_early_dir),
                &s(&generator_late_dir),
            ])?;
        } else {
            // automatically reloads systemd, as we might have changed
            // service units, such as
            // /run/systemd/generator.late/systemd-networkd-wait-online.service.d/10-netplan.conf
            let res = utils::systemctl_daemon_reload()?;
            if res != 0 {
                py::error(&format!("systemctl daemon-reload call failed: error {res}"));
                return py::exit(res);
            }
        }

        py::debug(&format!(
            "command configure: running {}",
            utils::py_repr_list(&argv)
        ));
        res = call(&argv)?;
        match sub::check_call(&["udevadm", "control", "--reload"]) {
            Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => {
                py::debug(&format!("Could not call \"udevadm control --reload\": {e}"));
            }
            other => other?,
        }
    }

    py::exit(res)
}

fn call(argv: &[String]) -> Result<i32> {
    let argv: Vec<&str> = argv.iter().map(String::as_str).collect();
    sub::call(&argv)
}
