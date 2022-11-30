#!/bin/sh -ex
#
#       <encryption_partitioner.sh>
#
#       Creates a simple partition layout
#
#       Copyright 2021 Dell Inc.
#           Crag Wang <crag.wang@dell.com>
#
set -eux

# default variables
disk=$1
zfs=
disk_index_esp=1
disk_index_recovery=2
disk_index_keystore=3
disk_index_boot=4
disk_index_rootfs=5
part_prefix=""
pkg_dependencies='cryptsetup cryptsetup-bin'
target="/target"
target_keystore="/target_keystore"

# adjust variables according to args
if [ "$#" -gt "1" ]; then zfs=$2; fi
if [ -n "$zfs" ]; then pkg_dependencies="$pkg_dependencies zfsutils-linux"; fi

# vfuncs
check_prerequisites() {
    echo "I: Checking system requirements"

    if [ $(id -u) -ne 0 ]; then
        echo "E: Script must be executed as root. Exiting!"
        exit 1
    fi

    for pkg in $@; do
        if ! dpkg-query -W -f'${Status}' "${pkg}"|grep -q "install ok installed" 2>/dev/null; then
            echo "E: $pkg is required and not installed on this system. Exiting!"
            exit 1
        fi
    done
}

do_partition(){
	local part_num=$1
	local part_label=$2
	local part_size=$3
	local part_type=$4
	local part_format=$5
	local disk=$disk
	local part_prefix=${part_prefix}

	printf "do_partition():
			disk=$disk,
			part_num=$part_num,
			part_label=$part_label,
			part_size=$part_size,
			part_type=$part_type,
			part_format=$part_format,
			part_prefix=${part_prefix}
			"
	sgdisk --new=$part_num:0:$part_size \
	       --typecode=$part_num:$part_type \
		   --change-name=$part_num:$part_label \
		   $disk

	partprobe $disk 2>/dev/null || true
	wipefs -a $disk$part_prefix$part_num || true

	case "$part_format" in
		vfat)
			mkfs.vfat -F 32 -n $part_label $disk$part_prefix$part_num
			;;
		ext4)
			mkfs.ext4 -q -L $part_label $disk$part_prefix$part_num
			;;
	esac
}
do_luks(){
	case "$1" in
		rootfs)
			local tmpdir=$(mktemp -d)
			mkdir -p $tmpdir
			mount /dev/mapper/keystore $tmpdir
			#keyfile
			dd if=/dev/urandom bs=1024 count=4 status=none of=$tmpdir/luks-rootfs.keyfile
			chmod u+r,go-rwx $tmpdir/luks-rootfs.keyfile
			#cryptsetup
			cryptsetup luksFormat \
					--key-file=$tmpdir/luks-rootfs.keyfile \
					${disk}${part_prefix}${disk_index_rootfs}
			cryptsetup open \
					--key-file=$tmpdir/luks-rootfs.keyfile \
					${disk}${part_prefix}${disk_index_rootfs} \
					rootfs
			mkfs.ext4 -q -L rootfs /dev/mapper/rootfs
			#cleanup
			umount $tmpdir
			rm -rf $tmpdir
			;;
		keystore)
			#cryptsetup
			local serial_number=$(cat /sys/class/dmi/id/product_serial)
			if [ -z "$serial_number" ]; then
				serial_number=$(cat /sys/class/dmi/id/product_uuid)
			fi

			local tmpdir=$(mktemp -d)
			mkdir -p $tmpdir
			printf $serial_number | openssl dgst -sha256 -binary -out $tmpdir/hwid.key
			cryptsetup luksFormat \
					--key-file=$tmpdir/hwid.key \
					--key-slot=0 \
					${disk}${part_prefix}${disk_index_keystore}
			cryptsetup open \
					--key-file=$tmpdir/hwid.key \
					--key-slot=0 \
					--priority=prefer \
					${disk}${part_prefix}${disk_index_keystore} keystore
			printf $serial_number | cryptsetup luksAddKey \
					--key-file=$tmpdir/hwid.key \
					--key-slot=1 \
					--priority=prefer \
					${disk}${part_prefix}${disk_index_keystore}

			mkfs.ext4 -q -L keystore /dev/mapper/keystore
			rm -rf $tmpdir
			;;
		*)
			printf "skipped..\n"
	esac
}
do_disk_layout() {
	if ! sfdisk -d "${disk}" | grep -iq "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"; then
		do_partition "$disk_index_esp" "ESP" "+128M" "ef00" "vfat"
	fi
	if ! [ -e ${disk}${part_prefix}2 ]; then
		do_partition "$disk_index_recovery" "RECOVERY" "+`expr $(blockdev --getsize64 /dev/cdrom) / 1024 / 1024 + 600`M" "8300" "vfat"
	fi
	do_partition "$disk_index_keystore" "keystore" "+512M" "8300" "ext4"
	do_partition "$disk_index_boot" "boot" "+1024M" "8300" "ext4"
	do_partition "$disk_index_rootfs" "rootfs" "0" "8300" "ext4"
	do_luks "keystore"

	if [ -n "$zfs" ]; then
		printf "doing zfs layout, skip luks encryption for rootfs\n"
		init_zfs
		zfs mount -a
	else
		do_luks "rootfs"
		mkdir -p $target
		mount "/dev/mapper/rootfs" $target
		#crypttab, fstab
		mkdir -p $target/etc
		uuid_rootfs=$(blkid -s UUID -o value -t PARTLABEL=rootfs)
		echo "rootfs UUID=${uuid_rootfs}  none  luks,keyscript=/usr/share/dell/scripts-initramfs/fs-unlock.sh,initramfs" >> "$target/etc/crypttab"
		echo "/dev/mapper/rootfs  /  ext4  errors=remount-ro  0  1" >> "$target/etc/fstab"
	fi
}

