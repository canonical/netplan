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