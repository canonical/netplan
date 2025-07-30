---
title: "Introduction to Netplan"
---

Distribution installers, cloud instantiation, image builds for particular
devices, or any other way to deploy an operating system put its desired
network configuration into YAML configuration file(s). During
early boot, the Netplan "network renderer" runs which reads
`/{lib,etc,run}/netplan/*.yaml` and writes configuration to `/run` to hand
off control of devices to the specified networking daemon.

 - Configured devices get handled by systemd-networkd by default,
   unless explicitly marked as managed by a specific renderer (NetworkManager)
 - Devices not covered by the network configuration do not get touched at all.
 - Usable in initramfs (few dependencies and fast)
 - No persistent generated configuration, only original YAML configuration
 - Parser supports multiple configuration files to allow applications like libvirt or
   `lxd` to package expected network configuration (`virbr0`, `lxdbr0`), or to change
   the global default policy to use NetworkManager for everything.
 - Retains the flexibility to change back ends/policy later or adjust to
   removing NetworkManager, as generated configuration is ephemeral.

## General structure

Netplan configuration files use the
[YAML](http://yaml.org/spec/1.1/current.html) format. All
`/{lib,etc,run}/netplan/*.yaml` are considered. Lexicographically later files
(regardless of in which directory they are) amend (new mapping keys) or
override (same mapping keys) previous ones. A file in `/run/netplan`
completely shadows a file with same name in `/etc/netplan`, and a file in
either of those directories shadows a file with the same name in `/lib/netplan`.

The top-level node in a Netplan configuration file is a `network:` mapping
that contains `version: 2` (the YAML currently being used by curtin, MAAS,
etc. is version 1), and then device definitions grouped by their type, such as
`ethernets:`, `modems:`, `wifis:`, or `bridges:`. These are the types that our
renderer can understand and are supported by our back ends.

Each type block contains device definitions as a map where the keys (called
"configuration IDs") are defined as below.

## Device configuration IDs

The key names below the per-device-type definition maps (like `ethernets:`)
are called "ID"s. They must be unique throughout the entire set of
configuration files. Their primary purpose is to serve as anchor names for
composite devices, for example to enumerate the members of a bridge that is
currently being defined.

(Since 0.97) If an interface is defined with an ID in a configuration file; it
will be brought up by the applicable renderer. To not have Netplan touch an
interface at all, it should be completely omitted from the Netplan configuration
files.

There are two physically/structurally different classes of device definitions,
and the ID field has a different interpretation for each:

Physical devices

> (Examples: Ethernet, modem, Wi-Fi) These can dynamically come and go between
> reboots and even during runtime (hot plugging). In the generic case, they
> can be selected by `match:` rules on desired properties, such as name/name
> pattern, MAC address, driver, or device paths. In general these will match
> any number of devices (unless they refer to properties which are unique
> such as the full path or MAC address), so without further knowledge about
> the  hardware these will always be considered as a group.
>
> It is valid to specify no match rules at all, in which case the ID field is
> simply the interface name to be matched. This is mostly useful if you want
> to keep simple cases simple, and it's how network device configuration has
> been done for a long time.
>
> If there are ``match``: rules, then the ID field is a purely opaque name
> which is only being used  for references from definitions of compound
> devices in the configuration.

Virtual devices

> (Examples: `veth`, `bridge`, `bond`, `vrf`) These are fully under the control of the
> configuration file(s) and the network stack. I. e. these devices are being created
> instead of matched. Thus `match:` and `set-name:` are not applicable for
> these, and the ID field is the name of the created virtual device.
