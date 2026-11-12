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

//! `netplan apply` – apply current netplan config to the running system.
//!
//! Port of `netplan_cli/cli/commands/apply.py`.

use std::path::Path;

use anyhow::Result;

use crate::argparse::Arg;
use crate::configmanager::{self, ConfigManager, CONFIG_ERRORS};
use crate::utils::sub::{self, Io};
use crate::utils::{self, GENERATOR_LATE_DIR};
use crate::{cli, ovs, py, sriov};

pub const OVS_CLEANUP_SERVICE: &str = "netplan-ovs-cleanup.service";

const IF_NAMESIZE: usize = 16;

/// `os.EX_CONFIG`
pub const EX_CONFIG: i32 = 78;
/// `os.EX_NOPERM`
const EX_NOPERM: i32 = 77;

/// `NetplanApply`
#[derive(Default)]
pub struct NetplanApply {
    pub sriov_only: bool,
    pub only_ovs_cleanup: bool,
    pub state: Option<String>,
}

/// `netplan apply [--sriov-only] [--only-ovs-cleanup] [--state DIR]`
pub fn command(argv0: &str, args: &[String]) -> Result<i32> {
    let mut p = cli::command_parser(argv0, "apply", cli::description("apply"));
    p.add(
        Arg::new(&["--sriov-only"])
            .store_true()
            .help("Only apply SR-IOV related configuration and exit"),
    );
    p.add(
        Arg::new(&["--only-ovs-cleanup"])
            .store_true()
            .help("Only clean up old OpenVSwitch interfaces and exit"),
    );
    p.add(Arg::new(&["--state"]).help("Directory containing previous YAML configuration"));
    let ns = cli::parse_leaf(&p, args)?;
    let mut apply = NetplanApply {
        sriov_only: ns.bool("sriov_only"),
        only_ovs_cleanup: ns.bool("only_ovs_cleanup"),
        state: ns.str("state"),
    };
    apply.command_apply(true, false, true, None)?;
    Ok(0)
}

