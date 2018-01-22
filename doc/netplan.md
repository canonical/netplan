---
title: netplan
section: 5
author:
- Mathieu Trudel-Lapierre (<cyphermox@ubuntu.com>)
- Martin Pitt (<martin.pitt@ubuntu.com>)
...

Introduction
============
Distribution installers, cloud instantiation, image builds for particular
devices, or any other way to deploy an operating system put its desired
network configuration into YAML configuration file(s). During
early boot, the netplan "network renderer" runs which reads
``/{lib,etc,run}/netplan/*.yaml`` and writes configuration to ``/run`` to hand
off control of devices to the specified networking daemon.

 - Configured devices get handled by systemd-networkd by default,
   unless explicitly marked as managed by a specific renderer (NetworkManager)
 - Devices not covered by the network config do not get touched at all.
 - Usable in initramfs (few dependencies and fast)
 - No persistent generated config, only original YAML config
 - Parser supports multiple config files to allow applications like libvirt or lxd
   to package up expected network config (``virbr0``, ``lxdbr0``), or to change the
   global default policy to use NetworkManager for everything.
 - Retains the flexibility to change backends/policy later or adjust to
   removing NetworkManager, as generated configuration is ephemeral.

General structure
=================
netplan's configuration files use the
[YAML](<http://yaml.org/spec/1.1/current.html>) format. All
``/{lib,etc,run}/netplan/*.yaml`` are considered. Lexicographically later files
(regardless of in which directory they are) amend (new mapping keys) or
override (same mapping keys) previous ones. A file in ``/run/netplan``
completely shadows a file with same name in ``/etc/netplan``, and a file in
either of those directories shadows a file with the same name in
``/lib/netplan``.

The top-level node in a netplan configuration file is a ``network:`` mapping
that contains ``version: 2`` (the YAML currently being used by curtin, MaaS,
etc. is version 1), and then device definitions grouped by their type, such as
``ethernets:``, ``wifis:``, or ``bridges:``. These are the types that our
renderer can understand and are supported by our backends.

Each type block contains device definitions as a map where the keys (called
"configuration IDs") are defined as below.

Device configuration IDs
========================

The key names below the per-device-type definition maps (like ``ethernets:``)
are called "ID"s. They must be unique throughout the entire set of
configuration files. Their primary purpose is to serve as anchor names for
composite devices, for example to enumerate the members of a bridge that is
currently being defined.

There are two physically/structurally different classes of device definitions,
and the ID field has a different interpretation for each:

Physical devices

:   (Examples: ethernet, wifi) These can dynamically come and go between
    reboots and even during runtime (hotplugging). In the generic case, they
    can be selected by ``match:`` rules on desired properties, such as name/name
    pattern, MAC address, driver, or device paths. In general these will match
    any number of devices (unless they refer to properties which are unique
    such as the full path or MAC address), so without further knowledge about
    the  hardware these will always be considered as a group.

    It is valid to specify no match rules at all, in which case the ID field is
    simply the interface name to be matched. This is mostly useful if you want
    to keep simple cases simple, and it's how network device configuration has
    been done for a long time.

    If there are ``match``: rules, then the ID field is a purely opaque name
    which is only being used  for references from definitions of compound
    devices in the config.


Virtual devices

:  (Examples: veth, bridge, bond) These are fully under the control of the
   config file(s) and the network stack. I. e. these devices are being created
   instead of matched. Thus ``match:`` and ``set-name:`` are not applicable for
   these, and the ID field is the name of the created virtual device.

Common properties for physical device types
===========================================

``match`` (mapping)

:    This selects a subset of available physical devices by various hardware
     properties. The following configuration will then apply to all matching
     devices, as soon as they appear. *All* specified properties must match.

     ``name`` (scalar)
     :   Current interface name. Globs are supported, and the primary use case
         for matching on names, as selecting one fixed name can be more easily
         achieved with having no ``match:`` at all and just using the ID (see
         above). Note that currently only networkd supports globbing,
         NetworkManager does not.

     ``macaddress`` (scalar)
     :   Device's MAC address in the form "XX:XX:XX:XX:XX:XX". Globs are not
         allowed.

     ``driver`` (scalar)
     :   Kernel driver name, corresponding to the ``DRIVER`` udev property.
         Globs are supported. Matching on driver is *only* supported with
         networkd.

     Examples:

     - all cards on second PCI bus:

            match:
              name: enp2*

     - fixed MAC address:

            match:
              macaddress: 11:22:33:AA:BB:FF

     - first card of driver ``ixgbe``:

            match:
              driver: ixgbe
              name: en*s0

``set-name`` (scalar)

:    When matching on unique properties such as path or MAC, or with additional
     assumptions such as "there will only ever be one wifi device",
     match rules can be written so that they only match one device. Then this
     property can be used to give that device a more specific/desirable/nicer
     name than the default from udev’s ifnames.  Any additional device that
     satisfies the match rules will then fail to get renamed and keep the
     original kernel name (and dmesg will show an error).

``wakeonlan`` (bool)

:    Enable wake on LAN. Off by default.


Common properties for all device types
======================================

``renderer`` (scalar)

:   Use the given networking backend for this definition. Currently supported are
    ``networkd`` and ``NetworkManager``. This property can be specified globally
    in ``networks:``, for a device type (in e. g. ``ethernets:``) or
    for a particular device definition. Default is ``networkd``.

``dhcp4`` (bool)

:   Enable DHCP for IPv4. Off by default.

``dhcp6`` (bool)

:   Enable DHCP for IPv6. Off by default.

``accept-ra`` (bool)

:   Accept Router Advertisement that would have the kernel configure IPv6 by itself.
    On by default.

``addresses`` (sequence of scalars)

:   Add static addresses to the interface in addition to the ones received
    through DHCP or RA. Each sequence entry is in CIDR notation, i. e. of the
    form ``addr/prefixlen``. ``addr`` is an IPv4 or IPv6 address as recognized
    by **``inet_pton``**(3) and ``prefixlen`` the number of bits of the subnet.

    Example: ``addresses: [192.168.14.2/24, "2001:1::1/64"]``

``gateway4``, ``gateway6`` (scalar)

:   Set default gateway for IPv4/6, for manual address configuration. This
    requires setting ``addresses`` too. Gateway IPs must be in a form
    recognized by **``inet_pton``**(3).

    Example for IPv4: ``gateway4: 172.16.0.1``  
    Example for IPv6: ``gateway6: "2001:4::1"``

``nameservers`` (mapping)

:   Set DNS servers and search domains, for manual address configuration. There
are two supported fields: ``addresses:`` is a list of IPv4 or IPv6 addresses
similar to ``gateway*``, and ``search:`` is a list of search domains.

    Example:

        ethernets:
          id0:
            [...]
            nameservers:
              search: [lab, home]
              addresses: [8.8.8.8, "FEDC::1"]


Properties for device type ``ethernets:``
=========================================
Ethernet device definitions do not support any specific properties beyond the
common ones described above.

Properties for device type ``wifis:``
=====================================
Note that ``systemd-networkd`` does not natively support wifi, so you need
wpasupplicant installed if you let the ``networkd`` renderer handle wifi.

``access-points`` (mapping)

:    This provides pre-configured connections to NetworkManager. Note that
     users can of course select other access points/SSIDs. The keys of the
     mapping are the SSIDs, and the values are mappings with the following
     supported properties:

     ``password`` (scalar)
     :    Enable WPA2 authentication and set the passphrase for it. If not
          given, the network is assumed to be open. Other authentication modes
          are not currently supported.

     ``mode`` (scalar)
     :    Possible access point modes are ``infrastructure`` (the default),
          ``ap`` (create an access point to which other devices can connect),
          and ``adhoc`` (peer to peer networks without a central access point).
          ``ap`` is only supported with NetworkManager.

Properties for device type ``bridges:``
=======================================

``interfaces`` (sequence of scalars)

:    All devices matching this ID list will be added to the bridge.

     Example:

          ethernets:
            switchports:
              match: {name: "enp2*"}
          [...]
          bridges:
            br0:
              interfaces: [switchports]

``parameters`` (mapping)

:    Customization parameters for special bridging options. Using the
     NetworkManager renderer, parameter values for time intervals should be
     expressed in milliseconds; for the systemd renderer, they should be in
     seconds unless otherwise specified.

     ``ageing-time`` (scalar)
     :    Set the period of time to keep a MAC address in the forwarding
          database after a packet is received.

     ``priority`` (scalar)
     :    Set the priority value for the bridge. This value should be a
          number between ``0`` and ``65535``. Lower values mean higher
          priority. The bridge with the higher priority will be elected as
          the root bridge.

     ``port-priority`` (scalar)
     :    Set the port priority to <priority>. The priority value is
          a number between ``0`` and ``63``. This metric is used in the
          designated port and root port selection algorithms.

     ``forward-delay`` (scalar)
     :    Specify the period of time the bridge will remain in Listening and
          Learning states before getting to the Forwarding state. This value
          should be set in seconds for the systemd backend, and in milliseconds
          for the NetworkManager backend.

     ``hello-time`` (scalar)
     :    Specify the interval between two hello packets being sent out from
          the root and designated bridges. Hello packets communicate
          information about the network topology.

     ``max-age`` (scalar)
     :    Set the maximum age of a hello packet. If the last hello packet is
          older than that value, the bridge will attempt to become the root
          bridge.

     ``path-cost`` (scalar)
     :    Set the cost of a path on the bridge. Faster interfaces should have
          a lower cost. This allows a finer control on the network topology
          so that the fastest paths are available whenever possible.

     ``stp`` (bool)
     :    Define whether the bridge should use Spanning Tree Protocol. The
          default value is "true", which means that Spanning Tree should be
          used.


Properties for device type ``bonds:``
=======================================

``interfaces`` (sequence of scalars)

:    All devices matching this ID list will be added to the bond.

     Example:

          ethernets:
            switchports:
              match: {name: "enp2*"}
          [...]
          bonds:
            bond0:
              interfaces: [switchports]

``parameters`` (mapping)

:    Customization parameters for special bonding options. Using the
     NetworkManager renderer, parameter values for intervals should be
     expressed in milliseconds; for the systemd renderer, they should be in
     seconds unless otherwise specified.

     ``mode`` (scalar)
     :    Set the bonding mode used for the interfaces. The default is
          ``balance-rr`` (round robin). Possible values are ``balance-rr``,
          ``active-backup``, ``balance-xor``, ``broadcast``, ``802.3ad``,
          ``balance-tlb``, and ``balance-alb``.

     ``lacp-rate`` (scalar)
     :    Set the rate at which LACPDUs are transmitted. This is only useful
          in 802.3ad mode. Possible values are ``slow`` (30 seconds, default),
          and ``fast`` (every second).

     ``mii-monitor-interval`` (scalar)
     :    Specifies the interval for MII monitoring (verifying if an interface
          of the bond has carrier). The default is ``0``; which disables MII
          monitoring.

     ``min-links`` (scalar)
     :    The minimum number of links up in a bond to consider the bond
          interface to be up.

     ``transmit-hash-policy`` (scalar)
     :    Specifies the transmit hash policy for the selection of slaves. This
          is only useful in balance-xor, 802.3ad and balance-tlb modes.
          Possible values are ``layer2``, ``layer3+4``, ``layer2+3``,
          ``encap2+3``, and ``encap3+4``.

     ``ad-select`` (scalar)
     :    Set the aggregation selection mode. Possible values are ``stable``,
          ``bandwidth``, and ``count``. This option is only used in 802.3ad
          mode.

     ``all-slaves-active`` (bool)
     :    If the bond should drop duplicate frames received on inactive ports,
          set this option to ``false``. If they should be delivered, set this
          option to ``true``. The default value is false, and is the desirable
          behavior in most situations.

     ``arp-interval`` (scalar)
     :    Set the interval value for how frequently ARP link monitoring should
          happen. The default value is ``0``, which disables ARP monitoring.

     ``arp-ip-targets`` (sequence of scalars)
     :    IPs of other hosts on the link which should be sent ARP requests in
          order to validate that a slave is up. This option is only used when
          ``arp-interval`` is set to a value other than ``0``. At least one IP
          address must be given for ARP link monitoring to function. Only IPv4
          addresses are supported. You can specify up to 16 IP addresses. The
          default value is an empty list.

     ``arp-validate`` (scalar)
     :    Configure how ARP replies are to be validated when using ARP link
          monitoring. Possible values are ``none``, ``active``, ``backup``,
          and ``all``.

     ``arp-all-targets`` (scalar)
     :    Specify whether to use any ARP IP target being up as sufficient for
          a slave to be considered up; or if all the targets must be up. This
          is only used for ``active-backup`` mode when ``arp-validate`` is
          enabled. Possible values are ``any`` and ``all``.

     ``up-delay`` (scalar)
     :    Specify the delay before enabling a link once the link is physically
          up. The default value is ``0``.

     ``down-delay`` (scalar)
     :    Specify the delay before disabling a link once the link has been
          lost. The default value is ``0``.

     ``fail-over-mac-policy`` (scalar)
     :    Set whether to set all slaves to the same MAC address when adding
          them to the bond, or how else the system should handle MAC addresses.
          The possible values are ``none``, ``active``, and ``follow``.

     ``gratuitious-arp`` (scalar)
     :    Specify how many ARP packets to send after failover. Once a link is
          up on a new slave, a notification is sent and possibly repeated if
          this value is set to a number greater than ``1``. The default value
          is ``1`` and valid values are between ``1`` and ``255``. This only
          affects ``active-backup`` mode.

     ``packets-per-slave`` (scalar)
     :    In ``balance-rr`` mode, specifies the number of packets to transmit
          on a slave before switching to the next. When this value is set to
          ``0``, slaves are chosen at random. Allowable values are between
          ``0`` and ``65535``. The default value is ``1``. This setting is
          only used in ``balance-rr`` mode.

     ``primary-reselect-policy`` (scalar)
     :    Set the reselection policy for the primary slave. On failure of the
          active slave, the system will use this policy to decide how the new
          active slave will be chosen and how recovery will be handled. The
          possible values are ``always``, ``better``, and ``failure``.

     ``learn-packet-interval`` (scalar)
     :    Specify the interval between sending learning packets to each slave.
          The value range is between ``1`` and ``0x7fffffff``. The default
          value is ``1``. This option only affects ``balance-tlb`` and
          ``balance-alb`` modes.

     ``primary`` (scalar)
     :    Specify a device to be used as a primary slave, or preferred device
          to use as a slave for the bond (ie. the preferred device to send
          data through), whenever it is available. This only affects
          ``active-backup``, ``balance-alb``, and ``balance-tlb`` modes.


Properties for device type ``vlans:``
=======================================

``id`` (scalar)

:    VLAN ID, a number between 0 and 4094.

``link`` (scalar)

:    netplan ID of the underlying device definition on which this VLAN gets
     created.

Example:

    ethernets:
      eno1: {...}
    vlans:
      en-intra:
        id: 1
        link: eno1
        dhcp4: yes
      en-vpn:
        id: 2
        link: eno1
        address: ...


Examples
========
Configure an ethernet device with networkd, identified by its name, and enable
DHCP:

    network:
      version: 2
      ethernets:
        eno1:
          dhcp4: true

This is a complex example which shows most available features:

    network:
      version: 2
      # if specified, can only realistically have that value, as networkd cannot
      # render wifi/3G.
      renderer: NetworkManager
      ethernets:
        # opaque ID for physical interfaces, only referred to by other stanzas
        id0:
          match:
            macaddress: 00:11:22:33:44:55
          wakeonlan: true
          dhcp4: true
          addresses:
            - 192.168.14.2/24
            - "2001:1::1/64"
          gateway4: 192.168.14.1
          gateway6: "2001:1::2"
          nameservers:
            search: [foo.local, bar.local]
            addresses: [8.8.8.8]
          routes:
            - to: 0.0.0.0/0
              via: 11.0.0.1
              metric: 3
        lom:
          match:
            driver: ixgbe
          # you are responsible for setting tight enough match rules
          # that only match one device if you use set-name
          set-name: lom1
          dhcp6: true
        switchports:
          # all cards on second PCI bus; unconfigured by themselves, will be added
          # to br0 below
          match:
            name: enp2*
          mtu: 1280
      wifis:
        all-wlans:
          # useful on a system where you know there is only ever going to be one device
          match: {}
          access-points:
            "Joe's home":
              # mode defaults to "infrastructure" (client)
              password: "s3kr1t"
        # this creates an AP on wlp1s0 using hostapd; no match rules, thus ID is
        # the interface name
        wlp1s0:
          access-points:
            "guest":
               mode: ap
               channel: 11
               # no WPA config implies default of open
      bridges:
        # the key name is the name for virtual (created) interfaces; no match: and
        # set-name: allowed
        br0:
          # IDs of the components; switchports expands into multiple interfaces
          interfaces: [wlp1s0, switchports]
          dhcp4: true

<!--- vim: ft=markdown
-->
