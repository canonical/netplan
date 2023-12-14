---
title: NETPLAN-STATUS
section: 8
author:
- Danilo Egea Gondolfo (danilo.egea.gondolfo@canonical.com)
...

## NAME

`netplan-status` - query networking state of the running system

## SYNOPSIS

  **`netplan`** \[*--debug*\] **status** **-h**|**--help**

  **`netplan`** \[*--debug*\] **status** \[*interface*\]

## DESCRIPTION

**`netplan status [interface]`** queries the current network configuration and displays it in human-readable format.

You can specify `interface` to display the status of a specific interface.

Currently, **`netplan status`** depends on `systemd-networkd` as a source of data and will try to start it if it's not masked.

## OPTIONS

`-h`, `--help`
:   Print basic help.

`--debug`
:   Print debugging output during the process.

`-a`, `--all`
:   Show all interface data including inactive.

`-f` *`FORMAT`*, `--format` *`FORMAT`*
:   Output in machine-readable `json` or `yaml` format.

## SEE ALSO

  **`netplan`**(5), **`netplan-get`**(8), **`netplan-ip`**(8)
