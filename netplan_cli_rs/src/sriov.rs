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

//! Port of `netplan_cli/cli/sriov.py`.
//!
//! PORT PENDING: only the parse step of `apply_sriov_config()` exists so far.

use anyhow::Result;

use crate::configmanager::ConfigManager;

/// Go through all interfaces, identify which ones are SR-IOV VFs, create
/// them and perform all other necessary setup.
pub fn apply_sriov_config(config_manager: &mut ConfigManager, _rootdir: &str) -> Result<()> {
    config_manager.parse(&[])?;
    Ok(())
}
