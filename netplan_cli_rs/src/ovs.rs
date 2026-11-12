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

use std::collections::HashSet;
use std::path::Path;
use std::sync::LazyLock;

use anyhow::Result;

use crate::configmanager::ConfigManager;
use crate::netplan::NetDef;
use crate::py::{self, Exception};
use crate::utils::sub::{self, Io};
use crate::utils::{py_repr_str, py_splitlines};

pub const OVS_DB_SERVER_NOT_RUNNING: &str = "netplan_cli.cli.ovs.OvsDbServerNotRunning";
pub const OVS_DB_SERVER_NOT_INSTALLED: &str = "netplan_cli.cli.ovs.OvsDbServerNotInstalled";

const OPENVSWITCH_OVS_VSCTL: &str = "ovs-vsctl";

/// `DEFAULTS.get(column)`: defaults for non-optional settings, as defined here:
/// http://www.openvswitch.org/ovs-vswitchd.conf.db.5.pdf
fn defaults(column: &str) -> Option<&'static str> {
    match column {
        // Mandatory columns:
        "mcast_snooping_enable" => Some("false"),
        "rstp_enable" => Some("false"),
        _ => None,
    }
}

/// `GLOBALS.get(key)`: global commands, `set-*` -> (`del-*`, `get-*`)
fn globals(key: &str) -> Option<(&'static str, &'static str)> {
    match key {
        "set-ssl" => Some(("del-ssl", "get-ssl")),
        "set-fail-mode" => Some(("del-fail-mode", "get-fail-mode")),
        "set-controller" => Some(("del-controller", "get-controller")),
        _ => None,
    }
}

fn ovs_vsctl_path_select() -> String {
    if Path::new(&format!("/usr/bin/{OPENVSWITCH_OVS_VSCTL}")).exists()
        || !Path::new(&format!("/snap/bin/{OPENVSWITCH_OVS_VSCTL}")).exists()
    {
        format!("/usr/bin/{OPENVSWITCH_OVS_VSCTL}")
    } else {
        format!("/snap/bin/{OPENVSWITCH_OVS_VSCTL}")
    }
}

/// `OVS_VSCTL_PATH`, determined once (at import time in Python).
static OVS_VSCTL_PATH: LazyLock<String> = LazyLock::new(ovs_vsctl_path_select);

fn ovs_vsctl() -> &'static str {
    OVS_VSCTL_PATH.as_str()
}

fn ovs_installed() -> bool {
    Path::new(ovs_vsctl()).exists()
}

fn ovs_active() -> Result<bool> {
    Ok(sub::call_with(&[ovs_vsctl(), "show"], Io::Null, Io::Null)? == 0)
}

/// Cleanup values from a column (i.e. "column=value")
fn del_col(type_: &str, iface: &str, column: &str, value: &str) -> Result<()> {
    match defaults(column) {
        None => {
            // removes the exact value only if it was set by netplan
            let cmd = [ovs_vsctl(), "remove", type_, iface, column, value];
            py::debug(&format!("Running: {}", cmd.join(" ")));
            sub::check_call(&cmd)?;
        }
        Some(default) if !default.is_empty() && default != value => {
            // reset to default, if its not the default already
            let kv = format!("{column}={default}");
            let cmd = [ovs_vsctl(), "set", type_, iface, &kv];
            py::debug(&format!("Running: {}", cmd.join(" ")));
            sub::check_call(&cmd)?;
        }
        Some(_) => {}
    }
    Ok(())
}

/// Cleanup values from a dictionary (i.e. "column:key=value")
fn del_dict(type_: &str, iface: &str, column: &str, key: &str, value: &str) -> Result<()> {
    // removes the exact value only if it was set by netplan
    let kv = format!("{key}=\"{value}\"");
    let cmd = [ovs_vsctl(), "remove", type_, iface, column, &kv];
    py::debug(&format!("Running: {}", cmd.join(" ")));
    sub::check_call(&cmd)?;
    Ok(())
}

/// Cleanup commands from the global namespace
fn del_global(_type: &str, iface: &str, key: &str, value: &str) -> Result<()> {
    let Some((del_cmd, get_cmd)) = globals(key) else {
        // raise Exception('Reset command unknown for:', key)
        return Err(Exception::err(
            "Exception",
            format!("('Reset command unknown for:', {})", py_repr_str(key)),
        ));
    };
    // iface = None for del-ssl; `if iface:` treats '' like None
    let iface = if del_cmd == "del-ssl" { "" } else { iface };

    let mut args_get = vec![ovs_vsctl(), get_cmd];
    let mut args_del = vec![ovs_vsctl(), del_cmd];
    if !iface.is_empty() {
        args_get.push(iface);
        args_del.push(iface);
    }
    // Check the current value of a global command and compare it to the tag-value, e.g.:
    // * get-ssl: netplan/global/set-ssl=/private/key.pem,/another/cert.pem,/some/ca-cert.pem
    // * get-fail-mode: netplan/global/set-fail-mode=secure
    // * get-controller: netplan/global/set-controller=tcp:127.0.0.1:1337,unix:/some/socket
    let out = sub::check_output(&args_get)?;
    // Clean it only if the exact same value(s) were set by netplan.
    // Don't touch it if other values were set by another integration.
    if value.split(',').all(|item| out.contains(item)) {
        sub::check_call(&args_del)?;
    }
    Ok(())
}

