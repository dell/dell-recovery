#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# «dell-bootstrap» - Ubiquity plugin for Dell Factory Process
#
# Copyright (C) 2010-2014, Dell Inc.
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
################################################################################

from ubiquity.plugin import InstallPlugin, Plugin, PluginUI
from ubiquity import misc
from threading import Thread
import time
from Dell.recovery_threading import ProgressBySize
import debconf
import Dell.recovery_common as magic
from Dell.recovery_xml import BTOxml
import os
import re
import shutil
import dbus
from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)
import glob
import zipfile
import tarfile
import gi
gi.require_version('UDisks', '2.0')
from gi.repository import GLib, UDisks

NAME = 'dell-bootstrap'
BEFORE = 'language'
WEIGHT = 12
OEM = False

#Partition Definitions
EFI_ESP_PARTITION       =     '1'
EFI_RP_PARTITION        =     '2'
EFI_OS_PARTITION        =     '3'
EFI_SWAP_PARTITION      =     '4'

#Continually Reused ubiquity templates
RECOVERY_TYPE_QUESTION =  'dell-recovery/recovery_type'

no_options = GLib.Variant('a{sv}', {})

#######################
# Noninteractive Page #
#######################
class PageNoninteractive(PluginUI):
    """Non-Interactive frontend for the dell-bootstrap ubiquity plugin"""
    def __init__(self, controller, *args, **kwargs):
        self.controller = controller
        PluginUI.__init__(self, controller, *args, **kwargs)

    def get_type(self):
        '''For the noninteractive frontend, get_type always returns an empty str
            This is because the noninteractive frontend always runs in "factory"
            mode, which expects such a str""'''
        return ""

    def set_type(self, value, stage):
        """Empty skeleton function for the non-interactive UI"""
        pass

    def show_dialog(self, which, data = None):
        """Empty skeleton function for the non-interactive UI"""
        pass

    def get_selected_device(self):
        """Empty skeleton function for the non-interactive UI"""
        pass

    def populate_devices(self, devices):
        """Empty skeleton function for the non-interactive UI"""
        pass

    def set_advanced(self, item, value):
        """Empty skeleton function for the non-interactive UI"""
        pass

############
# GTK Page #
############
class PageGtk(PluginUI):
    """GTK frontend for the dell-bootstrap ubiquity plugin"""
    #OK, so we're not "really" a language page
    #We are just cheating a little bit to make sure our widgets are translated
    plugin_is_language = True

    def __init__(self, controller, *args, **kwargs):
        self.plugin_widgets = None

        oem = 'UBIQUITY_OEM_USER_CONFIG' in os.environ

        self.efi = False
        with misc.raised_privileges():
            self.genuine = magic.check_vendor()

        if not oem:
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk
            builder = Gtk.Builder()
            builder.add_from_file('/usr/share/ubiquity/gtk/stepDellBootstrap.ui')
            builder.connect_signals(self)
            self.controller = controller
            self.controller.add_builder(builder)
            self.plugin_widgets = builder.get_object('stepDellBootstrap')
            self.automated_recovery = builder.get_object('automated_recovery')
            self.automated_recovery_box = builder.get_object('automated_recovery_box')
            self.automated_combobox = builder.get_object('hard_drive_combobox')
            self.interactive_recovery = builder.get_object('interactive_recovery')
            self.interactive_recovery_box = builder.get_object('interactive_recovery_box')
            self.hdd_recovery = builder.get_object('hdd_recovery')
            self.hdd_recovery_box = builder.get_object('hdd_recovery_box')
            self.hidden_radio = builder.get_object('hidden_radio')
            self.info_box = builder.get_object('info_box')
            self.info_spinner = Gtk.Spinner()
            builder.get_object('info_spinner_box').add(self.info_spinner)
            self.restart_box = builder.get_object('restart_box')
            self.err_dialog = builder.get_object('err_dialog')
            self.log_dialog = builder.get_object('log_dialog')

            #advanced page widgets
            icon = builder.get_object('dell_image')
            icon.set_tooltip_markup("Dell Recovery Advanced Options")
            self.advanced_page = builder.get_object('advanced_window')
            self.version_detail = builder.get_object('version_detail')
            self.mount_detail = builder.get_object('mountpoint_detail')
            self.memory_detail = builder.get_object('memory_detail')

            if not (self.genuine and 'UBIQUITY_AUTOMATIC' in os.environ):
                builder.get_object('error_box').show()
            PluginUI.__init__(self, controller, *args, **kwargs)

    def plugin_get_current_page(self):
        """Called when ubiquity tries to realize this page.
           * Disable the progress bar
           * Check whether we are on genuine hardware
        """
        #are we real?
        if not (self.genuine and 'UBIQUITY_AUTOMATIC' in os.environ):
            self.interactive_recovery_box.hide()
            self.automated_recovery_box.hide()
            self.automated_recovery.set_sensitive(False)
            self.interactive_recovery.set_sensitive(False)
            self.controller.allow_go_forward(False)
        self.toggle_progress()

        return self.plugin_widgets

    def toggle_progress(self):
        """Toggles the progress bar for RP build"""
        if 'UBIQUITY_AUTOMATIC' in os.environ and \
                            hasattr(self.controller, 'toggle_progress_section'):
            self.controller.toggle_progress_section()

    def get_type(self):
        """Returns the type of recovery to do from GUI"""
        if self.automated_recovery.get_active():
            return "automatic"
        elif self.interactive_recovery.get_active():
            return "interactive"
        else:
            return ""

    def get_selected_device(self):
        """Returns the selected device from the GUI"""
        device = size = ''
        model = self.automated_combobox.get_model()
        iterator = self.automated_combobox.get_active_iter()
        if iterator is not None:
            device = model.get_value(iterator, 0)
            size = model.get_value(iterator, 1)
        return (device, size)

    def set_type(self, value, stage):
        """Sets the type of recovery to do in GUI"""
        if not self.genuine:
            return
        self.hidden_radio.set_active(True)

        if value == "automatic":
            self.automated_recovery.set_active(True)
        elif value == "interactive":
            self.interactive_recovery.set_active(True)
        elif value == "factory":
            if stage == 2:
                self.plugin_widgets.hide()
        else:
            self.controller.allow_go_forward(False)
            if value == "hdd":
                self.hdd_recovery_box.show()
                self.interactive_recovery_box.hide()
                self.automated_recovery_box.hide()
                self.interactive_recovery.set_sensitive(False)
                self.automated_recovery.set_sensitive(False)

    def toggle_type(self, widget):
        """Allows the user to go forward after they've made a selection'"""
        self.controller.allow_go_forward(True)
        self.automated_combobox.set_sensitive(self.automated_recovery.get_active())

    def show_dialog(self, which, data = None):
        """Shows a dialog"""
        if which == "info":
            self.controller._wizard.quit.set_label(
                         self.controller.get_string('ubiquity/imported/cancel'))
            self.controller.allow_go_forward(False)
            self.automated_recovery_box.hide()
            self.interactive_recovery_box.hide()
            self.info_box.show_all()
            self.info_spinner.start()
            self.toggle_progress()
        elif which == "forward":
            self.automated_recovery_box.hide()
            self.interactive_recovery_box.hide()
            self.toggle_progress()
        else:
            self.info_spinner.stop()
            if which == "exception":
                self.err_dialog.format_secondary_text(str(data))
                self.err_dialog.run()
                self.err_dialog.hide()
                return

    def populate_devices(self, devices):
        """Feeds a selection of devices into the GUI
           devices should be an array of 3 column arrays
        """
        #populate the devices
        liststore = self.automated_combobox.get_model()
        for device in devices:
            liststore.append(device)

        #default to the first item active (it should be sorted anyway)
        self.automated_combobox.set_active(0)

    ##                      ##
    ## Advanced GUI options ##
    ##                      ##
    def toggle_advanced(self, widget, data = None):
        """Shows the advanced page"""
        self.plugin_widgets.set_sensitive(False)
        self.advanced_page.run()
        self.advanced_page.hide()
        self.plugin_widgets.set_sensitive(True)

    def collect_logs(self, widget, data = None):
        """click to collect the installation logs when install OS failed"""
        log_script_path = "/usr/share/dell/scripts/fetch_logs.sh"
        if os.path.exists(log_script_path):
            respond = misc.execute_root('sh',log_script_path)
            if respond is True:
                self.log_dialog.run()
                self.log_dialog.hide()
                return
            else:
                data = magic.fetch_output(["tail", "/var/log/syslog" ,"-n" "5"])
                self.err_dialog.format_secondary_text(str(data))
                self.err_dialog.run()
                self.err_dialog.hide()
                return

    def set_advanced(self, item, value):
        """Populates the options that should be on the advanced page"""

        if item == 'efi' and value:
            self.efi = True
        elif item == "mem" and value:
            self.memory_detail.set_markup("Total Memory: %f GB" % value)
        elif item == "version":
            self.version_detail.set_markup("Version: %s" % value)
        elif item == "mount":
            self.mount_detail.set_markup("Mounted From: %s" % value)
        else:
            if type(value) is bool:
                if value:
                    value = 'true'
                else:
                    value = 'false'

