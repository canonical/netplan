# How to configure a VM host with a single network interface

This guide shows how to configure a virtual-machine host using Netplan and the `virsh` interface. The host in this scenario has a single network interface.

```{include} reuse/configure-vm-prerequisites.txt

```


### Networking

- IPv4:
  - Network: 192.168.150.0/24
  - DNS1: 1.1.1.1
  - DNS2: 8.8.8.8
- Switch
- Router
  - IPv4: 192.168.150.254/24
  - DNS and DHCP configured
- Firewall configured; see [UFW](https://help.ubuntu.com/community/UFW).

TODO 123
#### Disable netfilter for bridged interfaces

To allow communication between the host server, its virtual machines, and the devices in the local VLANs, disable netfilter for bridged interfaces:

1. Add the following lines to the `/etc/systemctl.conf` configuration file:

    ```
    net.bridge.bridge-nf-call-iptables = 0
    net.bridge.bridge-nf-call-ip6tables = 0
    net.bridge.bridge-nf-call-arptables = 0
    ```

2. Apply the changes immediately, without rebooting the host.

    ```none
    sysctl -p /etc/sysctl.conf
    ```


## Netplan configuration

Configure Netplan:

- Disable DHCP on the NIC.
- Create a bridge interface: `br0`.
- Assign IPv4 address to `br0`.
- Configure routes.
- Configure DNS.

1. To achieve this, modify the Netplan configuration file, `/etc/netplan/00-installer-config.yaml`,  as follows:

    ```yaml
    # network configuration:
    # eno1 - Single NIC on the host
    # br0 - bridge for the eon1 interface

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

2. Test the new network settings:

    ```none
    netplan try
    ```

3. Apply the configuration:

    ```
    netplan apply
    ```

TODO 123
## Configure virtual networks using `virsh`

The next step is to configure virtual networks defined for `virsh` domains. This is not necessary, but it makes VM deployment and management easier.

TODO 123
### Check networking and delete the default network

1. Check existing virtual networks:

    ```none
    virsh net-list --all
    ```

   There should be one default network as in this example:

    ```
    Name      State    Autostart   Persistent
    --------------------------------------------
    default   active   yes         yes
    ```

   If needed, use the `net-info` command to gather more details about the default network:

    ```
    virsh net-info default
    ```

2. Remove the default network:

    ```
    virsh net-destroy default
    virsh net-undefine default
    ```

3. Check network list to confirm the changes have been applied. There should no networks defined now:

    ```none
    virsh net-list --all
    ```


### Create bridged networks

1. Create a directory for VM data. For example:

    ```none
    mkdir /mnt/vmstore/
    cd /mnt/vmstore/
    ```

2. Define the bridge interface, `br0`, for libvirt by creating the `/mnt/vmstore/net-br0.xml` file with  the following contents:

    ```xml
    <network>
        <name>br0</name>
        <forward mode="bridge" />
        <bridge name="br0" />
    </network>
    ```

3. Enable the virtual (bridged) network. This consists of three steps:

   1. Define the network.
   2. Start the network.
   3. Set the network to autostart.

    ```
    virsh net-define net-br0.xml
    virsh net-start br0
    virsh net-autostart br0
    ```

4. Test the bridged networks.

Congratulations, the configuration is complete. You can now create a virtual machine, assign the desired network using your preferred VM configuration tool, and run some tests.
