#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# «recovery_backend» - Backend Manager.  Handles backend service calls
#
# Copyright (C) 2009, Dell Inc.
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

import logging, os, os.path, signal, re

from gi.repository import GLib
import dbus
import dbus.service
import dbus.mainloop.glib
import atexit
import tempfile
import subprocess
import tarfile
import shutil
import datetime
import distutils.dir_util
import lsb_release
from hashlib import md5

from Dell.recovery_common import (DOMAIN, LOCALEDIR,
                                  walk_cleanup, create_new_uuid, white_tree,
                                  black_tree, fetch_output, check_version,
                                  DBUS_BUS_NAME, DBUS_INTERFACE_NAME,
                                  RestoreFailed, CreateFailed,
                                  regenerate_md5sum, PermissionDeniedByPolicy)
from Dell.recovery_threading import ProgressByPulse, ProgressBySize
from Dell.recovery_xml import BTOxml

import fcntl
import select

#Translation support
from gettext import gettext as _
from gettext import bindtextdomain, textdomain

from debian_bundle import debian_support

def safe_tar_extract(filename, destination):
    """Safely extracts a tarball into destination"""
    logging.debug('safe_tar_extract: %s to %s', (filename, destination))

    rfd = tarfile.open(filename)
    dangerous_file = False
    for name in rfd.getnames():
        if name.startswith('..') or name.startswith('/'):
            dangerous_file = True
            break
    if not dangerous_file:
        rfd.extractall(destination)
    rfd.close()

