# How to configure a virtual machine host with bonded network interfaces and three VLANs

In this How to, you will learn how to configure a virtual machine host using netplan and virsh. The host in this scenario has four network interface. The host will be using network bonding and three VLAN networks. 


## Prerequisites

Before we can get started, we need to establish our setup and make sure our prerequisite steps are completed and tested.

### Reference setup

- A computer with 4 NICs:
    - 1 NIC dedicated to be used in passthrough mode, out of scope of this how to.
    - 3 NICs bonded using 802.3ad for the host, Virtual Machines, and containers.
- Ubuntu Server installed.
- QEMU/KVM installed.
- IPv4:
    - VLAN 1 untagged (management).
        - IPv4: ```192.168.150.0/24```.
    - VLAN 40 tagged (guest).
        - IPv4: ```192.168.151.0/24```.
    - VLAN 41 tagged (dmz).
        - IPv4: ```192.168.152.0/24```.
    - DNS1: ```1.1.1.1```.
    - DNS2: ```8.8.8.8```.
- A switch that supports [VLAN](https://en.wikipedia.org/wiki/VLAN) and [LACP](https://en.wikipedia.org/wiki/Link_aggregation#Link_Aggregation_Control_Protocol). 
- A router/firewall that supports [VLAN](https://en.wikipedia.org/wiki/VLAN).
    - VLAN1 IPv4: ```192.168.150.254/24```.
    - VLAN40 IPv4: ```192.168.151.254/24```.
    - VLAN41 IPv4: ```192.168.152.254/24```.
    - Firewall policies, interVLAN routing, DNS, DHCP configured and tested.



### Elevated privileges
All commands in this tutorial assume you are using elevated privileges.

### QEMU/KVM installed
QEMU/KVM should be installed. Installation instructions can be found on [this Ubuntu Wiki page](https://help.ubuntu.com/community/KVM/Installation).

### Disable netfilter for bridged interfaces

We need to disable netfilter for bridged interfaces, in order to allow communications between the homeserver, its virtual machines, and the devices in the local VLANs.

- Edit this file: ```/etc/systemctl.conf```
- Add the following lines to the file

```
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-arptables = 0
```

- Apply the changes immediately, without rebooting the host.

```
sysctl -p /etc/sysctl.conf
```


### Edit or firewall rules


Remember to edit, configure, or disable firewall according to your needs. You can refer to [ufw documentation](https://help.ubuntu.com/community/UFW) if you need help configuring it.



## Netplan configuration

### Edit netplan configuration

Edit netplan configuration file:  ```/etc/netplan/00-installer-config.yaml```

  - Leave the first NIC unconfigured.
  - Disable dhcp on all interfaces.
  - Create a 802.3ad bond with three NICs.
  - Create two VLANs (40 and 41) under the bond.
  - Create three Bridges.
    - br0: this is a bridge on the untagged VLAN1, and management interface of our server.
    - br0-vlan40: this is a bridge on tagged vlan40.
    - br0-vlan41: this is a bridge on tagged vlan40.
  - Assign IPv4 address to br0.
  - Assign IPv4 address to br0-vlan40.
  - Assign IPv4 address to br0-vlan41.
  - Configure routes.
  - Configure DNS.




The configuration file should look like this:

```
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

### Test and apply network settings

Before we apply settings, you can check without applying with this command:

```
netplan try
```

If no major issues are reported, you can apply the configuration with the following command.

```
netplan apply
```


## Configure virtual networks in virsh

The next step is to configure virtual networks defined in virsh. While not strictly necessary, it will make VM deployment and management easier.


### Check networking and delete the default network

Check virtual networks with the following command.

```
virsh net-list --all
```


There should be one default network, like in the example below.

```
 Name      State    Autostart   Persistent
--------------------------------------------
 default   active   yes         yes

```

If needed, we can use the command below to gather more details about the default network.

```
virsh net-info default
```

We are now going to remove the default network.

```
virsh net-destroy default
virsh net-undefine default
```

Checking network list again to confirm our changes were applied. We expect to see no networks defined now.

```
virsh net-list --all
```


### Create bridged networks

Before we define virtual networks  with virsh, we are going to create a folder and enter it.

```
mkdir /mnt/vmstore/
cd /mnt/vmstore/
```


#### Prepare vlan1 for libvirt

create and edit this document: ```/mnt/vmstore/net-br0.xml```

```
<network>
    <name>br0</name>
    <forward mode="bridge" />
    <bridge name="br0" />
</network>
```

#### Prepare vlan40 for libvirt

create and edit this document: ```/mnt/vmstore/net-br0-vlan40.xml```

```
<network>
    <name>br0-vlan40</name>
    <forward mode="bridge" />
    <bridge name="br0-vlan40" />
</network>
```

#### prepare vlan41 for libvirt

create and edit this document: ```/mnt/vmstore/net-br0-vlan41.xml```

```
<network>
    <name>br0-vlan41</name>
    <forward mode="bridge" />
    <bridge name="br0-vlan41" />
</network>
```

#### Enable virtual networks

Now that our virtual networks are ready, we need to define, start, and set for autostart all of them.

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


### Test bridged networks 

Congratulations, the configuration is complete. We can now create a virtual machine, assign the desired network from our preferred VM configuration tool, and run some tests.



