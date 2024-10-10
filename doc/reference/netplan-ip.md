---
title: NETPLAN-IP
section: 8
author:
- Danilo Egea Gondolfo (danilo.egea.gondolfo@canonical.com)
...

## NAME

`netplan-ip` - retrieve IP information (like DHCP leases) from the system

## SYNOPSIS

  **`netplan`** \[*--debug*\] **ip** **-h**|**--help**

  **`netplan`** \[*--debug*\] **ip** *COMMAND* \[*--root-dir=ROOT_DIR*\] *ARGUMENTS*

## DESCRIPTION

**`netplan ip`** retrieves IP information (like DHCP leases) from the system.

## DHCP COMMANDS

**`leases`** `INTERFACE`
:    Displays DHCP IP leases

     Example: `netplan ip leases enp5s0`

## OPTIONS

`-h`, `--help`
:    Print basic help.

`--debug`
:    Print debugging output during the process.

`--root-dir`
:    Read YAML files from this root instead of `/`.

## SEE ALSO

  **`netplan`**(5), **`netplan-get`**(8), **`netplan-status`**(8)
