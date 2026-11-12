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

//! Centralised subprocess execution.
//!
//! All command invocations go through [`Command`] + [`CommandRunner`] so
//! that the implementation can be swapped for a mock in tests.

use std::ops::Deref;
use std::process::{self, Output, Stdio};

use anyhow::{Context, Result};

pub(crate) trait CommandRunner {
    fn run<'args>(
        &self,
        command: Command<'args, impl Iterator<Item = &'args str>>,
    ) -> Result<Output>;
}

#[derive(Debug, Default)]
pub(crate) struct NativeCommandRunner;

impl NativeCommandRunner {
    pub(crate) fn new() -> Self {
        Self
    }
}

impl CommandRunner for NativeCommandRunner {
    fn run<'args>(
        &self,
        command: Command<'args, impl Iterator<Item = &'args str>>,
    ) -> Result<Output> {
        let Command {
            name,
            args,
            stdin,
            stdout,
            stderr,
        } = command;
        let mut cmd = process::Command::new(name);
        if let Some(args) = args {
            cmd.args(args);
        }
        if let Some(stdin) = stdin {
            cmd.stdin(stdin);
        }
        if let Some(stdout) = stdout {
            cmd.stdout(stdout);
        }
        if let Some(stderr) = stderr {
            cmd.stderr(stderr);
        }

        let ret = cmd
            .output()
            .with_context(|| format!("failed to run '{name}'"))?;
        if !ret.status.success() {
            return Err(ProcessError {
                name: name.to_string(),
                output: ret,
            }
            .into());
        }
        Ok(ret)
    }
}

#[derive(Debug, thiserror::Error)]
#[error("'{name}' terminated unsuccessfully")]
pub(crate) struct ProcessError {
    pub(crate) name: String,
    pub(crate) output: Output,
}

impl Deref for ProcessError {
    type Target = Output;

    fn deref(&self) -> &Self::Target {
        &self.output
    }
}

#[derive(Debug)]
#[must_use]
pub(crate) struct Command<'args, A: 'args> {
    name: &'args str,
    args: Option<A>,
    stdin: Option<Stdio>,
    stdout: Option<Stdio>,
    stderr: Option<Stdio>,
}

impl<'args> Command<'args, std::iter::Empty<&'args str>> {
    pub(crate) fn new(name: &'args str) -> Self {
        Self {
            name,
            args: None,
            stdin: None,
            stdout: None,
            stderr: None,
        }
    }

    pub(crate) fn args<I: IntoIterator<Item = &'args str>>(
        self,
        args: I,
    ) -> Command<'args, I::IntoIter> {
        Command {
            name: self.name,
            args: Some(args.into_iter()),
            stdin: self.stdin,
            stdout: self.stdout,
            stderr: self.stderr,
        }
    }
}

impl<'args, A> Command<'args, A> {
    #[allow(dead_code)]
    pub(crate) fn stdin(mut self, stdin: impl Into<Stdio>) -> Self {
        self.stdin = Some(stdin.into());
        self
    }
}

impl<'args, A> Command<'args, A>
where
    A: Iterator<Item = &'args str>,
{
    pub(crate) fn run_with(self, runner: &impl CommandRunner) -> Result<Output> {
        runner.run(self)
    }
}
