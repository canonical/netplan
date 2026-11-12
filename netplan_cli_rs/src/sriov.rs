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
//! Python's dicts become insertion-ordered `Vec`s of key/value pairs (see
//! [`upsert`]); its sets become de-duplicated `Vec`s (any order is fine
//! there). Exceptions keep their Python class so that callers' `except`
//! clauses (`utils.config_errors`, `except Exception`) behave the same.

use std::io::Write;
use std::path::Path;

use anyhow::Result;

use crate::configmanager::{configuration_error, ConfigManager};
use crate::netplan::{NetDef, State};
use crate::py;
use crate::utils::sub::{self, Io};
use crate::utils::{self, py_repr_list};

// ── Python helpers ────────────────────────────────────────────────────────────

/// `os.path.join(a, b)`
fn path_join(a: &str, b: &str) -> String {
    if b.starts_with('/') {
        b.to_string()
    } else if a.is_empty() || a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

/// `os.path.basename(p)`
fn basename(p: &str) -> String {
    p.rsplit('/').next().unwrap_or("").to_string()
}

/// `os.path.exists(p)`
fn exists(p: &str) -> bool {
    Path::new(p).exists()
}

/// `os.readlink(p)`
fn readlink(p: &str) -> std::result::Result<String, PyOsError> {
    std::fs::read_link(p)
        .map(|t| t.to_string_lossy().into_owned())
        .map_err(|e| PyOsError::new(e, Some(p)))
}

/// An `OSError` with its errno, which some `except` clauses inspect.
pub struct PyOsError {
    err: std::io::Error,
    path: Option<String>,
}

impl PyOsError {
    fn new(err: std::io::Error, path: Option<&str>) -> Self {
        PyOsError {
            err,
            path: path.map(str::to_string),
        }
    }

    fn errno(&self) -> i32 {
        self.err.raw_os_error().unwrap_or(0)
    }

    fn is_file_not_found(&self) -> bool {
        self.errno() == 2
    }
}

impl std::fmt::Display for PyOsError {
    /// `str(OSError)`; errors from `write()`/`close()` carry no filename.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match &self.path {
            Some(p) => f.write_str(&utils::py_oserror_str(&self.err, Path::new(p))),
            None => {
                let errno = self.errno();
                write!(
                    f,
                    "[Errno {errno}] {}",
                    nix::errno::Errno::from_raw(errno).desc()
                )
            }
        }
    }
}

impl From<PyOsError> for anyhow::Error {
    fn from(e: PyOsError) -> Self {
        match &e.path {
            Some(p) => utils::oserror(&e.err, Path::new(p)),
            None => {
                let kind = match e.errno() {
                    2 => "FileNotFoundError",
                    1 | 13 => "PermissionError",
                    21 => "IsADirectoryError",
                    20 => "NotADirectoryError",
                    _ => "OSError",
                };
                py::Exception::err(kind, e.to_string())
            }
        }
    }
}

/// Error of a text-mode read: an `OSError` or a `UnicodeDecodeError`.
enum ReadError {
    Os(PyOsError),
    Decode(String),
}

impl From<ReadError> for anyhow::Error {
    fn from(e: ReadError) -> Self {
        match e {
            ReadError::Os(e) => e.into(),
            ReadError::Decode(msg) => py::Exception::err("UnicodeDecodeError", msg),
        }
    }
}

/// `open(path).read()` in text mode (strict UTF-8, universal newlines).
fn read_text(path: &str) -> std::result::Result<String, ReadError> {
    let bytes = std::fs::read(path).map_err(|e| ReadError::Os(PyOsError::new(e, Some(path))))?;
    let text = String::from_utf8(bytes).map_err(|e| {
        ReadError::Decode(format!(
            "'utf-8' codec can't decode byte at position {}: invalid start byte",
            e.utf8_error().valid_up_to()
        ))
    })?;
    Ok(text.replace("\r\n", "\n").replace('\r', "\n"))
}

/// `with open(path, 'w') as f: f.write(data)`
fn write_text(path: &str, data: &str) -> std::result::Result<(), PyOsError> {
    let mut f = std::fs::File::create(path).map_err(|e| PyOsError::new(e, Some(path)))?;
    f.write_all(data.as_bytes())
        .map_err(|e| PyOsError::new(e, None))
}

fn type_error_none() -> anyhow::Error {
    py::Exception::err(
        "TypeError",
        "expected str, bytes or os.PathLike object, not NoneType",
    )
}

