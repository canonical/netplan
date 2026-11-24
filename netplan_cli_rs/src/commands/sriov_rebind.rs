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

//! `netplan rebind` – rebind SR-IOV virtual functions to their driver.
//!
//! Port of `netplan_cli/cli/commands/sriov_rebind.py`. Its messages go
//! through a dedicated `sriov_rebind` logger that writes to stdout (flushed
//! after every record) and only shows DEBUG records with `rebind --debug`.

use std::path::Path;
use std::time::Duration;

use anyhow::Result;

use crate::argparse::{Arg, Nargs};
use crate::sriov::{bind_vfs, get_pci_slot_name, PciDevice};
use crate::{cli, netplan, py};

const FALLBACK_WAIT_TIME_SEC: f64 = 3.0;
const INTERVAL_SEC: f64 = 0.2;
const MAX_WAITING_TIME_SEC: f64 = 5.0;

/// Why the mlx5 VF LAG state did not become 'active'.
enum Mlx5VfLagState {
    NotFound,
    CannotBeRead,
    Disabled,
}

struct Rebind {
    root_dir: String,
    netdevs: Vec<String>,
    debug: bool,
}

/// `netplan rebind [--root-dir DIR] [netdevs ...]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "rebind", cli::description("rebind"));
    p.add(
        Arg::new(&["--root-dir"])
            .default_str("/")
            .help("Search for configuration files in this root directory instead of /"),
    );
    p.add(
        Arg::new(&["netdevs"])
            .nargs(Nargs::ZeroOrMore)
            .help("Space separated list of PF interface names"),
    );
    let ns = cli::parse_leaf(&p, args)?;
    let cmd = Rebind {
        root_dir: ns.str("root_dir").unwrap_or_default(),
        netdevs: ns.list("netdevs"),
        debug: ns.bool("debug"),
    };
    cmd.command_rebind()?;
    Ok(0)
}

impl Rebind {
    /// `self.logger.debug(msg)`: "DEBUG:msg" on stdout with `--debug`.
    fn log_debug(&self, msg: &str) {
        if self.debug {
            crate::pyprintln!("DEBUG:{msg}");
            py::flush_stdout();
        }
    }

    /// Bind virtual functions of SR-IOV devices to their corresponding driver
    /// after eswitch mode was changed
    fn command_rebind(&self) -> Result<()> {
        for iface in &self.netdevs {
            let pci_addr = get_pci_slot_name(iface)?;
            let pcidev = PciDevice::new(pci_addr);
            if !pcidev.is_pf()? {
                self.log_debug(&format!(
                    "{iface} does not seem to be a SR-IOV physical function"
                ));
                continue;
            }

            // There are some hardware-specific configuration that must happen *before* the bind
            // of VFs to their drivers. Some settings take time to be effective and, when possible,
            // we need to wait until the driver reports it's ready.
            self.perform_hardware_specific_quirks(iface, &pcidev)?;

            let bound_vfs = bind_vfs(&pcidev.vfs()?, &pcidev.driver()?)?;
            self.log_debug(&format!(
                "{}: bound {bound_vfs} VFs",
                pcidev.pci_addr.as_deref().unwrap_or("None")
            ));
        }
        Ok(())
    }

    /// Perform any hardware-specific quirks for the given SR-IOV device to make
    /// sure it's ready before the bind.
    fn perform_hardware_specific_quirks(&self, iface: &str, pf: &PciDevice) -> Result<()> {
        if pf.driver()? != "mlx5_core" {
            return Ok(());
        }
        // Mellanox specific quirks
        let np_state = netplan::load_state(&self.root_dir)?;

        for netdef in np_state.netdefs_of_type("ethernets") {
            let selected = (netdef.has_match() && netdef.set_name()?.as_deref() == Some(iface))
                || netdef.id()? == iface;
            if !selected {
                continue;
            }
            let Some(bond_link) = netdef.bond_link() else {
                continue;
            };
            // VF LAG support. See LP: #1988018
            // If the PF is a member of a bond, the user might be trying to enable the
            // VF LAG feature.
            // Mellanox VF LAG requires that the LAG state reports as 'active'
            // *before* VFs can be bound to the driver. Performing the bind operation
            // before the device is ready will cause the VF LAG feature to never be enabled.

            // Another condition for the VF LAG activation is that the LAG mode
            // must be one of 'active-backup', 'balanced-xor' or '802.3ad'.
            let bond_mode = bond_link.bond_mode()?;
            if !matches!(
                bond_mode.as_deref(),
                Some("active-backup" | "balanced-xor" | "802.3ad")
            ) {
                self.log_debug(&format!(
                    "{iface} - LAG mode {} is not supported by VF LAG",
                    bond_mode.as_deref().unwrap_or("None")
                ));
                continue;
            }

            self.log_debug(&format!(
                "{iface} - waiting for the LAG state to be 'active'"
            ));
            match self.wait_for_mlx5_pf_lag_state_active(pf) {
                Err(Mlx5VfLagState::CannotBeRead) => {
                    self.log_debug(&format!("{iface} - VF LAG state cannot be read"))
                }
                Err(Mlx5VfLagState::NotFound) => {
                    self.log_debug(&format!("{iface} - VF LAG state debugfs file not found"))
                }
                Err(Mlx5VfLagState::Disabled) => self.log_debug(&format!(
                    "{iface} - VF LAG state is still 'disabled' after waiting"
                )),
                Ok(()) => self.log_debug(&format!("{iface} - VF LAG state is 'active'")),
            }
        }
        Ok(())
    }

    /// The mlx5 driver added debugfs support (torvalds/linux commit 7f46a0b7327a),
    /// available since kernel 5.19.
    fn wait_for_mlx5_pf_lag_state_active(
        &self,
        pf: &PciDevice,
    ) -> std::result::Result<(), Mlx5VfLagState> {
        let mut retries = (MAX_WAITING_TIME_SEC / INTERVAL_SEC) as i64;
        let pci_addr = pf.pci_addr.as_deref().unwrap_or("None");
        let path = format!("/sys/kernel/debug/mlx5/{pci_addr}/lag/state");

        if !Path::new(&path).exists() {
            // If the debugfs file doesn't exist, it might be because this version of the mlx5 driver
            // still doesn't support it or because the debugfs is not mounted.
            // In this case, we probably should still wait for a few seconds to give time for the
            // driver to change state.
            std::thread::sleep(Duration::from_secs_f64(FALLBACK_WAIT_TIME_SEC));
            return Err(Mlx5VfLagState::NotFound);
        }

        while retries > 0 {
            match get_mlx5_vf_lag_state(pci_addr) {
                Some(state) if state != "active" => {
                    self.log_debug(&format!(
                        "{pci_addr} VF LAG state is not active yet, retrying..."
                    ));
                    std::thread::sleep(Duration::from_secs_f64(INTERVAL_SEC));
                }
                Some(_) => return Ok(()),
                None => return Err(Mlx5VfLagState::CannotBeRead),
            }
            retries -= 1;
        }

        Err(Mlx5VfLagState::Disabled)
    }
}

/// The mlx5 VF LAG state, or `None` if it cannot be read.
fn get_mlx5_vf_lag_state(pci_addr: &str) -> Option<String> {
    let path = format!("/sys/kernel/debug/mlx5/{pci_addr}/lag/state");
    let bytes = std::fs::read(path).ok()?;
    let text = String::from_utf8(bytes).ok()?;
    Some(text.trim().to_string())
}