################
# Debconf Page #
################
class Page(Plugin):
    """Debconf driven page for the dell-bootstrap ubiquity plugin"""
    def __init__(self, frontend, db=None, ui=None):
        self.device = None
        self.device_size = 0
        self.efi = False
        self.preseed_config = ''
        self.rp_builder = None
        self.disk_size = None
        self.stage = 1
        Plugin.__init__(self, frontend, db, ui)

    def log(self, error):
        """Outputs a debugging string to /var/log/installer/debug"""
        self.debug("%s: %s" % (NAME, error))

    def delete_swap(self):
        """Disables any swap partitions in use"""
        udisks = UDisks.Client.new_sync(None)
        manager = udisks.get_object_manager()
        for item in manager.get_objects():
            swap = item.get_swapspace()
            if not swap:
                continue

            part = item.get_partition()
            if not part:
                continue

            #Check if the swap is active or not
            swap_active = swap.get_cached_property("Active").get_boolean()
            if not swap_active:
                continue

            block = item.get_block()
            if not block:
                continue

            device = block.get_cached_property('Device').get_bytestring().decode('utf-8')

            swap.call_stop_sync(no_options)

            # Only delete the swap partitions on the target
            if device.startswith(self.device):
                part.call_delete_sync(no_options)

    def sleep_network(self):
        """Requests the network be disabled for the duration of install to
           prevent conflicts"""
        bus = dbus.SystemBus()
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        try:
            backend_iface = dbus.Interface(bus.get_object(magic.DBUS_BUS_NAME, '/RecoveryMedia'), magic.DBUS_INTERFACE_NAME)
            backend_iface.force_network(False)
            backend_iface.request_exit()
        except Exception:
            pass

    def test_swap(self):
        """Tests whether to do a swap fixup"""
        import lsb_release
        release = lsb_release.get_distro_information()

        #starting with 17.04, we replace the whole swap partition to swap file
        if float(release["RELEASE"]) >= 17.04:
            try:
                self.db.set('partman-swapfile/percentage', '50')
                self.db.set('partman-swapfile/size', self.mem * 2048)
            except debconf.DebconfError as err:
                self.log(str(err))
            return True

        if (self.mem >= 32 or self.disk_size <= 64):
            return True
        else:
            return False

    def clean_recipe(self):
        """Cleans up the recipe to remove swap if we have a small drive"""

        if self.test_swap():
            self.log("Performing swap recipe fixup (hdd: %i, mem: %f)" % \
                                        (self.disk_size, self.mem))
            try:
                recipe = self.db.get('partman-auto/expert_recipe')
                self.db.set('partman-auto/expert_recipe',
                                     ' . '.join(recipe.split('.')[0:-2])+' .')
            except debconf.DebconfError as err:
                self.log(str(err))

    def remove_extra_partitions(self):
        """Removes partitions we are installing on for the process to start"""
       #check for small disks.
       #on small disks or big mem, don't look for extended or delete swap.
        swap_part = EFI_SWAP_PARTITION
        os_part = EFI_OS_PARTITION

       # check dual boot or not
        try:
            if self.db.get('dell-recovery/dual_boot') == 'true':
           ##dual boot get the partition number of OS and swap
                os_label = self.db.get('dell-recovery/os_partition')
                os_part,swap_part = self.dual_partition_num(os_label)
        except debconf.DebconfError as err:
            self.log(str(err))

        if self.test_swap():
            swap_part = ''
       #remove extras
        for number in (os_part,swap_part):
            if number.isdigit():
                remove = misc.execute_root('parted', '-s', self.device, 'rm', number)
                if remove is False:
                    self.log("Error removing partition number: %s on %s (this may be normal)'" % (number, self.device))
                refresh = misc.execute_root('partx', '-d', '--nr', number, self.device)
                if refresh is False:
                    self.log("Error updating partition %s for kernel device %s (this may be normal)'" % (number, self.device))

    def dual_partition_num(self,label):
       #remove UBUNTU patition for dual boot
       ##OS num
        os_part = ''
        swap_part = ''
        digits = re.compile('\d+')
        try:
            os_path = magic.fetch_output(['readlink','/dev/disk/by-label/'+label]).split('\n')
        except Exception as err:
            # compatible with DUALSYS partition label when boot from hdd
            os_path = magic.fetch_output(['readlink','/dev/disk/by-label/UBUNTU']).split('\n')
            if not os_path:
                self.log('os_path command is executed failed, the error is %s'%str(err))
        os_part = digits.search(os_path[0].split('/')[-1]).group()

        with misc.raised_privileges():
            partitions = magic.fetch_output(['parted','-s',self.device,'print']).split('\n')
            for line in partitions:
                if 'linux-swap' in line:
                    swap_part = line.split()[0]

        return os_part,swap_part

    def explode_sdr(self):
        '''Explodes all content explicitly defined in an SDR
           If no SDR was found, don't change drive at all
        '''
        sdr_file = glob.glob(magic.CDROM_MOUNT + "/*SDR")
        if not sdr_file:
            sdr_file = glob.glob(magic.ISO_MOUNT + "/*SDR")
        if not sdr_file:
            return

        #RP Needs to be writable no matter what
        if not os.path.exists(magic.ISO_MOUNT):
            cd_mount = misc.execute_root('mount', '-o', 'remount,rw', magic.CDROM_MOUNT)
            if cd_mount is False:
                raise RuntimeError("Error remounting RP to explode SDR.")

        #Parse SDR
        srv_list = []
        dest = ''
        with open(sdr_file[0], 'r') as rfd:
            sdr_lines = rfd.readlines()
        for line in sdr_lines:
            if line.startswith('SI'):
                columns = line.split()
                if len(columns) > 2:
                    #always assume lower case (in case case sensitive FS)
                    srv_list.append(columns[2].lower())
            if line.startswith('HW'):
                columns = line.split()
                if len(columns) > 2 and columns[1] == 'destination':
                    dest = columns[2]

        #Explode SRVs that match SDR
        for srv in srv_list:
            fname = os.path.join(os.path.join(magic.CDROM_MOUNT, 'srv', '%s' % srv))
            if os.path.exists('%s.tgz' % fname):
                archive = tarfile.open('%s.tgz' % fname)
            elif os.path.exists('%s.zip' % fname):
                archive = zipfile.ZipFile('%s.zip' % fname)
            else:
                self.log("Skipping SRV %s. No file on filesystem." % srv)
                continue
            with misc.raised_privileges():
                self.log("Extracting SRV %s onto filesystem" % srv)
                archive.extractall(path=magic.CDROM_MOUNT)
            archive.close()

        #if the destination is somewhere special, change the language
        if dest:
            self.preseed('dell-recovery/destination', dest)
        if dest == 'CN':
            self.preseed('debian-installer/locale', 'zh_CN.UTF-8')
            self.ui.controller.translate('zh_CN.UTF-8')

    def usb_boot_preseeds(self, more_keys=None):
        """Sets/unsets preseeds that are common to a USB boot scenario.
           This can either happen if booted from USB stick while in stage 2
           or if booted from USB stick in stage 1 and choosing to only restore
           the linux partition
        """
        keys = ['ubiquity/poweroff', 'ubiquity/reboot']
        if more_keys:
            keys += more_keys
        for key in keys:
            self.db.fset(key, 'seen', 'false')
            self.db.set(key, '')
        self.db.set('ubiquity/partman-skip-unmount', 'false')
        self.db.set('partman/filter_mounted', 'true')

    def unset_drive_preseeds(self):
        """Unsets any preseeds that are related to setting a drive"""
        keys = [ 'partman-auto/init_automatically_partition',
                 'partman-auto/disk',
                 'partman-auto/expert_recipe',
                 'partman-basicfilesystems/no_swap',
                 'grub-installer/only_debian',
                 'grub-installer/with_other_os',
                 'grub-installer/bootdev',
                 'grub-installer/make_active',
                 'oem-config/early_command',
                 'oem-config/late_command']
        self.usb_boot_preseeds(keys)

    def fixup_recovery_devices(self):
        """Discovers the first hard disk to install to"""
        disks = []
        udisks = UDisks.Client.new_sync(None)
        manager = udisks.get_object_manager()
        drive = None

        raids = {}
        for item in manager.get_objects():
            mdraid = item.get_mdraid()
            if mdraid:
                level = mdraid.get_cached_property("Level").get_string()
                if level in ('raid0', 'raid1', 'raid4', 'raid5', 'raid6', 'raid10'):
                    uuid = mdraid.get_cached_property("UUID").get_string()
                    raids[uuid] = level.upper()

        for item in manager.get_objects():
            loop = item.get_loop()
            block = item.get_block()
            partition = item.get_partition()

            if loop or \
               partition or \
               not block or \
               block.get_cached_property("ReadOnly").get_boolean():
                continue

            id_type = block.get_cached_property("IdType").get_string()
            if id_type == 'isw_raid_member':
                continue

            device_path = block.get_cached_property("Device").get_bytestring().decode('utf-8')

            # Check if the disk is the type of dmraid
            if device_path.startswith('/dev/dm'):
                output = block.get_cached_property("Id").get_string()
                model = output.split("-")[-1]
                # device_path = os.path.join("/dev/mapper",model)
                dmraid_dev_size = block.get_cached_property("Size").unpack()
                disks.append([device_path, dmraid_dev_size, "%s (%s)" % (model, device_path)])
                continue

            # Check if the disk is the type of mdraid
            elif device_path.startswith('/dev/md'):
                if block.get_cached_property('Size').get_uint64() == int(0):
                    continue
                name = block.get_cached_property("PreferredDevice").get_bytestring().decode('utf-8').split("/")[-1]
                uuid = block.get_cached_property("Id").get_string().split("-")[-1]
                size = block.get_cached_property("Size").unpack()
                model = "%s %s %i GB" % (name, raids[uuid], size / 1000000000)
                disks.append([device_path, size, "%s (%s)" % (model, device_path)])
                continue

            # Check if the disk is the type of NVME SSD
            elif device_path.startswith('/dev/nvme'):
                output = block.get_cached_property("Id").get_string()
                model = output.split("-")[-1].replace("_", " ")
                nvme_dev_size = block.get_cached_property("Size").unpack()
                disks.append([device_path, nvme_dev_size, "%s (%s)" % (model, device_path)])
                continue

            # Support Persistent Memory storage
            elif device_path.startswith('/dev/pmem'):
                pmem_dev_size = block.get_cached_property("Size").unpack()
                model = 'Persistent Memory %i GB' % (pmem_dev_size / 1000000000)
                disks.append([device_path, pmem_dev_size, "%s (%s)" % (model, device_path)])
                continue

            drive_obj = block.get_cached_property("Drive").get_string()
            if drive_obj == '/':
                continue

            drive = udisks.get_object(drive_obj).get_drive()
            if drive:
                bus = drive.get_cached_property("ConnectionBus").get_string()
                if bus == 'usb':
                    continue
                elif bus == 'sdio':
                    media = drive.get_cached_property("Media").get_string()
                    if not media:
                        continue
            else:
                continue

            devicesize = drive.get_cached_property("Size").unpack()
            if devicesize == 0:
                continue

            devicefile = block.get_cached_property("Device").get_bytestring().decode('utf-8')
            devicemodel = drive.get_cached_property("Model").get_string()
            devicevendor = drive.get_cached_property("Vendor").get_string()
            devicesize_gb = "%i" % (devicesize / 1000000000)

            disks.append([devicefile, devicesize, "%s GB %s %s (%s)" % (devicesize_gb, devicevendor, devicemodel, devicefile)])

        if len(disks) == 0:
            raise RuntimeError("Unable to find and candidate hard disks to install to.")

        # Search for the recovery partition on the same disk first
        the_same_disk = None
        for disk in disks:
            device = disk[0]
            with open('/proc/mounts', 'r') as mounts:
                for line in mounts.readlines():
                    if device in line:
                        self.device = device
                        the_same_disk = disk
                        break
            if the_same_disk:
                break
        if the_same_disk:
            disks.remove(the_same_disk)
            disks.insert(0, the_same_disk)
        else:
            disks.sort()
            self.device = disks[0][0]

        #If multiple candidates were found, record in the logs
        if len(disks) > 1:
            self.log("Multiple disk candidates were found: %s" % disks)

        self.log("Initially selected candidate disk: %s" % self.device)

        #populate UI
        self.ui.populate_devices(disks)

    def fixup_factory_devices(self, rec_part):
        """Find the factory recovery partition, and re-adjust preseeds to use that data"""
        #Ignore any EDD settings - we want to just plop on the same drive with
        #the right FS label (which will be valid right now)
        #Don't you dare put a USB stick in the system with that label right now!

        self.device = rec_part["slave"]

        if os.path.exists(magic.ISO_MOUNT):
            location = magic.ISO_MOUNT
        else:
            location = magic.CDROM_MOUNT

        early = '/usr/share/dell/scripts/oem_config.sh early %s' % location
        self.db.set('oem-config/early_command', early)
        self.db.set('partman-auto/disk', self.device)

        #EFI install finds ESP
        self.db.set('grub-installer/bootdev', self.device)

        # install GRUB if it's dmraid installation
        if self.device.startswith("/dev/dm"):
            grub_command = 'debconf-set partman-auto/disk %s' % magic.transfer_dmraid_path(self.device)
            self.db.set('partman/early_command', grub_command)

        self.disk_size = rec_part["size_gb"]

        self.log("Detected device we are operating on is %s" % self.device)
        self.log("Detected a %s filesystem on the %s recovery partition" % (rec_part["fs"], rec_part["label"]))

    def prepare(self, unfiltered=False):
        """Prepare the Debconf portion of the plugin and gather all data"""
        #version
        with misc.raised_privileges():
            version = magic.check_version()
        self.log("version %s" % version)

        #mountpoint
        mount = find_boot_device()
        self.log("mounted from %s" % mount)

        #recovery type
        rec_type = None
        try:
            rec_type = self.db.get(RECOVERY_TYPE_QUESTION)
        except debconf.DebconfError as err:
            self.log(str(err))
            rec_type = 'dynamic'
            self.db.register('debian-installer/dummy', RECOVERY_TYPE_QUESTION)
            self.db.set(RECOVERY_TYPE_QUESTION, rec_type)

        #If we were preseeded to dynamic, look for an RP
        rec_part = magic.find_factory_partition_stats()
        if "slave" in rec_part:
            self.stage = 2
        if rec_type == 'dynamic':
            # we rebooted with no USB stick or DVD in drive and have the RP
            # mounted at /cdrom
            if self.stage == 2 and rec_part["slave"] in mount:
                self.log("Detected RP at %s, setting to factory boot" % mount)
                rec_type = 'factory'
            # check if the mount point is dmraid
            elif mount.startswith("/dev/dm") and self.stage == 2 and rec_part["slave"][:-1] in mount:
                self.log("Detected RP at %s, setting to factory boot" % mount)
                rec_type = 'factory'
            # check if the mount point is mdraid
            elif mount.startswith("/dev/md") and self.stage == 2 and rec_part["slave"][:-1] in mount:
                self.log("Detected RP at %s, setting to factory boot" % mount)
                rec_type = 'factory'
            # check if the mount point is Persistent Memory
            elif mount.startswith("/dev/pmem") and self.stage == 2 and rec_part["slave"][:-1] in mount:
                self.log("Detected RP at %s, setting to factory boot" % mount)
                rec_type = 'factory'
            else:
                self.log("No (matching) RP found.  Assuming media based boot")
                rec_type = 'dvd'

        #Media boots should be interrupted at first screen in --automatic mode
        if rec_type == 'factory':
            self.db.fset(RECOVERY_TYPE_QUESTION, 'seen', 'true')
        else:
            self.db.set(RECOVERY_TYPE_QUESTION, '')
            self.db.fset(RECOVERY_TYPE_QUESTION, 'seen', 'false')

        #If we detect that we are booted into uEFI mode, then we only want
        #to do a GPT install.
        if os.path.isdir('/proc/efi') or os.path.isdir('/sys/firmware/efi'):
            self.efi = True

        #Amount of memory in the system
        self.mem = 0
        if os.path.exists('/sys/firmware/memmap'):
            for root, dirs, files in os.walk('/sys/firmware/memmap', topdown=False):
                if os.path.exists(os.path.join(root, 'type')):
                    with open(os.path.join(root, 'type')) as rfd:
                        type = rfd.readline().strip('\n')
                    if type != "System RAM":
                        continue
                    with open(os.path.join(root, 'start')) as rfd:
                        start = int(rfd.readline().strip('\n'),0)
                    with open(os.path.join(root, 'end')) as rfd:
                        end = int(rfd.readline().strip('\n'),0)
                    self.mem += (end - start + 1)
            self.mem = float(self.mem/1024)
        if self.mem == 0:
            with open('/proc/meminfo','r') as rfd:
                for line in rfd.readlines():
                    if line.startswith('MemTotal'):
                        self.mem = float(line.split()[1].strip())
                        break
        self.mem = round(self.mem/1048575) #in GB

        #Fill in UI data
        twiddle = {"mount": mount,
                   "version": version,
                   "mem": self.mem,
                   "efi": self.efi}
        # The order invoking set_advanced() is important. (LP: #1324394)
        for twaddle in reversed(sorted(twiddle)):
            self.ui.set_advanced(twaddle, twiddle[twaddle])
        self.ui.set_type(rec_type, self.stage)

        #Make sure some locale was set so we can guarantee automatic mode
        try:
            language = self.db.get('debian-installer/locale')
        except debconf.DebconfError:
            language = ''
        if not language:
            language = 'en_US.UTF-8'
            self.preseed('debian-installer/locale', language)
            self.ui.controller.translate(language)

        # If there is a Kylin overlay, set language to zh_CN.UTF-8
        client_type = os.path.join('/cdrom', '.oem', 'client_type')
        if os.path.isfile(client_type):
            with open (client_type, "r") as myfile:
                content=myfile.read().replace('\n', '')
            if content == "kylin":
                language = 'zh_CN.UTF-8'
            self.preseed('debian-installer/locale', language)
            self.ui.controller.translate(language)

        #Clarify which device we're operating on initially in the UI
        try:
            self.fixup_recovery_devices()
            self.log("rec_type %s, stage %d, device %s" % (rec_type, self.stage, self.device))
            if (rec_type == 'factory' and self.stage == 2) or rec_type == 'hdd':
                self.fixup_factory_devices(rec_part)
        except Exception as err:
            self.handle_exception(err)
            self.cancel_handler()

        #force wyse systems to always take minimal mode (18.04+)
        if self.db.get('dell-recovery/wyse_mode') == 'true' or magic.check_family(b"wyse"):
            self.preseed("ubiquity/minimal_install", "true")

        return (['/usr/share/ubiquity/dell-bootstrap'], [RECOVERY_TYPE_QUESTION])

    def ok_handler(self):
        """Copy answers from debconf questions"""
        #basic questions
        rec_type = self.ui.get_type()
        self.log("recovery type set to '%s'" % rec_type)
        self.preseed(RECOVERY_TYPE_QUESTION, rec_type)
        (device, size) = self.ui.get_selected_device()
        if device:
            self.device = device
        if size:
            self.device_size = size
        self.log("selected device %s %d" % (device, size))

        return Plugin.ok_handler(self)

    def report_progress(self, info, percent):
        """Reports to the frontend an update about th progress"""
        self.frontend.debconf_progress_info(info)
        self.frontend.debconf_progress_set(percent)

    def cleanup(self):
        """Do all the real processing for this plugin.
           * This has to be done here because ok_handler won't run in a fully
             automated load, and we need to run all steps in all scenarios
           * Run is the wrong time too because it runs before the user can
             answer potential questions
        """
        rec_type = self.db.get('dell-recovery/recovery_type')

        try:
            # User recovery - need to copy RP
            if rec_type == "automatic" or \
               (rec_type == "factory" and self.stage == 1):

                if not (rec_type == "factory" and self.stage == 1):
                    self.ui.show_dialog("info")
                self.sleep_network()
                self.delete_swap()

                #init progress bar and size thread
                self.frontend.debconf_progress_start(0, 100, "")
                size_thread = ProgressBySize("Copying Files",
                                               "/mnt",
                                               "0")
                size_thread.progress = self.report_progress
                #init builder
                self.rp_builder = RPbuilder(self.device,
                                            self.device_size,
                                            self.mem,
                                            self.efi,
                                            self.preseed_config,
                                            size_thread)
                self.rp_builder.exit = self.exit_ui_loops
                self.rp_builder.status = self.report_progress
                self.rp_builder.start()
                self.enter_ui_loop()
                self.rp_builder.join()
                if self.rp_builder.exception:
                    self.handle_exception(self.rp_builder.exception)
                reboot_machine(None)

            # User recovery - resizing drives
            elif rec_type == "interactive":
                self.ui.show_dialog("forward")
                self.unset_drive_preseeds()

            # Factory install, and booting from RP
            else:
                if 'dell-recovery/recovery_type=hdd' in open('/proc/cmdline', 'r').read().split():
                    self.ui.toggle_progress()
                self.sleep_network()
                self.delete_swap()
                self.clean_recipe()
                self.remove_extra_partitions()
                self.explode_sdr()
        except Exception as err:
            #For interactive types of installs show an error then reboot
            #Otherwise, just reboot the system
            if rec_type == "automatic" or rec_type == "interactive" or \
               ('UBIQUITY_DEBUG' in os.environ and 'UBIQUITY_ONLY' in os.environ):
                self.handle_exception(err)
            self.cancel_handler()

        #translate languages
        self.ui.controller.translate(just_me=False, not_me=True, reget=True)
        Plugin.cleanup(self)

    def cancel_handler(self):
        """Called when we don't want to perform recovery'"""
        if os.path.exists(os.path.join('/cdrom', '.disk', 'info.recovery')) and \
           os.path.exists(os.path.join('/cdrom', '.disk', 'info')) and \
           misc.execute_root('mount', '-o', 'remount,rw', '/cdrom'):
            with misc.raised_privileges():
                os.remove(os.path.join('/cdrom', '.disk', 'info'))
            misc.execute_root('mount', '-o', 'remount,ro', '/cdrom')
        misc.execute_root('reboot')

    def handle_exception(self, err):
        """Handle all exceptions thrown by any part of the application"""
        self.log(str(err))
        self.ui.show_dialog("exception", err)