fn attribute_error_none(attr: &str) -> anyhow::Error {
    py::Exception::err(
        "AttributeError",
        format!("'NoneType' object has no attribute '{attr}'"),
    )
}

/// `dict[key] = value`: replace in place or append.
fn upsert<V>(d: &mut Vec<(String, V)>, key: &str, value: V) {
    match d.iter_mut().find(|(k, _)| k == key) {
        Some(entry) => entry.1 = value,
        None => d.push((key.to_string(), value)),
    }
}

fn dict_get<'a, V>(d: &'a [(String, V)], key: &str) -> Option<&'a V> {
    d.iter().find(|(k, _)| k == key).map(|(_, v)| v)
}

/// `str(value)` of a JSON value (only used in debug messages).
fn json_str(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Null => "None".into(),
        serde_json::Value::Bool(true) => "True".into(),
        serde_json::Value::Bool(false) => "False".into(),
        other => other.to_string(),
    }
}

/// `np_state[netdef_id]`
fn state_get(state: &State, id: &str) -> Result<NetDef> {
    state
        .get_netdef(id)
        .ok_or_else(|| py::Exception::err("IndexError", ""))
}

fn ethernets(state: &State) -> Vec<NetDef> {
    state.netdefs_of_type("ethernets")
}

// ── PCIDevice ─────────────────────────────────────────────────────────────────

/// Helper class for interaction with a PCI device
/// (`pci_addr` is `None` when the PCI slot name could not be found).
pub struct PciDevice {
    pub pci_addr: Option<String>,
}

impl PciDevice {
    pub fn new(pci_addr: Option<String>) -> Self {
        PciDevice { pci_addr }
    }

    /// /sys path for PCI device
    fn path(&self) -> Result<String> {
        match &self.pci_addr {
            Some(a) => Ok(path_join("/sys/bus/pci/devices", a)),
            None => Err(type_error_none()),
        }
    }

    fn subpath(&self, subpath: &str) -> Result<String> {
        Ok(path_join(&self.path()?, subpath))
    }

    /// Kernel driver for PCI device
    pub fn driver(&self) -> Result<String> {
        let mut driver = String::new();
        if exists(&self.subpath("driver")?) {
            driver = basename(&readlink(&self.subpath("driver")?)?);
        }
        Ok(driver)
    }

    /// Determine if device is bound to a kernel driver
    fn bound(&self) -> Result<bool> {
        Ok(exists(&self.subpath("driver")?))
    }

    /// Determine if device is a SR-IOV Physical Function
    pub fn is_pf(&self) -> Result<bool> {
        Ok(exists(&self.subpath("sriov_numvfs")?))
    }

    /// List Virtual Function addresses associated with a Physical Function
    fn vf_addrs(&self) -> Result<Vec<String>> {
        let mut vf_addrs = vec![];
        let mut i = 0;
        loop {
            match readlink(&self.subpath(&format!("virtfn{i}"))?) {
                Ok(target) => vf_addrs.push(basename(&target)),
                Err(e) if e.is_file_not_found() => break,
                Err(e) => return Err(e.into()),
            }
            i += 1;
        }
        Ok(vf_addrs)
    }

    /// List Virtual Function associated with a Physical Function
    pub fn vfs(&self) -> Result<Vec<PciDevice>> {
        Ok(self
            .vf_addrs()?
            .into_iter()
            .map(|a| PciDevice::new(Some(a)))
            .collect())
    }

    fn is_autoprobe_available(&self) -> Result<bool> {
        Ok(exists(&self.subpath("sriov_drivers_autoprobe")?))
    }

    /// Get the current value of SR-IOV drivers autoprobe
    fn sriov_drivers_autoprobe(&self) -> Result<bool> {
        if self.is_autoprobe_available()? {
            return Ok(read_text(&self.subpath("sriov_drivers_autoprobe")?)?.trim() == "1");
        }
        py::warning(&format!(
            "Get sriov_drivers_autoprobe: path does not exist for {}",
            self.addr_str()
        ));
        Ok(false)
    }

    fn set_sriov_drivers_autoprobe(&self, value: bool) -> Result<()> {
        if self.is_autoprobe_available()? {
            write_text(
                &self.subpath("sriov_drivers_autoprobe")?,
                if value { "1" } else { "0" },
            )?;
        } else {
            py::warning(&format!(
                "Set sriov_drivers_autoprobe: path does not exist for {}",
                self.addr_str()
            ));
        }
        Ok(())
    }

