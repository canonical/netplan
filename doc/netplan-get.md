---
title: netplan-get
section: 8
author:
- Lukas Märdian (lukas.maerdian@canonical.com)
...

## NAME

netplan-get - read merged netplan YAML configuration

## SYNOPSIS

  **netplan** [--debug] **get** -h | --help

  **netplan** [--debug] **get** [--root-dir=ROOT_DIR] [key]

## DESCRIPTION

**netplan get [key]** reads all YAML files from ``/{etc,lib,run}/netplan/*.yaml`` and returns a merged view of the current configuration

You can specify ``all`` as a key (the default) to get the full YAML tree or extract a subtree by specifying a nested key like: ``[network.]ethernets.eth0``.

For details of the configuration file format, see **netplan**(5).

## OPTIONS

  -h, --help
:    Print basic help.

  --debug
:    Print debugging output during the process.

  --root-dir
:    Read YAML files from this root instead of /

## SEE ALSO

  **netplan**(5), **netplan-set**(8), **netplan-dbus**(8)