impl NetplanApply {
    pub fn command_apply(
        &mut self,
        run_generate: bool,
        mut sync: bool,
        exit_on_error: bool,
        state_dir: Option<&str>,
    ) -> Result<()> {
        let mut config_manager = ConfigManager::new("/");
        if let Some(s) = state_dir {
            self.state = Some(s.to_string());
        }

        // For certain use-cases, we might want to only apply specific configuration.
        // If we only need SR-IOV configuration, do that and exit early.
        if self.sriov_only {
            return process_sriov_config(&mut config_manager, exit_on_error);
        }
        // If we only need OpenVSwitch cleanup, do that and exit early.
        if self.only_ovs_cleanup {
            return process_ovs_cleanup(&mut config_manager, false, false, exit_on_error);
        }

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
                "Apply",
            ])?;
            if res != 0 {
                if exit_on_error {
                    return py::exit(res);
                } else if res == 130 {
                    return Err(py::Exception::err(
                        "PermissionError",
                        "failed to communicate with dbus service",
                    ));
                } else {
                    return Err(py::Exception::err(
                        "RuntimeError",
                        format!("failed to communicate with dbus service: error {res}"),
                    ));
                }
            }
            return Ok(());
        }

        let ovs_cleanup_service = format!("{GENERATOR_LATE_DIR}{OVS_CLEANUP_SERVICE}");
        let old_files_networkd = !utils::glob_paths("/run/systemd/network/*netplan-*").is_empty();
        let mut old_ovs_glob = utils::glob_paths(&format!("{GENERATOR_LATE_DIR}netplan-ovs-*"));
        // Ignore netplan-ovs-cleanup.service, as it can always be there
        remove_first(&mut old_ovs_glob, &ovs_cleanup_service);
        let old_files_ovs = !old_ovs_glob.is_empty();
        let old_nm_glob = utils::glob_paths("/run/NetworkManager/system-connections/netplan-*");
        let mut nm_ifaces =
            get_nm_interfaces(&old_nm_glob, &utils::get_interfaces(), exit_on_error)?;
        let old_files_nm = !old_nm_glob.is_empty();

        let mut configure: Vec<String> = vec![];
        let mut configure_out = Io::Inherit;
        if std::env::var_os("NETPLAN_PROFILE").is_some() {
            configure.extend(["valgrind".to_string(), "--leak-check=full".to_string()]);
            configure_out = Io::Stdout;
        }
        configure.push(utils::get_configure_path());
        if run_generate {
            py::debug(&format!(
                "command configure: running {}",
                utils::py_repr_list(&configure)
            ));
            let argv: Vec<&str> = configure.iter().map(String::as_str).collect();
            if sub::call_with(&argv, Io::Inherit, configure_out)? != 0 {
                if exit_on_error {
                    return py::exit(EX_CONFIG);
                }
                return Err(configmanager::configuration_error(
                    "the configuration could not be generated".into(),
                ));
            }
            // Running 'systemctl daemon-reload' will re-run the netplan systemd generator.
            py::debug("executing Netplan systemd-generator via daemon-reload");
            let res = utils::systemctl_daemon_reload()?;
            if res != 0 {
                if exit_on_error {
                    return py::exit(res);
                }
                return Err(py::Exception::err(
                    "RuntimeError",
                    format!("systemctl daemon-reload call failed: error {res}"),
                ));
            }
        }

        let mut devices = utils::get_interfaces();

        // Re-start service when
        // 1. We have configuration files for it
        // 2. Previously we had config files for it but not anymore
        let mut restart_networkd = !utils::glob_paths("/run/systemd/network/*netplan-*").is_empty();
        if !restart_networkd && old_files_networkd {
            restart_networkd = true;
        }
        let mut restart_ovs_glob = utils::glob_paths(&format!("{GENERATOR_LATE_DIR}netplan-ovs-*"));
        remove_first(&mut restart_ovs_glob, &ovs_cleanup_service);
        let restart_ovs = !restart_ovs_glob.is_empty();
        if !restart_ovs && old_files_ovs {
            // OVS is managed via systemd units
            restart_networkd = true;
        }

        let restart_nm_glob = utils::glob_paths("/run/NetworkManager/system-connections/netplan-*");
        for i in get_nm_interfaces(&restart_nm_glob, &devices, exit_on_error)? {
            if !nm_ifaces.contains(&i) {
                nm_ifaces.push(i);
            }
        }
        let mut restart_nm = !restart_nm_glob.is_empty();
        if !restart_nm && old_files_nm {
            restart_nm = true;
        }

        // stop backends
        if restart_networkd {
            py::debug("netplan generated networkd configuration changed, reloading networkd");
            // Clean up any old netplan related OVS ports/bonds/bridges, if applicable
            process_ovs_cleanup(
                &mut config_manager,
                old_files_ovs,
                restart_ovs,
                exit_on_error,
            )?;
            utils::systemctl("stop", &["netplan-wpa-*.service"], sync)?;
        } else {
            py::debug("no netplan generated networkd configuration exists");
        }

        let mut loopback_connection = String::new();
        if restart_nm {
            py::debug("netplan generated NM configuration changed, restarting NM");
            if utils::nm_running()? {
                if nm_ifaces.iter().any(|i| i == "lo") {
                    loopback_connection = utils::nm_get_connection_for_interface("lo")?;
                }
                // restarting NM does not cause new config to be applied, need to shut down devices first
                for device in &devices {
                    if !nm_ifaces.contains(device) {
                        continue; // do not touch this interface
                    }
                    // ignore failures here -- some/many devices might not be managed by NM
                    match utils::nmcli(&["device", "disconnect", device]) {
                        Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => {}
                        other => other?,
                    }
                }
                utils::systemctl_network_manager("stop", sync)?;
            }
        } else {
            py::debug("no netplan generated NM configuration exists");
        }

        // Refresh devices now; restarting a backend might have made something appear.
        devices = utils::get_interfaces();

        // evaluate config for extra steps we need to take (like renaming)
        // for now, only applies to non-virtual (real) devices.
        config_manager.parse(&[])?;
        let changes = process_link_changes(&devices, &config_manager);
        // delete virtual interfaces that have been defined in a previous state
        // but are not configured anymore in the current YAML
        if let Some(state) = self.state.as_deref().filter(|s| !s.is_empty()) {
            let mut cm = ConfigManager::new(state);
            cm.parse(&[])?; // get previous configuration state
            let prev_links: Vec<String> = cm
                .virtual_interfaces()
                .into_iter()
                .map(|(k, _)| k)
                .collect();
            let curr_links: Vec<String> = config_manager
                .virtual_interfaces()
                .into_iter()
                .map(|(k, _)| k)
                .collect();
            clear_virtual_links(&prev_links, &curr_links, &devices)?;
        }

        // if the interface is up, we can still apply some .link file changes
        // but we cannot apply the interface rename via udev, as it won't touch
        // the interface name, if it was already renamed once (e.g. during boot),
        // because of the NamePolicy=keep default:
        // https://www.freedesktop.org/software/systemd/man/systemd.net-naming-scheme.html
        devices = utils::get_interfaces();
        for device in &devices {
            py::debug(&format!("netplan triggering .link rules for {device}"));
            let syspath = format!("/sys/class/net/{device}");
            let result = sub::check_call_with(
                &["udevadm", "test-builtin", "net_setup_link", &syspath],
                Io::Null,
                Io::Null,
            )
            .and_then(|_| sub::check_call_with(&["udevadm", "test", &syspath], Io::Null, Io::Null));
            match result {
                Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => {
                    py::debug(&format!("Ignoring device without syspath: {device}"));
                }
                other => other?,
            }
        }

        let devices_after_udev = utils::get_interfaces();
        // apply some more changes manually
        for (iface, new_name) in &changes {
            // rename non-critical network interfaces
            if new_name.is_empty() {
                continue;
            }
            if new_name.chars().count() >= IF_NAMESIZE {
                py::warning(&format!(
                    "Interface name {new_name} is too long. {iface} will not be renamed"
                ));
                continue;
            }
            if devices.contains(iface) && devices_after_udev.contains(new_name) {
                py::debug(&format!(
                    "Interface rename {iface} -> {new_name} already happened."
                ));
                continue; // re-name already happened via 'udevadm test'
            }
            // bring down the interface, using its current (matched) interface name
            sub::check_call_with(
                &["ip", "link", "set", "dev", iface, "down"],
                Io::Null,
                Io::Null,
            )?;
            // rename the interface to the name given via 'set-name'
            sub::check_call_with(
                &["ip", "link", "set", "dev", iface, "name", new_name],
                Io::Null,
                Io::Null,
            )?;
        }

        sub::check_call(&["udevadm", "control", "--reload"])?;

        match sub::check_call(&[
            "udevadm",
            "trigger",
            "--action=move",
            "--subsystem-match=net",
            "--settle",
        ]) {
            // udevadm trigger returns 1 if it cannot trigger devices since
            // systemd v248, e.g. in containers (LP: #2095203)
            Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => {
                py::warning(&format!("Ignoring device trigger error: {e}"));
            }
            other => other?,
        }

        // apply any SR-IOV related changes, if applicable
        process_sriov_config(&mut config_manager, exit_on_error)?;

        // (re)set global regulatory domain
        if Path::new(&format!("{GENERATOR_LATE_DIR}netplan-regdom.service")).exists() {
            utils::systemctl("start", &["netplan-regdom.service"], false)?;
        }
        // (re)start backends
        if restart_networkd {
            let basenames = |pattern: &str| -> Vec<String> {
                utils::glob_paths(pattern)
                    .into_iter()
                    .filter(|f| !f.ends_with(&format!("/{OVS_CLEANUP_SERVICE}")))
                    .map(|f| f.rsplit('/').next().unwrap_or_default().to_string())
                    .collect()
            };
            let netplan_wpa = basenames(&format!(
                "{GENERATOR_LATE_DIR}*.wants/netplan-wpa-*.service"
            ));
            // exclude the special 'netplan-ovs-cleanup.service' unit
            let netplan_ovs = basenames(&format!(
                "{GENERATOR_LATE_DIR}*.wants/netplan-ovs-*.service"
            ));
            // Run 'systemctl start' command synchronously, to avoid race conditions
            // with 'oneshot' systemd service units, e.g. netplan-ovs-*.service.
            let reload = utils::networkctl_reload()
                .and_then(|_| utils::networkd_interfaces())
                .and_then(|ifaces| utils::networkctl_reconfigure(&ifaces));
            match reload {
                Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => {
                    // (re-)start systemd-networkd if it is not running, yet
                    py::warning("Falling back to a hard restart of systemd-networkd.service");
                    utils::systemctl("restart", &["systemd-networkd.service"], true)?;
                }
                other => other?,
            }
            // 1st: execute OVS cleanup, to avoid races while applying OVS config
            utils::systemctl("start", &[OVS_CLEANUP_SERVICE], true)?;
            // 2nd: start all other services
            let start: Vec<String> = netplan_wpa.into_iter().chain(netplan_ovs).collect();
            utils::systemctl("start", &start, true)?;
        }
        if restart_nm {
            // Flush all IP addresses of NM managed interfaces, to avoid NM creating
            // new, non netplan-* connection profiles, using the existing IPs.
            let nm_interfaces = get_nm_interfaces(&restart_nm_glob, &devices, exit_on_error)?;
            for iface in &nm_interfaces {
                utils::ip_addr_flush(iface)?;
            }
            // clear NM state, especially the [device].managed=true config, as that might have been
            // re-set via an udev rule setting "NM_UNMANAGED=1"
            let _ = std::fs::remove_dir_all("/run/NetworkManager/devices");
            utils::systemctl_network_manager("start", sync)?;

            // If 'lo' is in the nm_interfaces set we flushed it's IPs (see above) and disconnected it.
            // NM will not bring it back automatically after restarting and we need to do that manually.
            // For that, we need NM up and ready to accept commands
            let lo_managed = nm_interfaces.iter().any(|i| i == "lo");
            if lo_managed {
                sync = true;
            }

            if sync {
                // wait a bit for 'connected (site/local-only)' or
                // 'connected' to appear in 'nmcli general' STATE
                for _ in 0..10 {
                    let out = sub::run(&["nmcli", "general", "status"], Io::Pipe, Io::Pipe)?;
                    // Handle nmcli's "not running" return code (8) gracefully,
                    // giving some more time for NetworkManager startup
                    if out.returncode == 8 {
                        std::thread::sleep(std::time::Duration::from_secs(1));
                        continue;
                    }
                    if out.stdout.contains("\nconnected") {
                        break;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(500));
                }
            }

            // If "lo" is managed by NM through Netplan, apply will flush its addresses and disconnect it.
            // NM will not bring it back automatically.
            if lo_managed && !loopback_connection.is_empty() {
                utils::nm_bring_interface_up(&loopback_connection)?;
            }
        }
        Ok(())
    }
}

