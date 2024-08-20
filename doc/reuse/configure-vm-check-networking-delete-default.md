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