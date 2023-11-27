# Reference

## YAML configuration
Netplan's configuration files use the
[YAML (v1.1)](<http://yaml.org/spec/1.1/current.html>) format. All files in
`/{lib,etc,run}/netplan/*.yaml` are considered and are supposed to use
restrictive file permissions (`600` / `rw-------`), i.e. owner (root) read-write
only.

The top-level node in a netplan configuration file is a ``network:`` mapping
that contains ``version: 2`` (the YAML currently being used by curtin, MaaS,
etc. is version 1), and then device definitions grouped by their type, such as
``ethernets:``, ``modems:``, ``wifis:``, or ``bridges:``. These are the types
that our renderer can understand and are supported by our backends.

```{toctree}
---
maxdepth: 1
---
netplan-yaml
```

## libnetplan API
`libnetplan` is a component of the Netplan project that contains the logic for
data parsing, validation and generation. It is build as a dynamic `.so` library
that can be used from different binaries (like Netplan’s `generate`,
`netplan-dbus`, the `netplan apply/try/get/set/...` CLI or via the corresponding
Python bindings or external applications like the NetworkManager, using the
Netplan backend).

```{toctree}
libnetplan API <apidoc/index>
```

## Netplan CLI
Netplan's manpages describe the usage of the different command line interface
tools available. Those are also installed on a system running Netplan and can be
accessed, using the `man` utility.
```{toctree}
---
maxdepth: 2
---
cli
```

## Netplan D-Bus
Netplan provides a daemon that can be run to provide the `io.netplan.Netplan`
D-Bus API, to control certain aspects of a system's Netplan configuration
programmatically. See also: [DBus config API](/dbus-config).
```{toctree}
---
maxdepth: 1
---
Netplan D-Bus <netplan-dbus>
```
