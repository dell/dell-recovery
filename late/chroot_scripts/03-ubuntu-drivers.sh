#!/bin/sh

. /usr/share/dell/scripts/fifuncs ""

export DEBIAN_FRONTEND=noninteractive

IFHALT "Run ubuntu-drivers autoinstall"
echo 'APT::Get::AllowUnauthenticated "true";' > /etc/apt/apt.conf.d/99disable_authentication
for blacklist in $(find /cdrom/scripts/chroot-scripts/blacklist /isodevice/scripts/chroot-scripts/blacklist -type f 2>/dev/null); do
    UBUNTU_DRIVERS_BLACKLIST="$UBUNTU_DRIVERS_BLACKLIST $(cat $blacklist)"
done
if [ -n "$UBUNTU_DRIVERS_BLACKLIST" ]; then
    echo "UBUNTU_DRIVERS_BLACKLIST: $UBUNTU_DRIVERS_BLACKLIST"
fi
for pkg in `ubuntu-drivers list`; do
    if dpkg-query -W $pkg >/dev/null 2>&1; then
        echo "$pkg has been installed."
    else
        if [ -n "$UBUNTU_DRIVERS_BLACKLIST" ] && echo "$UBUNTU_DRIVERS_BLACKLIST" | grep $pkg >/dev/null 2>&1; then
            echo "Won't install '$pkg' listed in UBUNTU_DRIVERS_BLACKLIST"
        else
            apt-get install --yes $pkg
        fi
    fi
done

#install meta package based upon BIOS ID
BIOS_ID=$(dmidecode -t 11 | sed '/ 1\[/!d; s,.* 1\[,,; s,\],,' | tr A-Z a-z)
SERIES=$(lsb_release -cs)
for pkg in dell-$BIOS_ID-meta dell-$BIOS_ID-$SERIES-meta; do
    if ! dpkg-query -W $pkg >/dev/null 2>&1; then
        apt-get install --yes $pkg || true
    fi
done

rm /etc/apt/apt.conf.d/99disable_authentication
IFHALT "Done with ubuntu-drivers autoinstall"