/// Check if this setting is in a dict or a colum and delete accordingly
pub fn clear_setting(type_: &str, iface: &str, setting: &str, value: &str) -> Result<()> {
    let split: Vec<&str> = setting.splitn(3, '/').collect();
    // split[1]: an IndexError in Python if there is no '/'
    let Some(&col) = split.get(1) else {
        return Err(Exception::err("IndexError", "list index out of range"));
    };
    if col == "global" && split.len() > 2 {
        del_global(type_, iface, split[2], value)?;
    } else if split.len() > 2 {
        del_dict(type_, iface, split[1], split[2], value)?;
    } else {
        del_col(type_, iface, split[1], value)?;
    }
    // Cleanup the tag itself (i.e. "netplan/column[/key]")
    sub::check_call(&[ovs_vsctl(), "remove", type_, iface, "external-ids", setting])?;
    Ok(())
}

/// `np_interface_dict` is `{id: netdef}` (as a list of pairs).
pub fn is_ovs_interface(iface: &str, np_interface_dict: &[(String, NetDef)]) -> bool {
    np_interface_dict
        .iter()
        .find(|(k, _)| k == iface)
        .is_some_and(|(_, nd)| nd.backend() == "OpenVSwitch")
}

/// `ovs-vsctl --columns=<cols> -f csv -d bare --no-headings list <table>`
fn list_table(table: &str, cols: &str) -> Result<String> {
    let columns = format!("--columns={cols}");
    sub::check_output(&[
        ovs_vsctl(),
        &columns,
        "-f",
        "csv",
        "-d",
        "bare",
        "--no-headings",
        "list",
        table,
    ])
}

/// Query OpenVSwitch state through 'ovs-vsctl' and filter for netplan=true
/// tagged ports/bonds and bridges. Delete interfaces which are not defined
/// in the current configuration.
/// Also filter for individual settings tagged netplan/<column>[/<key]=value
/// in external-ids and clear them if they have been set by netplan.
pub fn apply_ovs_cleanup(
    config_manager: &mut ConfigManager,
    _ovs_old: bool,
    _ovs_current: bool,
) -> Result<()> {
    if !ovs_installed() {
        return Err(Exception::err(
            OVS_DB_SERVER_NOT_INSTALLED,
            "Cannot apply OpenvSwitch cleanup: ovs-vsctl is 'not-found'",
        ));
    }

    if !ovs_active()? {
        return Err(Exception::err(
            OVS_DB_SERVER_NOT_RUNNING,
            "OpenvSwitch database is not running",
        ));
    }

    let state = config_manager.parse(&[])?;
    // config_manager.netdefs: {nd.id: nd}
    let netdefs: Vec<(String, NetDef)> = state
        .netdefs()
        .into_iter()
        .map(|nd| (nd.id().unwrap_or_default(), nd))
        .collect();
    let mut ovs_ifaces: HashSet<&str> = HashSet::new();
    for (i, _) in &netdefs {
        if is_ovs_interface(i, &netdefs) {
            ovs_ifaces.insert(i);
        }
    }

    // Tear down old OVS interfaces, not defined in the current config.
    // Use 'del-br' on the Interface table, to delete any netplan created VLAN fake bridges.
    // Use 'del-bond-iface' on the Interface table, to delete netplan created patch port interfaces
    // Step 1: Delete all interfaces, which are not part of the current OVS config
    for (table, del) in [
        ("Port", "del-port"),
        ("Bridge", "del-br"),
        ("Interface", "del-br"),
    ] {
        let out = list_table(table, "name,external-ids")?;
        for line in py_splitlines(&out) {
            if line.contains("netplan=true") {
                let iface = line.split(',').next().unwrap_or("");
                // Skip cleanup if this OVS interface is part of the current netplan OVS config
                if ovs_ifaces.contains(iface) {
                    continue;
                }
                if table == "Interface" && sub::call(&[ovs_vsctl(), "br-exists", iface])? > 0 {
                    sub::check_call(&[ovs_vsctl(), "--if-exists", "del-bond-iface", iface])?;
                } else {
                    sub::check_call(&[ovs_vsctl(), "--if-exists", del, iface])?;
                }
            }
        }
    }

    // Step 2: Clean up the settings of the remaining interfaces
    for table in ["Port", "Bridge", "Interface", "Open_vSwitch", "Controller"] {
        let cols = match table {
            "Open_vSwitch" => "external-ids",
            // handle _uuid as if it would be the iface 'name'
            "Controller" => "_uuid,external-ids",
            _ => "name,external-ids",
        };
        let out = list_table(table, cols)?;
        for line in py_splitlines(&out) {
            if line.contains("netplan/") {
                let mut iface = ".";
                let mut extids = line;
                if table != "Open_vSwitch" {
                    // iface, extids = line.split(',', 1)
                    let Some((i, e)) = line.split_once(',') else {
                        return Err(Exception::err(
                            "ValueError",
                            "not enough values to unpack (expected 2, got 1)",
                        ));
                    };
                    iface = i;
                    extids = e;
                }
                // Check each line (interface) if it contains any netplan tagged settings, e.g.:
                // ovs0,"iface-id=myhostname netplan=true netplan/external-ids/iface-id=myhostname"
                // ovs1,"netplan=true netplan/global/set-fail-mode=standalone netplan/mcast_snooping_enable=false"
                for entry in extids.trim_matches('"').split(' ') {
                    if let Some((setting, val)) = entry.split_once('=') {
                        if entry.starts_with("netplan/") {
                            clear_setting(table, iface, setting, val)?;
                        }
                    }
                }
            }
        }
    }
    Ok(())
}
