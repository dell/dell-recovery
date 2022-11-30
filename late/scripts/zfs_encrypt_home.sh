#!/bin/sh
set -eu

if [ -z "$TARGET" ]; then
    export TARGET="/target"
fi

echo "I: setup zfs encryption for user home directory"
# pam_zfs_key

# systemd
mkdir -p $TARGET/lib/systemd/system/user-runtime-dir@.service.d
cat > $TARGET/lib/systemd/system/user-runtime-dir@.service.d/zfs-unload-encryption.conf <<'EOF'
[Service]
ExecStop=/usr/sbin/zfs-unload-encryption %i
EOF

# script - unmount
cat > $TARGET/usr/sbin/zfs-unload-encryption <<'EOF'
#!/bin/bash
set -eu

[ $1 -lt 1000 ] && exit 0
username="$(id -nu $1)"
userhome="$(getent passwd $1 | cut -d: -f6)"
ds_name=$(findmnt -n -M $userhome -o source)

[ "$ds_name" != "" ] || exit 1
echo "zfs: dataset '$ds_name' found for '$username'"

ds_mounted="$(zfs get mounted -o value -H $ds_name)"
[ "$ds_mounted" == "yes" ] || exit 1
zfs unmount $ds_name
echo "zfs: '$ds_name' unmounted"

ds_keystatus="$(zfs get keystatus -o value -H $ds_name)"
[ "$ds_keystatus" == "available" ] || exit 1
zfs unload-key $ds_name
echo "zfs: '$ds_name' key unloaded"
EOF
chmod +x $TARGET/usr/sbin/zfs-unload-encryption

