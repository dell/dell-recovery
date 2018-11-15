#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# «recovery_common» - Misc Functions and variables that are useful in many areas
#
# Copyright (C) 2009-2010, Dell Inc.
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

import dbus.mainloop.glib
import subprocess
import gi
gi.require_version('UDisks', '2.0')
from gi.repository import GLib, UDisks
import os
import shutil
import re
import tempfile
import glob
import sys
import datetime
import logging
import hashlib
import io
import locale

##                ##
##Common Variables##
##                ##

DBUS_BUS_NAME = 'com.dell.RecoveryMedia'
DBUS_INTERFACE_NAME = 'com.dell.RecoveryMedia'

#For install time
CDROM_MOUNT = '/cdrom'
ISO_MOUNT = '/isodevice'

#Translation Support
DOMAIN = 'dell-recovery'
LOCALEDIR = '/usr/share/locale'

#UI file directory
if os.path.isdir('gtk') and 'DEBUG' in os.environ:
    UIDIR = 'gtk'
else:
    UIDIR = '/usr/share/dell'

#SVG file directory
if os.path.isdir('gtk') and 'DEBUG' in os.environ:
    SVGDIR = 'gtk'
else:
    SVGDIR = '/usr/share/pixmaps'


#Supported burners and their arguments
DVD_BURNERS = { '/usr/share/dell/scripts/wodim-iso.py':['/dev/sr0'] }
USB_BURNERS = { 'usb-creator':['--iso'],
                'usb-creator-gtk':['--iso'],
                'usb-creator-kde':['--iso'] }

RP_LABELS = [ 'dualrcvy', 'recovery', 'install', 'os' ]

##                ##
##Common Functions##
##                ##

def black_tree(action, blacklist, src, dst='', base=None):
    """Recursively ACTIONs files from src to dest only
       when they don't match the blacklist outlined in blacklist"""
    return _tree(action, blacklist, src, dst, base, False)

def white_tree(action, whitelist, src, dst='', base=None):
    """Recursively ACTIONs files from src to dest only
       when they match the whitelist outlined in whitelist"""
    return _tree(action, whitelist, src, dst, base, True)

def _tree(action, list, src, dst, base, white):
    """Helper function for tree calls"""
    from distutils.file_util import copy_file

    if base is None:
        base = src
        if not base.endswith('/'):
            base += '/'

    names = os.listdir(src)

    if action == "copy":
        outputs = []
    elif action == "size":
        outputs = 0

    for n in names:
        src_name = os.path.join(src, n)
        dst_name = os.path.join(dst, n)
        end = src_name.split(base)[1]

        #don't copy symlinks or hardlinks, vfat seems to hate them
        if os.path.islink(src_name):
            continue

        #recurse till we find FILES
        elif os.path.isdir(src_name):
            if action == "copy":
                outputs.extend(
                    _tree(action, list, src_name, dst_name, base, white))
            elif action == "size":
                #add the directory we're in
                outputs += os.path.getsize(src_name)
                #add the files in that directory
                outputs += _tree(action, list, src_name, dst_name, base, white)

        #only copy the file if it matches the list / color
        elif (white and list.search(end)) or not (white or list.search(end)):
            if action == "copy":
                if not os.path.isdir(dst):
                    os.makedirs(dst)
                copy_file(src_name, dst_name, preserve_mode=1,
                          preserve_times=1, update=1, dry_run=0)
                outputs.append(dst_name)

            elif action == "size":
                outputs += os.path.getsize(src_name)

    return outputs

def check_family(test):
    """Checks if a system definitely matches a family"""
    path = '/sys/class/dmi/id/product_family'
    if not os.path.exists(path):
        return False
    with open(path, 'rb') as rfd:
        value = rfd.read().strip()
        if not value:
            return False
        if test.lower() in value.lower():
            return True
    return False

