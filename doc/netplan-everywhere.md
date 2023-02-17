# Network Manager and Netplan integration (Netplan everywhere)

Network Manager is the tool used by Ubuntu Desktop systems to manage
network devices such as Ethernet and Wifi adapters. While it is a great
tool for the job and users can directly use it through the command line
and the graphical interfaces to configure their devices, Ubuntu has its
own way of describing and storing network configuration via Netplan.

On Ubuntu, Network Manager uses (or will use, depending on when you are
reading this) Netplan's APIs to save the configuration created by the
user using any of its interfaces. Our goal is to have a centralized place
to store network configuration. In the Desktop it's convenient to use
graphical tools for configuration when they are available, so nothing will
change from the user perspective, only the way the configuration is
handled under the hood.

For more information on Netplan, check https://netplan.io/

For more information on Network Manager, check https://networkmanager.dev/

## How it works

Every time a non-temporary connection is created in Network Manager, instead
of persisting the original .nmconnection file, it will create a Netplan YAML
at `/etc/netplan` called `90-NM-<connection UUID>.yaml`. After creating the
file, Network Manager will call the Netplan generator to emit the configuration
for that connection.	Connections that are temporary, like the ones created
for virtual network interfaces when you connect to a VPN for example, are not
persisted as Netplan files. The reason for that is that these interfaces are
usually managed by external services and we don't want to cause any unexpected
change that would affect them.

## How to install it

### Creating a backup of your current configuration

The new NetworkManager will remove connection profiles that you eventually
modify from `/etc/NetworkManager`. So you might want to create a copy of all
your connection profiles before installing the new network-manager package:

```
$ mkdir ~/NetworkManager.bak && cd ~/NetworkManager.bak/
$ sudo cp -r /etc/NetworkManager/system-connections .
```

In any case, a backup will be created automatically for you at
`/root/NetworkManager.bak` during package installation.

And also keep a copy of all the original network-manager related packages in
case you want to revert to the previous installation:

```
$ apt download gir1.2-nm-1.0 libnm0 network-manager network-manager-config-connectivity-ubuntu
```

### Installing NetworkManager

The NetworkManager 1.42.0 package containing the Netplan integration patch
is currently available as a PPA. In order to install it, you will need to
have `netplan.io >= 0.106` installed in your system (it is available in Lunar).

```
$ sudo add-apt-repository ppa:canonical-foundations/networkmanager-netplan
$ sudo apt update
$ sudo apt install network-manager
```

## How connections are managed from now on
After installing the new NetworkManager, your existing connection profiles
will not be imported to Netplan YAML files, only new connections and the
existing ones you eventually modify.

For example, if you have a Wifi connection, you will find the connection
profile file at `/etc/NetworkManager/system-connections`. If you modify it
using one of the NetworkManager's interfaces (or delete and create a new one),
the respective file will be removed from `/etc/NetworkManager/system-connections`,
a Netplan YAML called `90-NM-<connection UUID>.yaml` will be created at
`/etc/netplan` and a new profile will be generated and stored at
`/run/NetworkManager/system-connections`.

## Limitation

Netplan doesn't yet support all the configuration available in
NetworkManager (or doesn't know how to interpret some of the keywords
found in the keyfile). After creating a new connection you might find
a section called "passthrough" in your YAML file, like in the example below:

```yaml
network:
  version: 2
  ethernets:
    NM-0f7a33ac-512e-4c03-b088-4db00fe3292e:
      renderer: NetworkManager
      match:
        name: "enp1s0"
      nameservers:
        addresses:
          - 8.8.8.8
      dhcp4: true
      wakeonlan: true
      networkmanager:
        uuid: "0f7a33ac-512e-4c03-b088-4db00fe3292e"
        name: "Ethernet connection 1"
        passthrough:
          ethernet._: ""
          ipv4.ignore-auto-dns: "true"
          ipv6.addr-gen-mode: "default"
          ipv6.method: "disabled"
          ipv6.ip6-privacy: "-1"
          proxy._: ""
```

All the configuration under the "passthrough" mapping will be added to
the `.nmconnection` file as they are.

In cases where the connection type is not supported by Netplan the
`nm-devices` network type will be used. The example below is an OpenVPN
client connection, which is not supported by Netplan at the moment.

```yaml
network:
  version: 2
  nm-devices:
    NM-db5f0f67-1f4c-4d59-8ab8-3d278389cf87:
      renderer: NetworkManager
      networkmanager:
        uuid: "db5f0f67-1f4c-4d59-8ab8-3d278389cf87"
        name: "myvpnconnection"
        passthrough:
          connection.type: "vpn"
          vpn.ca: "path to ca.crt"
          vpn.cert: "path to client.crt"
          vpn.cipher: "AES-256-GCM"
          vpn.connection-type: "tls"
          vpn.dev: "tun"
          vpn.key: "path to client.key"
          vpn.remote: "1.2.3.4:1194"
          vpn.service-type: "org.freedesktop.NetworkManager.openvpn"
          ipv4.method: "auto"
          ipv6.addr-gen-mode: "default"
          ipv6.method: "auto"
          proxy._: ""
```