############################
# RP Builder Worker Thread #
############################
class RPbuilder(Thread):
    """The recovery partition builder worker thread"""
    def __init__(self, device, size, mem, efi, preseed_config, sizing_thread):
        self.device = device
        self.device_size = size
        self.mem = mem
        self.efi = efi
        self.preseed_config = preseed_config
        self.exception = None
        self.file_size_thread = sizing_thread
        self.xml_obj = BTOxml()
        Thread.__init__(self)

    def build_rp(self, cushion=600):
        """Copies content to the recovery partition using a parted wrapper.
           This might be better implemented in python-parted or parted_server/partman,
           but those would require extra dependencies, and are generally more complex
           than necessary for what needs to be accomplished here."""

        black_pattern = re.compile('casper-rw|casper-uuid')

        #Check if we are booted from same device as target
        mounted_device = find_boot_device()
        if self.device in mounted_device:
            raise RuntimeError("Attempting to install to the same device as booted from.\n\
You will need to clear the contents of the recovery partition\n\
manually to proceed.")

        #Calculate RP size
        rp_size = magic.black_tree("size", black_pattern, magic.CDROM_MOUNT)
        #in mbytes
        rp_size_mb = (rp_size / 1000000) + cushion

        # replace the self.device for dmraid if needed
        # sample: /dev/dm-0 --> /dev/mapper/isw*
        if "/dev/dm" in self.device:
            self.device = magic.transfer_dmraid_path(self.device)

        if self.device.startswith('/dev/md') and shutil.which('mdadm'):
            misc.execute_root('mdadm', '--misc', '--action=frozen', self.device)

        # Build new partition table
        command = ('parted', '-s', self.device, 'mklabel', 'gpt')
        result = misc.execute_root(*command)
        if result is False:
            raise RuntimeError("Error creating new partition table on %s" % (self.device))

        self.status("Creating Partitions", 1)
        grub_size = 250
        commands = [('parted', '-a', 'optimal', '-s', self.device, 'mkpart', 'primary', 'fat16', '0', str(grub_size)),
                    ('parted', '-s', self.device, 'name', '1', "'EFI System Partition'"),
                    ('parted', '-s', self.device, 'set', '1', 'boot', 'on')]
        if self.device[-1].isnumeric():
            commands.append(('mkfs.msdos', self.device + 'p' + EFI_ESP_PARTITION))
            rp_part = 'p' + EFI_RP_PARTITION
            esp_part = 'p' + EFI_ESP_PARTITION
        else:
            commands.append(('mkfs.msdos', self.device + EFI_ESP_PARTITION))
            rp_part = EFI_RP_PARTITION
            esp_part = EFI_ESP_PARTITION
        for command in commands:
            #wait for settle
            if command[0] == 'mkfs.msdos':
                while not os.path.exists(command[-1]):
                    time.sleep(1)
            result = misc.execute_root(*command)
            if result is False:
                if self.efi:
                    raise RuntimeError("Error formatting disk.")

        #Build RP
        command = ('parted', '-a', 'optimal', '-s', self.device, 'mkpart', "fat32", "fat32", str(grub_size), str(rp_size_mb + grub_size))
        result = misc.execute_root(*command)
        if result is False:
            raise RuntimeError("Error creating new %s mb recovery partition on %s" % (rp_size_mb, self.device))

        #Build RP filesystem
        self.status("Formatting Partitions", 2)
        command = ('mkfs.msdos', '-n', 'OS', self.device + rp_part)
        while not os.path.exists(command[-1]):
            time.sleep(1)
        result = misc.execute_root(*command)
        if result is False:
            raise RuntimeError("Error creating fat32 filesystem on %s%s" % (self.device, rp_part))

        #Mount RP
        mount = misc.execute_root('mount', self.device + rp_part, '/mnt')
        if mount is False:
            raise RuntimeError("Error mounting %s%s" % (self.device, rp_part))

        #Update status and start the file size thread
        self.file_size_thread.reset_write(rp_size)
        self.file_size_thread.set_scale_factor(85)
        self.file_size_thread.set_starting_value(2)
        self.file_size_thread.start()

        #Copy RP Files
        with misc.raised_privileges():
            if os.path.exists(magic.ISO_MOUNT):
                magic.black_tree("copy", re.compile(".*\.iso$"), magic.ISO_MOUNT, '/mnt')
            magic.black_tree("copy", black_pattern, magic.CDROM_MOUNT, '/mnt')

        self.file_size_thread.join()

        #find uuid of drive
        with misc.raised_privileges():
            blkid = magic.fetch_output(['blkid', self.device + rp_part, "-p", "-o", "udev"]).split('\n')
            for item in blkid:
                if item.startswith('ID_FS_UUID'):
                    uuid = item.split('=')[1]
                    break

        #read in any old seed
        seed = os.path.join('/mnt', 'preseed', 'dell-recovery.seed')
        keys = magic.parse_seed(seed)

        #process the new options
        for item in self.preseed_config.split():
            if '=' in item:
                key, value = item.split('=')
                keys[key] = value

        #write out a dell-recovery.seed configuration file
        with misc.raised_privileges():
            if not os.path.isdir(os.path.join('/mnt', 'preseed')):
                os.makedirs(os.path.join('/mnt', 'preseed'))
            magic.write_seed(seed, keys)

        #Check for a grub.cfg - replace as necessary
        files = {'recovery_partition.cfg': 'grub.cfg',
                }
        for item in files:
            full_path = os.path.join('/mnt', 'factory', files[item])
            if os.path.exists(full_path):
                with misc.raised_privileges():
                    shutil.move(full_path, full_path + '.old')

            with misc.raised_privileges():
                magic.process_conf_file('/usr/share/dell/grub/' + item, \
                                        full_path, uuid, EFI_RP_PARTITION)

        #Install grub
        self.status("Installing GRUB", 88)
        ##If we don't have grub binaries, build them
        grub_files = ['/cdrom/efi/boot/bootx64.efi',
                      '/cdrom/efi/boot/grubx64.efi']

        ##Mount ESP
        mount = misc.execute_root('mount', self.device + esp_part, '/mnt/efi')
        if mount is False:
            raise RuntimeError("Error mounting %s%s" % (self.device, esp_part))

        ##find old entries and prep directory
        direct_path = '/mnt/efi' + '/efi/ubuntu'
        with misc.raised_privileges():
            os.makedirs(direct_path)

            #copy boot loader files
            for item in grub_files:
                if not os.path.exists(item):
                    raise RuntimeError("Error, %s doesn't exist." % item)
                shutil.copy(item, direct_path)

            #find old entries
            bootmgr_output = magic.fetch_output(['efibootmgr', '-v']).split('\n')

            #delete old entries
            for line in bootmgr_output:
                bootnum = ''
                if line.startswith('Boot') and 'ubuntu' in line.lower():
                    bootnum = line.split('Boot')[1].replace('*', '').split()[0]
                if bootnum:
                    bootmgr = misc.execute_root('efibootmgr', '-v', '-b', bootnum, '-B')
                    if bootmgr is False:
                        raise RuntimeError("Error removing old EFI boot manager entries")

        target = 'shimx64.efi'
        with misc.raised_privileges():
            os.rename(os.path.join(direct_path, 'bootx64.efi'),
                      os.path.join(direct_path, target))

        add = misc.execute_root('efibootmgr', '-v', '-c', '-d', self.device, '-p', EFI_ESP_PARTITION, '-l', '\\EFI\\ubuntu\\%s' % target, '-L', 'ubuntu')
        if add is False:
            raise RuntimeError("Error adding efi entry to %s%s" % (self.device, esp_part))

        ##clean up ESP mount
        misc.execute_root('umount', '/mnt/efi')

        #Make changes that would normally be done in factory stage1
        ##rename efi directory so we don't offer it to customer boot in NVRAM menu
        if os.path.exists('/mnt/efi'):
            with misc.raised_privileges():
                shutil.move('/mnt/efi', '/mnt/efi.factory')

        ##set install_in_progress flag
        with misc.raised_privileges():
            if not os.path.exists('/mnt/factory/grub.cfg'):
                build = misc.execute_root('/usr/share/dell/grub/build-factory.sh')
                if build is False:
                    raise RuntimeError("Error building grub cfg.")
                with misc.raised_privileges():
                    magic.white_tree("copy", re.compile('.'), '/var/lib/dell-recovery', '/mnt/factory')
            magic.fetch_output(['grub-editenv', '/mnt/factory/grubenv', 'set', 'install_in_progress=1'])

        #update bto.xml
        path = os.path.join(magic.CDROM_MOUNT, 'bto.xml')
        if os.path.exists(path):
            self.xml_obj.load_bto_xml(path)
        bto_version = self.xml_obj.fetch_node_contents('iso')
        bto_date = self.xml_obj.fetch_node_contents('date')
        with misc.raised_privileges():
            dr_version = magic.check_version('dell-recovery')
            ubi_version = magic.check_version('ubiquity')
            self.xml_obj.replace_node_contents('bootstrap', dr_version)
            self.xml_obj.replace_node_contents('ubiquity' , ubi_version)
            if os.path.exists('/var/log/syslog'):
                with open('/var/log/syslog', 'rb') as rfd:
                    self.xml_obj.replace_node_contents('syslog', rfd.read())
            if os.path.exists('/var/log/installer/debug'):
                with open('/var/log/installer/debug', 'rb') as rfd:
                    self.xml_obj.replace_node_contents('debug', rfd.read())
            if not bto_version:
                self.xml_obj.replace_node_contents('iso', '[native]')
            if not bto_date:
                with open(os.path.join(magic.CDROM_MOUNT, '.disk', 'info')) as rfd:
                    line = rfd.readline().strip()
                date = line.split()[len(line.split())-1]
                self.xml_obj.replace_node_contents('date', date)
            self.xml_obj.write_xml('/mnt/bto.xml')
        misc.execute_root('umount', '/mnt')

        if self.device.startswith('/dev/md') and shutil.which('mdadm'):
            misc.execute_root('mdadm', '--misc', '--action=idle', self.device)

        for count in range(100,0,-10):
            self.status("Restarting in %d seconds." % int(count/10), count)
            time.sleep(1)


    def exit(self):
        """Function to request the builder thread to close"""
        pass

    def status(self, info, percent):
        """Stub function for passing data back up"""
        pass

    def run(self):
        """Start the RP builder thread"""
        try:
            self.build_rp()
        except Exception as err:
            self.exception = err
        self.exit()