fixup_part_prefix(){
	case "${disk}" in
		/dev/sd*|/dev/hd*|/dev/vd*)
			part_prefix=""
			;;
		*)
			part_prefix="p"
	esac
}

only_esp_recovery_survive(){
	for part in $(lsblk -o name -n -l $disk); do
		local num=${part##*[^0-9]}
		case "$num" in
			$disk_index_esp|$disk_index_recovery|'')
				;;
			*)
				sgdisk -d $num $disk
				;;
		esac
	done
}

init_zfs(){
	echo "I: Initializing ZFS"

	# Prepare 6 digits UUID for dataset use
	uuid_orig=$(head -100 /dev/urandom | tr -dc 'a-z0-9' |head -c6)

	# Let udev finish its job before proceeding with zpool creation
	udevadm settle

	# Use stable uuid for partition when available as device name can change
	bpooluuid=$(blkid -s PARTUUID -o value ${disk}${part_prefix}${disk_index_boot})
	partbpool=''
	[ -n "$bpooluuid" -a -e "/dev/disk/by-partuuid/$bpooluuid" ] && partbpool=/dev/disk/by-partuuid/$bpooluuid

	rpooluuid=$(blkid -s PARTUUID -o value ${disk}${part_prefix}${disk_index_rootfs})
	partrpool=''
	[ -n "$rpooluuid" -a -e "/dev/disk/by-partuuid/$rpooluuid" ] && partrpool=/dev/disk/by-partuuid/$rpooluuid

	# rpool
	zpool create -f \
		-o ashift=12 \
		-o autotrim=on \
		-O compression=lz4 \
		-O acltype=posixacl \
		-O xattr=sa \
		-O relatime=on \
		-O normalization=formD \
		-O mountpoint=/ \
		-O canmount=off \
		-O dnodesize=auto \
		-O sync=disabled \
		-O mountpoint=/ -R "${target}" rpool "${partrpool}"

	# bpool
	# The version of bpool is set to the default version to prevent users from upgrading
	# Then only features supported by grub are enabled.
	zpool create -f \
		-o ashift=12 \
		-o autotrim=on \
		-d \
		-o feature@async_destroy=enabled \
		-o feature@bookmarks=enabled \
		-o feature@embedded_data=enabled \
		-o feature@empty_bpobj=enabled \
		-o feature@enabled_txg=enabled \
		-o feature@extensible_dataset=enabled \
		-o feature@filesystem_limits=enabled \
		-o feature@hole_birth=enabled \
		-o feature@large_blocks=enabled \
		-o feature@lz4_compress=enabled \
		-o feature@spacemap_histogram=enabled \
		-O compression=lz4 \
		-O acltype=posixacl \
		-O xattr=sa \
		-O relatime=on \
		-O normalization=formD \
		-O canmount=off \
		-O devices=off \
		-O mountpoint=/boot -R "${target}" bpool "${partbpool}"

	# Root and boot dataset
	zfs create rpool/ROOT -o canmount=off -o mountpoint=none
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}" -o mountpoint=/
	zfs create bpool/BOOT -o canmount=off -o mountpoint=none
	zfs create "bpool/BOOT/ubuntu_${uuid_orig}" -o mountpoint=/boot

	# System dataset
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var" -o canmount=off
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/lib"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/lib/AccountsService"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/lib/apt"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/lib/dpkg"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/lib/NetworkManager"

	# Desktop specific system dataset
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/srv"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/usr" -o canmount=off
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/usr/local"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/games"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/log"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/mail"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/snap"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/spool"
	zfs create "rpool/ROOT/ubuntu_${uuid_orig}/var/www"

	# USERDATA datasets
	# Dataset associated to the user are created by the installer.
	zfs create rpool/USERDATA -o canmount=off -o mountpoint=/

	# Set zsys properties
	zfs set com.ubuntu.zsys:bootfs='yes' "rpool/ROOT/ubuntu_${uuid_orig}"
	zfs set com.ubuntu.zsys:last-used=$(date +%s) "rpool/ROOT/ubuntu_${uuid_orig}"
	zfs set com.ubuntu.zsys:bootfs='no' "rpool/ROOT/ubuntu_${uuid_orig}/srv"
	zfs set com.ubuntu.zsys:bootfs='no' "rpool/ROOT/ubuntu_${uuid_orig}/usr"
	zfs set com.ubuntu.zsys:bootfs='no' "rpool/ROOT/ubuntu_${uuid_orig}/var"
}

