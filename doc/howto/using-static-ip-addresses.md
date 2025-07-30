# How to use static IP addresses

:::{note}
These instructions assume a system setup based on the example configuration outlined in the [Netplan tutorial](/netplan-tutorial).
:::

In this exercise you're going to add an static IP address to the second interface with a default route and DNS configuration.

Edit the file `/etc/netplan/second-interface.yaml` created previously. Change it so it will look like this:

```yaml
network:
  version: 2
  ethernets:
    enp6s0:
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

The configuration above is what you'd expect in a desktop system for example. It defines the interface's IP address statically as `172.16.0.1/24`, a default route via gateway `172.16.0.254` and the DNS search domain and name servers.

Now use `netplan get` to visualise all your network configuration:

```
netplan get
```

You should see an output similar to this:

```yaml
network:
  version: 2
  ethernets:
    enp5s0:
      dhcp4: true
    enp6s0:
      addresses:
      - "172.16.0.1/24"
      nameservers:
        addresses:
        - 172.16.0.254
        - 172.16.0.253
        search:
        - netplanlab.local
      dhcp4: false
      dhcp6: false
      accept-ra: false
      routes:
      - to: "default"
        via: "172.16.0.254"
      link-local: []
```

You will notice that it might be a little different than what you have defined in the YAML file. Some things might be in a different order for example.

The reason for that is that `netplan get` loads and parses your configuration before outputting it, and the YAML parsing engine used by Netplan might shuffle things around. Although, what you see from `netplan get` is equivalent to what you have in the file.

Now use `netplan apply` to apply the new configuration:

```
netplan apply
```

And check the interface's new state:

```
ip address show dev enp6s0
```

You should see something similar to this:
```
3: enp6s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    link/ether 00:16:3e:0c:97:8a brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.1/24 brd 172.16.0.255 scope global enp6s0
       valid_lft forever preferred_lft forever
```

Check the routes associated to the interface:

```
ip route show dev enp6s0
```

You should see something similar to this:

```
default via 172.16.0.254 proto static
172.16.0.0/24 proto kernel scope link src 172.16.0.1
```

And check the DNS configuration:

```
netplan status enp6s0
```

You should see something similar to this:

```
     Online state: online
    DNS Addresses: 127.0.0.53 (stub)
       DNS Search: netplanlab.local
                   lxd

●  3: enp6s0 ethernet UP (networkd: enp6s0)
      MAC Address: 00:16:3e:0c:97:8a (Red Hat, Inc.)
        Addresses: 172.16.0.1/24
    DNS Addresses: 172.16.0.254
                   172.16.0.253
       DNS Search: netplanlab.local
           Routes: default via 172.16.0.254 (static)
                   172.16.0.0/24 from 172.16.0.1 (link)

2 inactive interfaces hidden. Use "--all" to show all.
```