    /// `"{}".format(self.pci_addr)`
    fn addr_str(&self) -> &str {
        self.pci_addr.as_deref().unwrap_or("None")
    }

    /// Set devlink options for the PCI device
    fn devlink_set(&self, obj_name: &str, prop: &str, value: &str) -> Result<()> {
        let pci = format!("pci/{}", self.addr_str());
        sub::check_call(&["/sbin/devlink", "dev", obj_name, "set", &pci, prop, value])
    }

    /// Query eswitch mode via devlink for the PCI device: the eswitch mode
    /// or '__undetermined' if it can't be retrieved.
    fn devlink_eswitch_mode(&self) -> Result<serde_json::Value> {
        let undetermined = serde_json::Value::String("__undetermined".into());
        let pci = format!("pci/{}", self.addr_str());
        let out = sub::run(
            &["/sbin/devlink", "-j", "dev", "eswitch", "show", &pci],
            Io::Pipe,
            Io::Null,
        )?;
        if out.returncode != 0 {
            return Ok(undetermined);
        }
        let json: serde_json::Value = serde_json::from_str(&out.stdout)
            .map_err(|e| py::Exception::err("json.decoder.JSONDecodeError", e.to_string()))?;

        // The JSON document looks like this when the 'mode' is available:
        // {"dev":{"pci/0000:03:00.0":{"mode":"switchdev"}}}
        // and like this when it's not available
        // {"dev":{}}
        // `dict.get(key, default)` on each level; anything but a dict has no
        // .get() and raises AttributeError.
        let get = |v: &serde_json::Value, key: &str| -> Result<Option<serde_json::Value>> {
            match v {
                serde_json::Value::Object(m) => Ok(m.get(key).cloned()),
                other => Err(py::Exception::err(
                    "AttributeError",
                    format!("'{}' object has no attribute 'get'", json_type(other)),
                )),
            }
        };
        let empty = serde_json::Value::Object(Default::default());
        let dev = get(&json, "dev")?.unwrap_or_else(|| empty.clone());
        let pcidev = get(&dev, &pci)?.unwrap_or_else(|| empty.clone());
        Ok(get(&pcidev, "mode")?.unwrap_or(undetermined))
    }
}

fn json_type(v: &serde_json::Value) -> &'static str {
    match v {
        serde_json::Value::Null => "NoneType",
        serde_json::Value::Bool(_) => "bool",
        serde_json::Value::Number(n) if n.is_f64() => "float",
        serde_json::Value::Number(_) => "int",
        serde_json::Value::String(_) => "str",
        serde_json::Value::Array(_) => "list",
        serde_json::Value::Object(_) => "dict",
    }
}

/// Bind unbound VFs to driver.
pub fn bind_vfs(vfs: &[PciDevice], driver: &str) -> Result<usize> {
    let mut bound_vfs = 0;
    for vf in vfs {
        if !vf.bound()? {
            write_text(
                &format!("/sys/bus/pci/drivers/{driver}/bind"),
                vf.addr_str(),
            )?;
            bound_vfs += 1;
        }
    }
    Ok(bound_vfs)
}

/// Unbind bound VFs from driver.
fn unbind_vfs(vfs: &[PciDevice], driver: &str) -> Result<usize> {
    let mut unbound_vfs = 0;
    for vf in vfs {
        if vf.bound()? {
            write_text(
                &format!("/sys/bus/pci/drivers/{driver}/unbind"),
                vf.addr_str(),
            )?;
            unbound_vfs += 1;
        }
    }
    Ok(unbound_vfs)
}

// ── Interface matching ────────────────────────────────────────────────────────

fn interface_matches(netdef: &NetDef, interface: &str) -> bool {
    let driver = utils::get_interface_driver_name(interface, false);
    let mac = utils::get_interface_macaddress(interface);
    // empty strings are passed to libnetplan as NULL
    netdef.matches_interface(
        interface,
        mac.as_deref().filter(|m| !m.is_empty()),
        driver.as_deref().filter(|d| !d.is_empty()),
    )
}

