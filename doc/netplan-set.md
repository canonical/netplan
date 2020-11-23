---
title: netplan-set
section: 8
author:
- Lukas Märdian (lukas.maerdian@canonical.com)
...

# NAME

netplan-set - write netplan YAML configuration snippets to file

# SYNOPSIS

  **netplan** [--debug] **set** -h | --help

  **netplan** [--debug] **set** [--root-dir=ROOT_DIR] [--origin-hint=ORIGIN_HINT] [key=value]

# DESCRIPTION

**netplan set [key=value]** writes a given key/value pair or YAML subtree into a YAML file in ``/etc/netplan/*.yaml`` and validates its format.

You can specify a single value as: ``"[network.]ethernets.eth0.dhcp4=[1.2.3.4/24, 5.6.7.8/24]"`` or a full subtree as: ``"[network.]ethernets.eth0={dhcp4: true, dhcp6: true}``.

For details of the configuration file format, see **netplan**(5).

# OPTIONS

  -h, --help
:    Print basic help.

  --debug
:    Print debugging output during the process.

  --root-dir
:    Write YAML files into this root instead of /

  --origin-hint
:    Specify the name of the overwrite YAML file, e.g.: ``70-netplan-set`` => ``/etc/netplan/70-netplan-set.yaml``

# SEE ALSO

  **netplan**(5), **netplan-get**(8), **netplan-dbus**(8)
