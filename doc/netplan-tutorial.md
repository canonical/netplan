# Pre-requisites

In order to do the exercises yourself you will need a virtual machine, preferably running Ubuntu. In this tutorial, we will use LXD to create virtual networks and launch virtual machines. Feel free to use a cloud instance or a different hypervisor. As long as you can achieve the same results, you should be fine. If you're going to use your own desktop/laptop system, some of the exercises might interrupt your network connectivity.

If you already have a setup where you can do the exercises you can just skip this section.

## Setting up the environment

You can follow the steps below to install and create a basic LXD configuration you can use to launch virtual machines. For more information about LXD, please visit [linuxcontainers.org](https://linuxcontainers.org/lxd/introduction/).

If you don't have LXD installed in your system, follow the steps below to install it:

```
$ snap install lxd
$ lxd init --minimal
```

For some of the exercises you will need a second network interface in your virtual machine. Run the command below to create a new network in LXD:

```
lxc network create netplanbr0 --type=bridge
```

You should see the output below:

```
Network netplanbr0 created
```

After executing the commands above you will have a usable LXD installation with a working network bridge.

Now create a virtual machine called `netplan-lab0`:

```
lxc init --vm ubuntu:22.04 netplan-lab0
```

You should see the out below:

```
Creating netplan-lab0
```

The new VM will have one network interface attached to the default LXD bridge.

Now attach a second network interface to the VM and associate it to the LXD network you created earlier:

```
lxc network attach netplanbr0 netplan-lab0 eth1
```

And start your new VM:

```
lxc start netplan-lab0
```

Access your new VM using `lxc exec`:

```
lxc exec netplan-lab0 bash
```

You can also use `lxc shell netplan-lab0` or `lxc console netplan-lab0` if the command about doesn't work for you.

You should now have a root shell inside your VM:

```
root@netplan-lab0:~#
```

If you see the command prompt above, congratulations, you got into your LXD virtual machine!

Run the command `ip link` to show your network interfaces:

```
ip link
```

You should see an output similar to the below:

```
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: enp5s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
    link/ether 00:16:3e:27:45:9d brd ff:ff:ff:ff:ff:ff
3: enp6s0: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000
    link/ether 00:16:3e:7b:68:9d brd ff:ff:ff:ff:ff:ff
```

In this case, `enp5s0` is the primary interface connected to the default LXD network and `enp6s0` is the second interface you added connected to your custom network.


Now, let's start with a simple exercise.

# Running netplan for the first time

Start by typing the command `netplan` in your shell:

```
netplan
```

You will see the output below

```
You need to specify a command
usage: /usr/sbin/netplan  [-h] [--debug]  ...

Network configuration in YAML

options:
  -h, --help  show this help message and exit
  --debug     Enable debug messages

Available commands:

    help      Show this help message
    apply     Apply current netplan config to running system
    generate  Generate backend specific configuration files from /etc/netplan/*.yaml
    get       Get a setting by specifying a nested key like "ethernets.eth0.addresses", or "all"
    info      Show available features
    ip        Retrieve IP information from the system
    set       Add new setting by specifying a dotted key=value pair like ethernets.eth0.dhcp4=true
    rebind    Rebind SR-IOV virtual functions of given physical functions to their driver
    status    Query networking state of the running system
    try       Try to apply a new netplan config to running system, with automatic rollback
```

As you can see, netplan has a number of sub commands. Let's explore some of them.

# Showing your current netplan configuration

To show your current configuration, run the command `netplan get`.

```
netplan get
```

You should see an output similar to the one below:


```yaml
network:
  version: 2
  ethernets:
    enp5s0:
      dhcp4: true
```

It shows you have an ethernet interface called `enp5s0` and it has DHCP enabled for IPv4.


# Showing your current network configuration

Netplan 0.106 introduced the `netplan status` command. You can use it to
show your system's current network configuration. Try that by typing
`netplan status --all` in your console:

```
netplan status --all
```

You should see an output similar to the one below:

```
     Online state: online
    DNS Addresses: 127.0.0.53 (stub)
       DNS Search: lxd

●  1: lo ethernet UNKNOWN/UP (unmanaged)
      MAC Address: 00:00:00:00:00:00
        Addresses: 127.0.0.1/8
                   ::1/128
           Routes: ::1 metric 256

●  2: enp5s0 ethernet UP (networkd: enp5s0)
      MAC Address: 00:16:3e:43:fc:e8 (Red Hat, Inc.)
        Addresses: 10.86.126.21/24 (dhcp)
                   fd42:bc43:e20e:8cf7:216:3eff:fe43:fce8/64
                   fe80::216:3eff:fe43:fce8/64 (link)
    DNS Addresses: 10.86.126.1
                   fe80::216:3eff:feab:beb9
       DNS Search: lxd
           Routes: default via 10.86.126.1 from 10.86.126.21 metric 100 (dhcp)
                   10.86.126.0/24 from 10.86.126.21 metric 100 (link)
                   10.86.126.1 from 10.86.126.21 metric 100 (dhcp, link)
                   fd42:bc43:e20e:8cf7::/64 metric 100 (ra)
                   fe80::/64 metric 256
                   default via fe80::216:3eff:feab:beb9 metric 100 (ra)

●  3: enp6s0 ethernet DOWN (unmanaged)
      MAC Address: 00:16:3e:4b:56:5c (Red Hat, Inc.)
```

# Checking the file where your configuration is stored

The configuration you just listed is stored at `/etc/netplan`. You can see the contents of the file with the command below:

```
cat /etc/netplan/50-cloud-init.yaml
```

You should see an output similar to this:

```yaml
# This file is generated from information provided by the datasource.  Changes
# to it will not persist across an instance reboot.  To disable cloud-init's
# network configuration capabilities, write a file
# /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg with the following:
# network: {config: disabled}
network:
    version: 2
    ethernets:
        enp5s0:
            dhcp4: true
```

This file was automatically generated by `cloud-init` when the system was initialized. As noted in the comments, changes to this file will not persist.

# Enabling your second network interface with DHCP

There are basically 2 ways to create or change netplan configuration:

1) Using the `netplan set` command
2) Editing the YAML files manually

