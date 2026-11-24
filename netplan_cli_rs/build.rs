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

use std::env;
use std::fs;
use std::io;
use std::os::unix::fs as unix_fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{Context, Result};

/// Standard Ubuntu/Debian multiarch library directories, in priority order.
const STANDARD_LIB_DIRS: &[&str] = &[
    "/usr/lib/aarch64-linux-gnu",
    "/usr/lib/x86_64-linux-gnu",
    "/usr/lib/arm-linux-gnueabihf",
    "/usr/local/lib",
    "/usr/lib",
];

fn main() -> Result<()> {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());

    // Emit every candidate search path we can find, from most to least specific.
    // The linker uses the first directory that contains the library.
    emit_link_search_paths(&manifest_dir)?;

    println!("cargo:rustc-link-lib=netplan");

    // Re-run if any source C/H files change (feature flag extraction)
    let src_dir = manifest_dir.parent().unwrap().join("src");
    println!("cargo:rerun-if-changed={}", src_dir.display());

    // Extract feature flags from /* netplan-feature: <name> */ annotations
    // in src/*.{h,c}, mirroring features_py_generator.sh logic.
    let features = extract_features(&src_dir)?;

    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let code = format!(
        "pub const FEATURE_FLAGS: &[&str] = &[{}];\n",
        features
            .iter()
            .map(|f| format!("\"{f}\""))
            .collect::<Vec<_>>()
            .join(", ")
    );
    let features_path = out_dir.join("features.rs");
    fs::write(&features_path, code)
        .with_context(|| format!("cannot write {}", features_path.display()))?;
    Ok(())
}

/// Locate `libnetplan.so*` and ensure the linker can find `-lnetplan`.
///
/// The linker requires an *unversioned* `libnetplan.so` symlink (normally
/// provided by the `-dev` package).  When only a versioned file exists
/// (e.g. `libnetplan.so.1` from the runtime package or a meson build), we
/// create a `libnetplan.so` symlink inside `OUT_DIR` and add that to the
/// search path.
fn emit_link_search_paths(manifest_dir: &Path) -> Result<()> {
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());

    // 1. NETPLAN_LIB_DIR env var — explicit override.
    if let Ok(dir) = env::var("NETPLAN_LIB_DIR") {
        ensure_unversioned_symlink(Path::new(&dir), &out_dir)?;
        println!("cargo:rustc-link-search=native={dir}");
        println!("cargo:rustc-link-search=native={}", out_dir.display());
        return Ok(());
    }

    // 2. pkg-config — authoritative when libnetplan-dev is installed or
    //    PKG_CONFIG_PATH points at the meson build's uninstalled pc files.
    for pc_name in &["netplan", "libnetplan"] {
        if let Some(dir) = pkg_config_libdir(pc_name) {
            let dir = PathBuf::from(&dir);
            ensure_unversioned_symlink(&dir, &out_dir)?;
            println!("cargo:rustc-link-search=native={}", dir.display());
            println!("cargo:rustc-link-search=native={}", out_dir.display());
            return Ok(());
        }
    }

    // 3. Walk every candidate directory.  Stop at the first one that holds
    //    any `libnetplan.so*` file and make the symlink if needed.
    for dir in candidate_dirs(manifest_dir) {
        if let Some(lib) = find_libnetplan_file(&dir)? {
            match lib.file_name().and_then(|n| n.to_str()) {
                Some("libnetplan.so") => {
                    // Unversioned file already present — dir is ready to use.
                    println!("cargo:rustc-link-search=native={}", dir.display());
                }
                _ => {
                    // Only a versioned file; create a libnetplan.so symlink.
                    make_symlink(&lib, &out_dir.join("libnetplan.so"))?;
                    println!("cargo:rustc-link-search=native={}", out_dir.display());
                }
            }
            return Ok(());
        }
    }

    // 4. Nothing found — emit all standard paths and hope for the best.
    for dir in STANDARD_LIB_DIRS {
        println!("cargo:rustc-link-search=native={dir}");
    }
    Ok(())
}

/// If `dir` contains only a versioned `libnetplan.so.X` (no plain `.so`),
/// create a `libnetplan.so` symlink in `link_dir`.
fn ensure_unversioned_symlink(dir: &Path, link_dir: &Path) -> Result<()> {
    if dir.join("libnetplan.so").exists() {
        return Ok(()); // already have an unversioned file
    }
    match find_libnetplan_file(dir)? {
        Some(versioned) => make_symlink(&versioned, &link_dir.join("libnetplan.so")),
        None => Ok(()),
    }
}

