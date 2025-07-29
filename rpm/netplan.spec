# Ubuntu calls their own software netplan.io in the archive due to name conflicts
%global ubuntu_name netplan.io

# If this isn't defined, define it
%{?!_systemdgeneratordir:%global _systemdgeneratordir /usr/lib/systemd/system-generators}

# Netplan library soversion major
%global libsomajor 1

# networkd is not available everywhere
%if 0%{?rhel} && ! 0%{?epel}
%bcond_with networkd_support
%else
%bcond_without networkd_support
%endif

%bcond_with tests

Name:           netplan
Version:        1.1.2
Release:        1%{?dist}
Summary:        Network configuration tool using YAML
License:        GPL-3.0-only
URL:            http://netplan.io/
Source0:        https://github.com/canonical/%{name}/archive/%{version}/%{name}-%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  meson >= 1.3
BuildRequires:  pkgconfig(bash-completion)
BuildRequires:  pkgconfig(glib-2.0)
BuildRequires:  pkgconfig(gio-2.0)
BuildRequires:  pkgconfig(libsystemd)
BuildRequires:  pkgconfig(systemd)
BuildRequires:  pkgconfig(yaml-0.1)
BuildRequires:  pkgconfig(uuid)
BuildRequires:  python3-devel
BuildRequires:  systemd-rpm-macros
BuildRequires:  %{_bindir}/pandoc
BuildRequires:  python3dist(cffi)
%if %{with tests}
# For tests
BuildRequires:  %{_sbindir}/ip
BuildRequires:  libcmocka-devel
BuildRequires:  python3dist(coverage)
BuildRequires:  python3dist(pytest)
BuildRequires:  python3dist(netifaces)
BuildRequires:  python3dist(pycodestyle)
BuildRequires:  python3dist(pyflakes)
BuildRequires:  python3dist(pyyaml)
%endif

# /usr/sbin/netplan is a Python 3 script that requires netifaces and PyYAML
Requires:       python3dist(netifaces)
Requires:       python3dist(pyyaml)
# 'ip' command is used in netplan apply subcommand
Requires:       %{_sbindir}/ip
# netplan ships dbus files
Requires:       dbus-common

# Netplan requires a backend for configuration
Requires:       %{name}-default-backend
# Prefer NetworkManager
Suggests:       %{name}-default-backend-NetworkManager

# Netplan requires its core libraries
Requires:       %{name}-libs%{?_isa} = %{version}-%{release}

# Python bindings are in their own package but are required for CLI
Requires:       python3-%{name}%{?_isa} = %{version}-%{release}

# Provide the package name that Ubuntu uses for it too...
Provides:       %{ubuntu_name} = %{version}-%{release}
Provides:       %{ubuntu_name}%{?_isa} = %{version}-%{release}