Let's see how you can enable your second network interface using both ways.

## Using `netplan set`

For simple tasks, you can use `netplan set` to change your configuration.

In the example below you are going to create a new YAML file called `second-interface.yaml` containing only the configuration needed to enable our second interfaces.

Considering your second network interface is `enp6s0`, run the command below:

```
netplan set --origin-hint second-interface ethernets.enp6s0.dhcp4=true
```

The command line parameter `--origin-hint` sets the name of the file where the configuration will be stored.

Now list the files in the directory `/etc/netplan`:

```
ls /etc/netplan
```

You should see the auto generated cloud-init file and a new file called `second-interface.yaml`:

```
root@netplan-lab0:~# ls /etc/netplan/
50-cloud-init.yaml  second-interface.yaml
```

Use the command `cat` to see its content:

```
cat /etc/netplan/second-interface.yaml
```

```yaml
network:
  version: 2
  ethernets:
    enp6s0:
      dhcp4: true
```

You will notice it is very similar to the one generated by cloud-init.

Now use `netplan get` to see your full configuration:

```
netplan get
```

You should see an output similar to the one below with both ethernet interfaces:

```yaml
network:
  version: 2
  ethernets:
    enp5s0:
      dhcp4: true
    enp6s0:
      dhcp4: true
```

## Applying your new configuration

The command `netplan set` created the configuration for your second network interface but it wasn't applied to the running system.

Run the command below to see the current state of your second network interface:

```
ip address show enp6s0
```

You should see an output similar to the one below:

```
3: enp6s0: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN group default qlen 1000
    link/ether 00:16:3e:7b:68:9d brd ff:ff:ff:ff:ff:ff
```

As you can see, this interface has no IP address and its state is DOWN.

In order to apply the netplan configuration, you can use the command `netplan apply`.

Run the command below in your shell:

```
netplan apply
```

Now check again the state of the interface `enp6s0`:

```
ip address show enp6s0
```

You should see an output similar to this:

```
3: enp6s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    link/ether 00:16:3e:7b:68:9d brd ff:ff:ff:ff:ff:ff
    inet 10.61.153.47/24 metric 100 brd 10.61.153.255 scope global dynamic enp6s0
       valid_lft 3583sec preferred_lft 3583sec
    inet6 fd42:28d1:1d7a:8e19:216:3eff:fe7b:689d/64 scope global dynamic mngtmpaddr noprefixroute
       valid_lft 3591sec preferred_lft 3591sec
    inet6 fe80::216:3eff:fe7b:689d/64 scope link
       valid_lft forever preferred_lft forever
```

You can also use `netplan status` to check the interface:

```
netplan status enp6s0
```

You should see an output similar to this:

```
     Online state: online
    DNS Addresses: 127.0.0.53 (stub)
       DNS Search: lxd

●  3: enp6s0 ethernet UP (networkd: enp6s0)
      MAC Address: 00:16:3e:4b:56:5c (Red Hat, Inc.)
        Addresses: 10.139.171.164/24 (dhcp)
                   fd42:d6c:8133:975f:216:3eff:fe4b:565c/64
                   fe80::216:3eff:fe4b:565c/64 (link)
    DNS Addresses: 10.139.171.1
                   fe80::216:3eff:fea1:7967
       DNS Search: lxd
           Routes: default via 10.139.171.1 from 10.139.171.164 metric 100 (dhcp)
                   10.139.171.0/24 from 10.139.171.164 metric 100 (link)
                   10.139.171.1 from 10.139.171.164 metric 100 (dhcp, link)
                   fd42:d6c:8133:975f::/64 metric 100 (ra)
                   fe80::/64 metric 256

2 inactive interfaces hidden. Use "--all" to show all.
```

