#!/bin/sh

# Disable hibernate (S4) if RAM >= 4GB. (LP: #1284474)

for i in $(dmidecode -t 17 | grep Size | cut -d ':' -f 2 | cut -d ' ' -f 2); do
    memsize=$((${memsize:-0} + i))
done

if [ ${memsize:-0} -ge 4096 ]; then
    if dpkg-query -W manage-hibernate >/dev/null 2>&1; then
        apt-get --yes purge manage-hibernate
    fi
fi

# vim:fileencodings=utf-8:expandtab:tabstop=4:shiftwidth=4:softtabstop=4
