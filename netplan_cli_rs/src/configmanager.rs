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

//! Port of `netplan_cli/configmanager.py`.

use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};

use anyhow::Result;

use crate::netplan::{NetDef, Parser, State};
use crate::py;
use crate::utils;

/// `ConfigurationError`: configuration could not be parsed or has otherwise
/// failed to apply.
pub fn configuration_error(message: String) -> anyhow::Error {
    py::Exception::err("netplan_cli.configmanager.ConfigurationError", message)
}

/// The exception classes in `utils.config_errors`.
pub const CONFIG_ERRORS: &[&str] = &[
    "netplan_cli.configmanager.ConfigurationError",
    "NetplanException",
    "RuntimeError",
];

pub struct ConfigManager {
    prefix: String,
    /// source -> destination of files added with [`add`](Self::add)
    extra_files: Vec<(String, String)>,
    tempdir: Option<PathBuf>,
    pub np_state: Option<State>,
}

impl ConfigManager {
    pub fn new(prefix: &str) -> Self {
        ConfigManager {
            prefix: prefix.to_string(),
            extra_files: vec![],
            tempdir: None,
            np_state: None,
        }
    }

    /// Parse all config files (plus `extra_config`) into a libnetplan state.
    pub fn parse(&mut self, extra_config: &[String]) -> Result<&State> {
        let state = (|| -> Result<State> {
            let mut parser = Parser::new()?;
            parser.load_yaml_hierarchy(&self.prefix)?;
            for f in extra_config {
                parser.load_yaml_file(f)?;
            }
            let mut state = State::new()?;
            state.import_parser_results(&mut parser)?;
            Ok(state)
        })()
        .map_err(|e| match e.downcast_ref::<py::NetplanError>() {
            // ConfigurationError(str(e)): the message without its location
            Some(ne) => configuration_error(ne.message.clone()),
            None => e,
        })?;
        if py::debug_enabled() {
            py::debug(&format!("Merged config:\n{}", state.dump_yaml()?));
        }
        self.np_state = Some(state);
        Ok(self.np_state.as_ref().unwrap())
    }

    fn state(&self) -> &State {
        self.np_state
            .as_ref()
            .expect("Must call parse() before accessing the config.")
    }

    /// ethernets, modems and wifis (in that order), keyed by id.
    pub fn physical_interfaces(&self) -> Vec<(String, NetDef)> {
        self.by_types(&["ethernets", "modems", "wifis"])
    }

    /// bridges, bonds, dummy-devices, tunnels, virtual-ethernets, vlans and
    /// vrfs (in that order), keyed by id.
    pub fn virtual_interfaces(&self) -> Vec<(String, NetDef)> {
        self.by_types(&[
            "bridges",
            "bonds",
            "dummy-devices",
            "tunnels",
            "virtual-ethernets",
            "vlans",
            "vrfs",
        ])
    }

    /// `dict.update()` of each type's `{id: netdef}` dict, in order.
    fn by_types(&self, types: &[&str]) -> Vec<(String, NetDef)> {
        let mut out: Vec<(String, NetDef)> = vec![];
        for t in types {
            for nd in self.state().netdefs_of_type(t) {
                let id = nd.id().unwrap_or_default();
                match out.iter_mut().find(|(k, _)| *k == id) {
                    Some(entry) => entry.1 = nd,
                    None => out.push((id, nd)),
                }
            }
        }
        out
    }

    /// Copy each `(source, destination)` and remember it for `revert()`.
    pub fn add(&mut self, files: &[(String, String)]) -> Result<()> {
        for (src, dst) in files {
            copy_file(src, dst)?;
        }
        for (src, dst) in files {
            match self.extra_files.iter_mut().find(|(s, _)| s == src) {
                Some(entry) => entry.1 = dst.clone(),
                None => self.extra_files.push((src.clone(), dst.clone())),
            }
        }
        self.np_state = None;
        Ok(())
    }

    fn tempdir(&mut self) -> Result<PathBuf> {
        if self.tempdir.is_none() {
            self.tempdir = Some(mkdtemp("netplan_")?);
        }
        Ok(self.tempdir.clone().unwrap())
    }

    pub fn backup(&mut self, backup_config_dir: bool) -> Result<()> {
        let tempdir = self.tempdir()?;
        let temp_etc = tempdir.join("etc");
        let temp_run = tempdir.join("run");
        let prefix = Path::new(&self.prefix);
        if backup_config_dir {
            copy_tree(
                &prefix.join("etc/netplan"),
                &temp_etc.join("netplan"),
                false,
                false,
            )?;
        }
        copy_tree(
            &prefix.join("run/NetworkManager/system-connections"),
            &temp_run.join("NetworkManager").join("system-connections"),
            true,
            false,
        )?;
        copy_tree(
            &prefix.join("run/systemd/network"),
            &temp_run.join("systemd").join("network"),
            true,
            false,
        )?;
        Ok(())
    }

