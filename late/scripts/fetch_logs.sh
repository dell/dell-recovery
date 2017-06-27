#! /bin/sh
################################################################################
#
# Get the OS installation failed logs by USB key
# After running the script, it will store the logs into the target folder (OSLogs)
#
#
################################################################################
#save the /cdrom mount property
MOUNT_PROPERTY=$(mount | sed '/\/cdrom/!d; s,.* (,,; s,),,;')
export MOUNT_PROPERTY

# Execute CLEANUP-SCRIPT if we exit for any reason (abnormally)
trap ". /usr/share/dell/scripts/CLEANUP-SCRIPT" TERM INT HUP EXIT QUIT

dump_MFG()
{
    ESP=""
    BD=""
    BDD=""
    # check to see if it's already mounted, if not mount it
    readlink /dev/disk/by-label/OS | grep "sd"
    if [ $? -eq 0 ]; then
      BD=`readlink /dev/disk/by-label/OS | cut -c7-9`
      drive="/dev/${BD}1"
      BDD="/dev/${BD}"
      echo "Find boot disk ${drive}"
    else
      readlink /dev/disk/by-label/OS | grep "mmc"
      if [ $? -eq 0 ]; then
        BD=`readlink /dev/disk/by-label/OS | cut -c7-13`
        drive="/dev/${BD}p1"
        BDD="/dev/${BD}"
        log "Find boot disk ${drive}"
        echo "Find boot disk ${drive}"
      else
        readlink /dev/disk/by-label/OS | grep "nvme"
        if [ $? -eq 0 ]; then
          BD=`readlink /dev/disk/by-label/OS | cut -c7-13`
          drive="/dev/${BD}p1"
          BDD="/dev/${BD}"
          echo "Find boot disk ${drive}"
        else
          echo "Fail to find boot disk !!!"
          return 255
        fi
      fi
    fi
    mount | grep -iqs "$drive"
    if [ $? -gt 0 ]; then
      echo "Mounting EFI System Partition"
      if [ ! -d /mnt/efi ]; then
        mkdir /mnt/efi
      fi
      mount $drive /mnt/efi
      ESP="/mnt/efi"
    else
      ESP=`mount | grep -is "$drive" | cut -d" " -f3`
    fi
    ##################################################################
    if [ "$ESP" = "" ]; then
      echo "Unable to find EFI System Partition which holds MFGMEDIA"
    fi
    # this code will account for case sensitivity of MFGMEDIA path
    MFGMEDIA=`ls ${ESP} | grep -i "MFGMEDIA"`
    if [ "$MFGMEDIA" = "" ]; then
      echo "Missing MFGMEDIA folder from EFI System Partition"
    else
      # copy the file
      cp -rf ${ESP}/${MFGMEDIA} ./
      if [ $? -gt 0 ]; then
        echo "Failed to copy MFGMEDIA"
        return 255
      else
        mfglog="MFGMEDIA/"
      fi
      sync
    fi
}

#find the usb key mount point
usb_part=`mount | grep "/cdrom" | cut -d ' ' -f 1`
if [ $? -ne 0 ]; then
    echo "Can't find the USB key!!"
	exit 1
fi
#make the USB key partition write acess
mount -o remount,rw /cdrom
#create the target folder to save logs
#clear the previous
if [ -d /cdrom/OSLogs ];then
    rm -rf /cdrom/OSLogs
fi
mkdir /cdrom/OSLogs

linux_part=`fdisk -l | grep "Linux filesystem" | cut -d ' ' -f 1`
#check the mount partition
if [ -z $linux_part ];then
    #store the disk layout info
    lsblk > /cdrom/OSLogs/disk_part
    echo "This disk has not parted yet!!"
	exit 1
fi
#mount the partition
mount | grep "/mnt" 2>/dev/null
if [ $? -ne 0 ];then
    mount $linux_part /mnt
fi
#copy the FI logs if installation happens during FI
mfglog=''
if [ -x /dell/fist/tal ]; then
    dump_MFG
fi

#copy the logs into usb target folder
if [ -d /mnt/var/log ];then
#    cp -r /mnt/var/log/ /cdrom/OSLogs
    # create a dmesg.log file to record the dmesg info
    touch dmesg.log 2>&1
    chattr +a dmesg.log
    dmesg >> dmesg.log
    tar -zcf "/cdrom/OSLogs/ubuntu.log.tar.gz" /mnt/var/log/ dmesg.log $mfglog 2>/dev/null
    if [ $? -eq 0 ];then
        echo "Finish copying the OS installation logs!"
    fi
else
    echo "/var/log dir doesn't exist!" > /cdrom/OSLogs/error_message
	exit 1
fi
# reset traps, as we are now exiting normally
trap - TERM INT HUP EXIT QUIT
#Clean up the environment
. /usr/share/dell/scripts/CLEANUP-SCRIPT

