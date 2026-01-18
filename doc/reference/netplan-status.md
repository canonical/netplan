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

`--diff`
:   Analyse and display differences between the current system configuration and network definitions present in the YAML files.
    The configuration analysed includes IP addresses, routes, MAC addresses, DNS addresses, search domains and missing network interfaces.

    The output format is similar to popular diff tools, such `diff` and `git diff`. Configuration present only in the system (and therefore missing in the Netplan YAML)
    will be displayed with a `+` sign and will be highlighted in green. Configuration present only in Netplan (and therefore missing in the system) will be displayed
    with a `-` sign and highlighted in red. The same is applied to network interfaces.

`--diff-only`
:   Same as `--diff` but omits all the information that is not a difference.

`--root-dir`
:   Read YAML files from this root instead of `/`.

`--verbose`
:   Show extra information.

`-f` *`FORMAT`*, `--format` *`FORMAT`*
:   Output in machine-readable `json` or `yaml` format.

## SEE ALSO

  **`netplan`**(5), **`netplan-get`**(8), **`netplan-ip`**(8)
