#!/bin/sh
BASE=$(dirname $0)
OUTPUT=$BASE/netplan_cli/_features.py
INPUT=$BASE/src/[!_]*.[hc]
echo "# Generated file" > $OUTPUT
echo "NETPLAN_FEATURE_FLAGS = [" >> $OUTPUT
awk 'match ($0, /netplan-feature:.*/ ) { $0=substr($0, RSTART, RLENGTH); print "    \""$2"\"," }' $INPUT >> $OUTPUT
echo "]" >> $OUTPUT
cat $OUTPUT
