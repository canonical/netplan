# Netplan - Declarative network configuration for various backends

[![Build+ABI](https://github.com/canonical/netplan/workflows/Build%20&%20ABI%20compatibility/badge.svg?branch=main)](https://github.com/canonical/netplan/actions/workflows/build-abi.yml?query=branch%3Amain)
[![Test+Coverage](https://github.com/canonical/netplan/workflows/Unit%20tests%20&%20Coverage/badge.svg?branch=main)](https://github.com/canonical/netplan/actions/workflows/check-coverage.yml?query=branch%3Amain)
[![CI](https://github.com/canonical/netplan/workflows/Autopkgtest%20CI/badge.svg?branch=main)](https://github.com/canonical/netplan/actions/workflows/autopkgtest.yml?query=branch%3Amain)


# Website

http://netplan.io

# Documentation

An overview of the architecture can be found at [netplan.io/design](https://netplan.io/design)

Find the full [documentation for Netplan](https://netplan.readthedocs.io) on "Read the Docs".

# Build using Meson

Steps to build netplan using the [Meson](https://mesonbuild.com) build system inside the `build/` directory:

* meson setup build --prefix=/usr [-Db_coverage=true]
* meson compile -C build
* meson test -C build --verbose [TEST_NAME]
* meson install -C build --destdir ../tmproot

# Bug reports

Please file bug reports in [Launchpad](https://bugs.launchpad.net/netplan/+filebug).

# Contact us

Please join us on [IRC in #netplan](https://web.libera.chat/gamja/?channels=%23netplan) at Libera.Chat.

Our mailing list is [here](https://lists.launchpad.net/netplan-developers/).

Email the list at [netplan-developers@lists.launchpad.net](mailto:netplan-developers@lists.launchpad.net).

