#!/usr/bin/env python3

from os.path import basename
import apt
import glob
import json
import os
import subprocess as cmd

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

cdrom = cmd.check_output("findmnt -M /cdrom -o source -v | tail -n1",
                         shell=True)
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


def check_depends(pkg_name, depends):
    if pkg_name not in cache:
        return

    pkg = cache[pkg_name]

    if not pkg.has_versions:
        return

    depends_list = pkg.version_list[0].depends_list

    if not depends_list:
        return

    if 'Depends' in depends_list:
        for dep in depends_list['Depends']:
            pkg_name = dep[0].all_targets()[0].parent_pkg.name
            pkg = cache[pkg_name]
            if pkg_name not in depends \
                    and not pkg.current_ver \
                    and pkg.has_versions \
                    and pkg.version_list[0].downloadable:
                depends.append(pkg_name)


cache = apt.apt_pkg.Cache()
langs = ("ca", "cs", "da", "de", "en", "en_US", "es", "eu", "fr", "gl", "it",
         "hu", "nl", "pl", "pt", "pt_BR", "sl", "fi", "sv", "el", "bg", "ru",
         "ko", "zh-hans", "zh-hant", "ja")
depends = []

for lang in langs:
    pkgs = cmd.check_output('check-language-support'
                            + ' --show-installed'
                            + ' -l ' + lang,
                            shell=True)
    pkgs = pkgs.decode('utf-8').strip().split(' ')
    for pkg_name in pkgs:
        pkg = cache[pkg_name]
        if pkg_name not in depends \
                and not pkg.current_ver \
                and pkg.has_versions \
                and pkg.version_list[0].downloadable:
            depends.append(pkg_name)

pre_len = len(depends)

while True:
    for dep in depends.copy():
        check_depends(dep, depends)
    if len(depends) != pre_len:
        pre_len = len(depends)
    else:
        break

os.makedirs('/dell/debs')
os.chdir('/dell/debs')
cmd.check_output('apt-get download --allow-unauthenticated '
                 + ' '.join(depends), shell=True)
