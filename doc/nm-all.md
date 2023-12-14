# NetworkManager default configuration

Without configuration, Netplan will not do anything. Therefore, on Desktop
systems, a useful configuration snippet to just bring up networking via DHCP is
as follows:

```yaml
network:
  version: 2
  renderer: NetworkManager
```

This will make NetworkManager manage all devices and by default. Any Ethernet
device will come up with DHCP, once carrier is detected. This is basically
Netplan passing control over to NetworkManager at boot time.

You can still define any more specific IDs in you Netplan configuration, to
configure interfaces individually, according to Netplan [YAML reference](/netplan-yaml/).

When NetworkManager [Netplan desktop integration](/netplan-everywhere/) is
activated, NetworkManager will automatically create specific Netplan IDs for
each of its connection profiles.

This configuration snippet is shipped by default on Ubuntu Desktop systems
through the [ubuntu-settings](https://launchpad.net/ubuntu/+source/ubuntu-settings)
package as `/usr/lib/netplan/00-network-manager-all.yaml`.