fn remove_first(list: &mut Vec<String>, item: &str) {
    if let Some(i) = list.iter().position(|x| x == item) {
        list.remove(i);
    }
}

/// Calculate the delta of virtual links. And remove the links that were
/// dropped from the YAML config, if they were not dropped by the backend
/// already.
pub fn clear_virtual_links(
    prev_links: &[String],
    curr_links: &[String],
    devices: &[String],
) -> Result<Vec<String>> {
    if devices.is_empty() {
        py::warning("Cannot clear virtual links: no network interfaces provided.");
        return Ok(vec![]);
    }
    let dropped: Vec<String> = prev_links
        .iter()
        .filter(|l| !curr_links.contains(l))
        .cloned()
        .collect();
    // some interfaces might have been cleaned up already, e.g. by the
    // NetworkManager backend
    for link in dropped.iter().filter(|l| devices.contains(l)) {
        match sub::check_call(&["ip", "link", "delete", "dev", link]) {
            Err(e) if sub::is_exception(&e, &["subprocess.CalledProcessError"]) => {
                py::warning(&format!("Could not delete interface {link}"));
            }
            other => other?,
        }
    }
    Ok(dropped)
}

/// Go through the pending changes and pick what needs special handling.
/// Only applies to non-critical interfaces which can be safely updated.
/// Returns `(current name, new name)` pairs.
fn process_link_changes(
    interfaces: &[String],
    config_manager: &ConfigManager,
) -> Vec<(String, String)> {
    let mut changes: Vec<(String, String)> = vec![];

    // Find physical interfaces which need a rename
    // But do not rename virtual interfaces
    for (id, netdef) in config_manager.physical_interfaces() {
        let Some(newname) = netdef.set_name().ok().flatten() else {
            continue; // Skip if no new name needs to be set
        };
        if !netdef.has_match() {
            continue; // Skip if no match for current name is given
        }
        // Find current name of the interface, according to match conditions and globs (name, mac, driver)
        let Some(current_iface_name) = utils::find_matching_iface(interfaces, &netdef) else {
            py::warning(&format!("Cannot find unique matching interface for {id}"));
            continue;
        };
        if current_iface_name == newname {
            // Skip interface if it already has the correct name
            py::debug(&format!("Skipping correctly named interface: {newname}"));
            continue;
        }
        if netdef.critical() {
            // Skip interfaces defined as critical, as we should not take them down in order to rename
            py::warning(&format!(
                "Cannot rename {id} ({current_iface_name} -> {newname}) at runtime (needs reboot), due to being critical"
            ));
            continue;
        }

        // record the interface rename change
        match changes.iter_mut().find(|(k, _)| *k == current_iface_name) {
            Some(entry) => entry.1 = newname,
            None => changes.push((current_iface_name, newname)),
        }
    }

    if py::debug_enabled() {
        let items: Vec<String> = changes
            .iter()
            .map(|(k, v)| {
                format!(
                    "{}: {{'name': {}}}",
                    utils::py_repr_str(k),
                    utils::py_repr_str(v)
                )
            })
            .collect();
        py::debug(&format!("Link changes: {{{}}}", items.join(", ")));
    }
    changes
}