def check_vendor():
    """Checks to make sure that the app is running on Dell HW"""
    path = '/sys/class/dmi/id/'
    variables = ['bios_vendor', 'sys_vendor']
    valid = [b'dell', b'alienware', b'wyse', b'innotek']
    for var in variables:
        target = os.path.join(path, var)
        if os.path.exists(target):
            with open(target, 'rb') as rfd:
                value = rfd.read().strip()
                if not value:
                    return True
                value = value.split()[0].lower()
            if value in valid:
                return True
    return check_rebrand()

def check_rebrand():
    """If on a rebrand system, see if it was originally created
       by Dell"""
    call = subprocess.Popen(['dmidecode', '--type', '11'],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    output = call.communicate()[0].decode()
    if call.returncode != 0:
        print("Unable to run dmidecode:", call.returncode)
        return False
    header = "String 1: "
    for line in output.split('\n'):
        if header in line:
            result = line.split(header)
            if (len(result) > 1):
                result = line.split(header)[1].strip()
                if "Dell System" == result:
                    return True
                else:
                    break
    return False

def check_version(package='dell-recovery'):
    """Queries the package management system for the current tool version"""
    try:
        import apt.cache
        cache = apt.cache.Cache()
        if cache[package].is_installed:
            return cache[package].installed.version
    except Exception as msg:
        print("Error checking %s version: %s" % (package, msg),
              file=sys.stderr)
        return "unknown"

def process_conf_file(original, new, uuid, number, recovery_text='', recovery_type='hdd'):
    """Replaces all instances of a partition, OS, and extra in a conf type file
       Generally used for things that need to touch grub"""
    if not os.path.isdir(os.path.split(new)[0]):
        os.makedirs(os.path.split(new)[0])
    import lsb_release
    release = lsb_release.get_distro_information()

    #starting with 10.10, we replace the whole drive string (/dev/sdX,gptY)
    #earlier releases are hardcoded to (hd0,Y)
    if float(release["RELEASE"]) >= 10.10:
        number = 'gpt' + number

    with open(original, "r") as base:
        with open(new, 'w', encoding='utf-8') as output:
            for line in base.readlines():
                if "#RECOVERY_TEXT#" in line:
                    line = line.replace("#RECOVERY_TEXT#", recovery_text)
                if "#UUID#" in line:
                    line = line.replace("#UUID#", uuid)
                if "#PARTITION#" in line:
                    line = line.replace("#PARTITION#", number)
                if "#OS#" in line:
                    line = line.replace("#OS#", "%s %s" % (release["ID"], release["RELEASE"]))
                if "#REC_TYPE#" in line:
                    line = line.replace("#REC_TYPE#", recovery_type)
                output.write(line)

def fetch_output(cmd, data='', environment=os.environ):
    '''Helper function to just read the output from a command'''
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 stdin=subprocess.PIPE,
                                 env=environment,
                                 universal_newlines=True)
    try:
        (out, err) = proc.communicate(data)
    except UnicodeDecodeError as error:
        if locale.getpreferredencoding() != "UTF-8":
            os.environ["LC_ALL"] = "C.UTF-8"
            locale.setlocale(locale.LC_ALL, '')

        if sys.stdout.encoding != "utf8":
            sys.stdout = io.open(sys.stdout.fileno(), 'w', encoding='utf8')
        if sys.stderr.encoding != "utf8":
            sys.stderr = io.open(sys.stderr.fileno(), 'w', encoding='utf8')
        if sys.stdin.encoding != "utf8":
            sys.stdin = io.open(sys.stdin.fileno(), 'r', encoding='utf8')

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     stdin=subprocess.PIPE,
                                     env=environment,
                                     universal_newlines=True)
        (out, err) = proc.communicate(data)

    if proc.returncode is None:
        proc.wait()
    if proc.returncode != 0:
        error = "Command %s failed with stdout/stderr: %s\n%s" % (cmd, out, err)
        import syslog
        syslog.syslog(error)
        raise RuntimeError(error)
    return out

