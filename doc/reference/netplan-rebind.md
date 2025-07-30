---
title: NETPLAN-REBIND
section: 8
author:
- Danilo Egea Gondolfo (danilo.egea.gondolfo@canonical.com)
...

## NAME

`netplan-rebind` - rebind SR-IOV virtual functions to their driver

## SYNOPSIS

  **`netplan`** \[*--debug*\] **rebind** **-h**|**--help**

  **`netplan`** \[*--debug*\] **rebind** \[*interfaces*\]

## DESCRIPTION

**`netplan rebind [interfaces]`** rebinds SR-IOV virtual functions of given physical functions to their driver.

## OPTIONS

`-h`, `--help`
:    Print basic help.

`--debug`
:   Print debugging output during the process.

`interfaces`
:   Space-separated list of physical-function interface names.

## SEE ALSO

  **`netplan`**(5), **`netplan-set`**(8), **`netplan-apply`**(8)
