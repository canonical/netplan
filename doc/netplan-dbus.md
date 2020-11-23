---
title: netplan-dbus
section: 8
author:
- Lukas Märdian (<lukas.maerdian@canonical.com>)
...

# NAME

netplan-dbus - daemon to access netplan's functionality via a DBus API

# SYNOPSIS

  **netplan-dbus**

# DESCRIPTION

**netplan-dbus** is a DBus daemon, providing ``io.netplan.Netplan`` on the system bus. The ``/io/netplan/Netplan`` object provides an ``io.netplan.Netplan`` interface, offering the following methods:

 * ``Apply() -> b``: calls **netplan apply** and returns a success or failure status.
 * ``Info() -> a(sv)``: returns a dict "Features -> as", containing an array of all available feature flags.
 * ``Config() -> o``: prepares a new config object as ``/io/netplan/Netplan/config/<ID>``, by copying the current state from ``/{etc,run,lib}/netplan/*.yaml``

The ``/io/netplan/Netplan/config/<ID>`` objects provide a ``io.netplan.Netplan.Config`` interface, offering the following methods:

 * ``Get() -> s``: calls **netplan get --root-dir=/tmp/netplan-config-ID all** and returns the merged YAML config of the the given config object's state
 * ``Set(s:CONFIG_DELTA, s:ORIGIN_HINT) -> b``: calls **netplan set --root-dir=/tmp/netplan-config-ID --origin-hint=<ORIGIN_HINT> CONFIG_DELTA**, where CONFIG_DELTA can be something like: ``network.ethernets.eth0.dhcp4=true`` and ORIGIN_HINT can be something like: ``70-snapd`` (it will then write the config to ``70-snapd.yaml``)
 * ``Try(u:TIMEOUT_SEC) -> b``: replaces the main netplan configuration with this config object's state and calls **netplan try --timeout=TIMEOUT_SEC**
 * ``Cancel() -> b``: rejects a currently running ``Try()`` attempt on this config object and/or discards the config object
 * ``Apply() -> b``: replaces the main netplan configuration with this config object's state and calls **netplan apply**

For information about the Apply()/Try()/Get()/Set() functionality, see
**netplan-apply**(8)/**netplan-try**(8)/**netplan-get**(8)/**netplan-set**(8)
accordingly. For details of the configuration file format, see **netplan**(5).

# SEE ALSO

  **netplan**(5), **netplan-apply**(8), **netplan-try**(8), **netplan-get**(8),
  **netplan-set**(8)
