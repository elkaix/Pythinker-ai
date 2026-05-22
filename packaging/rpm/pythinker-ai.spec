# RPM spec for the Pythinker CLI (PyInstaller-frozen bundle).
#
# Built by packaging/rpm/build-rpm.sh, which:
#   1. Pre-stages a PyInstaller --onedir bundle into %{_builddir}.
#   2. Invokes rpmbuild with this spec.
#
# %{version} and %{rpm_arch} are passed via --define on the command line.

%global pkgname     pythinker-ai
%global appname     pythinker
%global libdir      /usr/lib/pythinker

# Skip auto-strip / auto-debuginfo for the frozen bundle (PyInstaller binaries
# already contain stripped CPython; auto-strip can corrupt the bootloader).
%define __strip /bin/true
%define debug_package %{nil}
%global __os_install_post %{nil}

Name:           %{pkgname}
Version:        %{rpm_version}
Release:        1%{?dist}
Summary:        Tiny async agent framework with chat channels, memory, MCP, and an OpenAI-compatible API
License:        MIT
URL:            https://github.com/mohamed-elkholy95/Pythinker
BuildArch:      %{rpm_arch}

%description
Pythinker is a Python, asyncio-native agent runtime that runs one assistant
across many chat platforms and APIs. This RPM ships a self-contained
PyInstaller bundle of the pythinker CLI; no system Python is required.

%prep
# build-rpm.sh has already populated %{_builddir}/bundle with the PyInstaller
# output, so %prep is a no-op.

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}%{libdir}
mkdir -p %{buildroot}%{_bindir}
cp -a %{_builddir}/bundle/. %{buildroot}%{libdir}/

cat >%{buildroot}%{_bindir}/%{appname} <<'LAUNCH'
#!/bin/sh
exec /usr/lib/pythinker/pythinker "$@"
LAUNCH
chmod 0755 %{buildroot}%{_bindir}/%{appname}

%files
%{libdir}
%{_bindir}/%{appname}

%changelog
* Fri May 22 2026 Mohamed Elkholy <moelkholy1995@gmail.com> - 2.7.0-1
- Initial RPM packaging of the PyInstaller-frozen pythinker CLI.