pub fn process_sriov_config(config_manager: &mut ConfigManager, exit_on_error: bool) -> Result<()> {
    match sriov::apply_sriov_config(config_manager, "/") {
        Err(e) if sub::is_exception(&e, CONFIG_ERRORS) => {
            py::error(&e.to_string());
            if exit_on_error {
                return py::exit(1);
            }
            Ok(())
        }
        other => other,
    }
}

pub fn process_ovs_cleanup(
    config_manager: &mut ConfigManager,
    ovs_old: bool,
    ovs_current: bool,
    exit_on_error: bool,
) -> Result<()> {
    match ovs::apply_ovs_cleanup(config_manager, ovs_old, ovs_current) {
        Err(e) if sub::is_exception(&e, &["OSError", "RuntimeError"]) => {
            py::error(&e.to_string());
            if exit_on_error {
                return py::exit(1);
            }
            Ok(())
        }
        Err(e) if sub::is_exception(&e, &[ovs::OVS_DB_SERVER_NOT_RUNNING]) => {
            py::warning(&format!("Cannot call Open vSwitch: {e}."));
            Ok(())
        }
        Err(e) if sub::is_exception(&e, &[ovs::OVS_DB_SERVER_NOT_INSTALLED]) => {
            py::debug(&format!("Cannot call Open vSwitch: {e}."));
            Ok(())
        }
        other => other,
    }
}

fn get_nm_interfaces(
    paths: &[String],
    devices: &[String],
    exit_on_error: bool,
) -> Result<Vec<String>> {
    match utils::nm_interfaces(paths, devices) {
        Err(e) if sub::is_exception(&e, &["PermissionError"]) => {
            py::error(&e.to_string());
            if exit_on_error {
                return py::exit(EX_NOPERM);
            }
            Err(e)
        }
        other => other,
    }
}
