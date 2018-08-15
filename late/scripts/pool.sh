#!/bin/sh
#
#       <pool.sh>
#
#       Builds a pool from important stuff in /cdrom
#       * Expects to be called as root w/ /cdrom referring to our stuff
#
#       Copyright 2010 Dell Inc.
#           Mario Limonciello <Mario_Limonciello@Dell.com>
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
# vim:ts=8:sw=8:et:tw=0

[ -d /cdrom/debs -o -d /isodevice/debs ]

#Persistent mode has a tendency to break the dynamic apt cache
if grep -q persistent /proc/cmdline 2>/dev/null; then
    rm -f /etc/apt/sources.list.d/dell.list
fi

#This allows things that aren't signed to be installed
if [ ! -f /etc/apt/apt.conf.d/00AllowUnauthenticated ]; then
    cat > /etc/apt/apt.conf.d/00AllowUnauthenticated << EOF
APT::Get::AllowUnauthenticated "true";
Aptitude::CmdLine::Ignore-Trust-Violations "true";
Acquire::AllowInsecureRepositories "true";
EOF
fi

#Prevents apt-get from complaining about unmounting and mounting the hard disk
if [ ! -f /etc/apt/apt.conf.d/00NoMountCDROM ]; then
    cat > /etc/apt/apt.conf.d/00NoMountCDROM << EOF
APT::CDROM::NoMount "true";
Acquire::cdrom 
{
    mount "/cdrom";
    "/cdrom/" 
    {
        Mount  "true";
        UMount "true";
    };
    AutoDetect "false";
};
EOF
fi

if [ ! -f /etc/apt/sources.list.d/dell.list ]; then
    #extra sources need to be disabled for this
    if find /etc/apt/sources.list.d/ -type f | grep sources.list.d; then
        mkdir -p /etc/apt/sources.list.d.old
        mv /etc/apt/sources.list.d/* /etc/apt/sources.list.d.old
    fi
    #Produce a dynamic list
    for dir in /cdrom/debs /isodevice/debs;
    do
        if [ -d "$dir" ]; then
            cd $dir
            apt-ftparchive packages ../../$dir | sed "s/^Filename:\ ..\//Filename:\ .\//" >> /Packages
        fi
    done
    if [ -f /Packages ]; then
        echo "deb file:/ /" > /etc/apt/sources.list.d/dell.list
    fi

    #add the static list to our file
    apt-cdrom -m add
    if grep "^deb cdrom" /etc/apt/sources.list >> /etc/apt/sources.list.d/dell.list; then
        sed -i "/^deb\ cdrom/d" /etc/apt/sources.list
    fi

    #fill up the cache
    mv /etc/apt/sources.list /etc/apt/sources.list.ubuntu
    touch /etc/apt/sources.list
    apt-get update

fi

if [ "$1" = "cleanup" ]; then
    #cleanup
    #if /etc/apt/sources.list has contained the regional mirror site, it is better to use it.
    if grep -v "^#" /etc/apt/sources.list | grep archive.ubuntu.com >/dev/null 2>&1; then
        rm -f /etc/apt/sources.list.ubuntu
        # Ensure Canonical's 'partner' repository enabled.
        sed -i 's/# deb \(.*\) partner$/deb \1 partner/g' /etc/apt/sources.list
    else
        mv /etc/apt/sources.list.ubuntu /etc/apt/sources.list
    fi
    rm -f /Packages /etc/apt/apt.conf.d/00AllowUnauthenticated /etc/apt/apt.conf.d/00NoMountCDROM
    rm -f /etc/apt/sources.list.d/dell.list
    if [ -d /etc/apt/sources.list.d.old ]; then
        mv /etc/apt/sources.list.d.old/* /etc/apt/sources.list.d
        rm -rf /etc/apt/sources.list.d.old
    fi
fi
