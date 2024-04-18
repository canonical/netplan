# Netplan tutorial

Use this tutorial to learn about basic use of the Netplan utility: how to set up an environment to try it, run it for the first time, check its configuration, and modify its settings.


# Trying Netplan in a virtual machine

To try Netplan, you can use a virtual environment, preferably running Ubuntu. This tutorial uses LXD to create virtual networks and launch virtual machines. You can also use a cloud instance or a different hypervisor.

:::{warning}
When using your own system without virtualisation, some of the exercises might interrupt your network connectivity.
:::


## Setting up the virtual environment

Follow the steps below to install and create a basic LXD configuration to launch virtual machines (VM). For more information about LXD, visit [documentation.ubuntu.com/lxd](https://documentation.ubuntu.com/lxd/).

1. Install LXD: [LXD | How to install LXD](https://documentation.ubuntu.com/lxd/en/latest/installing/).

   On Ubuntu, use `snap` to install LXD:

   ```
   snap install lxd
   ```

2. Initialise LXD configuration:

   ```
   lxd init --minimal
   ```

3. Create a new network in LXD (some of the exercises require a second network interface in the virtual machine):

   ```
   lxc network create netplanbr0 --type=bridge
   ```

   The following output confirms the successful creation of the bridge network:

   ```
   Network netplanbr0 created
   ```

   Now you have a usable LXD installation with a working network bridge.

4. Create a virtual machine called `netplan-lab0`:

   ```none
   lxc init --vm ubuntu:23.10 netplan-lab0
   ```

   You should see the output below:

   ```
   Creating netplan-lab0
   ```

   The new VM has one network interface attached to the default LXD bridge.

5. Attach the network you created (`netplanbr0`) to the VM (`netplan-lab0`) as the `eth1` interface:

   ```
   lxc network attach netplanbr0 netplan-lab0 eth1
   ```

   :::{tip}
   For more on LXD networking, visit [LXD | Attach a network to an instance](https://documentation.ubuntu.com/lxd/en/latest/howto/network_create/#attach-a-network-to-an-instance).
   :::

6. Start the new VM:

   ```
   lxc start netplan-lab0
   ```

7. Access the new VM using `lxc shell`:

   ```
   lxc shell netplan-lab0
   ```

   In case of problems, try running `lxc exec netplan-lab0 bash` or `lxc console netplan-lab0`.

   You should now have a root shell inside the VM:

   ```none
   root@netplan-lab0:~#
   ```

8. Run the `ip link` command to show the network interfaces:

   ```
   ip link
   ```

   You should see an output similar to the below:

   ```none
   1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
       link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
   2: enp5s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DEFAULT group default qlen 1000
       link/ether 00:16:3e:13:ae:10 brd ff:ff:ff:ff:ff:ff
   3: enp6s0: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000
       link/ether 00:16:3e:0c:97:8a brd ff:ff:ff:ff:ff:ff
   ```

   In this case:

   * `enp5s0` is the primary interface connected to the default LXD network.
   * `enp6s0` is the second interface you added connected to your custom network.

You're ready to start the first exercise.


# Running Netplan for the first time

Start by typing the command `netplan` in your shell:

```
netplan
```

You should see the following output:

```none
You need to specify a command
usage: /usr/sbin/netplan  [-h] [--debug]  ...

Network configuration in YAML

options:
  -h, --help  show this help message and exit
  --debug     Enable debug messages

Available commands:

    help      Show this help message
    apply     Apply current Netplan config to running system
    generate  Generate back end specific configuration files from /etc/netplan/*.yaml
    get       Get a setting by specifying a nested key like "ethernets.eth0.addresses", or "all"
    info      Show available features
    ip        Retrieve IP information from the system
    set       Add new setting by specifying a dotted key=value pair like ethernets.eth0.dhcp4=true
    rebind    Rebind SR-IOV virtual functions of given physical functions to their driver
    status    Query networking state of the running system
    try       Try to apply a new Netplan config to running system, with automatic rollback
```

As you can see, Netplan has a number of sub-commands. Let's explore some of them.


# Showing current Netplan configuration

To show the current configuration, run the `netplan get` command:

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

This means:

* There's an Ethernet interface called `enp5s0`.
* DHCP is enabled for the IPv4 protocol on `enp5s0`.


# Showing current network configuration

Netplan 0.106 introduced the `netplan status` command. The command displays the current network configuration of the system. Try it by running:

```none
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
      MAC Address: 00:16:3e:13:ae:10 (Red Hat, Inc.)
        Addresses: 10.86.126.221/24 (dhcp)
                   fd42:bc43:e20e:8cf7:216:3eff:fe13:ae10/64
                   fe80::216:3eff:fe13:ae10/64 (link)
    DNS Addresses: 10.86.126.1
                   fe80::216:3eff:feab:beb9
       DNS Search: lxd
           Routes: default via 10.86.126.1 from 10.86.126.221 metric 100 (dhcp)
                   10.86.126.0/24 from 10.86.126.221 metric 100 (link)
                   10.86.126.1 from 10.86.126.221 metric 100 (dhcp, link)
                   fd42:bc43:e20e:8cf7::/64 metric 100 (ra)
                   fe80::/64 metric 256
                   default via fe80::216:3eff:feab:beb9 metric 100 (ra)

●  3: enp6s0 ethernet DOWN (unmanaged)
      MAC Address: 00:16:3e:0c:97:8a (Red Hat, Inc.)
```


# Checking Netplan configuration files

Netplan configuration is stored in YAML-formatted files in the `/etc/netplan` directory. To display the contents of the directory, run:

```none
ls -1 /etc/netplan/
```

Provided your system was initialised using `cloud-init`, such as the Ubuntu virtual machine recommended for testing Netplan in [Trying Netplan in a virtual machine](#trying-netplan-in-a-virtual-machine), you can find the initial Netplan configuration in the `50-cloud-init.yaml` file:

```none
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

This configuration file is automatically generated by the `cloud-init` tool when the system is initialised. As noted in the file comments, direct changes to this file do not persist.


# Creating and modifying Netplan configuration

There are two methods to create or modify Netplan configuration:

Using the `netplan set` command
: Example: [Using netplan set to enable a network interface with DHCP](#using-netplan-set-to-enable-a-network-interface-with-dhcp)

Editing the YAML configuration files manually
: Example: [Editing Netplan YAML files to disable IPv6](#editing-netplan-yaml-files-to-disable-ipv6)


## Using `netplan set` to enable a network interface with DHCP

For simple configuration changes, use the `netplan set` command. In the example below, you are going to create a new YAML file called `second-interface.yaml` containing only the configuration needed to enable the second network interface.

1. To create a second network interface called `enp6s0`, run:

   ```
   netplan set --origin-hint second-interface ethernets.enp6s0.dhcp4=true
   ```

   The `--origin-hint` command-line parameter sets the name of the file in which the configuration is stored.

2. List the files in the directory `/etc/netplan`:

   ```none
   ls -1 /etc/netplan
   ```

   You should see the auto-generated `cloud-init` file and a new file called `second-interface.yaml`:

   ```none
   50-cloud-init.yaml
   second-interface.yaml
   ```

3. Use the command `cat` to see the file content:

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

   Notice it is similar to the configuration file generated by `cloud-init` ([Checking Netplan configuration files](#checking-netplan-configuration-files)).

4. Check the full configuration using `netplan get`:

   ```
   netplan get
   ```

   You should see an output similar to the one below with both Ethernet interfaces:

   ```yaml
   network:
     version: 2
     ethernets:
       enp5s0:
         dhcp4: true
       enp6s0:
         dhcp4: true
   ```

The interface configuration has been created. To apply the changes to the system, follow the instructions in [Applying new Netplan configuration](#applying-new-netplan-configuration).


## Editing Netplan YAML files to disable IPv6

For more complex settings, you can edit existing or create new configuration files manually.

For example, to disable automatic IPv6 configuration on the second network interface created in [Using netplan set to enable a network interface with DHCP](#using-netplan-set-to-enable-a-network-interface-with-dhcp), edit the `/etc/netplan/second-interface.yaml` file:

1. Add the following lines to the configuration section of the interface:

   ```yaml
   accept-ra: false
   link-local: []
   ```

   When you finish, the whole configuration in `second-interface.yaml` should look like this:

   ```yaml
   network:
     version: 2
     ethernets:
       enp6s0:
         dhcp4: true
         accept-ra: false
         link-local: []
   ```

   With this new configuration, the network configuration back end (`systemd-networkd` in this case) does not accept Route Advertisements and does not add the `link-local` address to the interface.

2. Check the new configuration using the `netplan get` command:

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

IPv6 has been disabled for the interface in the configuration. To apply the changes to the system, follow the instructions in [Applying new Netplan configuration](#applying-new-netplan-configuration).


# Applying new Netplan configuration

New or modified Netplan settings need to be applied before they take effect on a running system.

:::{note}
Using the `netplan set` command to modify configuration or editing (creating) the Netplan YAML configuration files directly does not automatically apply the new settings to the running system.
:::

After creating a new configuration as described in [Using netplan set to enable a network interface with DHCP](#using-netplan-set-to-enable-a-network-interface-with-dhcp), follow these steps to apply the settings and confirm they have taken effect.

1. Display the current state of the network interface:

   ```
   ip address show enp6s0
   ```

   Where `enp6s0` is the interface you wish to display status for. You should see an output similar to the one below:

   ```none
   3: enp6s0: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN group default qlen 1000
       link/ether 00:16:3e:0c:97:8a brd ff:ff:ff:ff:ff:ff
   ```

   This interface has no IP address and its state is `DOWN`.

2. Apply the new Netplan configuration:

   ```
   netplan apply
   ```

3. Check the state of the `enp6s0` interface again using one of the following two methods:

   * Using the `ip` tool:

     ```
     ip address show enp6s0
     ```

     You should see an output similar to this:

     ```none
     3: enp6s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
         link/ether 00:16:3e:0c:97:8a brd ff:ff:ff:ff:ff:ff
         inet 10.33.59.157/24 metric 100 brd 10.33.59.255 scope global dynamic enp6s0
           valid_lft 3589sec preferred_lft 3589sec
     ```

   * Using the `netplan status` command:

     ```
     netplan status enp6s0
     ```

     You should see an output similar to this:

     ```
         Online state: online
         DNS Addresses: 127.0.0.53 (stub)
           DNS Search: lxd

     ●  3: enp6s0 ethernet UP (networkd: enp6s0)
           MAC Address: 00:16:3e:0c:97:8a (Red Hat, Inc.)
             Addresses: 10.33.59.157/24 (dhcp)
         DNS Addresses: 10.33.59.1
           DNS Search: lxd
               Routes: default via 10.33.59.1 from 10.33.59.157 metric 100 (dhcp)
                       10.33.59.0/24 from 10.33.59.157 metric 100 (link)
                       10.33.59.1 from 10.33.59.157 metric 100 (dhcp, link)

     2 inactive interfaces hidden. Use "--all" to show all.
     ```

---

In this tutorial you learned how to set up a learning environment for Netplan using LXD virtual machines, explored Netplan configuration, including its underlying configuration files, and tried the `netplan set`, `netplan get`, `netplan apply`, and `netplan status` commands. You also used some of the Ethernet configuration options to enable a network interface with DHCP.
