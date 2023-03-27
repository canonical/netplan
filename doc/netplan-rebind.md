---
title: netplan-rebind
section: 8
author:
- Danilo Egea Gondolfo (danilo.egea.gondolfo@canonical.com)
...

## NAME

netplan-rebind - rebind SR-IOV virtual functions to their driver

## SYNOPSIS

  **netplan** [--debug] **rebind** -h | --help

  **netplan** [--debug] **rebind** [netdevs]

## DESCRIPTION

**netplan rebind [netdevs]** rebinds SR-IOV virtual functions of given physical functions to their driver.

## OPTIONS

  -h, --help
:   Print basic help.

  --debug
:   Print debugging output during the process.

  netdevs
:   Space separated list of PF interface names.

## SEE ALSO

  **netplan**(5), **netplan-set**(8), **netplan-apply**(8)
