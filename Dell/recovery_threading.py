#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# «recovery_threading» - Threading classes for use to report progress
#
# Copyright (C) 2009-2010, Dell Inc.
#           (C) 2008 Canonical Ltd.
#
# Author:
#  - Mario Limonciello <Mario_Limonciello@Dell.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this application; if not, write to the Free Software Foundation, Inc., 51
# Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
##################################################################################
from threading import Thread, Event
import logging
import os
import sys

if sys.version_info.major >= 3:
    if sys.version_info.minor >= 10:
        def callable(obj):
            import collections
            return isinstance(obj, collections.abc.Callable)
    else:
        def callable(obj):
            import collections
            return isinstance(obj, collections.Callable)

#--------------------------------------------------------------------#
#Borrowed from USB-Creator initially
class ProgressBySize(Thread):
    """Used for emitting progress for subcalls that don't nicely use stdout'"""
    def __init__(self, input_str, device, to_write):
        Thread.__init__(self)
        self._stopevent = Event()
        self.str = input_str
        self.device = device
        self.scale = 100
        self.start_value = 0
        self.reset_write(to_write)

    def reset_write(self, to_write):
        """Resets the amount to be written counter"""
        self.to_write = to_write
        statvfs = os.statvfs(self.device)
        self.start_free = statvfs.f_bsize * statvfs.f_bavail

    def set_scale_factor(self, factor):
        """"Sets a floating point scaling factor (0-100)"""
        if factor > 100 or factor < 0:
            self.scale = 100
        else:
            self.scale = factor

    def set_starting_value(self, value):
        """Sets the initial value for the progress bar (0-100)"""
        if value > 100 or value < 0:
            self.start_value = 0
        else:
            self.start_value = value

    def progress(self, input_str, percent):
        """Function intended to be overridden to the correct external function
        """
        pass

    def run(self):
        """Runs the thread"""
        try:
            while not self._stopevent.isSet():
                statvfs = os.statvfs(self.device)
                free = statvfs.f_bsize * statvfs.f_bavail
                written = self.start_free - free
                veecent = self.start_value + int((written / float(self.to_write)) * self.scale)
                if callable(self.progress):
                    self.progress(self.str, veecent)
                self._stopevent.wait(2)
        except Exception:
            logging.exception('Could not update progress:')

    def join(self, timeout=None):
        """Stops the thread"""
        self._stopevent.set()
        Thread.join(self, timeout)

class ProgressByPulse(Thread):
    """Used for emitting the thought of progress for subcalls that don't show
       anything'"""
    def __init__(self, input_str):
        Thread.__init__(self)
        self._stopevent = Event()
        self.str = input_str

    def progress(self, input_str, percent):
        """Function intended to be overridden to the correct external function
        """
        pass

    def run(self):
        """Runs the thread"""
        try:
            while not self._stopevent.isSet():
                if callable(self.progress):
                    self.progress(self.str, "-1")
                self._stopevent.wait(.5)
        except Exception:
            logging.exception('Could not update progress:')

    def join(self, timeout=None):
        """Stops the thread"""
        self._stopevent.set()
        Thread.join(self, timeout)

#--------------------------------------------------------------------#
