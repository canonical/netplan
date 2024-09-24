---
title: "Netplan Generator"
---

Netplan uses a [systemd-generator](https://www.freedesktop.org/software/systemd/man/latest/systemd.generator.html)
to emit network configuration at boot time. This generator is called very early during the boot
process to ensure that all the configuration needed will be available for the back end
the user chose to use.

The generator executes the same tool used by the command `netplan generate`. One of the
differences is that, when called as a systemd generator, parsing errors will be ignored by default.
That means that errors in the configuration will not prevent Netplan to emit network configuration.
When executed via the CLI, via `netplan generate` or `netplan apply` for example, errors will not
be ignored and the user is encouraged to fix them, otherwise the commands will fail.

When an error is ignored, Netplan might end up with network definitions that are not
fully valid and incomplete. Users are advised to fix any issues present in their
configuration to avoid having network connectivity problems.

