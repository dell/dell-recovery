#!/bin/bash
#
#       <run_chroot>
#
#       Individually launches each postinstall (chroot) script
#       Both Python (.py) and Shell (.sh) scripts are supported
#       Scripts are launched in this order:
#        > fish
#        > os-post
#
#       Copyright 2008-2010 Dell Inc.
#           Mario Limonciello <Mario_Limonciello@Dell.com>
#           Hatim Amro <Hatim_Amro@Dell.com>
#           Michael E Brown <Michael_E_Brown@Dell.com>
#
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.

. /usr/share/dell/scripts/fifuncs ""

set -x
set -e

trap 'echo Command FAILED: $i' ERR

echo "in $0"

[ -f /cdrom/superhalt.flg ] && touch /tmp/superhalt.flg

IFHALT "Chroot-scripts execution start..."
for d in /cdrom/scripts/chroot-scripts/fish /isodevice/scripts/chroot-scripts/fish /usr/share/dell/scripts/non-negotiable /cdrom/scripts/chroot-scripts/os-post
do
    if [ -d "$d" ]; then
        IFHALT "Executing Scripts in DIR: $d"
        for i in $(find $d -type f -executable | sort);
        do
            echo "running chroot script: $i"  > /dev/tty12
            IFHALT "$i"
            # ext=`echo $i | sed 's/^.*\.//'`
            echo "${i//^.*\.//}"
            $i
        done
    fi
done
IFHALT "Done with chroot scripts"