def find_factory_partition_stats():
    """Uses udisks to find the RP of a system and return stats on it
       Only use this method during bootstrap.
    """
    recovery = {}
    labels = RP_LABELS

    udisks = UDisks.Client.new_sync(None)
    manager = udisks.get_object_manager()
    for label in labels:
        for item in manager.get_objects():
            block = item.get_block()
            if not block:
                continue
            check_label = block.get_cached_property("IdLabel")
            if not check_label:
                continue

            # Only search for the recovery partition on the same disk
            device = block.get_cached_property("Device").get_bytestring().decode('utf-8')
            if device[-1].isnumeric():
                offset = 2
            else: # /dev/sd[a-z]
                offset = 1
            the_same_drive = False
            with open('/proc/mounts', 'r') as mounts:
                for line in mounts.readlines():
                    if device[:-offset] in line:
                        the_same_drive = True
                        break
                    # support dmraid corner case
                    elif line.startswith("/dev/mapper/isw"):
                        if transfer_dmraid_path(device)[:-2] in line:
                            the_same_drive = True
                            break
            if not the_same_drive:
                continue

            if check_label.get_string().lower() == label:
                partition = item.get_partition()
                recovery["label"] = check_label.get_string()
                recovery["device"] = block.get_cached_property("Device").get_bytestring()
                recovery["fs"] = block.get_cached_property("IdType").get_string()
                recovery["drive"] = block.get_cached_property("Drive").get_string()
                recovery["number"] = partition.get_cached_property("Number").unpack()
                recovery["uuid"] = block.get_cached_property("IdUUID").get_string()
        if recovery:
            break

    #find parent slave node, used for dell-bootstrap
    if "device" in recovery:
        for item in manager.get_objects():
            table = item.get_partition_table()
            if not table:
                continue
            block = item.get_block()
            if not block:
                continue
            if block.get_cached_property("Drive").get_string() == recovery["drive"]:
                recovery["slave"] = block.get_cached_property("Device").get_bytestring().decode('utf-8')
                recovery["size_gb"] = block.get_cached_property("Size").unpack() / 1000000000
                break
    return recovery

def find_partition():
    """Searches the system for recovery partitions"""

    recovery = find_factory_partition_stats()
    if 'device' in recovery:
        recovery = recovery['device']
    else:
        recovery = ''
    return recovery

def find_burners():
    """Checks for what utilities are available to burn with"""
    def which(program):
        """Emulates the functionality of the unix which command"""
        def is_exe(fpath):
            """Determines if a filepath is executable"""
            return os.path.exists(fpath) and os.access(fpath, os.X_OK)

        fpath = os.path.split(program)[0]
        if fpath:
            if is_exe(program):
                return program
        else:
            for path in os.environ["PATH"].split(os.pathsep):
                exe_file = os.path.join(path, program)
                if is_exe(exe_file):
                    return exe_file

        return None

    def find_command(array):
        """Determines if a command listed in the array is valid"""
        for item in array:
            path = which(item)
            if path is not None:
                return [path] + array[item]
        return None

    dvd = find_command(DVD_BURNERS)
    usb = find_command(USB_BURNERS)

    #If we have apps for DVD burning, check hardware
    if dvd:
        found_supported_dvdr = False
        valid_media_types=[ 'optical_dvd_plus_r', 'optical_dvd_plus_r_dl',
                            'optical_dvd_plus_rw', 'optical_dvd_r',
                            'optical_dvd_ram', 'optical_dvd_rw' ]
        udisks = UDisks.Client.new_sync(None)
        manager = udisks.get_object_manager()
        for item in manager.get_objects():
            drive = item.get_drive()
            if not drive or not drive.get_cached_property("MediaRemovable"):
                continue
            compatibility = drive.get_cached_property("MediaCompatibility")
            for media in valid_media_types:
                if media in compatibility:
                    found_supported_dvdr = True
                    break
            if found_supported_dvdr:
                break
        if not found_supported_dvdr:
            dvd = None
    return (dvd, usb)

