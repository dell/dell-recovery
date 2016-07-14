#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# update the image md5sum during FI process

from Dell.recovery_common import regenerate_md5sum
import os

#get the mount point
mntdir = os.getcwd().split('/scripts')[0]

#update the md5sum.txt
try:
    regenerate_md5sum(os.path.join(mntdir, 'md5sum.txt'))
except Exception:
    pass
