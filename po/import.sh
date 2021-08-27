#!/bin/sh
FILE=launchpad-export.tar.gz
if [ -n "$1" ]; then
    if echo "$1" | grep "launchpadlibrarian.net" 2>/dev/null; then
        wget "$1" -O $FILE
    else
        FILE="$1"
    fi
fi
if [ ! -f "$FILE" ]; then
	echo "Missing file: $FILE"
	exit 1
fi
tar xzzf "$FILE"
mv dell-recovery/*.po .
rm -rf dell-recovery
for x in dell-recovery-*.po ;
do
    echo "$x" ;
    mv "$x" "${x#dell-recovery-}" ;
done
