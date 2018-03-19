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


Name:           netplan
Version:        0.34.1
Release:        0%{?dist}
Summary:        Network configuration tool using YAML
Group:          System Environment/Base
License:        GPLv3
URL:            http://netplan.io/
Source0:        https://github.com/CanonicalLtd/%{name}/archive/%{version}/%{name}-%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  pkgconfig(bash-completion)
BuildRequires:  pkgconfig(systemd)
BuildRequires:  pkgconfig(glib-2.0)
BuildRequires:  pkgconfig(yaml-0.1)
BuildRequires:  pkgconfig(uuid)
BuildRequires:  %{_bindir}/pandoc
BuildRequires:  python%{python3_pkgversion}-devel
# For tests
BuildRequires:  python%{python3_pkgversion}-coverage
BuildRequires:  python%{python3_pkgversion}-PyYAML
BuildRequires:  python%{python3_pkgversion}-pycodestyle
BuildRequires:  python%{python3_pkgversion}-pyflakes

# /usr/sbin/netplan is a Python 3 script that requires PyYAML
Requires:       python%{python3_pkgversion}-PyYAML

# netplan supports either systemd or NetworkManager as backends to configure the network
Requires:       systemd

%if 0%{?el7}
# systemd-networkd is a separate subpackage in EL7
Requires:       systemd-networkd
%endif

%if 0%{?fedora} || 0%{?rhel} >= 8
# NetworkManager is preferred, but wpa_supplicant can be used directly for Wi-Fi networks
Suggests:       (NetworkManager or wpa_supplicant)
%endif

# Provide the package name that Ubuntu uses for it too...
Provides:       %{ubuntu_name} = %{version}-%{release}
Provides:       %{ubuntu_name}%{?_isa} = %{version}-%{release}

%description
netplan reads network configuration from /etc/nplan/*.yaml which are written by administrators,
installers, cloud image instantiations, or other OS deployments. During early boot, it generates
backend specific configuration files in /run to hand off control of devices to a particular
networking daemon.

Currently supported backends are systemd-networkd and NetworkManager.


%prep
%autosetup -p1

# Drop -Werror to avoid the following error:
# /usr/include/glib-2.0/glib/glib-autocleanups.h:28:3: error: 'ip_str' may be used uninitialized in this function [-Werror=maybe-uninitialized]
sed -e "s/-Werror//g" -i Makefile


%build
%make_build CFLAGS="%{optflags}"


%install
%make_install ROOTPREFIX=%{_prefix}

# Pre-create the config directory
mkdir -p %{buildroot}%{_sysconfdir}/%{name}


%check
make check


%files
%license COPYING
%doc debian/changelog
%doc %{_docdir}/%{name}/
%{_sbindir}/%{name}
%{_datadir}/%{name}/
%{_unitdir}/%{name}*.service
%{_systemdgeneratordir}/%{name}
%{_mandir}/man5/%{name}.5*
%dir %{_sysconfdir}/%{name}
%{_prefix}/lib/%{name}/
%{_datadir}/bash-completion/completions/%{name}


%changelog
* Tue Mar 13 2018 Neal Gompa <ngompa13@gmail.com> - 0.34-0.1
- Update to 0.34

* Wed Mar  7 2018 Neal Gompa <ngompa13@gmail.com> - 0.33-0.1
- Rebase to 0.33

* Sat Nov  4 2017 Neal Gompa <ngompa13@gmail.com> - 0.30-1
- Rebase to 0.30

* Sun Jul  2 2017 Neal Gompa <ngompa13@gmail.com> - 0.23~17.04.1-1
- Initial packaging
