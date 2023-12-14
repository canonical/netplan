# How-to guides

Below is a collection of how-to guides for common scenarios.
If you see a scenario missing or have one to contribute, please,
[file a bug](https://bugs.launchpad.net/netplan/+filebug) against this
documentation with the example.

To configure Netplan, save configuration files in the `/etc/netplan/` directory
with a `.yaml` extension (e.g. `/etc/netplan/config.yaml`), then run
`sudo netplan apply`. This command parses and applies the configuration to the
system. Configuration written to disk under `/etc/netplan/` persists between
reboots.

For each of the example below, use the `renderer` that applies to your scenario.
For example, for Ubuntu Desktop the `renderer` is usually `NetworkManager`,
and `networkd` for Ubuntu Server.

Also, see [/examples](https://github.com/canonical/netplan/tree/main/examples)
on GitHub.

```{toctree}
:maxdepth: 1

examples
dbus-config
netplan-everywhere
contribute-docs
```
