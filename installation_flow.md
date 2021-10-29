# Installation Flow

Although the installer for Dell recovery media is the same as standard Ubuntu
(*ubiquity*), the installation flow varies.

## Standard Ubuntu installation

A standard Ubuntu installation from a USB key only has one installation *phase*.
  The user is prompted for installation options such as disk, timezone, keyboard
   and username and installation runs in the background.

When the install is complete, upon rebooting the machine they are brought to a
Ubuntu login screen and can use the computer.

## *Standard* OEM installation

A standard OEM Ubuntu installation will be preseeded to operate in an automated
fashion.  Any questions that are not answered in the preseeding process will be
prompted by the GUI.  After installation is finished, the system will either be
shut down or rebooted into **OEM-Config mode**.

In **OEM-Config mode** the user will be prompted for questions that might not be
 the same as those preseeded.  For example, Keyboard layout, Timezone or
 Language.

After completing OEM-Config, the user is brought to an Ubuntu login screen.

## Dell OEM installation

The Dell OEM installation is split across ***three** distinct phases*.
It is split this way to be able to support an archicture with a factory recovery
 partition on the hard disk.
This factory recovery partition is used both for Dell manufacturing as well as
for customer based recovery.

### Phase 1: Prepare partitions and content

The first phase prepares the disk and loads the recovery partition content onto
it.  This can be approached from 3 different methods.

#### Dell factory

1. In the Dell factory we integrate with existing manufacturing tools, and these
 tools create initial partition layout (ESP and Recovery partition) and load the
  content onto the disk.

2. Other manufacturing tools also configure next boot (`BootOrder`/`BootNext`
 variables)
3. Other manufacturing tools control reboot cycle.
4. On the next boot we’ll boot directly into phase 2.

#### Customer USB recovery

1. If customer boots up USB recovery disk, it will come to a prompt selecting
which disk to use to install to.
2. Customer presses next, and disk is wiped, content copied to ESP and recovery
 partition
3. Boot variables set for next boot
4. System automatically reboots into phase 2.

#### Customer HDD recovery

1. GUI tool is offered in OS that will change grub next boot option to a recove
ry option we left to boot recovery partition.
2. Customer can also interrupt GRUB silent menu to select this option.
3. Customer agrees to wipe content.
4. System continues to phase 2.

### Phase 2: Install Ubuntu

This part of the installation is fully automated.  The OS is booted from the rec
overy partition and the Ubiquity installer will launch.

Ubiquity will create additional partitions to install into, and all files will
be copied in.  Any applicable drivers and updated packages distributed in
`/debs` of the recovery partition will be installed by Ubiquity and
dell-recovery plugins.

After Ubiquity finishes, a set of post-install scripts provided by Dell in the
`/scripts` directory of the recovery partition will run to complete the install.

When this phase is run during manufacturing, the system will return to Dell
manufacturing process.

### Phase 3: Out of box experience

In a Dell manufactured machine, this is the first phase that a customer will
actually see.

As with standard OEM installation, the customer will select the Language,
Timezone, Keyboard Layout, a username and a password.

However specific to the Dell OEM install an additional page will prompt to
create USB recovery media to use in the event of a failure.
