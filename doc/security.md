---
title: "Netplan security"
---

Overview of security aspects of Netplan.

## Storing credentials

Credentials, such as VPN keys and Wi-Fi passwords, are stored along with the rest
of the configuration in YAML files. The recommended set of file permissions is
to have all YAML files owned by and only readable/writable by the root user (`chmod 600`).

When using Network Manager to manage WireGuard tunnels, you can rely on an
external key chain to store your private keys. For more details, see `private-key-flags`
in the Netplan YAML configuration reference.

:::{important}
Security advice: ensure all YAML files in `/etc/netplan`, `/run/netplan` and
`/lib/netplan` are not readable by non-privileged users.
:::

## Systemd `.service` units

Netplan generates many systemd `.service` units, which are world-accessible to
any local user through systemd APIs by design, e.g. using `systemctl show UNIT_NAME.service`

Such service units are therefore generated with `0o644` permissions. This
needs to be taken into consideration especially for the `netplan-ovs-*.service`
units that might contain arbitrary content, for example using the `other-config`
or `external-ids`. Make sure not to put any secrets into those fields, as those
will become world-readable.

* `/run/systemd/system/netplan-ovs-*.service`
* `/run/systemd/system/netplan-sriov-*.service`
* `/run/systemd/system/netplan-regdom.service`
* `/run/systemd/system/netplan-wpa-*.service`
* `/run/systemd/system/systemd-networkd-wait-online.service.d/10-netplan*.conf`

## Static analysis with Coverity

To ensure that common issues do not sneak undetected in our code base,
we scan it periodically with [Coverity](https://scan.coverity.com/).
Through Coverity static analysis, we can achieve a degree of confidence
that some types of issues, such as obvious memory leaks, do not stay
unnoticed in the code.

## Memory issue checks

As part of our CI (continuous integration) workflows, we build Netplan with the GCC
address sanitiser and run unit tests and the Netplan generator against a
number of YAML files. This helps us to detect issues, such as memory leaks and
buffer overflows, at runtime using real configuration as input. When a memory
issue is detected, the process crashes, indicating that some issue was
introduced in the change.

Every time a pull request is created or changes are merged to the main branch,
CI executes these tests, and, if a crash happens, the workflow fails. 

## Binary package hardening

On Ubuntu and Debian, Netplan is built (and in fact most of the binary packages are)
with a number of security flags that apply some hardening to the resulting binary.
That is intended to make the life of attackers harder in case any security issue is
discovered. See the `dpkg-buildflags(1)` manual page for details.
