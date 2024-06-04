# How to configure a virtual machine host with a single network interface

In this How to, you will learn how to configure a virtual machine host using Netplan and virsh. The host in this scenario has a single network interface. 


## Prerequisites

Before we can get started, we need to establish our setup and make sure our prerequisite steps are completed and tested.

### Reference setup

- A computer with a single NIC.
- Ubuntu Server installed.
- QEMU/KVM installed.
- IPv4: 
    - Network: 192.168.150.0/24
    - DNS1: 1.1.1.1
    - DNS2: 8.8.8.8
- A switch
- A router/firewall
    - IPv4: 192.168.150.254/24
    - Firewall policies, DNS, DHCP configured and tested.


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



### Edit Netplan configuration

Edit Netplan's configuration file:  ```/etc/netplan/00-installer-config.yaml```
  - Disable dhcp on NIC
  - Create a bridge interface: br0
  - Assign IPv4 address to br0
  - Configure routes
  - Configure DNS

The configuration file should look like this:

```
# network configuration:
# eno1 - Single NIC on the host
# br0 - bridge for interface eno1

network:
  version: 2
  ethernets:
    eno1:
      dhcp4: false
  bridges:
    br0:
      interfaces: [eno1]
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
```

### Test and apply network settings

Before we apply settings, you can check without applying with this command.

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

Check virtual networks with this command. 

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

Before we define virtual networks with virsh, we are going to create a folder and enter it.

```
mkdir /mnt/vmstore/
cd /mnt/vmstore/
```


#### prepare br0 for libvirt

Create and edit this file: ```/mnt/vmstore/net-br0.xml```

```
<network>
    <name>br0</name>
    <forward mode="bridge" />
    <bridge name="br0" />
</network>
```


#### Enable virtual network

Now that virtual network is ready, we need to define, start, and set for autostart it.


```
virsh net-define net-br0.xml
virsh net-start br0
virsh net-autostart br0
```


### Test bridged networks 

Congratulations, the configuration is complete. We can now create a virtual machine, assign the desired network from our preferred VM configuration tool, and run some tests.