####################
# Helper Functions #
####################
def find_boot_device():
    """Finds the device we're booted from'"""
    mounted_device = ''
    with open('/proc/mounts', 'r') as mounts:
        for line in mounts.readlines():
            if magic.ISO_MOUNT in line:
                mounted_device = line.split()[0]
                break
            if magic.CDROM_MOUNT in line:
                found = line.split()[0]
                if not 'loop' in found:
                    mounted_device = line.split()[0]
                    break
    return mounted_device

def reboot_machine(objpath):
    """Reboots the machine"""
    reboot_cmd = '/sbin/reboot'
    reboot = misc.execute_root(reboot_cmd)
    if reboot is False:
        raise RuntimeError("Reboot failed from %s" % str(objpath))

def find_item_iterator(combobox, value, column = 0):
    """Searches a combobox for a value and returns the iterator that matches"""
    model = combobox.get_model()
    iterator = model.get_iter_first()
    while iterator is not None:
        if value == model.get_value(iterator, column):
            break
        iterator = model.iter_next(iterator)
    return iterator

def find_n_set_iterator(combobox, value, column = 0):
    """Searches a combobox for a value, and sets the iterator to that value if
       it's found"""
    iterator = find_item_iterator(combobox, value, column)
    if iterator is not None:
        combobox.set_active_iter(iterator)

