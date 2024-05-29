# Security Policy

## Supported Versions

We generally support Netplan versions that are being used by the latest Ubuntu LTS and newer.
Please see [Launchpad.net](https://launchpad.net/ubuntu/+source/netplan.io) for the specific version numbers.

## Security best practices

Netplan is a system component that is supposed to be driven as root. Its configuration might contain secret information such as WiFi passwords or VPN credentials, so it's recommended to keep the file permissions for Netplan's configuration very tight, as described in our [threat model](https://netplan.readthedocs.io/en/latest/security/).

## Reporting a Vulnerability

To report a security issue, please email <security@ubuntu.com> with a description of the issue, the steps you took to create the issue, affected versions, and, if known, mitigations for the issue.

Our vulnerability management team will respond within 3 working days of your email. If the issue is confirmed to be a vulnerability, we will assign a CVE. This project follows a maximum disclosure timeline of 90 days.
