#!/bin/sh
#
#       <20-initramfs>
#
#       Rerun update-initramfs for any changes from added packages or logical
#       partition support that was added.
#
#       Copyright 2010 Dell Inc.
#           Crag Wang <Crag.Wang@dell.com>
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

IFHALT "Rerun initramfs update"
for device in $(dmsetup info --target crypt -c -o blkdevs_used --noheadings); do
	if cryptsetup isLuks /dev/$device ; then
		ln -s /usr/share/dell/scripts-initramfs/dell-initramfs /usr/share/initramfs-tools/hooks/dell-initramfs
		/usr/sbin/update-initramfs -u -k all
		break
	fi
done
IFHALT "Done with initramfs update"