As you can see, even though you haven't enabled DHCP for IPv6 on this interface, the network configuration backend (in this case systemd-networkd) enabled it anyway. But let's assume you want only IPv4.

Let's address this situation in the next exercise.

## Editing YAML files

For more complex configuration, you can just create or edit a new file yourself using your favorite text editor.

Continuing the exercise from the previous section, let's go ahead and disable automatic IPv6 configuration on your second interface. But this time let's do it by manually editing the YAML file.

Use your favorite text editor and open the file `/etc/netplan/second-interface.yaml`.

Add the configuration below to the interface configuration section:

```yaml
accept-ra: false
link-local: []
```

When you finish, it should look like this:

```yaml
network:
  version: 2
  ethernets:
    enp6s0:
      dhcp4: true
      accept-ra: false
      link-local: []
```

With this new configuration, the network configuration backend (systemd-networkd in this case) will not accept Route Advertisements and will not add the link-local address to our interface.

Now check your new configuration with the `netplan get` command:

```
netplan get
```

You should see something similar to this:

```yaml
network:
  version: 2
  ethernets:
    enp5s0:
      dhcp4: true
    enp6s0:
      dhcp4: true
      accept-ra: false
      link-local: []
```

Now use `netplan apply` to apply your new configuration:

```
netplan apply
```

And check your interface configuration:

```
ip address show enp6s0
```

You should see an output similar to this:

```
3: enp6s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    link/ether 00:16:3e:7b:68:9d brd ff:ff:ff:ff:ff:ff
    inet 10.61.153.47/24 metric 100 brd 10.61.153.255 scope global dynamic enp6s0
       valid_lft 3281sec preferred_lft 3281sec
```

And as you can see, now it only has an IPv4 address.

In this exercise you explored the `netplan set`, `netplan get` and `netplan apply` commands. You also used some of the ethernet configuration options to get a network interface up and running with DHCP.

# Using static IP addresses

In this exercise you're going to add an static IP address to the second interface with a default route and DNS configuration.

Use your favorite text editor to open the file `/etc/netplan/second-interface.yaml` created previously. Change it so it will look like this:

```yaml
network:
  version: 2
  ethernets:
    enp6s0:
      dhcp4: false
      dhcp6: false
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

The configuration above is what you'd expect in a desktop system for example. It defines the interface's IP address statically as `172.16.0.1/24`, a default route via gateway `172.16.0.254` and the DNS search domain and nameservers.

Now use `netplan get` to visualize all your network configuration:

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
      routes:
      - to: "default"
        via: "172.16.0.254"
```

You will notice that it might be a little different than what you have defined in the YAML file. Some things might be in a different order for example.

The reason for that is that `netplan get` loads and parses your configuration before outputting it and the YAML parsing engine used by netplan might shuffle things around. Although, what you see from `netplan get` is equivalent to what you have in the file.

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
    link/ether 00:16:3e:7b:68:9d brd ff:ff:ff:ff:ff:ff
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
       DNS Search: lxd
                   netplanlab.local

●  3: enp6s0 ethernet UP (networkd: enp6s0)
      MAC Address: 00:16:3e:4b:56:5c (Red Hat, Inc.)
        Addresses: 172.16.0.1/24
                   fd42:d6c:8133:975f:216:3eff:fe4b:565c/64
                   fe80::216:3eff:fe4b:565c/64 (link)
    DNS Addresses: 172.16.0.254
                   172.16.0.253
                   fe80::216:3eff:fea1:7967
       DNS Search: netplanlab.local
           Routes: default via 172.16.0.254 (static)
                   172.16.0.0/24 from 172.16.0.1 (link)
                   fd42:d6c:8133:975f::/64 metric 1024 (ra)
                   fe80::/64 metric 256
                   default via fe80::216:3eff:fea1:7967 metric 1024 (ra)

2 inactive interfaces hidden. Use "--all" to show all.
```

# Matching the interface by MAC address

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
    link/ether 00:16:3e:7b:68:9d brd ff:ff:ff:ff:ff:ff
```

Use your favorite text editor to open the file `/etc/netplan/second-interface.yaml` and make the following changes:

```yaml
network:
  version: 2
  ethernets:
    netplan-isp-interface:
      match:
        macaddress: 00:16:3e:7b:68:9d
      set-name: netplan-isp
      dhcp4: false
      dhcp6: false
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
        macaddress: 00:16:3e:7b:68:9d
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
    link/ether 00:16:3e:27:45:9d brd ff:ff:ff:ff:ff:ff
3: netplan-isp: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
    link/ether 00:16:3e:7b:68:9d brd ff:ff:ff:ff:ff:ff
```
