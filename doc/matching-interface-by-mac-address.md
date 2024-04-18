# How to match the interface by MAC address

:::{note}
These instructions assume a system setup based on the example configuration outlined in the [Netplan tutorial](/netplan-tutorial).
:::

Sometimes you can't rely on the interface names to apply configuration to them. Changes in the system might cause a change in their names, such as when you move an interface card from a PCI slot to another.

In this exercise you will use the `match` keyword to locate the device based on its MAC address and also set a more meaningful name to the interface.

Let's assume that your second interface is connected to the Netplan ISP internet provider company and you want to identify it as such.

First identify its MAC address:

```
ip link show enp6s0
```

In the output, the MAC address is the number in front of the `link/ether` property.
```
3: enp6s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
    link/ether 00:16:3e:0c:97:8a brd ff:ff:ff:ff:ff:ff
```

Edit the file `/etc/netplan/second-interface.yaml` and make the following changes:

```yaml
network:
  version: 2
  ethernets:
    netplan-isp-interface:
      match:
        macaddress: 00:16:3e:0c:97:8a
      set-name: netplan-isp
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

These are the important changes in this exercise:

```yaml
  ethernets:
    netplan-isp-interface:
      match:
        macaddress: 00:16:3e:0c:97:8a
      set-name: netplan-isp
```

Note that, as you are now matching the interface by its MAC address, you are free to identify it with a different name. It makes it easier to read and find information in the YAML file.

After changing the file, apply your new configuration:

```
netplan apply
```

Now list your interfaces:

```
ip link show
```

As you can see, your interface is now called `netplan-isp`.

```
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: enp5s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
    link/ether 00:16:3e:13:ae:10 brd ff:ff:ff:ff:ff:ff
3: netplan-isp: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
    link/ether 00:16:3e:0c:97:8a brd ff:ff:ff:ff:ff:ff
```