/// Create (or replace) a symlink at `link` pointing to `target`.
fn make_symlink(target: &Path, link: &Path) -> Result<()> {
    match fs::remove_file(link) {
        Ok(()) => {}
        Err(e) if e.kind() == io::ErrorKind::NotFound => {}
        Err(e) => return Err(e).with_context(|| format!("cannot remove {}", link.display())),
    }
    unix_fs::symlink(target, link)
        .with_context(|| format!("cannot create symlink {}", link.display()))
}

/// Collect all directories worth searching, meson build tree first.
fn candidate_dirs(manifest_dir: &Path) -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = Vec::new();

    // Meson / cmake build trees inside the parent repo directory.
    if let Some(repo_root) = manifest_dir.parent() {
        for bd_name in &[
            "build", "builddir", "_build", ".build", "out", "obj", "debug", "release",
        ] {
            let bd = repo_root.join(bd_name);
            if !bd.is_dir() {
                continue;
            }
            for sub in &["src", "lib", ""] {
                let dir = if sub.is_empty() {
                    bd.clone()
                } else {
                    bd.join(sub)
                };
                if dir.is_dir() {
                    dirs.push(dir);
                }
            }
        }
    }

    dirs.extend(STANDARD_LIB_DIRS.iter().map(PathBuf::from));

    dirs
}

/// Return the path to any `libnetplan.so*` file in `dir`, preferring the
/// unversioned name.  Returns `Ok(None)` if `dir` doesn't exist or contains
/// no such file.
fn find_libnetplan_file(dir: &Path) -> Result<Option<PathBuf>> {
    let entries = match fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e).with_context(|| format!("cannot read {}", dir.display())),
    };

    let mut versioned: Option<PathBuf> = None;
    for entry in entries {
        let entry = entry.with_context(|| format!("cannot read {}", dir.display()))?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let path = entry.path();
        match name.strip_prefix("libnetplan.so") {
            Some("") => return Ok(Some(path)), // exact match — no need to look further
            Some(_) if versioned.is_none() => versioned = Some(path),
            _ => {} // not a libnetplan.so* file, or a versioned one we already have
        }
    }
    Ok(versioned)
}

/// Query `pkg-config --variable=libdir <name>` and return the library directory,
/// or `None` if pkg-config is unavailable or the package is unknown.
fn pkg_config_libdir(name: &str) -> Option<String> {
    let out = Command::new("pkg-config")
        .args(["--variable=libdir", name])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let path = String::from_utf8(out.stdout).ok()?;
    let path = path.trim().to_string();
    if path.is_empty() {
        None
    } else {
        Some(path)
    }
}

/// Parse `src/*.{h,c}` (excluding `_`-prefixed files) for lines containing
/// `netplan-feature: <name>` and return a deduplicated, ordered list of names.
fn extract_features(src_dir: &Path) -> Result<Vec<String>> {
    let mut features: Vec<String> = Vec::new();

    let entries = match fs::read_dir(src_dir) {
        Ok(entries) => entries,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(features),
        Err(e) => return Err(e).with_context(|| format!("cannot read {}", src_dir.display())),
    };

    let mut paths: Vec<PathBuf> = Vec::new();
    for entry in entries {
        let entry = entry.with_context(|| format!("cannot read {}", src_dir.display()))?;
        let path = entry.path();
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if !name.starts_with('_') && (name.ends_with(".h") || name.ends_with(".c")) {
            paths.push(path);
        }
    }
    // Sort for deterministic output
    paths.sort();

    for path in paths {
        let content =
            fs::read_to_string(&path).with_context(|| format!("cannot read {}", path.display()))?;
        for line in content.lines() {
            if let Some(pos) = line.find("netplan-feature:") {
                let rest = &line[pos + "netplan-feature:".len()..];
                if let Some(name) = rest.split_whitespace().next() {
                    // Skip if first char is not alphabetic (e.g. stray "*/" tokens)
                    if name.starts_with(|c: char| c.is_ascii_alphabetic()) {
                        let name = name.to_string();
                        if !features.contains(&name) {
                            features.push(name);
                        }
                    }
                }
            }
        }
    }

    Ok(features)
}