/// Try to match a netdef with the real system network interface.
/// Throws ConfigurationError if there is more than one match.
fn get_interface_name_for_netdef(netdef: &NetDef) -> Result<Option<String>> {
    let interfaces = utils::get_interfaces();
    if netdef.has_match() {
        // now here it's a bit tricky
        let set_name = netdef.set_name()?;
        if let Some(set_name) = set_name.filter(|s| interfaces.contains(s)) {
            // if we had a match: stanza and set-name: this means we should
            // assume that, if found, the interface has already been
            // renamed - use the new name
            return Ok(Some(set_name));
        }
        // a set: insertion order is as good as any
        let mut matches: Vec<String> = vec![];
        // we walk through all the system interfaces to determine if there is
        // more than one matched interface
        for interface in &interfaces {
            if !interface_matches(netdef, interface) {
                continue;
            }
            // we have a matching PF
            // error out if we matched more than one
            if matches.len() > 1 {
                return Err(configuration_error(format!(
                    "matched more than one interface for a PF device: {}",
                    netdef.id()?
                )));
            }
            if !matches.contains(interface) {
                matches.push(interface.clone());
            }
        }
        if let Some(first) = matches.into_iter().next() {
            return Ok(Some(first));
        }
    } else {
        // no match field, assume entry name is the interface name
        let id = netdef.id()?;
        if interfaces.contains(&id) {
            return Ok(Some(id));
        }
    }
    Ok(None)
}

/// `if iface := _get_interface_name_for_netdef(netdef)`
fn truthy_interface_name(netdef: &NetDef) -> Result<Option<String>> {
    Ok(get_interface_name_for_netdef(netdef)?.filter(|s| !s.is_empty()))
}

/// Read PCI slot name for given interface name
pub fn get_pci_slot_name(netdev: &str) -> Result<Option<String>> {
    let uevent_path = path_join(&path_join("/sys/class/net", netdev), "device/uevent");
    let content = match read_text(&uevent_path) {
        Ok(c) => c,
        Err(ReadError::Os(e)) => {
            return Err(py::Exception::err(
                "RuntimeError",
                format!("failed parsing PCI slot name for {netdev}: {e}"),
            ))
        }
        Err(e) => return Err(e.into()),
    };
    for line in content.split_inclusive('\n') {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("PCI_SLOT_NAME=") {
            // line.split('=', 2)[1]
            return Ok(Some(rest.split('=').next().unwrap_or("").to_string()));
        }
    }
    Ok(None)
}

/// `netdef._vf_count`, with libnetplan errors as ConfigurationError
fn vf_count(state: &State, netdef: &NetDef) -> Result<i32> {
    state.vf_count_for_def(netdef).map_err(configuration_error)
}

/// Go through the list of netplan ethernet devices and identify which are
/// PFs matching them with actual network interfaces.
fn get_physical_functions(state: &State) -> Result<Vec<(String, String)>> {
    let mut pfs = vec![];
    for netdef in ethernets(state) {
        // If the sriov_link is present, the interface is a VF and link is the PF
        if let Some(link) = netdef.sriov_link() {
            let link_id = link.id()?;
            if let Some(iface) = truthy_interface_name(&state_get(state, &link_id)?)? {
                upsert(&mut pfs, &link_id, iface);
            }
        } else {
            // If a netdef also defines the embedded_switch_mode key we consider it's a PF
            // This enables us to change the eswitch mode even when the PF has no VFs.
            if netdef
                .embedded_switch_mode()?
                .is_some_and(|m| !m.is_empty())
            {
                if let Some(iface) = truthy_interface_name(&netdef)? {
                    upsert(&mut pfs, &netdef.id()?, iface);
                }
            }

            // If the netdef has any (positive) number of VFs that's because it's a PF
            if vf_count(state, &netdef)? > 0 {
                if let Some(iface) = truthy_interface_name(&netdef)? {
                    upsert(&mut pfs, &netdef.id()?, iface);
                }
            }
        }
    }
    Ok(pfs)
}

/// Go through the list of netplan ethernet devices and identify which ones
/// have VFs.
fn get_vf_number_per_pf(state: &State) -> Result<Vec<(String, i32)>> {
    let mut vf_counts = vec![];
    for netdef in ethernets(state) {
        let count = vf_count(state, &netdef)?;
        if count > 0 {
            if let Some(iface) = truthy_interface_name(&netdef)? {
                upsert(&mut vf_counts, &iface, count);
            }
        }
    }
    Ok(vf_counts)
}