# -- main() --
echo "I: Running $(basename "$0")"
check_prerequisites "${pkg_dependencies}"
fixup_part_prefix
only_esp_recovery_survive
do_disk_layout

# prepare boot
mkdir -p "$target/etc"
mkdir -p "$target/boot"
if [ -z "$zfs" ]; then
	mount $disk$part_prefix$disk_index_boot "$target/boot"
fi
uuid_boot=$(blkid -s UUID -o value "$disk$part_prefix$disk_index_boot")
echo "UUID=${uuid_boot}  /boot  ext4  defaults  0  2" >> "$target/etc/fstab"

# prepare efi
mkdir -p "$target/boot/efi"
mount -t vfat "$disk$part_prefix$disk_index_esp" "$target/boot/efi"
uuid_esp=$(blkid -s UUID -o value "$disk$part_prefix$disk_index_esp")
echo "UUID=${uuid_esp}  /boot/efi  vfat  umask=0022,fmask=0022,dmask=0022  0  1" >> "$target/etc/fstab"

# keep some utilities
apt-install tpm2-tools 2>/dev/null

if [ -n "$zfs" ]; then
	# finalize grub directory
	mkdir -p "${target}/boot/grub"
	mkdir -p "${target}/boot/efi/grub"
	mount -o bind "${target}/boot/efi/grub" "${target}/boot/grub"
	# Bind mount grub from ESP to the expected location
	echo "/boot/efi/grub\t/boot/grub\tnone\tdefaults,bind\t0\t0" >> "${target}/etc/fstab"
	# Make /boot/{grub,efi} world readable
	sed -i 's#\(.*boot/efi.*\)umask=0077\(.*\)#\1umask=0022,fmask=0022,dmask=0022\2#' "${target}/etc/fstab"

	apt-install zfsutils-linux 2>/dev/null
	apt-install zfs-initramfs 2>/dev/null
	apt-install zsys 2>/dev/null

	# Activate zfs generator.
	# After enabling the generator we should run zfs set canmount=on DATASET
	# in the chroot for one dataset of each pool to refresh the zfs cache.
	echo "I: Activating zfs generator"
	mkdir -p "${target}/etc/zfs/zed.d"
	ln -s /usr/lib/zfs-linux/zed.d/history_event-zfs-list-cacher.sh "${target}/etc/zfs/zed.d"

	# Create zpool cache
	zpool set cachefile= bpool
	zpool set cachefile= rpool
	cp /etc/zfs/zpool.cache "${target}/etc/zfs/"
	mkdir -p "${target}/etc/zfs/zfs-list.cache"
	touch "${target}/etc/zfs/zfs-list.cache/bpool"
	touch "${target}/etc/zfs/zfs-list.cache/rpool"

	zfs set canmount=noauto bpool/BOOT/ubuntu_${uuid_orig}
	zfs set canmount=noauto rpool/ROOT/ubuntu_${uuid_orig}
fi