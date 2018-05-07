---
title: netplan-apply
section: 8
author:
- Daniel Axtens (<daniel.axtens@canonical.com>)
...

# NAME

netplan-apply - apply configuration from netplan YAML files to a running system

# SYNOPSIS

  **netplan** [--debug] **apply** -h | --help

  **netplan** [--debug] **apply**

# DESCRIPTION

**netplan apply** applies the current netplan configuration to a running system.

The process works as follows:

 1. The backend configuration is generated from netplan YAML files.

 2. The appropriate backends (**systemd-networkd**(8) or
    **NetworkManager**(8)) are invoked to bring up configured interfaces.

 3. **netplan apply** iterates through interfaces that are still down, unbinding
    them from their drivers, and rebinding them. This gives **udev**(7) renaming
    rules the opportunity to run.

 4. If any devices have been rebound, the appropriate backends are re-invoked in
    case more matches can be done.

For information about the generation step, see
**netplan-generate**(8). For details of the configuration file format,
see **netplan**(5).

# OPTIONS

  -h, --help
:    Print basic help.

  --debug
:    Print debugging output during the process.

# KNOWN ISSUES

**netplan apply** looks for interfaces that are down after the first
pass and may unbind these interfaces from the drivers and rebind
them. While helpful for matches by name, this process is not always
robust and may lead to devices disappearing or being unexpectedly
renamed.

**netplan apply** will also not remove virtual devices such as bridges
and bonds that have been created, even if they are no longer described
in the netplan configuration.

In both of these cases the problems can be avoided or resolved by rebooting.

# SEE ALSO

  **netplan**(5), **netplan-generate**(8), **netplan-try**(8), **udev**(7),
  **systemd-networkd.service**(8), **NetworkManager**(8)