/// Go through the list of netplan ethernet devices and identify which ones
/// are virtual functions
fn get_virtual_functions(state: &State) -> Result<Vec<String>> {
    let mut vfs: Vec<String> = vec![];
    for netdef in ethernets(state) {
        // If the sriov_link is present and the PF is also present in the system we save the VF
        if let Some(link) = netdef.sriov_link() {
            if truthy_interface_name(&state_get(state, &link.id()?)?)?.is_some() {
                let id = netdef.id()?;
                if !vfs.contains(&id) {
                    vfs.push(id);
                }
            }
        }
    }
    Ok(vfs)
}

/// Allocate the required number of VFs for the selected PF.
fn set_numvfs_for_pf(pf: &str, vf_count: i32, manage_autoprobe: bool) -> Result<bool> {
    if vf_count > 256 {
        return Err(configuration_error(format!(
            "cannot allocate more VFs for PF {pf} than the SR-IOV maximum: {vf_count} > 256"
        )));
    }

    let devdir = path_join(&path_join("/sys/class/net", pf), "device");
    let numvfs_path = path_join(&devdir, "sriov_numvfs");
    let totalvfs_path = path_join(&devdir, "sriov_totalvfs");
    let invalid = || {
        py::Exception::err(
            "RuntimeError",
            format!("invalid sriov_totalvfs value for {pf}"),
        )
    };
    let vf_max = match read_text(&totalvfs_path) {
        Ok(s) => crate::argparse::python_int(s.trim()).ok_or_else(invalid)?,
        Err(ReadError::Os(e)) => {
            return Err(py::Exception::err(
                "RuntimeError",
                format!("failed parsing sriov_totalvfs for {pf}: {e}"),
            ))
        }
        // UnicodeDecodeError is a ValueError
        Err(ReadError::Decode(_)) => return Err(invalid()),
    };

    if vf_count as i64 > vf_max {
        return Err(configuration_error(format!(
            "cannot allocate more VFs for PF {pf} than supported: {vf_count} > {vf_max} (sriov_totalvfs)"
        )));
    }

    let mut autoprobe = None;
    if manage_autoprobe {
        let pci_addr = get_pci_slot_name(pf)?;
        let pcidev = PciDevice::new(pci_addr);
        let prev_autoprobe = pcidev.sriov_drivers_autoprobe()?;
        pcidev.set_sriov_drivers_autoprobe(false)?;
        autoprobe = Some((pcidev, prev_autoprobe));
    }

    let result = (|| -> Result<()> {
        let Err(e) = write_text(&numvfs_path, &vf_count.to_string()) else {
            return Ok(());
        };
        let mut bail = true;
        let mut e = e;
        if e.errno() == 16 {
            // device or resource busy
            py::warning(&format!(
                "device or resource busy while setting sriov_numvfs for {pf}, trying workaround"
            ));
            // doing this in two open/close sequences so that
            // it's as close to writing via shell as possible
            match write_text(&numvfs_path, "0")
                .and_then(|_| write_text(&numvfs_path, &vf_count.to_string()))
            {
                Err(e_inner) => e = e_inner,
                Ok(()) => bail = false,
            }
        }
        if bail {
            return Err(py::Exception::err(
                "RuntimeError",
                format!("failed setting sriov_numvfs to {vf_count} for {pf}: {e}"),
            ));
        }
        Ok(())
    })();
    // finally:
    if let Some((pcidev, prev_autoprobe)) = autoprobe {
        pcidev.set_sriov_drivers_autoprobe(prev_autoprobe)?;
    }
    result?;

    Ok(true)
}

/// Perform any hardware-specific quirks for the given SR-IOV device to make
/// sure all the VF-count changes are applied.
fn perform_hardware_specific_quirks(pf: &str) -> Result<()> {
    let devdir = path_join(&path_join("/sys/class/net", pf), "device");
    let read = |name: &str| -> Result<String> {
        match read_text(&path_join(&devdir, name)) {
            Ok(s) => Ok(s.trim().chars().skip(2).collect()),
            Err(ReadError::Os(e)) => Err(py::Exception::err(
                "RuntimeError",
                format!("could not determine vendor and device ID of {pf}: {e}"),
            )),
            Err(e) => Err(e.into()),
        }
    };
    let device_id = read("vendor")?;
    let vendor_id = read("device")?;

    let _combined_id = [vendor_id, device_id].join(":");
    // quirk_devices = ()  # TODO: add entries to the list
    // Currently no device needs special handling.
    Ok(())
}

