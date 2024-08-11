# How to configure a VM host with bonded network interfaces and three VLANs

This guide shows how to configure a virtual machine (VM) host using Netplan and the `virsh` interface. The host in this scenario has four network interface (NICs). The host uses network bonding and three VLAN networks.


## Prerequisites

Ensure the following prerequisites are satisfied.


### System

- Computer with 4 NICs:
  - 1 NIC dedicated to be used in passthrough mode (out of scope of this how to)
  - 3 NICs bonded using 802.3ad for the host, VMs, and containers
- Ubuntu Server installed.
- KVM and QEMU installed; see [KVM installation](https://help.ubuntu.com/community/KVM/Installation).
- Administrator privileges.


### Networking

- IPv4:
  - VLAN1 untagged (management), IPv4: 192.168.150.0/24
  - VLAN40 tagged (guest), IPv4: 192.168.151.0/24
  - VLAN41 tagged (dmz), IPv4: 192.168.152.0/24
  - DNS1: 1.1.1.1
  - DNS2: 8.8.8.8
- Switch with [VLAN](https://en.wikipedia.org/wiki/VLAN) and [LACP](https://en.wikipedia.org/wiki/Link_aggregation#Link_Aggregation_Control_Protocol) support
- Router with [VLAN](https://en.wikipedia.org/wiki/VLAN) support
  - VLAN1 IPv4: 192.168.150.254/24
  - VLAN40 IPv4: 192.168.151.254/24
  - VLAN41 IPv4: 192.168.152.254/24
  - InterVLAN routing, DNS, and DHCP configured
- Firewall configured; see [UFW](https://help.ubuntu.com/community/UFW).


```{include} reuse/configure-vm-disable-netfilter.txt

```


## Netplan configuration

Configure Netplan:

- Leave the first NIC unconfigured.
- Disable DHCP on all interfaces.
- Create a 802.3ad bond with three NICs.
- Create two VLANs (40 and 41) under the bond.
- Create three bridge interfaces, and assign IPv4 addresses to them:
  - `br0`: bridge on the untagged VLAN1 and the management interface of the server
  - `br0-vlan40`: bridge on `vlan40`
  - `br0-vlan41`: bridge on `vlan41`
- Configure routes.
- Configure DNS.

1. To achieve this, modify the Netplan configuration file, `/etc/netplan/00-installer-config.yaml`,  as follows:

    ```yaml
    # network configuration:
    # eno1 - dedicated to virtual firewall WAN
    # eno2, eno3, eno4 - bonded interfaces
    # bond0 - primary bond for untagged vlan1
    # bond0-vlan40 - vlan interface to connect to tagged vlan40
    # bond0-vlan41 - vlan interface to connect to tagged vlan41
    # br0 - bridge for interface bond0 on untagged vlan1
    # br0-vlan40 - bridge on tagged vlan40
    # br0-vlan41 - bridge on tagged vlan41

    network:
      version: 2
      ethernets:
        eno1:
          dhcp4: false
        eno2:
          dhcp4: false
        eno3:
          dhcp4: false
        eno4:
          dhcp4: false
      bonds:
        bond0:
          dhcp4: no
          interfaces: [eno2, eno3, eno4]
          parameters:
            mode: 802.3ad
            mii-monitor-interval: 1000
      vlans:
        bond0-vlan40:
          id: 40
          link: bond0
        bond0-vlan41:
          id: 41
          link: bond0
      bridges:
        br0:
          interfaces: [bond0]
          dhcp4: false
          addresses: [192.168.150.1/24]
          routes:
            - to: default
              via: 192.168.150.254
              metric: 100
              on-link: true
          nameservers:
            addresses: [1.1.1.1, 8.8.8.8]
            search: []
        br0-vlan40:
          interfaces: [bond0-vlan40]
          dhcp4: false
          routes:
            - to: 0.0.0.0
              via: 192.168.151.254
              metric: 100
              on-link: true
          nameservers:
            addresses: [1.1.1.1, 8.8.8.8]
        br0-vlan41:
          interfaces: [bond0-vlan41]
          dhcp4: false
          routes:
            - to: 0.0.0.0
              via: 192.168.152.254
              metric: 100
              on-link: true
          nameservers:
            addresses: [1.1.1.1, 8.8.8.8]
    ```

2. Test the new network settings:

    ```none
    netplan try
    ```

3. Apply the configuration:

    ```
    netplan apply
    ```


```{include} reuse/configure-vm-using-virsh.txt

```


```{include} reuse/configure-vm-check-networking-delete-default.txt

```


TODO 23
### Create bridged networks

1. Create a directory for VM data. For example:

    ```none
    mkdir /mnt/vmstore/
    cd /mnt/vmstore/
    ```

2. Define the bridge interface, `br0`, for VLAN1 by creating the `/mnt/vmstore/net-br0.xml` file with  the following contents:

    ```xml
    <network>
        <name>br0</name>
        <forward mode="bridge" />
        <bridge name="br0" />
    </network>
    ```

3. Define the bridge interface, `br0-vlan40`, for VLAN40 by creating the `/mnt/vmstore/net-br0-vlan40.xml` file with  the following contents:

    ```xml
    <network>
        <name>br0-vlan40</name>
        <forward mode="bridge" />
        <bridge name="br0-vlan40" />
    </network>
    ```

4. Define the bridge interface, `br0-vlan41`, for VLAN41 by creating the `/mnt/vmstore/net-br0-vlan41.xml` file with  the following contents:

    ```xml
    <network>
        <name>br0-vlan41</name>
        <forward mode="bridge" />
        <bridge name="br0-vlan41" />
    </network>
    ```

5. Enable the virtual (bridged) networks. This consists of three steps (performed for each of the networks):

   1. Define the network.
   2. Start  the network.
   3. Set the network to autostart.

    ```
    virsh net-define net-br0.xml
    virsh net-define net-br0-vlan40.xml
    virsh net-define net-br0-vlan41.xml
    virsh net-start br0
    virsh net-start br0-vlan40
    virsh net-start br0-vlan41
    virsh net-autostart br0
    virsh net-autostart br0-vlan40
    virsh net-autostart br0-vlan41
    ```

6. Test the bridged networks.

Congratulations, the configuration is complete. You can now create a virtual machine, assign the desired network using your preferred VM configuration tool, and run some tests.