###########################################
# Commands Processed During Install class #
###########################################
class Install(InstallPlugin):
    """The install time dell-bootstrap ubiquity plugin"""

    def __init__(self, frontend, db=None, ui=None):
        self.progress = None
        self.target = None
        InstallPlugin.__init__(self, frontend, db, ui)

    def log(self, error):
        """Outputs a debugging string to /var/log/installer/debug"""
        self.debug("%s: %s" % (NAME, error))

    def remove_ricoh_mmc(self):
        '''Removes the ricoh_mmc kernel module which is known to cause problems
           with MDIAGS'''
        lsmod = magic.fetch_output('lsmod').split('\n')
        for line in lsmod:
            if line.startswith('ricoh_mmc'):
                misc.execute('rmmod', line.split()[0])

    def wake_network(self):
        """Wakes the network back up"""
        bus = dbus.SystemBus()
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        try:
            backend_iface = dbus.Interface(bus.get_object(magic.DBUS_BUS_NAME, '/RecoveryMedia'), magic.DBUS_INTERFACE_NAME)
            backend_iface.force_network(True)
            backend_iface.request_exit()
        except Exception:
            pass


    def install(self, target, progress, *args, **kwargs):
        '''This is highly dependent upon being called AFTER configure_apt
        in install.  If that is ever converted into a plugin, we'll
        have some major problems!'''
        with misc.raised_privileges():
            genuine = magic.check_vendor()
            if not genuine:
                raise RuntimeError("This recovery media requires Dell Hardware.")

        self.target = target
        self.progress = progress

        rec_part  = magic.find_partition()

        from ubiquity import install_misc
        to_install = []
        to_remove  = []

        #if we are loop mounted, make sure the chroot knows it too
        if os.path.isdir(magic.ISO_MOUNT):
            os.makedirs(os.path.join(self.target, magic.ISO_MOUNT.lstrip('/')))
            misc.execute_root('mount', '--bind', magic.ISO_MOUNT, os.path.join(self.target, magic.ISO_MOUNT.lstrip('/')))

        #Fixup pool to only accept stuff on /cdrom or /isodevice
        # - This is reverted during SUCCESS_SCRIPT
        # - Might be in livefs already, but we always copy in in case there was an udpate
        pool_cmd = '/usr/share/dell/scripts/pool.sh'
        shutil.copy(pool_cmd, os.path.join(self.target, 'tmp', os.path.basename(pool_cmd)))
        install_misc.chrex(self.target, os.path.join('/tmp', os.path.basename(pool_cmd)))

        #Stuff that is installed on all configs without fish scripts
        to_install += magic.mark_unconditional_debs()

        #install dell-recovery only if there is an RP
        if rec_part:
            #hide the recovery partition as default
            try:
                recovery = magic.find_factory_partition_stats()
                command = ('parted', '-a', 'optimal', '-s', recovery['slave'], 'set', str(recovery['number']), 'msftres', 'on' )
                misc.execute_root(*command)                
            except Exception:
                pass
            
            to_install.append('dell-recovery')
            to_install.append('dell-eula')

            #block os-prober in grub-installer
            os.rename('/usr/bin/os-prober', '/usr/bin/os-prober.real')
            #don't allow OS prober to probe other drives in single OS install
            with open(os.path.join(self.target, 'etc/default/grub'), 'r') as rfd:
                default_grub = rfd.readlines()
            with open(os.path.join(self.target, 'etc/default/grub'), 'w') as wfd:
                found = False
                for line in default_grub:
                    if line.startswith("GRUB_DISABLE_OS_PROBER="):
                        line = "GRUB_DISABLE_OS_PROBER=true\n"
                        found = True
                    wfd.write(line)
                if not found:
                    wfd.write("GRUB_DISABLE_OS_PROBER=true\n")

            #set default recovery_type of 99_dell_recovery grub as 'hdd' for non-Wyse platforms
            recovery_type = 'hdd'
            #if wyse mode is on (dell-recovery/mode == 'wyse'), set the recovery_type to be 'factory'
            #as Wyse platforms will always skip the "Restore OS Linux partition" dialog
            if self.db.get('dell-recovery/wyse_mode') == 'true' or magic.check_family(b"wyse"):
                recovery_type = 'factory'
            #create 99_dell_recovery grub
            magic.create_grub_entries(self.target, recovery_type)

        #for tos
        try:
            destination = progress.get('dell-recovery/destination')
        except debconf.DebconfError:
            destination = ''
        fname = os.path.join(self.target, 'etc', 'default', 'dell-eula')
        if destination and not os.path.exists(fname):
            with open(fname, 'w') as wfd:
                wfd.write('WARRANTY=%s\n' % destination)

        to_install += magic.mark_upgrades()

        self.remove_ricoh_mmc()

        self.wake_network()

        install_misc.record_installed(to_install)
        install_misc.record_removed(to_remove)

        #copy the to_install package list into /tmp as backup to check
        apt_installed = "/var/lib/ubiquity/apt-installed"
        shutil.copy(apt_installed, os.path.join(self.target, 'tmp', os.path.basename(apt_installed)))

        return InstallPlugin.install(self, target, progress, *args, **kwargs)