def match_system_device(bus, vendor, device):
    '''Attempts to match the vendor and device combination  on the specified bus
       Allows the following formats:
       base 16 int (eg 0x1234)
       base 16 int in a str (eg '0x1234')
    '''
    def recursive_check_ids(directory, cvendor, cdevice, depth=1):
        """Recurses into a directory to check all files in that directory"""
        vendor = device = ''
        for root, dirs, files in os.walk(directory, topdown=True):
            for fname in files:
                if not vendor and (fname == 'idVendor' or fname == 'vendor'):
                    with open(os.path.join(root, fname), 'r') as filehandle:
                        vendor = filehandle.readline().strip('\n')
                    if len(vendor) > 4 and '0x' not in vendor:
                        vendor = ''
                elif not device and (fname == 'idProduct' or fname == 'device'):
                    with open(os.path.join(root, fname), 'r') as filehandle:
                        device = filehandle.readline().strip('\n')
                    if len(device) > 4 and '0x' not in device:
                        device = ''
            if vendor and device:
                if ( int(vendor, 16) == int(cvendor)) and \
                   ( int(device, 16) == int(cdevice)) :
                    return True
                else:
                    #reset devices so they aren't checked multiple times needlessly
                    vendor = device = ''
            if not files:
                if depth > 0:
                    for directory in [os.path.join(root, d) for d in dirs]:
                        if recursive_check_ids(directory, cvendor, cdevice, depth-1):
                            return True
        return False

    if bus != "usb" and bus != "pci":
        return False

    if type(vendor) == str and '0x' in vendor:
        vendor = int(vendor, 16)
    if type(device) == str and '0x' in device:
        device = int(device, 16)

    return recursive_check_ids('/sys/bus/%s/devices' % bus, vendor, device)

def increment_bto_version(version):
    """Increments the BTO version"""
    match = re.match(r"(?:(?P<alpha1>\w+\.[a-z]*)(?P<digits>\d+))"
                     r"|(?P<alpha2>\w+(?:\.[a-z]+)?)",
                     version, re.I)

    if match:
        if match.group('digits'):
            version = "%s%d" % (match.group('alpha1'),
                              int(match.group('digits'))+1)
        else:
            if '.' in match.group('alpha2'):
                version = "%s1" % match.group('alpha2')
            else:
                version = "%s.1" % match.group('alpha2')
    else:
        return 'A00'

    return version

