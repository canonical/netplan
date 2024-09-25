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

## Cryptography

Netplan does not directly utilise cryptography, but configures underlying tools
to do so. Such tools include `wpa_supplicant`, `systemd-networkd`, `NetworkManager`
or `Open vSwitch` and they can for example be configured to setup WPA2/WPA3
[encypted WiFi](https://w1.fi/wpa_supplicant/devel/code_structure.html#crypto_func)
connections, `802.1x` for wired and wireless authentication and authorisation,
[encrypted WireGuard](https://www.wireguard.com/protocol/) VPN tunnels or SSL
secured OVS endpoints.

### Cryptographic technology used by Netplan

Netplan does not use cryptographic technology directly itself at runtime.
However, when testing the code base it makes use of the `node:crypto`
[NodeJS module](https://nodejs.org/api/crypto.html) to generate random bytes for
our YAML schema fuzzer. See `tests/config_fuzzer/index.js`.

When shipping Netplan packages to the Debian/Ubuntu archive, OpenPGP keys are
used to sign the artifacts. Those commonly utilise 4096 bit RSA cryptography,
but [Launchpad](https://launchpad.net/people/+me/+editpgpkeys) also supports
varying key lengths of RSA, DSA, ECDSA, ECDH and EdDSA.

### Cryptographic technology exposed to the user

Netplan allows to configure certain cryptographic technology that can be
described in its {doc}`../reference/netplan-yaml`. Notable settings include the
{ref}`yaml-auth` block, e.g. `auth.password` can be used configure `WPA-PSK` or
`WPA-EAP` secrets, which can also be a special `hash:...` value for
`wpa_supplicant`. The `auth.method` field controls the technology, such as
`PSK`, `EAP`, `EAPSHA256`, `EAPSUITE_B_192`, `SAE` or `8021X`. The
`ca-certificate`, `client-certificate`, `client-key`, `client-key-password` or
`phase2-auth` can be used to control the CA certificates in an `EAP` context.

For `openvswitch` configurations, the `ssl` setting can contain configuration
for CA certificates and related private keys in `ssl.ca-cert`, `ssl.certificate`
or `ssl.private-key`.

{ref}`yaml-modems` include the `password` setting, which can be used to
authenticate with the carrier network.

{ref}`yaml-tunnels` can contain the `key` setting, describing `input`, `output`
or `private` keys. The latter can be a 256 bit, base64 encoded WireGuard key.

### Packages providing cryptographic functionality

* WireGuard (Linux kernel) – `linux-image`
* NetworkManager (GnuTLS) – `libgnutls30`
* Open vSwitch (OpenSSL) – `libssl3`
* systemd-networkd (OpenSSL) – `libssl3`
* wpa_supplicant (OpenSSL) – `libssl3`

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
