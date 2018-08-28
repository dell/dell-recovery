#! /usr/bin/env python3
#
# Copyright (C) 2015 Canonical Limited
# Author: Shih-Yuan Lee (FourDollars) <sylee@canonical.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import math, os, re, subprocess, sys, threading

from gettext import gettext as _
from gettext import textdomain

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, Gdk, Gtk

if os.getgid() == 0:
    sys.stdout = open('/var/log/wodim-iso.log', 'w', encoding='utf-8')

class Wodim:
    def __init__(self, device, iso):
        self.device = device
        self.iso = iso

    def get_minimum_speed(self):
        command = ['wodim', 'dev=' + self.device, '-prcap']
        output = subprocess.check_output(command, stderr=subprocess.STDOUT).decode('utf-8')
        # Write speed # 0:  5540 kB/s CLV/PCAV (CD  31x, DVD  4x)
        # Write speed # 1:  2770 kB/s CLV/PCAV (CD  15x, DVD  2x)
        speedpat = re.compile(r'(.*)DVD(\s+)(\d+)x')
        speed = None
        for line in output.splitlines():
            if line.startswith('  Write speed'):
                m = speedpat.match(line)
                speed = m.group(3)

        if not speed:
            return speed

        speed = math.floor(float(speed))
        return str(speed)

    def media_type(self):
        # Profile: 0x0012 (DVD-RAM)
        # Profile: 0x002B (DVD+R/DL)
        # Profile: 0x001B (DVD+R)
        # Profile: 0x001A (DVD+RW)
        # Profile: 0x0016 (DVD-R/DL layer jump recording)
        # Profile: 0x0015 (DVD-R/DL sequential recording)
        # Profile: 0x0014 (DVD-RW sequential recording)
        # Profile: 0x0013 (DVD-RW restricted overwrite)
        # Profile: 0x0011 (DVD-R sequential recording)
        # Profile: 0x0010 (DVD-ROM)
        # Profile: 0x000A (CD-RW)
        # Profile: 0x0009 (CD-R)
        # Profile: 0x0008 (CD-ROM)
        # Profile: 0x0002 (Removable disk)
        command = ['wodim', 'dev=' + self.device, 'driveropts=help', '-checkdrive', '-v']
        output = subprocess.check_output(command, stderr=subprocess.STDOUT).decode('utf-8')
        # Current: 0x0014 (DVD-RW sequential recording)
        typepat = re.compile(r'(.*)\(([^\s\)]+)')
        for line in output.splitlines():
            if line.startswith('Current:'):
                m = typepat.match(line)
                if m.group(2) == 'Reserved/Unknown':
                    return None
                else:
                    return m.group(2)

    def is_burnfree(self):
        command = ['wodim', 'dev=' + self.device, 'driveropts=help', '-checkdrive', '-v']
        output = subprocess.check_output(command, stderr=subprocess.STDOUT).decode('utf-8')
        for line in output.splitlines():
            if line.startswith('burnfree'):
                return True
        return False

    def is_blank(self):
        command = ['dvd+rw-mediainfo', self.device]
        output = subprocess.check_output(command, stderr=subprocess.STDOUT).decode('utf-8')
        for line in output.splitlines():
            if line.startswith(' Disc status:'):
                if line.split()[-1] == 'blank':
                    return True
                else:
                    return False

    def format(self):
        command = ['wodim', 'dev=' + self.device, '-format']
        print('> ' + ' '.join(command))
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True) as process:
            for line in process.stdout:
                print(line.strip())

    def fast_blank(self):
        command = ['wodim', 'dev=' + self.device, 'blank=fast']
        print('> ' + ' '.join(command))
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True) as process:
            for line in process.stdout:
                print(line.strip())

    def force_all_blank(self):
        command = ['wodim', 'dev=' + self.device, 'blank=all', '-force']
        print('> ' + ' '.join(command))
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True) as process:
            for line in process.stdout:
                print(line.strip())

    def burn(self, task=None):
        command = ['wodim', '-v', '-eject', 'dev=' + self.device, 'speed=' + self.get_minimum_speed(), self.iso]
        if self.is_burnfree():
            command.extend(['driveropts=burnfree'])
        print('> ' + ' '.join(command))
        progress = re.compile("Track \d+:\s+(?P<current>\d+) of (?P<total>\d+) MB written \(fifo\s+\d+%\) \[buf\s+\d+%\]\s+(?P<speed>[0-9.]+)x.")
        ending = re.compile("Track \d+: Total bytes read/written: (?P<read>\d+)/(?P<write>\d+) \((?P<sector>\d+) sectors\).")
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True) as process:
            for raw in process.stdout:
                line = raw.strip()
                if not line.startswith('Track'):
                    print(line)
                    continue
                if '%' in line:
                    result = progress.match(line)
                    if result:
                        current = int(result.group('current'))
                        total = int(result.group('total'))
                        percentage = current * 100 // total
                        fraction = current / total
                        task.prompt("%d / %d MB (%d%%)" % (current, total, percentage), fraction)
                else:
                    print(line)
                    result = ending.match(line)
                    if result:
                        task.prompt('Burning DVD')

    def eject(self):
        command = ['eject', self.device]
        print('> ' + ' '.join(command))
        subprocess.check_output(command, stderr=subprocess.STDOUT).decode('utf-8')

    def umount(self):
        command = ['umount', self.device]
        print('> ' + ' '.join(command))
        subprocess.check_output(command, stderr=subprocess.STDOUT).decode('utf-8')

