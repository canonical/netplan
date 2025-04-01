# How to create link aggregation

:::{note}
These instructions assume a system setup based on the example configuration outlined in the [Netplan tutorial](/netplan-tutorial).
:::

Let's suppose now that you need to configure your system to connect to your
ISP links via a link aggregation. On Linux you can do that with a `bond`
virtual interface.

On Netplan, an interface of type `bond` can be created inside a `bonds` mapping.

Now that the traffic will flow through the link aggregation, you will move
all the addressing configuration to the bond itself.

You can define a list of interfaces that will be attached to the bond. In our
simple scenario, we have a single one.

Edit the file `/etc/netplan/second-interface.yaml` and make the following changes:

```yaml
network:
  version: 2
  ethernets:
    netplan-isp-interface:
      dhcp4: false
      dhcp6: false
      match:
        macaddress: 00:16:3e:0c:97:8a
      set-name: netplan-isp
  bonds:
    isp-bond0:
      interfaces:
        - netplan-isp-interface
      dhcp4: false
      dhcp6: false
      accept-ra: false
      link-local: []
      addresses:
        - 172.16.0.1/24
      routes:
        - to: default
          via: 172.16.0.254
      nameservers:
        search:
          - netplanlab.local
        addresses:
          - 172.16.0.254
          - 172.16.0.253
```

Note that you can reference the interface used in the bond by the name you
defined for it in the `ethernets` section.

Now use `netplan apply` to apply your changes

```
netplan apply
```

Now your system has a new interface called `isp-bond0`. Use the command
`ip address show isp-bond0` or `netplan status` to check its state:

```
netplan status isp-bond0
```

You should see an output similar to the one below:

```
     Online state: online
    DNS Addresses: 127.0.0.53 (stub)
       DNS Search: lxd
                   netplanlab.local

●  4: isp-bond0 bond UP (networkd: isp-bond0)
      MAC Address: b2:6b:19:b1:9a:86
        Addresses: 172.16.0.1/24
    DNS Addresses: 172.16.0.254
                   172.16.0.253
       DNS Search: netplanlab.local
           Routes: default via 172.16.0.254 (static)
                   172.16.0.0/24 from 172.16.0.1 (link)

3 inactive interfaces hidden. Use "--all" to show all.
```
