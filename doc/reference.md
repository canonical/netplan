# Reference

Netplan's configuration files use the
[YAML](<http://yaml.org/spec/1.1/current.html>) format. All
`/{lib,etc,run}/netplan/*.yaml` are considered.

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

## API specification
`libnetplan` is a component of the Netplan. project that contains the logic for
data parsing, validation and generation. It is build as a dynamic `.so` library
that can be used from different binaries (like Netplan’s `generate`,
`netplan-dbus`, the `netplan apply/try/get/set/...` CLI or via the corresponding
Python bindings or external applications like the NetworkManager, using the
Netplan backend).

* [API reference](https://discourse.ubuntu.com/t/29106)
  – C API and Python bindings for libnetplan
