---
title: netplan
section: 5
author: Martin Pitt (<martin.pitt@ubuntu.com>)
...

Introduction
============
Distribution installers, cloud instantiation, image builds for particular
devices, or any other way to deploy an operating system put its desired
network configuration into a ``/etc/netplan/*.yaml`` configuration file. During
early boot, the netplan "network renderer" runs which reads
``/etc/netplan/`` and writes configuration to ``/run`` to hand off
control of devices to the specified networking daemon.

 - Wifi and WWAN get managed by NetworkManager
 - Any other configured devices get handled by systemd-networkd by default,
   unless explicitly marked as managed by a specific renderer (NetworkManager)
 - Devices not covered by the network config do not get touched at all.
 - Usable in initramfs (few dependencies and fast)
 - No persistent generated config, only original YAML config
 - Default policy applies with no config file present
 - Parser supports multiple config files to allow applications like libvirt or lxd
   to package up expected network config (``virbr0``, ``lxdbr0``), or to change the
   global default policy to use NetworkManager for everything.
 - Retains the flexibility to change backends/policy later or adjust to
   removing NetworkManager, as generated configuration is ephemeral.

General structure
=================
netplan's configuration files use the
[YAML](<http://yaml.org/spec/1.1/current.html>) format. All
``/etc/netplan/*.yaml`` are read in order, and lexicographically later files
amend (new mapping keys) or override (same mapping keys) previous ones.

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
         above).

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
    for a particular device definition. Default is ``networkd`` for all device
    types except wifi, for which ``NetworkManager`` is the default.

``dhcp4`` (bool)

:   Enable DHCP for IPv4. Off by default.

``dhcp6`` (bool)

:   Enable DHCP for IPv6. Off by default.

``addresses`` (sequence of scalars)

:   Add static addresses to the interface in addition to the ones received
    through DHCP or RA. Each sequence entry is in CIDR notation, i. e. of the
    form ``addr/prefixlen``. ``addr`` is an IPv4 or IPv6 address as recognized
    by **``inet_pton``**(3) and ``prefixlen`` the number of bits of the subnet.

    Example: ``addresses: [192.168.14.2/24, 2001:1::1/64]``

Properties for device type ``ethernets:``
=========================================
Ethernet device definitions do not support any specific properties beyond the
common ones described above.

Properties for device type ``wifis:``
=====================================
This device type is only supported by the ``NetworkManager`` backend.

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
            - 2001:1::1/64
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
              # mode defaults to "managed" (client)
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
          interfaces: [my_ap, switchports]
          dhcp4: true
      routes:
       - to: 0.0.0.0/0
         via: 11.0.0.1
         metric: 3
      nameservers:
        search: [foo.local, bar.local]
        addresses: [8.8.8.8]

<!--- vim: ft=markdown
-->