class Prompt(Gtk.Window):
    def __init__(self, title):
        Gtk.Window.__init__(self, title=title)
        self.set_border_width(10)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(vbox)
        self.progressbar = Gtk.ProgressBar()
        self.progressbar.pulse()
        self.progressbar.set_show_text(True)
        vbox.pack_start(self.progressbar, True, True, 0)
        self.timeout_id = GObject.timeout_add(50, self.on_timeout, None)
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_deletable(False)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.fraction = 0.0
        self.pulse = True

    def on_timeout(self, user_data):
        if self.pulse:
            self.progressbar.pulse()
        else:
            self.progressbar.set_fraction(self.fraction)
        return True

    def set_text(self, text, fraction):
        Gdk.threads_enter()
        self.progressbar.set_text(text)
        if fraction is None:
            self.pulse = True
        else:
            self.pulse = False
            self.fraction = fraction
        self.show_all()
        Gdk.threads_leave()

textdomain('brasero')

BLANKING_ERROR = _('Error while blanking.')
BURNING_ERROR = _('Error while burning.')
UNKNOWN_ERROR = _('An unknown error occurred')
REPLACE_DISC = _('Do you want to replace the disc and continue?')
REPLACE_DVD_W = _('Please replace the disc with a writable DVD.')
INSERT_DVD_W = _('Please insert a writable DVD.')
NOT_SUPPORTED = _('The disc is not supported')
NO_DISC = _('No disc available')

class DVDBurnTask:

    def __init__(self):
        self._running = True
        self._prompt = Prompt(_('Disc Burner'))

    def terminate(self):
        self._running = False
        Gdk.threads_enter()
        self._prompt.destroy()
        Gdk.threads_leave()
        Gtk.main_quit();

    def question(self, message, text):
        self.hide()
        Gdk.threads_enter()
        dialog = Gtk.MessageDialog(None, 0, Gtk.MessageType.QUESTION, Gtk.ButtonsType.YES_NO, message)
        dialog.format_secondary_text(text)
        response = dialog.run()
        dialog.destroy()
        Gdk.threads_leave()
        if response == Gtk.ResponseType.YES:
            return True
        else:
            return False

    def prompt(self, text, fraction=None):
        self._prompt.set_text(_(text), fraction)

    def hide(self):
        Gdk.threads_enter()
        self._prompt.hide()
        Gdk.threads_leave()

    def run(self):
        if len(sys.argv) != 3 or not sys.argv[1].startswith('/dev/') or not sys.argv[2].endswith('.iso'):
            self.terminate()
            return
        dvd = Wodim(device=sys.argv[1], iso=sys.argv[2])
        while self._running:
            # Get the media type.
            try:
                media_type = dvd.media_type()
            except subprocess.CalledProcessError:
                dvd.umount()
                continue

            # Insert another disc is no media type available.
            if not media_type:
                if not self.question(NO_DISC, INSERT_DVD_W):
                    self.terminate()
                continue

            # Check DVD
            if media_type.startswith('DVD'):
                blank = dvd.is_blank()
                # Blank DVD+RW needs to be formatted at least once.
                if '+RW' in media_type and blank:
                    self.prompt('Formatting disc')
                    try:
                        dvd.format()
                    except subprocess.CalledProcessError:
                        dvd.eject()
                        if not self.question(UNKNOWN_ERROR, REPLACE_DISC):
                            self.terminate()
                # Non-blank DVD-RW needs to be blanked.
                elif '-RW' in media_type and not blank:
                    self.prompt('Disc Blanking')
                    try:
                        dvd.fast_blank()
                    except subprocess.CalledProcessError:
                        try:
                            dvd.force_all_blank()
                        except subprocess.CalledProcessError:
                            dvd.eject()
                            if not self.question(BLANKING_ERROR, REPLACE_DISC):
                                self.terminate()
                # DVD+R and DVD-R need to be blank.
                elif not 'RW' in media_type and not blank:
                    dvd.eject()
                    if not self.question(NOT_SUPPORTED, REPLACE_DVD_W):
                        self.terminate()
                # Burning DVD if everything is ready.
                else:
                    self.prompt('Burning DVD')
                    try:
                        dvd.burn(self)
                    except subprocess.CalledProcessError:
                        if self.question(BURNING_ERROR, REPLACE_DISC):
                            continue
                    self.terminate()
            # CD is not supported.
            elif media_type.startswith('CD'):
                dvd.eject()
                if not self.question(NOT_SUPPORTED, REPLACE_DVD_W):
                    self.terminate()
            # Unknown media type is not supported.
            else:
                dvd.eject()
                if not self.question(NOT_SUPPORTED, REPLACE_DVD_W):
                    self.terminate()

if __name__ == '__main__':
    GObject.threads_init()
    Gdk.threads_init()

    task = DVDBurnTask()
    thread = threading.Thread(target=task.run)
    thread.start()

    Gtk.main()

    thread.join()
