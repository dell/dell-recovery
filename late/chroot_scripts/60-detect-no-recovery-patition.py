#!/usr/bin/env python3

import glob
import json
from os.path import basename
import os
import subprocess as cmd
import shutil

devices = []

for name in glob.glob('/sys/block/*'):
    name = basename(name)
    if name.startswith('sd'):
        devices.append(name)
    elif name.startswith('md'):
        devices.append(name)
    elif name.startswith('nvme'):
        devices.append(name)
    elif name.startswith('pmem'):
        devices.append(name)

root = cmd.check_output("findmnt -M / -o source -v | tail -n1", shell=True)
root = basename(root.decode().strip())
root_device = ''

cdrom = cmd.check_output("findmnt -M /cdrom -o source -v | tail -n1", shell=True)
cdrom = basename(cdrom.decode().strip())
cdrom_device = ''

disks = json.loads(cmd.check_output("lsblk -fs -J", shell=True).decode())
disks = disks['blockdevices']

for disk in disks:
    if disk['name'] == root:
        data = json.dumps(disk)
        for device in devices:
            if device in data:
                root_device = device
                break
    elif disk['name'] == cdrom:
        data = json.dumps(disk)
        for device in devices:
            if device in data:
                cdrom_device = device
                break

if root_device == cdrom_device:
    exit(0)

print('No recovery partition is detected.')

os.makedirs('/dell/debs')

for folder in ('/cdrom/pool', '/cdrom/debs'):
    for deb in glob.glob(f'{folder}/**/*.deb', recursive=True):
        shutil.copy(deb, f'/dell/debs')
