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