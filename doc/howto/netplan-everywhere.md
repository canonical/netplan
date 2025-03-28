# How to integrate Netplan with desktop

## NetworkManager YAML settings back end

NetworkManager is the tool used by Ubuntu Desktop systems to manage
network devices such as Ethernet and Wi-Fi adapters. While it is a great
tool for the job and users can directly use it through the command line
and the graphical interfaces to configure their devices, Ubuntu has its
own way of describing and storing network configuration via Netplan.

On Ubuntu 23.10 "Mantic Minotaur" and later, NetworkManager uses Netplan APIs
to save the configuration created using any of its graphical or programmatic
interfaces. This leads to having a centralised location to store network
configuration. On the Desktop, it's convenient to use graphical tools for
configuration when they are available, so nothing changes from the user
perspective; only the way the system handles the configuration in the background.

For more information on Netplan, see [netplan.io](https://netplan.io).

For more information on NetworkManager, see [networkmanager.dev](https://networkmanager.dev).

## How it works

Every time a non-temporary connection is created in NetworkManager, instead
of persisting the original `.nmconnection` file, it creates a Netplan YAML
file in `/etc/netplan/` called `90-NM-<connection UUID>.yaml`. After creating
the file, NetworkManager calls the Netplan generator to provide the
configuration for that connection. Connections that are temporary, like the ones
created for virtual network interfaces when you connect to a VPN for example,
are not persisted as Netplan files. The reason for that is that these interfaces
are usually managed by external services and we don't want to cause any
unexpected change that would affect them.

## How to use

### Installing NetworkManager

The NetworkManager 1.44.2 package containing the Netplan integration patch
is available by default in Ubuntu 23.10 "Mantic Minotaur" and later as part of
the official Ubuntu archive.

```
$ sudo apt update
$ sudo apt install network-manager
```

### User interface

From this point on, Netplan is aware of all your network configuration and
you can query it using its CLI tools, such as `sudo netplan get` or `sudo
netplan status`. All while keeping untouched the traditional way of modifying
it using NetworkManager (graphical UI, GNOME Quick Settings, `nmcli`,
`nmtui`, D-Bus APIs, ...).

### Management of connection profiles

The NetworkManager-Netplan integration imports connection profiles from
`/etc/NetworkManager/system-connections/` to Netplan during the installation
process. It automatically creates a copy of all your connection profiles during
the installation of the new network-manager package in
`/root/NetworkManager.bak/system-connections/`. The same migration happens
in the background whenever you add or modify any connection profile.

You can observe this migration on the `apt-get` command line. Watch for
logs like the following:

```
Setting up network-manager (1.44.2-1ubuntu1.2) ...
Migrating HomeNet (9d087126-ae71-4992-9e0a-18c5ea92a4ed) to /etc/netplan
Migrating eduroam (37d643bb-d81d-4186-9402-7b47632c59b1) to /etc/netplan
Migrating DebConf (f862be9c-fb06-4c0f-862f-c8e210ca4941) to /etc/netplan
```

For example, if you have a Wi-Fi connection, you will not find the connection
profile file at `/etc/NetworkManager/system-connections/` anymore. Instead,
the system removes the profile file, and Netplan creates a new YAML file called
`90-NM-<connection UUID>.yaml` in `/etc/netplan/` and generates a new ephemeral
profile in `/run/NetworkManager/system-connections/`.

## Limitation

Netplan doesn't yet support all the configuration options available in
NetworkManager (or doesn't know how to interpret some of the keywords
found in the key file). After creating a new connection you might find
a section called `passthrough` in your YAML file, like in the example below:

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

All the configuration under the `passthrough` mapping is added to
the `.nmconnection` file as they are.

In cases where the connection type is not supported by Netplan, the system uses
the `nm-devices` network type. The example below is an OpenVPN client
connection, which is not supported by Netplan at the moment.

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
