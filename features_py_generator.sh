#!/bin/sh
OUTPUT=netplan/_features.py
INPUT=src/[^_]*.[hc]
echo "# Generated file" > $OUTPUT
echo "NETPLAN_FEATURE_FLAGS = [" >> $OUTPUT
awk 'match ($0, /netplan-feature:.*/ ) { $0=substr($0, RSTART, RLENGTH); print "    \""$2"\"," }' $INPUT >> $OUTPUT
echo "]" >> $OUTPUT
