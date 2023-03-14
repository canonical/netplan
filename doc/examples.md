# Introduction

Below is a collection of howtos for common scenarios.
If you see a scenario missing or have one to contribute, please file a bug
against this documentation with the example.

To configure Netplan, save configuration files under `/etc/netplan/` with a
`.yaml` extension (e.g. `/etc/netplan/config.yaml`), then run
`sudo netplan apply`. This command parses and applies the configuration to the
system. Configuration written to disk under `/etc/netplan/` will persist between
reboots.

For each of the example below, use the `renderer` that applies to your scenario. For example, for Ubuntu Desktop your `renderer` will probably be `NetworkManager` and `networkd` for Ubuntu Server.

Also, see [/examples](https://github.com/canonical/netplan/tree/main/examples)
on GitHub.

# How to enable DHCP on an interface

To let the interface named `enp3s0` get an address via DHCP, create a YAML file with the following:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      dhcp4: true
```

# How to configure a static IP address on an interface

To set a static IP address, use the `addresses` keyword, which takes a list of (IPv4 or IPv6) addresses along with the subnet prefix length (e.g. /24).

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      addresses:
        - 10.10.10.2/24
```

# How to configure DNS servers and search domains

The lists of search domains and DNS server IPs can be defined as below:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      addresses:
        - 10.10.10.2/24
      nameservers:
        search:
          - "mycompany.local"
        addresses:
          - 10.10.10.253
          - 8.8.8.8
```

# How to connect multiple interfaces with DHCP

DHCP can be used with multiple interfaces. The metrics for the routes acquired from DHCP can be changed with the use of DHCP overrides.

In this example, `enp5s0` is preferred over `enp6s0`, as it has a lower route metric:

```yaml
network:
  version: 2
  ethernets:
    enp5s0:
      dhcp4: yes
      dhcp4-overrides:
        route-metric: 100
    enp6s0:
      dhcp4: yes
      dhcp4-overrides:
        route-metric: 200
```

# How to connect to an open wireless network

For open wireless networks, Netplan only requires that the access point is defined. In this example, `opennetwork` is the network SSID:

```yaml
network:
  version: 2
  wifis:
    wl0:
      access-points:
        opennetwork: {}
      dhcp4: yes
```

# How to configure your computer to connect to your home wifi network

If all you need is to connect to your local domestic wifi network, use the configuration below:

```yaml
network:
  version: 2
  renderer: NetworkManager
  wifis:
    wlp2s0b1:
      dhcp4: yes
      access-points:
        "network_ssid_name":
          password: "**********"
```

# How to connect to a WPA Personal wireless network without DHCP

For private wireless networks, the access point name and password must be specified:

```yaml
network:
  version: 2
  renderer: networkd
  wifis:
    wlp2s0b1:
      dhcp4: no
      dhcp6: no
      addresses: [192.168.0.21/24]
      nameservers:
        addresses: [192.168.0.1, 8.8.8.8]
      access-points:
        "network_ssid_name":
          password: "**********"
      routes:
        - to: default
          via: 192.168.0.1
```

# How to connect to WPA Enterprise wireless networks with EAP+TTLS

```yaml
network:
  version: 2
  wifis:
    wl0:
      access-points:
        workplace:
          auth:
            key-management: eap
            method: ttls
            anonymous-identity: "@internal.example.com"
            identity: "joe@internal.example.com"
            password: "v3ryS3kr1t"
      dhcp4: yes
```

# How to connect to WPA Enterprise wireless networks with EAP+TLS

```yaml
network:
  version: 2
  wifis:
    wl0:
      access-points:
        university:
          auth:
            key-management: eap
            method: tls
            anonymous-identity: "@cust.example.com"
            identity: "cert-joe@cust.example.com"
            ca-certificate: /etc/ssl/cust-cacrt.pem
            client-certificate: /etc/ssl/cust-crt.pem
            client-key: /etc/ssl/cust-key.pem
            client-key-password: "d3cryptPr1v4t3K3y"
      dhcp4: yes
```

Many different modes of encryption are supported. See the [Netplan reference](/reference) page.

# How to use multiple addresses on a single interface

The `addresses` keyword can take a list of addresses to assign to an interface. You can also defined a `label` for each address:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      addresses:
        - 10.100.1.37/24
        - 10.100.1.38/24:
            label: "enp3s0:0"
        - 10.100.1.39/24:
            label: "enp3s0:some-label"
```

# How to use multiple addresses with multiple gateways

Similar to the example above, interfaces with multiple addresses can be configured with multiple gateways.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      addresses:
        - 10.0.0.10/24
        - 11.0.0.11/24
      routes:
        - to: default
          via: 10.0.0.1
          metric: 200
        - to: default
          via: 11.0.0.1
          metric: 300
```

We configure individual routes to default (or 0.0.0.0/0) using the address of the gateway for the subnet. The `metric` value should be adjusted so the routing happens as expected.

DHCP can be used to receive one of the IP addresses for the interface. In this case, the default route for that address will be automatically configured with a `metric` value of 100.

# How to use Network Manager as a renderer

Netplan supports both networkd and Network Manager as backends.    You can specify which network backend should be used to configure particular devices by using the `renderer` key. You can also delegate all configuration of the network to Network Manager itself by specifying only the `renderer` key:

```yaml
network:
  version: 2
  renderer: NetworkManager
```

# How to configure interface bonding

Bonding is configured by declaring a bond interface with a list of physical interfaces and a bonding mode:

```yaml
network:
  version: 2
  renderer: networkd
  bonds:
    bond0:
      dhcp4: yes
      interfaces:
        - enp3s0
        - enp4s0
      parameters:
        mode: active-backup
        primary: enp3s0
```

# How to configure multiple bonds

Below is an example of a system acting as a router with various bonded interfaces and different types. Note the 'optional: true' key declarations that allow booting to occur without waiting for those interfaces to activate fully.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp1s0:
      dhcp4: no
    enp2s0:
      dhcp4: no
    enp3s0:
      dhcp4: no
      optional: true
    enp4s0:
      dhcp4: no
      optional: true
    enp5s0:
      dhcp4: no
      optional: true
    enp6s0:
      dhcp4: no
      optional: true
  bonds:
    bond-lan:
      interfaces: [enp2s0, enp3s0]
      addresses: [192.168.93.2/24]
      parameters:
        mode: 802.3ad
        mii-monitor-interval: 1
    bond-wan:
      interfaces: [enp1s0, enp4s0]
      addresses: [192.168.1.252/24]
      nameservers:
        search: [local]
        addresses: [8.8.8.8, 8.8.4.4]
      parameters:
        mode: active-backup
        mii-monitor-interval: 1
        gratuitious-arp: 5
      routes:
        - to: default
          via: 192.168.1.1
    bond-conntrack:
      interfaces: [enp5s0, enp6s0]
      addresses: [192.168.254.2/24]
      parameters:
        mode: balance-rr
        mii-monitor-interval: 1
```

# How to configure network bridges

Use the following configuration to create a simple bridge consisting of a single device that uses DHCP:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      dhcp4: no
  bridges:
    br0:
      dhcp4: yes
      interfaces:
        - enp3s0
```

# How to create a bridge with a VLAN for libvirtd
To get libvirtd to use a specific bridge with a tagged vlan, while continuing to provide an untagged interface as well would involve:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s25:
      dhcp4: true
  bridges:
    br0:
      addresses: [ 10.3.99.25/24 ]
      interfaces: [ vlan15 ]
  vlans:
    vlan15:
      accept-ra: no
      id: 15
      link: enp0s25
```

Then libvirtd would be configured to use this bridge by adding the following content to a new XML file under `/etc/libvirtd/qemu/networks/`. The name of the bridge in the &lt;bridge&gt; tag as well as in &lt;name&gt; need to match the name of the bridge device configured using netplan:

```xml
<network>
    <name>br0</name>
    <bridge name='br0'/>
    <forward mode="bridge"/>
</network>
```

# How to create VLANs

To configure multiple VLANs with renamed interfaces:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    mainif:
      match:
        macaddress: "de:ad:be:ef:ca:fe"
      set-name: mainif
      addresses: [ "10.3.0.5/23" ]
      nameservers:
        addresses: [ "8.8.8.8", "8.8.4.4" ]
        search: [ example.com ]
      routes:
        - to: default
          via: 10.3.0.1
  vlans:
    vlan15:
      id: 15
      link: mainif
      addresses: [ "10.3.99.5/24" ]
    vlan10:
      id: 10
      link: mainif
      addresses: [ "10.3.98.5/24" ]
      nameservers:
        addresses: [ "127.0.0.1" ]
        search: [ domain1.example.com, domain2.example.com ]
```

# How to use a directly connected gateway

This allows setting up a default route, or any route, using the "on-link" keyword where the gateway is an IP address that is directly connected to the network even if the address does not match the subnet configured on the interface.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens3:
      addresses: [ "10.10.10.1/24" ]
      routes:
        - to: default # or 0.0.0.0/0
          via: 9.9.9.9
          on-link: true
```

For IPv6 the config would be very similar:

```yaml
network:
    version: 2
    renderer: networkd
    ethernets:
        ens3:
            addresses: [ "2001:cafe:face:beef::dead:dead/64" ]
            routes:
             - to: default # or "::/0"
               via: "2001:cafe:face::1"
               on-link: true
```

# How to configure source routing

In the example below, ens3 is on the 192.168.3.0/24 network and ens5 is on the 192.168.5.0/24 network. This enables clients on either network to connect to the other and allow the response to come from the correct interface.

Furthermore, the default route is still assigned to ens5 allowing any other traffic to go through it.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens3:
      addresses:
        - 192.168.3.30/24
      dhcp4: no
      routes:
        - to: 192.168.3.0/24
          via: 192.168.3.1
          table: 101
      routing-policy:
        - from: 192.168.3.0/24
          table: 101
    ens5:
      addresses:
        - 192.168.5.24/24
      dhcp4: no
      routes:
        - to: default
          via: 192.168.5.1
        - to: 192.168.5.0/24
          via: 192.168.5.1
          table: 102
      routing-policy:
        - from: 192.168.5.0/24
          table: 102
```

# How to configure a loopback interface

Networkd does not allow creating new loopback devices, but a user can add new addresses to the standard loopback interface, lo, in order to have it considered a valid address on the machine as well as for custom routing:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    lo:
      addresses: [ "127.0.0.1/8", "::1/128", "7.7.7.7/32" ]
```

# How to integrate with Windows DHCP Server

For networks where DHCP is provided by a Windows Server using the dhcp-identifier keyword allows for interoperability:

```yaml
network:
  version: 2
  ethernets:
    enp3s0:
      dhcp4: yes
      dhcp-identifier: mac
```

# How to connect to an IPv6 over IPv4 tunnel

Here, 1.1.1.1 is the client's own IP address; 2.2.2.2 is the remote server's IPv4 address, "2001:dead:beef::2/64" is the client's IPv6 address as defined by the tunnel, and "2001:dead:beef::1" is the remote server's IPv6 address.

Finally, "2001:cafe:face::1/64" is an address for the client within the routed IPv6 prefix:

```yaml
network:
  version: 2
  ethernets:
    eth0:
      addresses:
        - 1.1.1.1/24
        - "2001:cafe:face::1/64"
      routes:
        - to: default
          via: 1.1.1.254
  tunnels:
    he-ipv6:
      mode: sit
      remote: 2.2.2.2
      local: 1.1.1.1
      addresses:
        - "2001:dead:beef::2/64"
      routes:
        - to: default
          via: "2001:dead:beef::1"
```

# How to configure SR-IOV Virtual Functions

For SR-IOV network cards, it is possible to dynamically allocate Virtual Function interfaces for every configured Physical Function. In netplan, a VF is defined by having a link: property pointing to the parent PF.

```yaml
network:
  version: 2
  ethernets:
    eno1:
      mtu: 9000
    enp1s16f1:
      link: eno1
      addresses : [ "10.15.98.25/24" ]
    vf1:
      match:
        name: enp1s16f[2-3]
      link: eno1
      addresses : [ "10.15.99.25/24" ]
```

# How to connect two systems with a WireGuard VPN

Generate the private and public keys in the first peer:

```bash
# wg genkey > private.key
# wg pubkey < private.key > public.key
# cat private.key
UMjI9WbobURkCDh2RT8SRM5osFI7siiR/sPOuuTIDns=
# cat public.key
EdNnZ1/2OJZ9HcScSVcwDVUsctCkKQ/xzjEyd3lZFFs=
```

Do the same in the second peer:

```bash
# wg genkey > private.key
# wg pubkey < private.key > public.key
# cat private.key
UAmjvLDVuV384OWFJkmI4bG8AIAZAfV7LarshnV3+lc=
# cat public.key
AIm+QeCoC23zInKASmhu6z/3iaT0R2IKraB7WwYB5ms=
```

Use the following configuration in the `first peer` (replace the keys and IPs as needed):

```yaml
network:
  tunnels:
    wg0:
      mode: wireguard
      port: 51820
      key: UMjI9WbobURkCDh2RT8SRM5osFI7siiR/sPOuuTIDns=
      addresses:
        - 172.16.0.1/24
      peers:
        - allowed-ips: [172.16.0.0/24]
          endpoint: 10.86.126.56:51820
          keys:
            public: AIm+QeCoC23zInKASmhu6z/3iaT0R2IKraB7WwYB5ms=
```

In the YAML file above, `key` is the first peer's `private key` and
`public` is the second peer's `public key`. `endpoint` is the `second peer` IP address.

Use the following configuration in the `second peer`:

```yaml
network:
  tunnels:
    wg0:
      mode: wireguard
      port: 51820
      key: UAmjvLDVuV384OWFJkmI4bG8AIAZAfV7LarshnV3+lc=
      addresses:
        - 172.16.0.2/24
      peers:
        - allowed-ips: [172.16.0.0/24]
          endpoint: 10.86.126.40:51820
          keys:
            public: EdNnZ1/2OJZ9HcScSVcwDVUsctCkKQ/xzjEyd3lZFFs=
```

In the YAML file above, `key` is the second peer's `private key` and
`public` is the first peer's `public key`. `endpoint` is the `first peer's` IP address.


# How to connect your home computer to a cloud instance with a WireGuard VPN

Follow the same steps from the previous howto to generate the necessary keys.

The difference here is that your computer is likely behind one or more devices doing NAT so you probably don't have a static public IP to use as endpoint in the remote system.

Use the following configuration in your computer:

```yaml
network:
  tunnels:
    wg0:
      mode: wireguard
      port: 51821
      key: UMjI9WbobURkCDh2RT8SRM5osFI7siiR/sPOuuTIDns=
      addresses:
        - 172.17.0.1/24
      peers:
        - allowed-ips: [172.17.0.0/24]
          endpoint: 54.234.x.y:51821
          keys:
            public: AIm+QeCoC23zInKASmhu6z/3iaT0R2IKraB7WwYB5ms=
```

Again, `key` is your private key and `public` is the remote system's public key. The `endpoint` is the public IP address of your instance.

In the remote instance you just need to omit the `endpoint`.

```yaml
network:
  tunnels:
    wg0:
      mode: wireguard
      port: 51821
      key: UAmjvLDVuV384OWFJkmI4bG8AIAZAfV7LarshnV3+lc=
      addresses:
        - 172.17.0.2/24
      peers:
        - allowed-ips: [172.17.0.0/24]
          keys:
            public: EdNnZ1/2OJZ9HcScSVcwDVUsctCkKQ/xzjEyd3lZFFs=
```

Don't forget to allow the UDP port `51821` in your instance's security group.

After applying your configuration you should be able to reach your remote instance through the IP address `172.17.0.2`.
