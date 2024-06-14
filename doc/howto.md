# How-to guides

This is a collection of how-to guides for common scenarios. If you see a scenario missing or have one to contribute, [file an issue](https://bugs.launchpad.net/netplan/+filebug) against this documentation with the example.

To configure Netplan, save configuration files in the `/etc/netplan/` directory with a `.yaml` extension (e.g. `/etc/netplan/config.yaml`), then run `sudo netplan apply`. This command parses and applies the configuration to the system. Configuration written to disk under `/etc/netplan/` persists between reboots. Visit [Applying new Netplan configuration](/netplan-tutorial.md#applying-new-netplan-configuration) for detailed guidance.

For each of the examples below, use the `renderer` that applies to your scenario. For example, for Ubuntu Desktop, the `renderer` is usually `NetworkManager`. For Ubuntu Server, it is `networkd`.


## Quick configuration examples

```{toctree}
:maxdepth: 1

examples
```

YAML configuration snippets for these examples, as well as additional examples, are available in the [examples](https://github.com/canonical/netplan/tree/main/examples) directory on GitHub.


## Complex how-to guides

```{toctree}
:maxdepth: 1

using-static-ip-addresses
matching-interface-by-mac-address
creating-link-aggregation
dbus-config
netplan-everywhere
single-nic-vm-host
single-nic-vm-host-with-vlans
```


## Documentation

```{toctree}
:maxdepth: 1

contribute-docs
```