def walk_cleanup(directory):
    """Walks a directory, removes all files, and removes that directory"""
    if os.path.exists(directory):
        if os.path.isfile(directory):
            os.remove(directory)
            return
        for root, dirs, files in os.walk(directory, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                full_name = os.path.join(root, name)
                if os.path.islink(full_name):
                    os.remove(full_name)
                elif os.path.isdir(full_name):
                    os.rmdir(full_name)
                #covers broken links
                else:
                    os.remove(full_name)
        os.rmdir(directory)

def create_new_uuid(old_initrd_directory, old_casper_directory,
                    new_initrd_directory, new_casper_directory,
                    new_compression="auto",
                    include_bootstrap=False):
    """ Regenerates the UUID contained in a casper initramfs
        Supported compression types:
        * auto (auto detects lzma/gzip)
        * lzma
        * gzip
        * None
        Returns full path of the old initrd and casper files (for blacklisting)
    """
    tmpdir = tempfile.mkdtemp()

    #Detect the old initramfs stuff
    try:
        old_initrd_files = glob.glob('%s/initrd*' % old_initrd_directory)
    except Exception as msg:
        logging.warning("create_new_uuid: %s" % str(msg))
        raise dbus.DBusException("Missing initrd in image.")
    try:
        old_uuid_file   = glob.glob('%s/casper-uuid*' % old_casper_directory)[0]
    except Exception as msg:
        logging.warning("create_new_uuid: Old casper UUID not found, assuming 'casper-uuid'")
        old_uuid_file   = '%s/casper-uuid' % old_casper_directory

    old_initrd_file = ''
    old_compression = ''
    old_suffix = ''
    for fname in old_initrd_files:
        if len(fname.split('.')) > 1:
            old_suffix = fname.split('.')[-1]
        if old_suffix == "lz":
            old_compression = "lzma"
            old_initrd_file = fname
            break
        elif old_suffix == "gz":
            old_compression = "gzip"
            old_initrd_file = fname
            break
        else:
            old_suffix = ''

    if not old_suffix or not old_initrd_file or not old_uuid_file:
        raise dbus.DBusException("Unable to detect valid initrd.")

    logging.debug("create_new_uuid: old initrd %s, old uuid %s, old suffix %s, \
old compression method %s" % (old_initrd_file, old_uuid_file,
                              old_suffix, old_compression))

    #Extract old initramfs
    chain0 = subprocess.Popen([old_compression, '-cd', old_initrd_file, '-S',
                               old_suffix], stdout=subprocess.PIPE)
    chain1 = subprocess.Popen(['cpio', '-id'], stdin=chain0.stdout, cwd=tmpdir)
    chain1.communicate()

    #Generate new UUID
    new_uuid_file = os.path.join(new_casper_directory,
                                 os.path.basename(old_uuid_file))
    logging.debug("create_new_uuid: new uuid file: %s" % new_uuid_file)
    chain0 = subprocess.Popen(['uuidgen', '-r'], stdout=subprocess.PIPE)
    new_uuid = chain0.communicate()[0]
    logging.debug("create_new_uuid: new UUID: %s" % new_uuid.strip())
    for item in [new_uuid_file, os.path.join(tmpdir, 'conf', 'uuid.conf')]:
        with open(item, "wb") as uuid_fd:
            uuid_fd.write(new_uuid)

    #Newer (Ubuntu 11.04+) images may support including the bootstrap in initrd
    if include_bootstrap:
        chain0 = subprocess.Popen(['/usr/share/dell/casper/hooks/dell-bootstrap'], env={'DESTDIR': tmpdir, 'INJECT': '1'})
        chain0.communicate()

    #Detect compression
    new_suffix = ''
    if new_compression == "gzip":
        new_suffix = '.gz'
    elif new_compression == 'lzma':
        new_suffix = '.lz'
    elif new_compression == "auto":
        new_compression = old_compression
        new_suffix = '.' + old_suffix
    logging.debug("create_new_uuid: new suffix: %s" % new_suffix)
    logging.debug("create_new_uuid: new compression method: %s" % new_compression)

    #Generate new initramfs
    new_initrd_file = os.path.join(new_initrd_directory, 'initrd' + new_suffix)
    logging.debug("create_new_uuid: new initrd file: %s" % new_initrd_file)
    chain0 = subprocess.Popen(['find'], cwd=tmpdir, stdout=subprocess.PIPE)
    chain1 = subprocess.Popen(['cpio', '--quiet', '-o', '-H', 'newc'],
                               cwd=tmpdir, stdin=chain0.stdout,
                               stdout=subprocess.PIPE)
    with open(new_initrd_file, 'wb') as initrd_fd:
        if new_compression:
            chain2 = subprocess.Popen([new_compression, '-9c'],
                                      stdin=chain1.stdout,
                                      stdout=subprocess.PIPE)
            initrd_fd.write(chain2.communicate()[0])
        else:
            initrd_fd.write(chain1.communicate()[0])
    walk_cleanup(tmpdir)

    return (old_initrd_file, old_uuid_file)

def parse_seed(seed):
    """Parses a preseed file and returns a set of keys"""
    keys = {}
    if os.path.exists(seed):
        with open(seed, 'r') as rfd:
            line = rfd.readline()
            while line:
                line = line.strip()
                if line and not line.startswith('#'):
                    line = line.split()
                    line.pop(0) # ubiquity or d-i generally
                    key = line.pop(0)
                    if '/' in key:
                        type = line.pop(0)
                        value = " ".join(line)
                        keys[key] = value
                line = rfd.readline()
    return keys

def write_seed(seed, keys):
    """Writes out a preseed file with a selected set of keys"""
    with open(seed, 'w') as wfd:
        wfd.write("# Dell Recovery configuration preseed\n")
        wfd.write("# Last updated on %s\n" % datetime.date.today())
        wfd.write("\n")
        for item in keys:
            if keys[item] == 'true' or keys[item] == 'false':
                type = 'boolean'
            else:
                type = 'string'
            wfd.write(" ubiquity %s %s %s\n" % (item, type, keys[item]))

def mark_upgrades():
    '''Mark packages that can upgrade to upgrade during install'''
    from apt.cache import Cache
    cache = Cache()
    to_install = []
    for key in cache.keys():
        if cache[key].is_upgradable:
            to_install.append(key)
    del cache
    return to_install

def mark_unconditional_debs(add_directory=''):
    '''Finds any debs from debs/main that we want unconditionally installed
       (but ONLY the latest version on the media)'''
    import apt_inst
    import apt_pkg

    def parse(fname):
        """ read a deb """
        control = apt_inst.DebFile(fname).control.extractdata("control")
        sections = apt_pkg.TagSection(control)
        if "Modaliases" in sections:
            modaliases = sections["Modaliases"]
        else:
            modaliases = ''
        return (sections["Architecture"], sections["Package"], modaliases)

    #process debs/main
    to_install = []
    my_arch = fetch_output(['dpkg', '--print-architecture']).strip()
    for top in [ISO_MOUNT, CDROM_MOUNT, add_directory]:
        repo = os.path.join(top, 'debs', 'main')
        if os.path.isdir(repo):
            for fname in os.listdir(repo):
                if '.deb' in fname:
                    arch, package, modaliases = parse(os.path.join(repo, fname))
                    if not modaliases and (arch == "all" or arch == my_arch):
                        to_install.append(package)

    return to_install

def create_grub_entries(target_dir='/target', rec_type='hdd'):
    '''Create GRUB entry for dell-recovery during ubiquity installation'''
    env = os.environ
    rpart = find_factory_partition_stats()
    target_grub = '%s/etc/grub.d/99_dell_recovery' % target_dir
    #create the grub entry only when recovery partition exists
    if rpart:
        rec_text = 'Restore OS to factory state'
        process_conf_file(original = '/usr/share/dell/grub/99_dell_recovery', \
                          new = target_grub,                                  \
                          uuid = str(rpart["uuid"]),                          \
                          number = str(rpart["number"]),                      \
                          recovery_text = rec_text,
                          recovery_type = rec_type)
        os.chmod(target_grub, 0o755)

def dbus_sync_call_signal_wrapper(dbus_iface, func, handler_map, *args, **kwargs):
    '''Run a D-BUS method call while receiving signals.

    This function is an Ugly Hack™, since a normal synchronous dbus_iface.fn()
    call does not cause signals to be received until the method returns. Thus
    it calls func asynchronously and sets up a temporary main loop to receive
    signals and call their handlers; these are assigned in handler_map (signal
    name → signal handler).
    '''
    if not hasattr(dbus_iface, 'connect_to_signal'):
        # not a D-BUS object
        return getattr(dbus_iface, func)(*args, **kwargs)

    def _h_reply(*args, **kwargs):
        """protected method to send a reply"""
        global _h_reply_result
        _h_reply_result = args
        loop.quit()

    def _h_error(exception=None):
        """protected method to send an error"""
        global _h_exception_exc
        _h_exception_exc = exception
        loop.quit()

    loop = GLib.MainLoop()
    global _h_reply_result, _h_exception_exc
    _h_reply_result = None
    _h_exception_exc = None
    kwargs['reply_handler'] = _h_reply
    kwargs['error_handler'] = _h_error
    kwargs['timeout'] = 86400
    for signame, sighandler in handler_map.items():
        dbus_iface.connect_to_signal(signame, sighandler)
    dbus_iface.get_dbus_method(func)(*args, **kwargs)
    loop.run()
    if _h_exception_exc:
        raise _h_exception_exc
    return _h_reply_result


def regenerate_md5sum(root_dir,sec_dir=None):
    '''generate the md5sum.txt when building the ISO image.

    No matter whether the md5sum.txt exits or not, we will walk through the files and then build a new file.
    '''
    #check and delete the previsous md5sum.txt if the root dir exists md5sum.txt file
    if os.path.exists(os.path.join(root_dir, 'md5sum.txt')):
        os.remove(os.path.join(root_dir, 'md5sum.txt'))

    #define the head info of md5sum.txt
    head_info = """This file contains the list of md5 checksums of all files on this medium.\n\nYou can verify them automatically with the 'integrity-check' boot parameter,\nor, manually with: 'md5sum -c md5sum.txt'.\n\n"""
    #get the root dir file list for summing md5
    root_list = []
    #some files don't need to check md5
    uncheck_list = ["md5sum.txt","grubenv"]
    for root,dirs,files in os.walk(root_dir):
        for f in files:
            if f not in uncheck_list:
                root_list.append(os.path.join(root,f))
    #sum md5 then write into file function
    def md5sum(fd,path,root):
        file_path = '.' + path.split(root)[1]
        md5 = hashlib.md5(open(path,'rb').read()).hexdigest()
        content = md5+"  "+file_path+"\n"
        fd.write(content)

    with open(os.path.join(root_dir, 'md5sum.txt'),'w') as wfd:
        wfd.write(head_info)
        try:
            #write the md5 of root file list
            for full_path in root_list:
                md5sum(wfd,full_path,root_dir)
            #check the secondary dir or not for building ISO image by dell recovery
            if sec_dir:
                for root,dirs,files in os.walk(sec_dir):
                    for f in files:
                        if f not in uncheck_list:
                            full_path = os.path.join(root,f)
                            if root_dir + full_path.split(sec_dir)[1] not in root_list:
                                md5sum(wfd,full_path,sec_dir)
        except Exception as err:
            import syslog
            syslog.syslog("rewrite the md5sum.txt file failed with : %s" %(err))

def transfer_dmraid_path(source_path):
    """two direction change the dmraid path representive
       sample : /dev/dm-X --> /dev/mapper/isw*
    """
    udisks = UDisks.Client.new_sync(None)
    manager = udisks.get_object_manager()
    for item in manager.get_objects():
        block = item.get_block()
        if not block:
            continue
        # Check the disk is type of dmraid
        device_path = block.get_cached_property("Device").get_bytestring().decode('utf-8')
        if device_path == source_path:
            output = block.get_cached_property("Id").get_string()
            model = output.split("-")[-1]
            dest_path = os.path.join("/dev/mapper", model)
            break
    return dest_path

##                ##
## Common Classes ##
##                ##

class RestoreFailed(dbus.DBusException):
    """Exception Raised if the restoration process failed for any reason"""
    _dbus_error_name = 'com.dell.RecoveryMedia.RestoreFailedException'

class CreateFailed(dbus.DBusException):
    """Exception Raised if the media creation process failed for any reason"""
    _dbus_error_name = 'com.dell.RecoveryMedia.CreateFailedException'

class PermissionDeniedByPolicy(dbus.DBusException):
    """Exception Raised if policy kit denied the user access"""
    _dbus_error_name = 'com.dell.RecoveryMedia.PermissionDeniedByPolicy'

class BackendCrashError(SystemError):
    """Exception Raised if the backend crashes"""
    pass