    pub fn revert(&mut self) -> Result<()> {
        let result = (|| -> Result<()> {
            while let Some((_, dst)) = self.extra_files.first().cloned() {
                std::fs::remove_file(&dst).map_err(|e| utils::oserror(&e, Path::new(&dst)))?;
                self.extra_files.remove(0);
            }
            let temp_run = self.tempdir()?.join("run");
            let prefix = Path::new(&self.prefix);
            let temp_nm_path = temp_run.join("NetworkManager/system-connections");
            let temp_networkd_path = temp_run.join("systemd/network");
            for (temp, live) in [
                (
                    temp_nm_path,
                    prefix.join("run/NetworkManager/system-connections"),
                ),
                (temp_networkd_path, prefix.join("run/systemd/network")),
            ] {
                if temp.exists() {
                    std::fs::remove_dir_all(&live).map_err(|e| utils::oserror(&e, &live))?;
                    copy_tree(&temp, &live, false, false)?;
                }
            }
            Ok(())
        })();
        if let Err(e) = result {
            if e.downcast_ref::<py::Exit>().is_some() {
                return Err(e);
            }
            // If we reach here, we're in big trouble. We may have wiped out
            // file NM or networkd are using, and we most likely removed the
            // "new" config -- or at least our copy of it.
            py::error(&format!(
                "Something really bad happened while reverting config: {e}"
            ));
            py::error("You should verify the netplan YAML in /etc/netplan and probably run 'netplan apply' again.");
            return py::exit(-1);
        }
        Ok(())
    }

    pub fn cleanup(&mut self) -> Result<()> {
        if let Some(t) = self.tempdir.take() {
            std::fs::remove_dir_all(&t).map_err(|e| utils::oserror(&e, &t))?;
        }
        Ok(())
    }
}

impl Drop for ConfigManager {
    fn drop(&mut self) {
        // __del__: cleanup(), ignoring an already removed tempdir
        if let Some(t) = self.tempdir.take() {
            let _ = std::fs::remove_dir_all(t);
        }
    }
}

/// `tempfile.mkdtemp(prefix=prefix)`
pub fn mkdtemp(prefix: &str) -> Result<PathBuf> {
    let base = std::env::var("TMPDIR")
        .ok()
        .filter(|d| Path::new(d).is_dir())
        .unwrap_or_else(|| "/tmp".into());
    let template = Path::new(&base).join(format!("{prefix}XXXXXXXX"));
    nix::unistd::mkdtemp(&template).map_err(|e| utils::oserror(&std::io::Error::from(e), &template))
}

/// `shutil.copy(src, dst)`: content and permission bits.
pub fn copy_file(src: &str, dst: &str) -> Result<()> {
    let mut target = PathBuf::from(dst);
    if target.is_dir() {
        target = target.join(Path::new(src).file_name().unwrap_or_default());
    }
    std::fs::copy(src, &target).map_err(|e| utils::oserror(&e, Path::new(src)))?;
    Ok(())
}

/// `shutil.copytree(src, dst, copy_function=copy_with_ownership)`: `dst`
/// must not exist unless `dirs_exist_ok`; a missing `src` is ignored when
/// `missing_ok`.
pub fn copy_tree(src: &Path, dst: &Path, missing_ok: bool, dirs_exist_ok: bool) -> Result<()> {
    let entries = match std::fs::read_dir(src) {
        Ok(e) => e,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound && missing_ok => return Ok(()),
        Err(e) => return Err(utils::oserror(&e, src)),
    };
    if dirs_exist_ok {
        std::fs::create_dir_all(dst).map_err(|e| utils::oserror(&e, dst))?;
    } else {
        create_dirs(dst)?;
    }
    for entry in entries {
        let entry = entry.map_err(|e| utils::oserror(&e, src))?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        // symlinks are followed (symlinks=False)
        let meta = std::fs::metadata(&from).map_err(|e| utils::oserror(&e, &from))?;
        if meta.is_dir() {
            copy_tree(&from, &to, false, dirs_exist_ok)?;
        } else {
            copy_with_ownership(&from, &to)?;
        }
    }
    // copystat(src, dst) on the directory
    if let Ok(meta) = std::fs::metadata(src) {
        let _ =
            std::fs::set_permissions(dst, std::fs::Permissions::from_mode(meta.mode() & 0o7777));
    }
    Ok(())
}

/// `os.makedirs(dst)`: parents as needed, error if `dst` exists.
fn create_dirs(dst: &Path) -> Result<()> {
    if dst.exists() {
        return Err(utils::oserror(&std::io::Error::from_raw_os_error(17), dst));
    }
    std::fs::create_dir_all(dst).map_err(|e| utils::oserror(&e, dst))
}

/// `shutil.copy2()` followed by `os.chown()` to the source's owner.
fn copy_with_ownership(src: &Path, dst: &Path) -> Result<()> {
    std::fs::copy(src, dst).map_err(|e| utils::oserror(&e, src))?;
    let meta = std::fs::metadata(src).map_err(|e| utils::oserror(&e, src))?;
    let times = std::fs::FileTimes::new()
        .set_accessed(meta.accessed().unwrap_or(std::time::SystemTime::now()))
        .set_modified(meta.modified().unwrap_or(std::time::SystemTime::now()));
    if let Ok(f) = std::fs::File::options().write(true).open(dst) {
        let _ = f.set_times(times);
    }
    std::os::unix::fs::chown(dst, Some(meta.uid()), Some(meta.gid()))
        .map_err(|e| utils::oserror(&e, dst))?;
    Ok(())
}
