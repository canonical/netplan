# Ensure hardened build on EL7
%global _hardened_build 1

# Ubuntu calls their own software netplan.io in the archive due to name conflicts
%global ubuntu_name netplan.io

# If the definition isn't available for python3_pkgversion, define it
%{?!python3_pkgversion:%global python3_pkgversion 3}

# If this isn't defined, define it
%{?!_systemdgeneratordir:%global _systemdgeneratordir /usr/lib/systemd/system-generators}

# Force auto-byte-compilation to Python 3
%global __python %{__python3}

# networkd is not available everywhere
%if 0%{?rhel}
%bcond_with networkd_support
%else
%bcond_without networkd_support
%endif

Name:           netplan
Version:        0.104
Release:        0%{?dist}
Summary:        Network configuration tool using YAML
Group:          System Environment/Base
License:        GPLv3
URL:            http://netplan.io/
Source0:        https://github.com/canonical/%{name}/archive/%{version}/%{name}-%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  pkgconfig(bash-completion)
BuildRequires:  pkgconfig(glib-2.0)
BuildRequires:  pkgconfig(gio-2.0)
BuildRequires:  pkgconfig(libsystemd)
BuildRequires:  pkgconfig(systemd)
BuildRequires:  pkgconfig(yaml-0.1)
BuildRequires:  pkgconfig(uuid)
BuildRequires:  python%{python3_pkgversion}-devel
BuildRequires:  systemd-rpm-macros
BuildRequires:  %{_bindir}/pandoc
# For tests
BuildRequires:  %{_sbindir}/ip
BuildRequires:  python%{python3_pkgversion}-coverage
BuildRequires:  python%{python3_pkgversion}-netifaces
BuildRequires:  python%{python3_pkgversion}-nose
BuildRequires:  python%{python3_pkgversion}-pycodestyle
BuildRequires:  python%{python3_pkgversion}-pyflakes
BuildRequires:  python%{python3_pkgversion}-PyYAML

# /usr/sbin/netplan is a Python 3 script that requires netifaces and PyYAML
Requires:       python%{python3_pkgversion}-netifaces
Requires:       python%{python3_pkgversion}-PyYAML
# 'ip' command is used in netplan apply subcommand
Requires:       %{_sbindir}/ip

# Netplan requires a backend for configuration
Requires:       %{name}-default-backend
# Prefer NetworkManager
Suggests:       %{name}-default-backend-NetworkManager

# Netplan requires its core libraries
Requires:       %{name}-libs%{?_isa} = %{version}-%{release}

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
%{_datadir}/dbus-1/system-services/io.netplan.Netplan.service
%{_datadir}/dbus-1/system.d/io.netplan.Netplan.conf
%{_systemdgeneratordir}/%{name}
%{_mandir}/man5/%{name}.5*
%{_mandir}/man8/%{name}*.8*
%dir %{_sysconfdir}/%{name}
%{_prefix}/lib/%{name}/
%{_datadir}/bash-completion/completions/%{name}

# ------------------------------------------------------------------------------------------------

%package libs
Summary:        Network configuration tool using YAML (core library)
Group:          System Environment/Libraries

%description libs
netplan reads network configuration from /etc/netplan/*.yaml which are written by administrators,
installers, cloud image instantiations, or other OS deployments. During early boot, it generates
backend specific configuration files in /run to hand off control of devices to a particular
networking daemon.

This package provides Netplan's core libraries.

%if 0%{?rhel} && 0%{?rhel} < 8
%post libs -p /sbin/ldconfig
%postun libs -p /sbin/ldconfig
%endif

%files libs
%license COPYING
%{_libdir}/libnetplan.so.*

# ------------------------------------------------------------------------------------------------

%package devel
Summary:        Network configuration tool using YAML (development files)
Group:          Development/Libraries
Requires:       %{name}-libs%{?_isa} = %{version}-%{release}

%description devel
netplan reads network configuration from /etc/netplan/*.yaml which are written by administrators,
installers, cloud image instantiations, or other OS deployments. During early boot, it generates
backend specific configuration files in /run to hand off control of devices to a particular
networking daemon.

This package provides development headers and libraries for building applications using Netplan.

%files devel
%{_includedir}/%{name}/
%{_libdir}/libnetplan.so

# ------------------------------------------------------------------------------------------------

%package default-backend-NetworkManager
Summary:        Network configuration tool using YAML (NetworkManager backend)
Group:          System Environment/Base
Requires:       %{name} = %{version}-%{release}
# Netplan requires NetworkManager for configuration
Requires:       NetworkManager
# Disable NetworkManager's autoconfiguration
Requires:       NetworkManager-config-server

%if 0%{?rhel} && 0%{?rhel} < 8
# This is needed for Wi-Fi
Requires:       NetworkManager-wifi
%else
# Generally, if linux-firmware-whence is installed, we want Wi-Fi capabilities
Recommends:     (NetworkManager-wifi if linux-firmware-whence)
# This is preferred for Wi-Fi
Suggests:       NetworkManager-wifi
%endif

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
%{_prefix}/lib/%{name}/00-netplan-default-renderer-nm.yaml

# ------------------------------------------------------------------------------------------------

%if %{with networkd_support}
%package default-backend-networkd
Summary:        Network configuration tool using YAML (systemd-networkd backend)
Group:          System Environment/Base
Requires:       %{name} = %{version}-%{release}
# Netplan requires systemd-networkd for configuration
Requires:       systemd-networkd

# Generally, if linux-firmware-whence is installed, we want Wi-Fi capabilities
Recommends:     (wpa_supplicant if linux-firmware-whence)
# This is preferred for Wi-Fi
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

# Drop -Werror to avoid the following error:
# /usr/include/glib-2.0/glib/glib-autocleanups.h:28:3: error: 'ip_str' may be used uninitialized in this function [-Werror=maybe-uninitialized]
sed -e "s/-Werror//g" -i Makefile


%build
%make_build CFLAGS="%{optflags}"


%install
%make_install ROOTPREFIX=%{_prefix} LIBDIR=%{_libdir} LIBEXECDIR=%{_libexecdir}

# Pre-create the config directory
mkdir -p %{buildroot}%{_sysconfdir}/%{name}

# Generate Netplan default renderer configuration
cat > %{buildroot}%{_prefix}/lib/%{name}/00-netplan-default-renderer-nm.yaml <<EOF
network:
  renderer: NetworkManager
EOF
%if %{with networkd_support}
cat > %{buildroot}%{_prefix}/lib/%{name}/00-netplan-default-renderer-networkd.yaml <<EOF
network:
  renderer: networkd
EOF
%endif


%check
make check


%changelog
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
