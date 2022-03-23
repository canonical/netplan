#!/bin/sh
OUTPUT=src/_features.h
INPUT=src/[^_]*.[hc]
printf "#include <stddef.h>\nstatic const char *feature_flags[] __attribute__((__unused__)) = {\n" > $OUTPUT
awk 'match ($0, /netplan-feature:.*/ ) { $0=substr($0, RSTART, RLENGTH); print "\""$2"\"," }' $INPUT >> $OUTPUT
echo "NULL, };" >> $OUTPUT
