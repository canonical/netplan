# Netplan CLI
```{toctree}
---
maxdepth: 1
hidden: true
---
generate <netplan-generate>
apply <netplan-apply>
try <netplan-try>
get <netplan-get>
set <netplan-set>
```
Netplan provides a command line interface, called `netplan`, which a user can
utilize to control certain aspects of the Netplan configuration.

| Tool | Description |
| --- | --- |
| help | Show a generic help message |
| info | Show the available feature flags |
| ip | Query DHCP leases |
| [generate](/netplan-generate) | Generate backend specific configuration files from `/etc/netplan/*.yaml` |
| [apply](/netplan-apply) | Apply current netplan config to running system |
| [try](/netplan-try) | Try to apply a new netplan config to running system, with automatic rollback |
| [get](/netplan-get) | Get a setting by specifying a nested key like `"ethernets.eth0.addresses"`, or "all" |
| [set](/netplan-set) | Add new setting by specifying a dotted `key=value` pair like `"ethernets.eth0.dhcp4=true"` |
| rebind | Rebind SR-IOV virtual functions of given physical functions to their driver |
