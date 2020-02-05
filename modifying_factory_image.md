Modifying Factory images
----
Factory images (.ISO) can be modified to include any additional Debian packages or to run extra scripts after the image installation is complete.

Development purposes
--

For development purposes, additional `.deb` packages can be placed onto a USB stick with a factory image already written to it if the USB stick is formatted as FAT32.

1. Create the directories `debs/main` on the USB stick if they don't already exist.
2.  Copy all .deb packages and their dependencies into the `debs/main` directory on the USB disk.

Production purposes
--
To write these packages into a new ISO image, the **Dell Recovery** tool needs to be executed in *builder* mode.  In *builder* mode it can take an existing factory ISO image and modify it.

From an Ubuntu machine with `dell-recovery` installed, execute:

`# dell-recovery --builder`

The GUI will ask for an existing factory ISO image.
On the (driver) FISH packages page, additional `.deb` files can be selected.

If you have a lot of packages, alternatively a command line version is available
that all `.deb` packages can be declared in a newline delimitted text file.

`# /usr/share/dell/bin/dell-bto-autobuilder`

The arguments are listed in the *--help* listing.
