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

//! Port of `netplan_cli/cli/ovs.py`.
//!
//! PORT PENDING: only the installed check of `apply_ovs_cleanup()` exists so far.

use std::path::Path;

use anyhow::Result;

use crate::configmanager::ConfigManager;
use crate::py::Exception;

pub const OVS_DB_SERVER_NOT_RUNNING: &str = "netplan_cli.cli.ovs.OvsDbServerNotRunning";
pub const OVS_DB_SERVER_NOT_INSTALLED: &str = "netplan_cli.cli.ovs.OvsDbServerNotInstalled";

fn ovs_vsctl_path() -> &'static str {
    if Path::new("/usr/bin/ovs-vsctl").exists() || !Path::new("/snap/bin/ovs-vsctl").exists() {
        "/usr/bin/ovs-vsctl"
    } else {
        "/snap/bin/ovs-vsctl"
    }
}

/// Delete netplan-tagged OVS interfaces and settings that are not part of
/// the current configuration.
pub fn apply_ovs_cleanup(
    _config_manager: &mut ConfigManager,
    _ovs_old: bool,
    _ovs_current: bool,
) -> Result<()> {
    if !Path::new(ovs_vsctl_path()).exists() {
        return Err(Exception::err(
            OVS_DB_SERVER_NOT_INSTALLED,
            "Cannot apply OpenvSwitch cleanup: ovs-vsctl is 'not-found'",
        ));
    }
    Ok(())
}