class Backend(dbus.service.Object):
    '''Backend manager.

    This encapsulates all services calls of the backend. It
    is implemented as a dbus.service.Object, so that it can be called through
    D-BUS as well (on the /RecoveryMedia object path).
    '''

    #
    # D-BUS control API
    #

    def __init__(self):
        dbus.service.Object.__init__(self)

        #initialize variables that will be used during create and run
        self.bus = None
        self.package_dir = None
        self.main_loop = None
        self._timeout = False
        self.dbus_name = None
        self.xml_obj = BTOxml()

        # cached D-BUS interfaces for _check_polkit_privilege()
        self.dbus_info = None
        self.polkit = None
        self.progress_thread = None
        self.enforce_polkit = True

        #Enable translation for strings used
        bindtextdomain(DOMAIN, LOCALEDIR)
        textdomain(DOMAIN)

    def run_dbus_service(self, timeout=None, send_usr1=False):
        '''Run D-BUS server.

        If no timeout is given, the server will run forever, otherwise it will
        return after the specified number of seconds.

        If send_usr1 is True, this will send a SIGUSR1 to the parent process
        once the server is ready to take requests.
        '''
        dbus.service.Object.__init__(self, self.bus, '/RecoveryMedia')
        self.main_loop = GLib.MainLoop()
        self._timeout = False
        if timeout:
            def _quit():
                """This function is ran at the end of timeout"""
                self.main_loop.quit()
                return True
            GLib.timeout_add(timeout * 1000, _quit)

        # send parent process a signal that we are ready now
        if send_usr1:
            os.kill(os.getppid(), signal.SIGUSR1)

        # run until we time out
        while not self._timeout:
            if timeout:
                self._timeout = True
            self.main_loop.run()

    @classmethod
    def create_dbus_server(cls, session_bus=False):
        '''Return a D-BUS server backend instance.

        Normally this connects to the system bus. Set session_bus to True to
        connect to the session bus (for testing).

        '''
        backend = Backend()
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        if session_bus:
            backend.bus = dbus.SessionBus()
            backend.enforce_polkit = True
        else:
            backend.bus = dbus.SystemBus()
        try:
            backend.dbus_name = dbus.service.BusName(DBUS_BUS_NAME, backend.bus)
        except dbus.exceptions.DBusException as msg:
            logging.error("Exception when spawning dbus service")
            logging.error(msg)
            return None
        return backend

    #
    # Internal methods
    #

    def _reset_timeout(self):
        '''Reset the D-BUS server timeout.'''

        self._timeout = False

    def _check_polkit_privilege(self, sender, conn, privilege):
        '''Verify that sender has a given PolicyKit privilege.

        sender is the sender's (private) D-BUS name, such as ":1:42"
        (sender_keyword in @dbus.service.methods). conn is
        the dbus.Connection object (connection_keyword in
        @dbus.service.methods). privilege is the PolicyKit privilege string.

        This method returns if the caller is privileged, and otherwise throws a
        PermissionDeniedByPolicy exception.
        '''
        if sender is None and conn is None:
            # called locally, not through D-BUS
            return
        if not self.enforce_polkit:
            # that happens for testing purposes when running on the session
            # bus, and it does not make sense to restrict operations here
            return

        # get peer PID
        if self.dbus_info is None:
            self.dbus_info = dbus.Interface(conn.get_object('org.freedesktop.DBus',
                '/org/freedesktop/DBus/Bus', False), 'org.freedesktop.DBus')
        pid = self.dbus_info.GetConnectionUnixProcessID(sender)

        # query PolicyKit
        if self.polkit is None:
            self.polkit = dbus.Interface(dbus.SystemBus().get_object(
                'org.freedesktop.PolicyKit1', '/org/freedesktop/PolicyKit1/Authority', False),
                'org.freedesktop.PolicyKit1.Authority')
        try:
            # we don't need is_challenge return here, since we call with AllowUserInteraction
            (is_auth, unused, details) = self.polkit.CheckAuthorization(
                    ('unix-process', {'pid': dbus.UInt32(pid, variant_level=1),
                        'start-time': dbus.UInt64(0, variant_level=1)}),
                    privilege, {'': ''}, dbus.UInt32(1), '', timeout=600)
        except dbus.DBusException as msg:
            if msg.get_dbus_name() == \
                                    'org.freedesktop.DBus.Error.ServiceUnknown':
                # polkitd timed out, connect again
                self.polkit = None
                return self._check_polkit_privilege(sender, conn, privilege)
            else:
                raise

        if not is_auth:
            logging.debug('_check_polkit_privilege: sender %s on connection %s pid %i is not authorized for %s: %s',
                    sender, conn, pid, privilege, str(details))
            raise PermissionDeniedByPolicy(privilege)

    #
    # Internal API for calling from Handlers (not exported through D-BUS)
    #

    def request_mount(self, recovery, type="r", sender=None, conn=None):
        '''Attempts to mount the recovery partition

           If successful, return mntdir.
           If we find that it's already mounted elsewhere, return that mount
           If unsuccessful, return an empty string
        '''
        logging.debug("request_mount: %s" % recovery)

        #In this is just a directory
        if os.path.isdir(recovery):
            return recovery

        #check for an existing mount
        command = subprocess.Popen(['mount'], stdout=subprocess.PIPE,
                                   universal_newlines=True)
        output = command.communicate()[0].split('\n')
        for line in output:
            processed_line = line.split()
            if len(processed_line) > 0 and processed_line[0] == recovery:
                return processed_line[2]

        #if not already, mounted, produce a mount point
        mntdir = tempfile.mkdtemp()
        mnt_args = ['mount', '-%s' %type, recovery, mntdir]
        if ".iso" in recovery:
            mnt_args.insert(1, 'loop')
            mnt_args.insert(1, '-o')
        else:
            self._check_polkit_privilege(sender, conn,
                                                'com.dell.recoverymedia.create')
        command = subprocess.Popen(mnt_args,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 universal_newlines=True)
        output = command.communicate()
        ret = command.wait()
        if ret is not 0:
            os.rmdir(mntdir)
            if ret == 32:
                try:
                    mntdir = output[1].strip('\n').split('on')[1].strip(' ')
                except IndexError:
                    mntdir = ''
                    logging.warning("IndexError when operating on output string")
            else:
                mntdir = ''
                logging.warning("Unable to mount recovery partition")
                logging.warning(output)
        else:
            atexit.register(self._unmount_drive, mntdir)
        return mntdir

    def _unmount_drive(self, mnt):
        """Unmounts something mounted at a particular mount point"""
        logging.debug("_unmount_drive: %s" % mnt)

        if os.path.exists(mnt):
            ret = subprocess.call(['umount', mnt])
            if ret is not 0:
                logging.warning(" _unmount_drive: Error unmounting %s" % mnt)
            try:
                os.rmdir(mnt)
            except OSError as msg:
                logging.warning(" _unmount_drive: Error cleaning up: %s" % str(msg))

    def _test_for_new_dell_recovery(self, mount, assembly_tmp):
        """Tests if the distro currently on the system matches the recovery media.
           If it does, check for any potential SRUs to apply to the recovery media
        """
        logging.debug("_test_for_new_dell_recovery: testing mount %s and assembly_tmp %s" % (mount, assembly_tmp))

        output = fetch_output(['zcat', '/usr/share/doc/dell-recovery/changelog.gz'])
        package_distro = output.split('\n')[0].split()[2].strip(';')

        for info in ('info.recovery', 'info'):
            file_path = os.path.join(mount, '.disk', info)
            if os.path.exists(file_path):
                with open(file_path) as rfd:
                    rp_distro = rfd.readline().split()[2].strip('"').lower()
                    break

        if rp_distro in package_distro:
            logging.debug("_test_for_new_dell_recovery: Distro %s matches %s", rp_distro, package_distro)
            from apt.cache import Cache
            cache = Cache()
            package_version = cache['dell-recovery'].installed.version
            rp_version = self.query_have_dell_recovery(mount)

            if debian_support.version_compare(package_version, rp_version) > 0:
                logging.debug("_test_for_new_dell_recovery: Including updated dell-recovery package version, %s (original was %s)", package_version, rp_version)
                dest = os.path.join(assembly_tmp, 'debs')
                if not os.path.isdir(dest):
                    os.makedirs(dest)
                call = subprocess.Popen(['dpkg-repack', 'dell-recovery'],
                                        cwd=dest, universal_newlines=True)
                (out, err) = call.communicate()
        else:
            logging.debug("_test_for_new_dell_recovery: RP Distro %s doesn't match our distro %s, not injecting updated package", rp_distro, package_distro)


    def _process_driver_fish(self, driver_fish, assembly_tmp):
        """Processes a driver FISH archive"""
        logging.debug("_process_driver_fish: assmebly_tmp: %s" % assembly_tmp)
        length = len(driver_fish)
        for fishie in driver_fish:
            logging.debug(" processing %s" % fishie)
            self.report_progress(_('Processing FISH packages'),
                                 driver_fish.index(fishie)/length*100)
            if os.path.isfile(fishie):
                with open(fishie, 'rb') as fish:
                    md5sum = md5(fish.read()).hexdigest()
                self.xml_obj.append_fish('driver', os.path.basename(fishie), md5sum)
            dest = None
            if fishie.endswith('.deb'):
                dest = os.path.join(assembly_tmp, 'debs')
                logging.debug("  Copying debian archive fishie %s", fishie)
            elif fishie.endswith('.pdf'):
                dest = os.path.join(assembly_tmp, 'docs')
                logging.debug("  Copying document fishie fishie %s", fishie)
            elif fishie.endswith('.py') or fishie.endswith('.sh'):
                dest = os.path.join(assembly_tmp, 'scripts', 'chroot-scripts', 'fish')
                logging.debug("  Copying python or shell fishie %s", fishie)
            elif os.path.exists(fishie) and tarfile.is_tarfile(fishie):
                nested = False
                rfd = tarfile.open(fishie)
                for member in rfd.getmembers():
                    name = member.get_info()['name']
                    if name.endswith('.html'):
                        nested = name
                        break
                if nested:
                    archive_tmp = tempfile.mkdtemp()
                    atexit.register(walk_cleanup, archive_tmp)
                    safe_tar_extract(fishie, archive_tmp)
                    children = []
                    for child in os.listdir(archive_tmp):
                        if child != name:
                            children.append(os.path.join(archive_tmp,child))
                    logging.debug("  Extracting nested archive %s", fishie)
                    self._process_driver_fish(children, assembly_tmp)
                else:
                    safe_tar_extract(fishie, assembly_tmp)
                    logging.debug(":  Extracting tar fishie %s", fishie)
                    pre_package = os.path.join(assembly_tmp, 'prepackage.dell')
                    if os.path.exists(pre_package):
                        os.remove(pre_package)
            else:
                logging.debug("  ignoring fishie %s", fishie)

            #If we just do a flat copy
            if dest is not None:
                if not os.path.isdir(dest):
                    os.makedirs(dest)
                distutils.file_util.copy_file(fishie, dest,
                                              verbose=1, update=0)


    def start_sizable_progress_thread(self, input_str, mnt, w_size):
        """Initializes the extra progress thread, or resets it
           if it already exists'"""
        self.progress_thread = ProgressBySize(input_str, mnt, w_size)
        self.progress_thread.progress = self.report_progress
        self.progress_thread.start()

    def stop_progress_thread(self):
        """Stops the extra thread for reporting progress"""
        self.progress_thread.join()

    def start_pulsable_progress_thread(self, input_str):
        """Starts the extra thread for pulsing progress in the UI"""
        self.progress_thread = ProgressByPulse(input_str)
        self.progress_thread.progress = self.report_progress
        self.progress_thread.start()
    #
    # Client API (through D-BUS)
    #

    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = 'b', out_signature = 'b', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def force_network(self, enable, sender=None, conn=None):
        """Forces a network manager disable request as root"""
        self._check_polkit_privilege(sender, conn, 'com.dell.recoverymedia.force_network')
        bus = dbus.SystemBus()
        obj = bus.get_object('org.freedesktop.NetworkManager', '/org/freedesktop/NetworkManager')
        int = dbus.Interface(obj, 'org.freedesktop.NetworkManager')
        return int.Sleep(not enable)

    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = '', out_signature = '', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def request_exit(self, sender=None, conn=None):
        """Closes the backend and cleans up"""
        self._check_polkit_privilege(sender, conn, 'com.dell.recoverymedia.request_exit')
        self._timeout = True
        self.main_loop.quit()

    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = 'sasa{ss}sssssb', out_signature = '', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def assemble_image(self,
                       base,
                       driver_fish,
                       application_fish,
                       dell_recovery_package,
                       create_fn,
                       version, iso, platform, no_update, sender=None, conn=None):
        """Assemble pieces that would be used for building a BTO image.
           base: mount point of base image (or directory)
           fish: list of packages to fish
           dell_recovery_package: a dell-recovery package to inject
           create_fn: function to call for creation of ISO
           version: version for ISO creation purposes
           iso: iso file name to create
           platform: platform name to identify
           no_update: don't include newer dell-recovery automatically"""
        logging.debug("assemble_image: base %s, driver_fish %s, application_fish\
%s, recovery %s, create_fn %s, version %s, iso %s, platform %s, no_update %s" %
                    (base, driver_fish, application_fish, dell_recovery_package,
                    create_fn, version, iso, platform, no_update))

        self._reset_timeout()

        base_mnt = self.request_mount(base, "r", sender, conn)

        assembly_tmp = tempfile.mkdtemp()
        atexit.register(walk_cleanup, assembly_tmp)

        #copy the base iso/mnt point/etc
        white_pattern = re.compile('')
        w_size = white_tree("size", white_pattern, base_mnt)
        self.start_sizable_progress_thread(_('Adding in base image'),
                                           assembly_tmp,
                                           w_size)
        white_tree("copy", white_pattern, base_mnt, assembly_tmp)
        self.stop_progress_thread()

        #Add in driver FISH content
        if len(driver_fish) > 0:
            # record the base iso used
            self.xml_obj.set_base(os.path.basename(base))

            self._process_driver_fish(driver_fish, assembly_tmp)
            logging.debug("assemble_image: done inserting driver fish")

        #Add in application FISH content
        length = float(len(application_fish))
        if length > 0:
            dest = os.path.join(assembly_tmp, 'srv')
            os.makedirs(dest)
            for fishie in application_fish:
                with open(fishie, 'rb') as fish:
                    md5sum = md5(fish.read()).hexdigest()
                new_name = application_fish[fishie]
                self.xml_obj.append_fish('application', os.path.basename(fishie), md5sum, new_name)
                if fishie.endswith('.zip'):
                    new_name += '.zip'
                elif os.path.exists(fishie) and tarfile.is_tarfile(fishie):
                    new_name += '.tgz'
                distutils.file_util.copy_file(fishie,
                                              os.path.join(dest, new_name),
                                              verbose=1, update=0)

        #If dell-recovery needs to be injected into the image
        if dell_recovery_package:
            self.xml_obj.replace_node_contents('deb_archive', dell_recovery_package)
            dest = os.path.join(assembly_tmp, 'debs')
            if not os.path.isdir(dest):
                os.makedirs(dest)
            if 'dpkg-repack' in dell_recovery_package:
                logging.debug("Repacking dell-recovery using dpkg-repack")
                call = subprocess.Popen(['dpkg-repack', 'dell-recovery'],
                                        cwd=dest, universal_newlines=True)
                (out, err) = call.communicate()
            else:
                logging.debug("Adding manually included dell-recovery package, %s", dell_recovery_package)
                distutils.file_util.copy_file(dell_recovery_package, dest)

        function = getattr(Backend, create_fn)
        function(self, assembly_tmp, version, iso, platform, no_update)

    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = 's', out_signature = 'ssssss', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def query_iso_information(self, iso, sender=None, conn=None):
        """Queries what type of ISO this is.  This same method will be used regardless
           of OS."""
        def find_arch(input_str):
            """Finds the architecture in an input string"""
            for item in input_str.split():
                for test in ('amd64', 'i386'):
                    if test in item:
                        return test
            return fetch_output(['dpkg', '--print-architecture']).strip()

        def find_float(input_str):
            """Finds the floating point number in a string"""
            for piece in input_str.split():
                try:
                    release = float(piece)
                except ValueError:
                    continue
                logging.debug("query_iso_information: find_float found %d", release)
                return piece
            return ''
        logging.debug("query_iso_information: iso %s" % iso)

        self._reset_timeout()
        self._check_polkit_privilege(sender, conn,
                                'com.dell.recoverymedia.query_iso_information')

        (bto_version, bto_date, bto_platform) = self.query_bto_version(iso, sender, conn)

        distributor_str = 'Unknown Base Image'
        distributor = ''

        #Ubuntu disks have .disk/info
        if os.path.isfile(iso) and iso.endswith('.iso'):
            cmd = ['isoinfo', '-J', '-i', iso, '-x', '/.disk/info']
            invokation = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          universal_newlines=True)
            out, err = invokation.communicate()
            if invokation.returncode is None:
                invokation.wait()
            if out:
                distributor_str = out
                distributor = "ubuntu"
            if err:
                logging.debug("error during isoinfo invokation: %s", err)
        else:
            mntdir = self.request_mount(iso, "r", sender, conn)

            if os.path.exists(os.path.join(mntdir, '.disk', 'info')):
                with open(os.path.join(mntdir, '.disk', 'info'), 'r') as rfd:
                    distributor_str = rfd.readline().strip('\n')
                distributor = "ubuntu"

            #RHEL disks have .discinfo
            elif os.path.exists(os.path.join(mntdir, '.discinfo')):
                with open(os.path.join(mntdir, '.discinfo'), 'r') as rfd:
                    timestamp = rfd.readline().strip('\n')
                    distributor_string = rfd.readline().strip('\n')
                    arch = rfd.readline().strip('\n')
                distributor = "redhat"
                distributor_str += ' ' + arch

        release = find_float(distributor_str)
        arch = find_arch(distributor_str)

        if bto_version and bto_date:
            distributor_str = "<b>Dell BTO Image</b>, version %s built on %s\n%s" % (bto_version.split('.')[0], bto_date, distributor_str)
        elif bto_version == '[native]':
            distributor_str = "<b>Dell BTO Compatible Image</b>\n%s" % distributor_str
        else:
            bto_version = ''

        self.report_iso_info(bto_version, distributor, release, arch, distributor_str, bto_platform)
        logging.debug(" returning bto_version %s, distributor %s, release %s, \
arch %s, distributor_str %s, bto_platform %s" % (bto_version, distributor, release, arch, distributor_str, bto_platform))
        return (bto_version, distributor, release, arch, distributor_str, bto_platform)

    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = 's', out_signature = 'sss', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def query_bto_version(self, recovery, sender=None, conn=None):
        """Queries the BTO version number internally stored in an ISO or RP"""

        def test_initrd(cmd0):
            """Tests an initrd using the selected command"""
            cmd1 = ['unlzma']
            cmd2 = ['cpio', '-it', '--quiet']
            chain0 = subprocess.Popen(cmd0, stdout=subprocess.PIPE)
            chain1 = subprocess.Popen(cmd1, stdin=chain0.stdout, stdout=subprocess.PIPE)
            chain2 = subprocess.Popen(cmd2, stdin=chain1.stdout, stdout=subprocess.PIPE,
                                      universal_newlines=True)
            out, err = chain2.communicate()
            if chain2.returncode is None:
                chain2.wait()
            if out:
                for line in out.split('\n'):
                    if 'scripts/casper-bottom/99dell_bootstrap' in line:
                        return '[native]'
            return ''
        logging.debug("query_bto_version: recovery %s" % recovery)

        self._reset_timeout()
        self._check_polkit_privilege(sender, conn,
                                    'com.dell.recoverymedia.query_bto_version')

        #mount the recovery partition
        version = ''
        date = ''
        platform = ''

        if os.path.isfile(recovery) and recovery.endswith('.iso'):
            cmd = ['isoinfo', '-J', '-i', recovery, '-x', '/bto.xml']
            out = fetch_output(cmd)
            if out:
                self.xml_obj.load_bto_xml(out)
                version = self.xml_obj.fetch_node_contents('revision') or \
                          self.xml_obj.fetch_node_contents('iso')
                platform = self.xml_obj.fetch_node_contents('platform')
                date = self.xml_obj.fetch_node_contents('date')
            else:
                cmd = ['isoinfo', '-J', '-i', recovery, '-x', '/bto_version']
                out = fetch_output(cmd)
                if out:
                    out = out.split('\n')
                    if len(out) > 1:
                        version = out[0]
                        date = out[1]
                else:
                    version = test_initrd(['isoinfo', '-J', '-i', recovery, '-x', '/casper/initrd.lz'])

        else:
            mntdir = self.request_mount(recovery, "r", sender, conn)
            if os.path.exists(os.path.join(mntdir, 'bto.xml')):
                self.xml_obj.load_bto_xml(os.path.join(mntdir, 'bto.xml'))
                version = self.xml_obj.fetch_node_contents('revision') or \
                          self.xml_obj.fetch_node_contents('iso')
                platform = self.xml_obj.fetch_node_contents('platform')
                date = self.xml_obj.fetch_node_contents('date')
            elif os.path.exists(os.path.join(mntdir, 'bto_version')):
                with open(os.path.join(mntdir, 'bto_version'), 'r') as rfd:
                    version = rfd.readline().strip('\n')
                    date = rfd.readline().strip('\n')
            #no /bto.xml or /bto_version found, check initrd for bootsrap files
            elif os.path.exists(os.path.join(mntdir, 'casper', 'initrd.lz')):
                version = test_initrd(['cat', os.path.join(mntdir, 'casper', 'initrd.lz')])

        return (version, date, platform)

    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = 's', out_signature = 's', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def query_have_dell_recovery(self, recovery, sender=None, conn=None):
        '''Checks if the given image contains the dell-recovery
           package suite'''

        def run_isoinfo_command(cmd):
            """Returns the output of an isoinfo command"""
            invokation = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          universal_newlines=True)
            out, err = invokation.communicate()
            if invokation.returncode is None:
                invokation.wait()
            if err:
                logging.debug("error invoking isoinfo: %s", err)
            return out

        def check_mentions(feed):
            '''Checks if given file mentions dell-recovery'''
            for line in feed.split('\n'):
                if 'dell-recovery' in line:
                    return line.split()[1]
            return ''
        logging.debug("query_have_dell_recovery: recovery %s" % recovery)

        found = ''

        #Recovery Partition is an ISO
        if os.path.isfile(recovery) and recovery.endswith('.iso'):
            #first find the interesting files
            cmd = ['isoinfo', '-J', '-i', recovery, '-f']
            logging.debug("query_have_dell_recovery: Checking %s", recovery)
            interesting_files = []
            for fname in run_isoinfo_command(cmd).split('\n'):
                if 'dell-recovery' in fname and (fname.endswith('.deb') or fname.endswith('.rpm')):
                    logging.debug("query_have_dell_recovery: Found %s", fname)
                    if '_' in fname:
                        new = fname.split('_')[1]
                        if new > found:
                            found = new
                    if not found:
                        found = '1'
                elif fname.endswith('.manifest'):
                    interesting_files.append(fname)
                    logging.debug("query_have_dell_recovery: Appending %s to interesting_files", fname)

            if not found:
                for fname in interesting_files:
                    cmd = ['isoinfo', '-J', '-i', recovery, '-x', fname]
                    logging.debug("query_have_dell_recovery: Checking %s ", fname)
                    version = check_mentions(run_isoinfo_command(cmd))
                    if version:
                        logging.debug("query_have_dell_recovery: Found %s in %s", version, fname)
                        if version > found:
                            found = version
        #Recovery partition is mount point or directory
        else:
            #Search for a flat file first (or a manifest for later)
            logging.debug("query_have_dell_recovery: Searching mount point %s", recovery)
            interesting_files = []
            for root, dirs, files in os.walk(recovery, topdown=False):
                for fname in files:
                    if 'dell-recovery' in fname and (fname.endswith('.deb') or fname.endswith('.rpm')):
                        logging.debug("query_have_dell_recovery: Found in %s", os.path.join(root, fname))
                        if '_' in fname:
                            new = fname.split('_')[1]
                            if new > found:
                                found = new
                        if not found:
                            found = '1'
                    elif fname.endswith('.manifest'):
                        interesting_files.append(os.path.join(root, fname))
                        logging.debug("query_have_dell_recovery: Appending %s to interesting_files", os.path.join(root, fname))

            if not found:
                for fname in interesting_files:
                    logging.debug("query_have_dell_recovery: Checking %s ", fname)
                    with open(fname, 'r') as rfd:
                        output = rfd.read()
                    version = check_mentions(output)
                    if version:
                        logging.debug("query_have_dell_recovery: Found %s in %s", version, fname)
                        if version > found:
                            found = version
        return found

    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = 's', out_signature = '', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def validate_driver_package(self, package, sender=None, conn=None):
        """Validates a Dell driver package"""
        logging.debug ("Validating driver package %s" % package)
        valid = 1
        description = ['']
        error_warning = ''
        if not os.path.exists(package) or not package.endswith('fish.tar.gz'):
            valid = -1
            error_warning = 'Bad file name'
        if valid >= 0:
            rfd = tarfile.open(package)
            prepackage = False
            for name in rfd.getnames():
                if name.endswith('prepackage.dell'):
                    prepackage = rfd.getmember(name)
                    break
            if not prepackage:
                valid = -1
                error_warning = 'Missing or invalid XML descriptor (prepackage.dell)'
        if valid >= 0:
            tmpdir = tempfile.mkdtemp()
            atexit.register(walk_cleanup, tmpdir)
            rfd.extract(prepackage, tmpdir)
            rfd.close()
            self.xml_obj.load_bto_xml(os.path.join(tmpdir, 'prepackage.dell'))
            our_os = lsb_release.get_lsb_information()['RELEASE']
            package_os = self.xml_obj.fetch_node_contents('os')
            if our_os != package_os:
                valid = 0
                error_warning = "OS Version of package %s doesn't match local OS version %s" % (package_os, our_os)
            description = self.xml_obj.fetch_node_contents('driver')
        logging.debug("Validation complete: valid %s" % valid)
        self.report_package_info(valid, description, error_warning)

    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = 'b', out_signature = '', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def enable_boot_to_restore(self, reboot, sender=None, conn=None):
        """Enables the default one-time boot option to be recovery"""
        self._reset_timeout()
        self._check_polkit_privilege(sender, conn, 'com.dell.recoverymedia.restore')
        logging.debug("enable_boot_to_restore:reboot=%s" % reboot)
        self._prepare_reboot("99_dell_recovery", reboot)

    def _prepare_reboot(self, dest, reboot):
        """Helper function to reboot into an entry"""
        #find our one time boot entry
        if not os.path.exists("/etc/grub.d/%s" % dest):
            raise RestoreFailed("missing %s to parse" % dest)

        with open('/etc/grub.d/%s' % dest) as rfd:
            grub_file = rfd.readlines()

        entry = False
        for line in grub_file:
            if "menuentry" in line:
                split = line.split('"')
                if len(split) > 1:
                    entry = split[1]
                    break

        if not entry:
            raise RestoreFailed("Error parsing %s for bootentry." % dest)

        #set us up to boot saved entries
        with open('/etc/default/grub', 'r') as rfd:
            default_grub = rfd.readlines()
        with open('/etc/default/grub', 'w') as wfd:
            for line in default_grub:
                if line.startswith("GRUB_DEFAULT="):
                    line = "GRUB_DEFAULT=saved\n"
                wfd.write(line)

        env = os.environ

        #Make sure the language is set properly
        with open('/etc/default/locale','r') as rfd:
            for line in rfd.readlines():
                if line.startswith('LANG=') and len(line.split('=')) > 1:
                    lang = line.split('=')[1].strip('\n').strip('"')
                    env['LANG'] = lang

        #Make sure the path is set properly
        if 'PATH' not in env and os.path.exists('/etc/environment'):
            with open('/etc/environment', 'r') as rfd:
                for line in rfd.readlines():
                    if line.startswith('PATH=') and len(line.split('=')) > 1:
                        path = line.split('=')[1].strip('\n').strip('"')
                        env['PATH'] = path

        ret = subprocess.call(['/usr/sbin/update-grub'], env=env)
        if ret is not 0:
            raise RestoreFailed("error updating grub configuration")

        ret = subprocess.call(['/usr/sbin/grub-reboot', entry])
        if ret is not 0:
            raise RestoreFailed("error setting one time grub entry")

        if reboot:
            logging.debug("Prepare to reboot")
            ret = subprocess.call(["/sbin/reboot", "--force"])
            if ret is not 0:
                raise RestoreFailed("error invoking reboot")


    @dbus.service.method(DBUS_INTERFACE_NAME,
        in_signature = 'ssssb', out_signature = '', sender_keyword = 'sender',
        connection_keyword = 'conn')
    def create_ubuntu(self, recovery, revision, iso, platform, no_update, sender=None, conn=None):
        """Creates Ubuntu compatible recovery media"""

        self._reset_timeout()
        self._check_polkit_privilege(sender, conn,
                                                'com.dell.recoverymedia.create')
        logging.debug("create_ubuntu: recovery %s, revision %s, iso %s, platform %s" %
            (recovery, revision, iso, platform))

        #create temporary workspace
        tmpdir = tempfile.mkdtemp()
        atexit.register(walk_cleanup, tmpdir)

        #mount the recovery partition
        mntdir = self.request_mount(recovery, "r", sender, conn)

        #validate that ubuntu is on the partition
        if not os.path.exists(os.path.join(mntdir, '.disk', 'info')) and \
           not os.path.exists(os.path.join(mntdir, '.disk', 'info.recovery')):
            logging.warning("create_ubuntu: recovery partition missing .disk/info and .disk/info.recovery")
            if os.path.exists(os.path.join(mntdir, 'bootmgr')):
                raise CreateFailed("This tool can not create a recovery image from a Windows recovery partition.")
            raise CreateFailed("Recovery partition is missing critical ubuntu files.")

        #test for an updated dell recovery deb to put in
        if not no_update:
            try:
                self._test_for_new_dell_recovery(mntdir, tmpdir)
            except:
                raise CreateFailed("Error injecting updated Dell Recovery into image.")

        #check for a nested ISO image
        if os.path.exists(os.path.join(mntdir, 'ubuntu.iso')):
            pattern = re.compile('^ubuntu.iso|^.disk')
            w_size = black_tree("size", pattern, mntdir)
            self.start_sizable_progress_thread(_('Preparing nested image'),
                                           tmpdir,
                                           w_size)
            black_tree("copy", pattern, mntdir, tmpdir)
            self.stop_progress_thread()
            mntdir = self.request_mount(os.path.join(mntdir, 'ubuntu.iso'), "r", sender, conn)

        #Generate BTO XML File
        self.xml_obj.replace_node_contents('date', str(datetime.date.today()))
        self.xml_obj.replace_node_contents('iso', os.path.basename(iso))
        self.xml_obj.replace_node_contents('revision', revision)
        self.xml_obj.replace_node_contents('platform', platform)
        self.xml_obj.replace_node_contents('generator', check_version())
        self.xml_obj.write_xml(os.path.join(tmpdir, 'bto.xml'))

        #Arg list
        xorrisoargs = ['xorriso',
                       '-as', 'mkisofs',
                       '-R',
                       '-r',
                       '-J',
                       '-joliet-long',
                       '-l',
                       '-iso-level', '3',
                       '-sysid', 'Linux',
                       '-V', 'Dell Recovery Media',
                       '-A', 'Dell Recovery',
                       '-p', 'Dell',
                       '-publisher', 'Dell',
                       '-o', iso,
                       '-m', '*.exe',
                       '-m', '*.sys',
                       '-m', '*.SDR',
                       '-m', 'SDR',
                       '-m', 'syslinux',
                       '-m', 'syslinux.cfg',
                       '-m', os.path.join(mntdir, 'bto.xml'),
                       '-m', os.path.join(mntdir, 'bto_version')]

        if platform and revision:
            xorrisoargs.append('-volset')
            xorrisoargs.append(platform + ' ' + revision)

        if os.path.exists(os.path.join('/', 'usr', 'lib', 'ISOLINUX', 'isohdpfx.bin')) and \
            os.path.exists(os.path.join(mntdir, 'isolinux', 'boot.cat')) and \
            os.path.exists(os.path.join(mntdir, 'isolinux', 'isolinux.bin')):
            xorrisoargs.append('-c')
            xorrisoargs.append('isolinux/boot.cat')
            xorrisoargs.append('-b')
            xorrisoargs.append('isolinux/isolinux.bin')
            xorrisoargs.append('-no-emul-boot')
            xorrisoargs.append('-boot-load-size')
            xorrisoargs.append('4')
            xorrisoargs.append('-boot-info-table')
            xorrisoargs.append('-isohybrid-mbr')
            xorrisoargs.append(os.path.join('/', 'usr', 'lib', 'ISOLINUX', 'isohdpfx.bin'))

        #include bootloader as eltorito if we have it
        if os.path.exists(os.path.join(mntdir, 'boot', 'efi.img')):
            xorrisoargs.append('-eltorito-alt-boot')
            xorrisoargs.append('-e')
            xorrisoargs.append('boot/efi.img')
            xorrisoargs.append('-no-emul-boot')
            xorrisoargs.append('-isohybrid-gpt-basdat')

        #disable 32 bit bootloader if it was there.
        grub_path = os.path.join(mntdir, 'boot', 'grub', 'i386-pc')
        if os.path.exists(grub_path):
            xorrisoargs.append('-m')
            xorrisoargs.append(grub_path)
        grub_path = os.path.join(tmpdir, 'boot', 'grub', 'i386-pc')
        os.makedirs(grub_path)
        for name in ['boot.img', 'core.img']:
            with open(os.path.join(grub_path, name), 'w'):
                pass

        #include EFI binaries
        if os.path.exists(os.path.join(mntdir, 'efi.factory')) and \
           not os.path.exists(os.path.join(mntdir, 'efi')):
            xorrisoargs.append('-m')
            xorrisoargs.append('efi.factory')
            shutil.copytree(os.path.join(mntdir, 'efi.factory'), os.path.join(tmpdir, 'efi'))

        #if no bootstrap in RP, we'll put it in the initrd
        bootstrap_initrd = not os.path.exists(os.path.join(mntdir, 'scripts', 'bootstrap.sh'))

        #Renerate UUID
        os.mkdir(os.path.join(tmpdir, '.disk'))
        os.mkdir(os.path.join(tmpdir, 'casper'))
        self.start_pulsable_progress_thread(_('Regenerating UUID / Rebuilding initramfs'))
        (old_initrd,
         old_uuid) = create_new_uuid(os.path.join(mntdir, 'casper'),
                        os.path.join(mntdir, '.disk'),
                        os.path.join(tmpdir, 'casper'),
                        os.path.join(tmpdir, '.disk'),
                        new_compression="auto",
                        include_bootstrap=bootstrap_initrd)
        self.stop_progress_thread()
        xorrisoargs.append('-m')
        xorrisoargs.append(os.path.join('.disk', old_uuid))
        xorrisoargs.append('-m')
        xorrisoargs.append(os.path.join('casper', old_initrd))

        #Renew .disk/ubuntu_dist_channel for ubuntu-report
        ubuntu_dist_channel = os.path.join(mntdir, '.disk', 'ubuntu_dist_channel')
        if os.path.exists(ubuntu_dist_channel) and platform and revision:
            xorrisoargs.append('-m')
            xorrisoargs.append(ubuntu_dist_channel)
            with open(os.path.join(tmpdir, '.disk', 'ubuntu_dist_channel'), 'w') as target, \
                 open(ubuntu_dist_channel) as source:
                for line in source:
                    if line.startswith('canonical-oem-somerville-') and \
                            not line.strip().endswith('+' + platform + '+' + revision):
                        target.write(line.strip() + '+' + platform + '+' + revision + '\n')
                    else:
                        target.write(line)

        #Restore .disk/info
        info_path = os.path.join(mntdir, '.disk', 'info.recovery')
        if os.path.exists(info_path):
            xorrisoargs.append('-m')
            xorrisoargs.append(info_path)
            shutil.copy(info_path, os.path.join(tmpdir, '.disk', 'info'))

        #if we have any any ISO/USB bootable bootloader on the image, copy in a theme
        grub_theme = False
        for topdir in [mntdir, tmpdir]:
            if os.path.exists(os.path.join(topdir, 'boot', 'grub', 'x86_64-efi')):
                grub_theme = True
        if grub_theme:
            if not os.path.exists(os.path.join(tmpdir, 'boot', 'grub')):
                os.makedirs(os.path.join(tmpdir, 'boot', 'grub'))
            #conffiles
            shutil.copy('/usr/share/dell/grub/theme/grub.cfg',
                        os.path.join(tmpdir, 'boot', 'grub', 'grub.cfg'))
            xorrisoargs.append('-m')
            xorrisoargs.append(os.path.join(mntdir,'boot/grub/grub.cfg'))
            directory = os.path.join(mntdir, 'boot', 'grub', 'x86-64_efi')
            if os.path.exists(directory):
                if not os.path.exists(os.path.join(tmpdir, 'boot', 'grub', 'x86_64-efi')):
                    os.makedirs(os.path.join(tmpdir, 'boot', 'grub', 'x86_64-efi'))
                shutil.copy('/usr/share/dell/grub/theme/%s/grub.cfg' % 'x86_64-efi',
                            os.path.join(tmpdir, 'boot', 'grub', 'x86_64-efi', 'grub.cfg'))
                xorrisoargs.append('-m')
                xorrisoargs.append(os.path.join(mntdir,'boot/grub/%s/grub.cfg' % 'x86_64-efi'))
            #theme
            if not os.path.exists(os.path.join(mntdir, 'boot', 'grub', 'dell')):
                shutil.copytree('/usr/share/dell/grub/theme/dell',
                                os.path.join(tmpdir, 'boot', 'grub', 'dell'))
            #fonts
            if not os.path.exists(os.path.join(mntdir, 'boot', 'grub', 'dejavu-sans-12.pf2')):
                ret = subprocess.call(['grub-mkfont', '/usr/share/fonts/truetype/ttf-dejavu/DejaVuSans.ttf',
                                       '-s=12', '--output=%s' % os.path.join(tmpdir, 'boot', 'grub', 'dejavu-sans-12.pf2')])
                if ret is not 0:
                    raise CreateFailed("Creating GRUB fonts failed.")

            if not os.path.exists(os.path.join(mntdir, 'boot', 'grub', 'dejavu-sans-bold-14.pf2')):
                ret = subprocess.call(['grub-mkfont', '/usr/share/fonts/truetype/ttf-dejavu/DejaVuSans-Bold.ttf',
                                       '-s=14', '--output=%s' % os.path.join(tmpdir, 'boot', 'grub', 'dejavu-sans-bold-14.pf2')])
                if ret is not 0:
                    raise CreateFailed("Creating GRUB fonts failed.")

        #if we previously backed up a grub.cfg or common.cfg
        for path in ['factory/grub.cfg', 'factory/common.cfg']:
            if os.path.exists(os.path.join(mntdir, path + '.old')):
                xorrisoargs.append('-m')
                xorrisoargs.append(os.path.join(mntdir, path) + '*')
                if not os.path.exists(os.path.join(tmpdir, 'factory')):
                    os.makedirs(os.path.join(tmpdir, 'factory'))
                shutil.copy(os.path.join(mntdir, path + '.old'), os.path.join(tmpdir, path))

        #regenerate md5sum file
        if os.path.exists(os.path.join(mntdir, 'md5sum.txt')):
            xorrisoargs.append('-m')
            xorrisoargs.append(os.path.join(mntdir, 'md5sum.txt'))
            regenerate_md5sum(tmpdir, mntdir)

        #ignore any failures on disk
        if os.path.exists(os.path.join(mntdir, 'factory', 'grubenv')):
            xorrisoargs.append('-m')
            xorrisoargs.append(os.path.join(mntdir, 'factory', 'grubenv'))

        #Directories to install
        xorrisoargs.append(tmpdir + '/')
        xorrisoargs.append(mntdir + '/')

        #ISO Creation
        seg1 = subprocess.Popen(xorrisoargs,
                              stderr=subprocess.PIPE,
                              stdout=subprocess.PIPE,
                              universal_newlines=True)
        pipe = seg1.stderr

        fcntl.fcntl(
            pipe.fileno(),
            fcntl.F_SETFL,
            fcntl.fcntl(pipe.fileno(), fcntl.F_GETFL) | os.O_NONBLOCK)

        retval = seg1.poll()
        logging.debug(" create_ubuntu: xorriso debug")
        while (retval is None):
            readx = select.select([pipe.fileno()], [], [])[0]
            if readx:
                output = pipe.read()
                if output.strip():
                    logging.debug(output.strip())
                    split = output.split()
                    if (len(split) > 4):
                        progress = split[4]
                        if (progress[-1:] == '%'):
                            self.report_progress(_('Building ISO'), progress[:-1])
            retval = seg1.poll()
        if retval is not 0:
            logging.error(" create_ubuntu: xorriso exited with a nonstandard return value.")
            logging.error("  cmd: %s" % xorrisoargs)
            logging.error("  stderror: %s" % pipe.readlines())
            logging.error("  error: %s" % output.strip())
            raise CreateFailed("ISO Building exited unexpectedly:\n%s" %
                               output.strip())

    @dbus.service.signal(DBUS_INTERFACE_NAME)
    def report_iso_info(self, version, distributor, release, arch, output_text, platform):
        '''Report ISO information to UI.
        '''
        return True

    @dbus.service.signal(DBUS_INTERFACE_NAME)
    def report_progress(self, this, that=''):
        '''Report progress of something to UI.
        '''
        return True

    @dbus.service.signal(DBUS_INTERFACE_NAME)
    def report_package_info(self, valid, description, error_warning):
        '''Reports package into to U/I'''
        return True

    @dbus.service.signal(DBUS_INTERFACE_NAME)
    def report_package_installed(self, exit_status, msg):
        '''Reports that a package is installed to the U/I'''
        return True
