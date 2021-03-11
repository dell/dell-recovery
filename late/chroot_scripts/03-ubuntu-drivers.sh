#!/bin/bash

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
BIOSID=$(cut -c 3-6 < /sys/bus/pci/devices/0000:00:00.0/subsystem_device)
for pkg in $(ubuntu-drivers list | awk -F'[ ,]' '{print $1}'); do
    if apt-cache show "$pkg" | grep ^Modaliases | grep -i "sv00001028sd0000$BIOSID" >/dev/null 2>&1; then
        factory="${pkg/oem-somerville/oem-somerville-factory}"
        if dpkg-query -W -f='${Status}\n' "$factory" 2>&1 | grep "install ok installed" >/dev/null 2>&1; then
            echo "$factory has been installed."
        else
            apt-get install --yes "$factory" || true
        fi
    fi
    if dpkg-query -W -f='${Status}\n' "$pkg" 2>&1 | grep "install ok installed" >/dev/null 2>&1; then
        echo "$pkg has been installed."
    else
        if [ -n "$UBUNTU_DRIVERS_BLACKLIST" ] && echo "$UBUNTU_DRIVERS_BLACKLIST" | grep "$pkg" >/dev/null 2>&1; then
            echo "Won't install '$pkg' listed in UBUNTU_DRIVERS_BLACKLIST"
        else
            apt-get install --yes "$pkg"
        fi
    fi
done
rm /etc/apt/apt.conf.d/99disable_authentication
IFHALT "Done with ubuntu-drivers autoinstall"
