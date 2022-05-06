#!/bin/bash

. /usr/share/dell/scripts/fifuncs ""

export DEBIAN_FRONTEND=noninteractive

IFHALT "Run ubuntu-drivers autoinstall"
echo 'APT::Get::AllowUnauthenticated "true";' > /etc/apt/apt.conf.d/99disable_authentication
for blocklist in $(find /cdrom/scripts/chroot-scripts/blocklist /isodevice/scripts/chroot-scripts/blocklist -type f 2>/dev/null); do
    UBUNTU_DRIVERS_BLOCKLIST="$UBUNTU_DRIVERS_BLOCKLIST $(cat $blocklist)"
done
if [ -n "$UBUNTU_DRIVERS_BLOCKLIST" ]; then
    echo "UBUNTU_DRIVERS_BLOCKLIST: $UBUNTU_DRIVERS_BLOCKLIST"
fi
# Use the i2c device's subsystem ID as the BIOS ID.
BIOSID=$(cut -c 3-6 < "$(dirname "$(find /sys -name modalias -exec echo {} \; -exec cat {} \; | grep bc0Csc05 -B 1 | head -n 1)")/subsystem_device")
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
        if [ -n "$UBUNTU_DRIVERS_BLOCKLIST" ] && echo "$UBUNTU_DRIVERS_BLOCKLIST" | grep "$pkg" >/dev/null 2>&1; then
            echo "Won't install '$pkg' listed in UBUNTU_DRIVERS_BLOCKLIST"
        else
            apt-get install --yes "$pkg"
        fi
    fi
done
rm /etc/apt/apt.conf.d/99disable_authentication
IFHALT "Done with ubuntu-drivers autoinstall"
