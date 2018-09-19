---
title: netplan-try
section: 8
author:
- Daniel Axtens (<daniel.axtens@canonical.com>)
...

# NAME

netplan-try - try a configuration, optionally rolling it back

# SYNOPSIS

  **netplan** [--debug] **try** -h | --help

  **netplan** [--debug] **try** [--config-file _CONFIG_FILE_] [--timeout _TIMEOUT_]

# DESCRIPTION

**netplan try** takes a **netplan**(5) configuration, applies it, and
automatically rolls it back if the user does not confirm the
configuration within a time limit.

This may be especially useful on remote systems, to prevent an
administrator being permanently locked out of systems in the case of a
network configuration error.

# OPTIONS

  -h, --help
:    Print basic help.

  --debug
:    Print debugging output during the process.

  --config-file _CONFIG_FILE_
:   In addition to the usual configuration, apply _CONFIG_FILE_. It must
    be a YAML file in the **netplan**(5) format.

 --timeout _TIMEOUT_
:   Wait for _TIMEOUT_ seconds before reverting. Defaults to 120
    seconds. Note that some network configurations (such as STP) may take
    over a minute to settle.

# KNOWN ISSUES

**netplan try** uses similar procedures to **netplan apply**, so some
of the same caveats apply around virtual devices.

There are also some known bugs: if **netplan try** times out or is
cancelled, make sure to verify if the network configuration has in
fact been reverted.

As with **netplan apply**, a reboot should fix any issues. However, be
sure to verify that the config on disk is in the state you expect
before rebooting!

# SEE ALSO

  **netplan**(5), **netplan-generate**(8), **netplan-apply**(8)

