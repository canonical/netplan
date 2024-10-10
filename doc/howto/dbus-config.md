# How to use D-Bus configuration API

See also:
* [Netplan D-Bus reference](/netplan-dbus)
* [`busctl` reference](https://www.freedesktop.org/software/systemd/man/busctl.html)

Copy the current state from `/{etc,run,lib}/netplan/*.yaml` by creating a new configuration object:

```console
busctl call io.netplan.Netplan /io/netplan/Netplan io.netplan.Netplan Config

o "/io/netplan/Netplan/config/ULJIU0"
```

Read the merged YAML configuration:

```console
busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 \
io.netplan.Netplan.Config Get

s "network:\n  ethernets:\n    eth0:\n      dhcp4: true\n  renderer: networkd\n  version: 2\n"
```

Write a new configuration snippet into `70-snapd.yaml`:

```console
busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 \
io.netplan.Netplan.Config Set ss "ethernets.eth0={dhcp4: false, dhcp6: true}" "70-snapd"

b true
```

Check the newly written configuration:

```console
busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 \
io.netplan.Netplan.Config Get

s "network:\n  ethernets:\n    eth0:\n      dhcp4: false\n      dhcp6: true\n  renderer: networkd\n  version: 2\n"
```

Try to apply the current state of the configuration object:

```console
busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 \
io.netplan.Netplan.Config Try u 20

b true
```

Accept the `Try()` state within the 20 seconds timeout, if not it will be auto-rejected:

```console
busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 \
io.netplan.Netplan.Config Apply

b true

[SIGNAL] io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 io.netplan.Netplan.Config Changed() is triggered
[OBJECT] io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 is removed from the bus
```

Create a new configuration object and get the merged YAML configuration:

```console
busctl call io.netplan.Netplan /io/netplan/Netplan io.netplan.Netplan Config

o "/io/netplan/Netplan/config/KC0IU0

busctl call io.netplan.Netplan /io/netplan/Netplan/config/KC0IU0 \
io.netplan.Netplan.Config Get

s "network:\n  ethernets:\n    eth0:\n      dhcp4: false\n      dhcp6: true\n  renderer: networkd\n  version: 2\n"
```

Reject that configuration object again:

```console
busctl call io.netplan.Netplan /io/netplan/Netplan/config/KC0IU0 \
io.netplan.Netplan.Config Cancel

b true

[SIGNAL] io.netplan.Netplan /io/netplan/Netplan/config/KC0IU0 io.netplan.Netplan.Config Changed() is triggered
[OBJECT] io.netplan.Netplan /io/netplan/Netplan/config/KC0IU0 is removed from the bus
```
