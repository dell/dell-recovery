Dell Recovery Media Creator
----
[![Build Status](https://travis-ci.org/dell/dell-recovery.png)](https://travis-ci.org/dell/dell-recovery)

The Dell Recovery media creation tool supports two different usage modes,
"End User Mode" and "Builder Mode".  In End User mode, the tool will simply
create an image from an existing recovery partition with no customizations.
In builder mode, the tool allows modifying the source of the base image,
the source of the framework, as well as injection of additional content.

# Tool Modes

End User Mode
---
When a customer receives a Dell machine that has been factory shipped
with Linux, there will be an icon available in GNOME shell to launch this
tool.  They will be prompted for what type of media they would like to create.

Out of box experience mode
---
If a DVD burner or USB port is found on the machine, customers will be offered
to create media at the end of the out of box experience.

Media builder mode
---
In builder mode, the user will be offered a variety of options that allow them to create ISOs based upon
different snapshots of release upon standard Ubuntu media.

The latest information on how to use builder mode will be documented within the integrated help dialog.

# Flow

Due to the nature of including a recovery partition, the installation flow varies from the standard Ubuntu
installation.
It is further documented [here](installation_flow.md).

Ubiquity
---
Dell recovery is built with an integrated Ubiquity plugin.  It is branched with each Ubuntu LTS release and
has code that will tightly integrate with Ubiquity for factory installation.  Documentation for all of the
features in Ubiquity mode and how to create packages to support it are stored outside of the dell-recovery
tree.

Modifying a factory image
---
Information about how to modify a factory image are available [here](modifying_factory_image.md).
