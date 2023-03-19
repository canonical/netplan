---
title: netplan-validate
section: 8
author:
- Danilo Egea Gondolfo (danilo.egea.gondolfo@canonical.com)
...

## NAME

netplan-validate - parse and validate your configuration without applying it

## SYNOPSIS

  **netplan** [--debug] **validate** -h | --help

  **netplan** [--debug] **validate** [--root-dir=ROOT_DIR]

## DESCRIPTION

**netplan validate** reads and parses all YAML files from ``/{etc,lib,run}/netplan/*.yaml`` and shows any issues found with them.

It doesn't generate nor apply the configuration to the running system.

You can specify ``--debug`` to see what files are processed by Netplan in the order they are parsed.
It will also show what files were shadowed, if any.

For details of the configuration file format, see **netplan**(5).

## OPTIONS

  -h, --help
:    Print basic help.

  --debug
:    Print debugging output during the process.

  --root-dir
:    Read YAML files from this root instead of /

## RETURN VALUE

On success, no issues were found, 0 is returned to the shell.

On error, 1 is returned.

## SEE ALSO

  **netplan**(5), **netplan-generate**(8), **netplan-apply**(8)
