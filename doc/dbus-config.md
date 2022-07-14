# How to use DBus config API

Copy the current state from `/{etc,run,lib}/netplan/*.yaml` by creating a new config object
```
$ busctl call io.netplan.Netplan /io/netplan/Netplan io.netplan.Netplan Config
o "/io/netplan/Netplan/config/ULJIU0"
```

Read the merged YAML configuration
```
$ busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 io.netplan.Netplan.Config Get
s "network:\n  ethernets:\n    eth0:\n      dhcp4: true\n  renderer: networkd\n  version: 2\n"
```

Write a new config snippet into `70-snapd.yaml`
```
$ busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 io.netplan.Netplan.Config Set ss "ethernets.eth0={dhcp4: false, dhcp6: true}" "70-snapd"
b true
```

Check the newly written configuration
```
$ busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 io.netplan.Netplan.Config Get
s "network:\n  ethernets:\n    eth0:\n      dhcp4: false\n      dhcp6: true\n  renderer: networkd\n  version: 2\n"
```

Try to apply the current config object's state
```
$ busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 io.netplan.Netplan.Config Try u 20
b true
```

Accept the Try() state within the 20 seconds timeout, if not it will be auto-rejected
```
$ busctl call io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 io.netplan.Netplan.Config Apply
b true

[SIGNAL] io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 io.netplan.Netplan.Config Changed() is triggered
[OBJECT] io.netplan.Netplan /io/netplan/Netplan/config/ULJIU0 is removed from the bus
```

Create a new config object and get the merged YAML config
```
$ busctl call io.netplan.Netplan /io/netplan/Netplan io.netplan.Netplan Config
o "/io/netplan/Netplan/config/KC0IU0
$ busctl call io.netplan.Netplan /io/netplan/Netplan/config/KC0IU0 io.netplan.Netplan.Config Get
s "network:\n  ethernets:\n    eth0:\n      dhcp4: false\n      dhcp6: true\n  renderer: networkd\n  version: 2\n"
```

Reject that config object again
```
$ busctl call io.netplan.Netplan /io/netplan/Netplan/config/KC0IU0 io.netplan.Netplan.Config Cancel
b true

[SIGNAL] io.netplan.Netplan /io/netplan/Netplan/config/KC0IU0 io.netplan.Netplan.Config Changed() is triggered
[OBJECT] io.netplan.Netplan /io/netplan/Netplan/config/KC0IU0 is removed from the bus
```
