#!/bin/sh
#
#       <95-set_UTC_TZ.sh>
#
#      This Script will run only run if the manufacturing site was on /proc/cmdline
#
#       This script will update Local Time To UTC(GMT)
#       The offsets in the dictionary below were lifted
#       from the file tztable.xpe used by our sister group.
#
#       Copyright 2008-2011 Dell Inc.
#           Mario Limonciello <Mario_Limonciello@Dell.com>
#           Hatim Amro <Hatim_Amro@Dell.com>
#           Michael E Brown <Michael_E_Brown@Dell.com>
#
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.


# *********** Warning ***************
# the time offset for ICC tz_offset.py was adjusted
# from 5:30 to 5
# ==== Do we need to change this???
ARGLIST=$(cat /proc/cmdline)
for arg in $ARGLIST; do
    if echo "$arg" | grep "MFGSITE=" > /dev/null 2>&1; then
        SITE=$(echo "$arg" | cut -d'=' -f2)
    fi
done

if [ -n "$SITE" ]; then
    cat > /etc/init.d/run-tz-fix <<EOF
#!/bin/sh

# Run tz_offset.py to fix the TZ adjust issue
/usr/bin/python /etc/init.d/tz_offset.py

# need to remove ThySelf here
rm -rf /etc/init.d/run-tz-fix
EOF

    cat > /etc/init.d/tz_offset.py <<EOF
#!/usr/bin/python

# This Script will run only once on
# the first boot.

# This script will update Local Time To UTC(GMT)
# The offsets in the dictionary below were lifted
# from the file tztable.xpe used by our sister group.

#DST is ignored since a large number of locales don't
#use it.  See
# http://en.wikipedia.org/wiki/Daylight_saving_time_around_the_world
# for more information

import os
from datetime import datetime, timedelta

Dict = {'amf':-5, 'apcc':+8, 'bcc':+3, 'ccc':+9, 'emf':+0, 'icc':+5, 'tcc':-6}

# The #VALUE# is substituted at image download time
# Dont edit the following line
EOF
    echo "MFGSITE = '$SITE'" >> /etc/init.d/tz_offset.py
    cat > /etc/init.d/tz_offset.py <<EOF

# Pick a MFGSITE OR set default value
FACTORY_OFFSET = Dict['amf']
if MFGSITE.lower() in Dict:
        FACTORY_OFFSET = Dict[MFGSITE.lower()]

offset = timedelta(hours=FACTORY_OFFSET)
current_date = datetime.today()
new_date = current_date - offset

os.system('date --set="' + new_date.strftime('%d %b %Y %H:%M') + '"')
os.system('hwclock --systohc')
os.remove('/etc/init.d/tz_offset.py')
os.remove('/etc/rc2.d/S02_force_utc')
EOF

    chmod +x /etc/init.d/tz_offset.py
    chmod +x /etc/init.d/run-tz-fix
    # link it to /etc/rc2.d/S02_force_utc
    ln -s /etc/init.d/run-tz-fix /etc/rc2.d/S02_force_utc
fi