/// Apply the hardware VLAN filtering for the selected VF.
fn apply_vlan_filter_for_vf(
    pf: Option<&str>,
    vf: &str,
    vlan_name: &str,
    vlan_id: Option<u32>,
) -> Result<()> {
    // this is more complicated, because to do this, we actually need to have
    // the vf index - just knowing the vf interface name is not enough
    let mut vf_index: Option<String> = None;
    let vf_devdir = path_join(&path_join("/sys/class/net", vf), "device");
    let vf_dev_id = basename(&readlink(&vf_devdir)?);
    let pf = pf.ok_or_else(type_error_none)?;
    let pf_devdir = path_join(&path_join("/sys/class/net", pf), "device");
    let entries = std::fs::read_dir(&pf_devdir).map_err(|e| PyOsError::new(e, Some(&pf_devdir)))?;
    for entry in entries {
        let entry = entry.map_err(|e| PyOsError::new(e, Some(&pf_devdir)))?;
        let f = entry.file_name().to_string_lossy().into_owned();
        if f.contains("virtfn") {
            let dev_path = path_join(&pf_devdir, &f);
            let dev_id = basename(&readlink(&dev_path)?);
            if dev_id == vf_dev_id {
                vf_index = Some(f.chars().skip(6).collect());
                break;
            }
        }
    }

    let Some(vf_index) = vf_index.filter(|i| !i.is_empty()) else {
        return Err(py::Exception::err(
            "RuntimeError",
            format!("could not determine the VF index for {vf} while configuring vlan {vlan_name}"),
        ));
    };

    // now, create the VLAN filter
    let vlan_id = vlan_id.map_or("None".to_string(), |v| v.to_string());
    match sub::check_call_with(
        &["ip", "link", "set", "dev", pf, "vf", &vf_index, "vlan", &vlan_id],
        Io::Null,
        Io::Null,
    ) {
        Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => {
            Err(py::Exception::err(
                "RuntimeError",
                format!(
                    "failed setting SR-IOV VLAN filter for vlan {vlan_name} (ip link set command failed)"
                ),
            ))
        }
        other => other,
    }
}

