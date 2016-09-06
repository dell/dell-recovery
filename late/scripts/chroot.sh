#!/bin/sh
#
#       <chroot.sh>
#
#       Prepares the installed system for entering into postinstall phase
#       Calls the postinatll phase script (run_chroot)
#       Cleans up after postinstall completes
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

set -x
set -e

export TARGET=/target

if [ -d "/isodevice" ]; then
    DEVICE=$(mount | sed -n 's/\ on\ \/isodevice.*//p')
else
    DEVICE=$(mount | sed -n 's/\ on\ \/cdrom.*//p')
fi

export BOOTDEV=${DEVICE%%[0-9]*}
DEVICE=$(mount | sed -n 's/\ on\ \/target.*//p')
export TARGETDEV=${DEVICE%%[0-9]*}

LOG="var/log"
if [ -d "$TARGET/$LOG/installer" ]; then
    LOG="$LOG/installer"
fi
export LOG

if [ -d "$TARGET/$LOG" ]; then
    exec > $TARGET/$LOG/chroot.sh.log 2>&1
    chroot $TARGET chattr +a $LOG/chroot.sh.log
else
    export TARGET=/
    exec > $TARGET/$LOG/chroot.sh.log 2>&1
fi

#for debugging later, show efibootmgr output before we proceed
efibootmgr -v

# Nobulate Here.
# This way if we die early we'll RED Screen
if [ -x /dell/fist/tal ]; then
    /dell/fist/tal nobulate 0
fi

if [ "$1" != "success" ]; then
    . /usr/share/dell/scripts/FAIL-SCRIPT
    exit 1
fi

echo "in $0"

# Execute FAIL-SCRIPT if we exit for any reason (abnormally)
trap ". /usr/share/dell/scripts/FAIL-SCRIPT" TERM INT HUP EXIT QUIT

mount --bind /dev $TARGET/dev
MOUNT_CLEANUP="$TARGET/dev $MOUNT_CLEANUP"
if ! mount | grep "$TARGET/run"; then
    mount --bind /run $TARGET/run
    MOUNT_CLEANUP="$TARGET/run $MOUNT_CLEANUP"
fi
if ! mount | grep "$TARGET/proc"; then
    mount -t proc targetproc $TARGET/proc
    MOUNT_CLEANUP="$TARGET/proc $MOUNT_CLEANUP"
fi
if ! mount | grep "$TARGET/sys"; then
    mount -t sysfs targetsys $TARGET/sys
    MOUNT_CLEANUP="$TARGET/sys $MOUNT_CLEANUP"
fi

if ! mount | grep "$TARGET/cdrom"; then
    mount --bind /cdrom $TARGET/cdrom
    MOUNT_CLEANUP="$TARGET/cdrom $MOUNT_CLEANUP"
fi

if [ ! -L $TARGET/media/cdrom ]; then
    ln -s /cdrom $TARGET/media/cdrom
    DIR_CLEANUP="$TARGET/media/cdrom $DIR_CLEANUP"
fi

#Make sure fifuncs and target_chroot are available
if [ ! -d $TARGET/usr/share/dell/scripts ]; then
    mkdir -p $TARGET/usr/share/dell/scripts
    DIR_CLEANUP="$TARGET/usr/share/dell/scripts $DIR_CLEANUP"
    mount --bind /usr/share/dell/scripts $TARGET/usr/share/dell/scripts
    MOUNT_CLEANUP="$TARGET/usr/share/dell/scripts $MOUNT_CLEANUP"
fi

#If we are loop mounted, this will have been done during the ubiquity
if [ -d /isodevice ]; then
    MOUNT_CLEANUP="$TARGET/isodevice $MOUNT_CLEANUP"
fi
export MOUNT_CLEANUP

#Make sure that WinPE isn't in our menus (happens in uEFI case)
if [ -d /dell/fist ] && ! grep "^GRUB_DISABLE_OS_PROBER" $TARGET/etc/default/grub >/dev/null; then
    echo "GRUB_DISABLE_OS_PROBER=true" >> $TARGET/etc/default/grub
fi

#Run chroot scripts
chroot $TARGET /usr/share/dell/scripts/target_chroot.sh

for mountpoint in $MOUNT_CLEANUP;
do
    umount -l $mountpoint
done
unset MOUNT_CLEANUP

for directory in $DIR_CLEANUP;
do
    rm -rf $directory
done

chroot $TARGET chattr -a $LOG/chroot.sh.log

sync;sync

# reset traps, as we are now exiting normally
trap - TERM INT HUP EXIT QUIT

. /usr/share/dell/scripts/SUCCESS-SCRIPT $BOOT_DEV $BOOT_PART_NUM
