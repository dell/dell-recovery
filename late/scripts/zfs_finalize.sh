#!/bin/sh
set -x

if [ -z "$TARGET" ]; then
    export TARGET="/target"
fi

move_user () {
       target="$1"
       user="$2"
       userhome="$3"
       uuid="$4"

       echo "I: Creating user $user with home $userhome"
       mv "${target}/${userhome}" "${target}/tmp/home/${user}"
       zfs create "rpool/USERDATA/${user}_${uuid}" -o canmount=on -o mountpoint=${userhome}
       chown $(chroot "${target}" id -u ${user}):$(chroot ${target} id -g ${user}) "${target}/${userhome}"
       rsync -a "${target}/tmp/home/${user}/" "${target}/${userhome}"
       bootfsdataset=$(grep "\s${target}\s" /proc/mounts | awk '{ print $1 }')
       zfs set com.ubuntu.zsys:bootfs-datasets="${bootfsdataset}" rpool/USERDATA/${user}_${UUID_ORIG}
}

# Handle userdata
UUID_ORIG=$(head -100 /dev/urandom | tr -dc 'a-z0-9' |head -c6)
mkdir -p "${TARGET}/tmp/home"

move_user "${TARGET}" root /root "${UUID_ORIG}"

echo "I: Changing sync mode of rpool to standard"
zfs set sync=standard rpool
