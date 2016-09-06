#! /bin/sh 
################################################################################
#
# Get the OS installation failed logs by USB key
# After running the script, it will store the logs into the target folder (OSLogs)
# 
#
################################################################################
#find the usb key mount point
usb_part=`mount | grep "/cdrom" | cut -d ' ' -f 1`
if [ $? -ne 0 ]; then
    echo "Can't find the USB key"
	exit 1
fi
#save the /cdrom mount property
mount_property = $(mount | sed '/\/cdrom/!d; s,.* (,,; s,),,;')
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
    #revert the mount points
    mount -o remount,$mount_property /cdrom
	exit 0
fi
#mount the partition
mount | grep "/mnt" 2>/dev/null
if [ $? -ne 0 ];then
    mount $linux_part /mnt
fi
#copy the logs into usb target folder
if [ -d /mnt/var/log ];then
#    cp -r /mnt/var/log/ /cdrom/OSLogs
    tar -zcf "/cdrom/OSLogs/ubuntu.log.tar.gz" /mnt/var/log/ 2>/dev/null	  
    if [ $? -eq 0 ];then
        echo "Finish copying the OS installation logs!"
    fi	
else
    echo "/var/log dir doesn't exist!" > /cdrom/OSLogs/error_message
fi 
#revert the mount points
umount /mnt
mount -o remount,$mount_property /cdrom