%description
netplan reads network configuration from /etc/netplan/*.yaml which are written by administrators,
installers, cloud image instantiations, or other OS deployments. During early boot, it generates
backend specific configuration files in /run to hand off control of devices to a particular
networking daemon.

Currently supported backends are NetworkManager and systemd-networkd.

%files
%license COPYING
%doc %{_docdir}/%{name}/
%{_sbindir}/%{name}
%{_datadir}/%{name}/
%{_datadir}/dbus-1/system-services/io.%{name}.Netplan.service
%{_datadir}/dbus-1/system.d/io.%{name}.Netplan.conf
%{_systemdgeneratordir}/%{name}
%{_mandir}/man5/%{name}.5*
%{_mandir}/man8/%{name}*.8*
%dir %{_sysconfdir}/%{name}
%dir %{_libexecdir}/%{name}
%{_libexecdir}/%{name}/generate
%{_libexecdir}/%{name}/%{name}-dbus
%{_datadir}/bash-completion/completions/%{name}

# ------------------------------------------------------------------------------------------------

%package libs
Summary:        Network configuration tool using YAML (core library)

%description libs
netplan reads network configuration from /etc/netplan/*.yaml which are written by administrators,
installers, cloud image instantiations, or other OS deployments. During early boot, it generates
backend specific configuration files in /run to hand off control of devices to a particular
networking daemon.

This package provides Netplan's core libraries.

%files libs
%license COPYING
%{_libdir}/lib%{name}.so.%{libsomajor}{,.*}

# ------------------------------------------------------------------------------------------------

%package devel
Summary:        Network configuration tool using YAML (development files)
Requires:       %{name}-libs%{?_isa} = %{version}-%{release}

%description devel
netplan reads network configuration from /etc/netplan/*.yaml which are written by administrators,
installers, cloud image instantiations, or other OS deployments. During early boot, it generates
backend specific configuration files in /run to hand off control of devices to a particular
networking daemon.

This package provides development headers and libraries for building applications using Netplan.

%files devel
%{_includedir}/%{name}/
%{_libdir}/lib%{name}.so
%{_libdir}/pkgconfig/%{name}.pc

# ------------------------------------------------------------------------------------------------

%package default-backend-NetworkManager
Summary:        Network configuration tool using YAML (NetworkManager backend)
Requires:       %{name} = %{version}-%{release}
# Netplan requires NetworkManager for configuration
Requires:       NetworkManager
# Disable NetworkManager's autoconfiguration
Requires:       NetworkManager-config-server

# Generally, if linux-firmware-whence is installed, we want Wi-Fi capabilities
Recommends:     (NetworkManager-wifi if linux-firmware-whence)
Suggests:       NetworkManager-wifi

# One and only one default backend permitted
Conflicts:      %{name}-default-backend
Provides:       %{name}-default-backend

BuildArch:      noarch

%description default-backend-NetworkManager
netplan reads network configuration from /etc/netplan/*.yaml which are written by administrators,
installers, cloud image instantiations, or other OS deployments. During early boot, it generates
backend specific configuration files in /run to hand off control of devices to a particular
networking daemon.

This package configures Netplan to use NetworkManager as its backend.

%files default-backend-NetworkManager
%attr(600,root,root) %{_prefix}/lib/%{name}/00-network-manager-all.yaml

# ------------------------------------------------------------------------------------------------

%package -n python3-%{name}
Summary:        Python bindings for lib%{name}

Requires:       python3-cffi
Requires:       %{name}-libs%{?_isa} = %{version}-%{release}

%description -n python3-%{name}
Declarative network configuration Python bindings
Netplan reads YAML network configuration files which are written
by administrators, installers, cloud image instantiations, or other OS
deployments. During early boot it then generates backend specific
configuration files in /run to hand off control of devices to a particular
networking daemon.

Currently supported backends are networkd and NetworkManager.

This package provides a CFFI based Python bindings to libnetplan.

%files -n python3-%{name}
%{python3_sitearch}/%{name}/

# ------------------------------------------------------------------------------------------------

%if %{with networkd_support}
%package default-backend-networkd
Summary:        Network configuration tool using YAML (systemd-networkd backend)
Requires:       %{name} = %{version}-%{release}
# Netplan requires systemd-networkd for configuration
Requires:       systemd-networkd

# Generally, if linux-firmware-whence is installed, we want Wi-Fi capabilities
Recommends:     (wpa_supplicant if linux-firmware-whence)
Suggests:       wpa_supplicant

# One and only one default backend permitted
Conflicts:      %{name}-default-backend
Provides:       %{name}-default-backend

BuildArch:      noarch

%description default-backend-networkd
netplan reads network configuration from /etc/netplan/*.yaml which are written by administrators,
installers, cloud image instantiations, or other OS deployments. During early boot, it generates
backend specific configuration files in /run to hand off control of devices to a particular
networking daemon.

This package configures Netplan to use systemd-networkd as its backend.

%files default-backend-networkd
%{_prefix}/lib/%{name}/00-netplan-default-renderer-networkd.yaml
%endif

# ------------------------------------------------------------------------------------------------


%prep
%autosetup -p1

# these tests all fail in containers, or are linting/codestyle which we don't care about
sed -i -e "/    test('legacy-tests',/,+3d" \
        -e "/    test('codestyle',/,+3d" \
        -e "/    test('linting',/,+3d" \
        -e "/    test('unit-tests',/,+4d" \
        meson.build


%build
%if %{with tests}
%meson
%else
%meson -Dtesting=false
%endif
%meson_build


%install
%meson_install

# Pre-create the config directory
mkdir -p %{buildroot}%{_sysconfdir}/%{name}

# Create the lib dir for default config
mkdir -p %{buildroot}%{_prefix}/lib/%{name}

mv -n %{buildroot}/%{python3_sitelib}/%{name}/* %{buildroot}/%{python3_sitearch}/%{name}/
rm -f %{python3_sitelib}/%{name}/

# Generate Netplan default renderer configuration
cat > %{buildroot}%{_prefix}/lib/%{name}/00-network-manager-all.yaml <<EOF
network:
  version: 2
  renderer: NetworkManager
EOF
%if %{with networkd_support}
cat > %{buildroot}%{_prefix}/lib/%{name}/00-netplan-default-renderer-networkd.yaml <<EOF
network:
  version: 2
  renderer: networkd
EOF
%endif


%if %{with tests}
%check
%meson_test
%endif


%changelog
* Thu Jul 10 2025 Jonathan Wright <jonathan@almalinux.org> - 1.1.2-0
- Update to 1.1.2
- Resync with Fedora spec

* Tue Feb 14 2023 Neal Gompa <ngompa13@gmail.com> - 0.106-0
- Update to 0.106
- Resync with Fedora spec
- Drop EL7 and EL8 support

* Thu Aug 18 2022 Lukas Märdian <slyon@ubuntu.com> - 0.105-0
- Update to 0.105

* Sun Feb 20 2022 Neal Gompa <ngompa13@gmail.com> - 0.104-0
- Update to 0.104
- Resync with Fedora spec

* Fri Dec 14 2018 Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com> - 0.95
- Update to 0.95

* Sat Oct 13 2018 Neal Gompa <ngompa13@gmail.com> - 0.40.3-0
- Rebase to 0.40.3

* Tue Mar 13 2018 Neal Gompa <ngompa13@gmail.com> - 0.34-0.1
- Update to 0.34

* Wed Mar  7 2018 Neal Gompa <ngompa13@gmail.com> - 0.33-0.1
- Rebase to 0.33

* Sat Nov  4 2017 Neal Gompa <ngompa13@gmail.com> - 0.30-1
- Rebase to 0.30

* Sun Jul  2 2017 Neal Gompa <ngompa13@gmail.com> - 0.23~17.04.1-1
- Initial packaging