/// Go through all interfaces, identify which ones are SR-IOV VFs, create
/// them and perform all other necessary setup.
pub fn apply_sriov_config(config_manager: &mut ConfigManager, _rootdir: &str) -> Result<()> {
    config_manager.parse(&[])?;
    let np_state = config_manager
        .np_state
        .as_ref()
        .expect("parse() sets np_state");

    // for sr-iov devices, we identify VFs by them having a link: field
    // pointing to an PF. So let's browse through all ethernet devices,
    // find all that are VFs and count how many of those are linked to
    // particular PFs, as we need to then set the numvfs for each.
    let vf_counts = get_vf_number_per_pf(np_state)?;
    // we also store all matches between VF/PF netplan entry names and
    // interface that they're currently matching to
    let vfs_set = get_virtual_functions(np_state)?;
    let pfs = get_physical_functions(np_state)?;
    let mut pf_to_netdef: Vec<(String, NetDef)> = vec![];
    for (nid, iface) in &pfs {
        upsert(&mut pf_to_netdef, iface, state_get(np_state, nid)?);
    }

    // setup the required number of VFs per PF
    // at the same time store which PFs got changed in case the NICs
    // require some special quirks for the VF number to change
    let mut vf_count_changed = vec![];
    for (pf, vf_count) in &vf_counts {
        // Disabling sriov_drivers_autoprobe before updating sriov_numvfs
        // is a suggested sequence to reduce load on NIC card's resources.
        // We start cautiously by implementing this suggestion only when
        // embedded-switch-mode is explicitly specified. (LP#2166228)
        let mut manage_autoprobe = false;
        if let Some(netdef) = dict_get(&pf_to_netdef, pf) {
            manage_autoprobe = matches!(
                netdef.embedded_switch_mode()?.as_deref(),
                Some("switchdev" | "legacy")
            );
        }
        if !set_numvfs_for_pf(pf, *vf_count, manage_autoprobe)? {
            continue;
        }
        vf_count_changed.push(pf.clone());
    }

    // some cards need special treatment when we want to change the
    // number of enabled VFs
    for pf in &vf_count_changed {
        perform_hardware_specific_quirks(pf)?;
    }

    // Walk the SR-IOV PFs and check if we need to change the eswitch mode
    for (netdef_id, iface) in &pfs {
        let netdef = state_get(np_state, netdef_id)?;
        let Some(eswitch_mode) = netdef
            .embedded_switch_mode()?
            .filter(|m| m == "switchdev" || m == "legacy")
        else {
            continue;
        };
        let pci_addr = get_pci_slot_name(iface)?;
        let pcidev = PciDevice::new(pci_addr);
        let current_eswitch_mode_system = pcidev.devlink_eswitch_mode()?;
        if current_eswitch_mode_system.as_str() != Some(eswitch_mode.as_str()) && pcidev.is_pf()? {
            let vf_addrs = pcidev.vf_addrs()?;
            py::debug(&format!(
                "Found VFs of {}: {}",
                pcidev.addr_str(),
                py_repr_list(&vf_addrs)
            ));
            if !pcidev.vfs()?.is_empty() {
                let unbind = (|| unbind_vfs(&pcidev.vfs()?, &pcidev.driver()?))();
                match unbind {
                    Err(e) if sub::is_exception(&e, &["Exception"]) => {
                        py::warning(&format!("Unbinding of VFs for {netdef_id} failed: {e}"));
                    }
                    other => {
                        other?;
                    }
                }
            }

            py::debug(&format!(
                "Changing eswitch mode from {} to {eswitch_mode} for: {netdef_id}",
                json_str(&current_eswitch_mode_system)
            ));
            pcidev.devlink_set("eswitch", "mode", &eswitch_mode)?;
        }

        if !pcidev.vfs()?.is_empty() && !netdef.delay_virtual_functions_rebind() {
            bind_vfs(&pcidev.vfs()?, &pcidev.driver()?)?;
        }
    }

    // now in theory we should have all the new VFs set up and existing;
    // this is needed because we will have to now match the defined VF
    // entries to existing interfaces, otherwise we won't be able to set
    // filtered VLANs for those.
    let mut vfs: Vec<(String, String)> = vec![];
    let interfaces = if vfs_set.is_empty() {
        vec![]
    } else {
        utils::get_interfaces()
    };
    for vf in &vfs_set {
        let netdef = state_get(np_state, vf)?;
        if netdef.has_match() {
            // right now we only match by name, as I don't think matching per
            // driver and/or macaddress makes sense
            for interface in &interfaces {
                if netdef.matches_interface(interface, None, None) {
                    if dict_get(&vfs, vf).is_some_and(|v| !v.is_empty()) {
                        return Err(configuration_error(format!(
                            "matched more than one interface for a VF device: {vf}"
                        )));
                    }
                    upsert(&mut vfs, vf, interface.clone());
                }
            }
        } else if interfaces.contains(vf) {
            upsert(&mut vfs, vf, vf.clone());
        }
    }

    let mut filtered_vlans_set: Vec<String> = vec![];
    for netdef in np_state.netdefs_of_type("vlans") {
        let vlan = netdef.id()?;
        // there is a special sriov vlan renderer that one can use to mark
        // a selected vlan to be done in hardware (VLAN filtering)
        if !netdef.has_sriov_vlan_filter() {
            continue;
        }
        // this only works for SR-IOV VF interfaces
        let link = netdef.vlan_link();
        let vlan_id = netdef.vlan_id();
        let link = link.ok_or_else(|| attribute_error_none("id"))?;
        let link_id = link.id()?;

        let Some(vf) = dict_get(&vfs, &link_id).filter(|v| !v.is_empty()).cloned() else {
            // it is possible this is not an error, for instance when
            // the configuration has been defined 'for the future'
            py::warning(&format!(
                "SR-IOV vlan defined for {vlan} but link {link_id} is either not a VF or has no matches"
            ));
            continue;
        };

        // get the parent pf interface
        // first we fetch the related vf netplan entry
        // and finally, get the matched pf interface
        let pf_link = link
            .sriov_link()
            .ok_or_else(|| attribute_error_none("id"))?;
        let pf = dict_get(&pfs, &pf_link.id()?).cloned();

        if filtered_vlans_set.contains(&vf) {
            return Err(configuration_error(format!(
                "interface {vf} for netplan device {link_id} ({vlan}) already has an SR-IOV vlan defined"
            )));
        }

        apply_vlan_filter_for_vf(pf.as_deref(), &vf, &vlan, vlan_id)?;
        filtered_vlans_set.push(vf);
    }
    Ok(())
}
