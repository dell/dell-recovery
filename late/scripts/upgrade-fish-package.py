#!/usr/bin/python3
# A helper script to upgrade an existing FISH package to new format (2012+)

import atexit
import tempfile
import tarfile
import argparse
import os.path
import lsb_release
from Dell.recovery_common import walk_cleanup
from Dell.recovery_xml import BTOxml
import sys

parser = argparse.ArgumentParser()
parser.add_argument('fname', nargs='?')
parser_args = parser.parse_args()

if not parser_args.fname or not os.path.exists(parser_args.fname):
    print("Call this script with the path to an existing FISH package as an input")
    sys.exit(1)

if parser_args.fname.endswith('.fish.tar.gz'):
    print ("This is likely already upgraded, please provide a package that doesn't end in .fish.tar.gz")
    sys.exit(1)

description = input("Enter a description for this FISH package.\n")

#extract old FISH package
package_dir = tempfile.mkdtemp()
atexit.register(walk_cleanup, package_dir)
rfd = tarfile.open(parser_args.fname)
rfd.extractall(package_dir)

xml_file = os.path.join(package_dir, 'prepackage.dell')

#write XML object
xml_obj = BTOxml()
if os.path.exists(xml_file):
    xml_obj.load_bto_xml(xml_file)
xml_obj.replace_node_contents('os', lsb_release.get_lsb_information()['RELEASE'])
xml_obj.append_fish('driver', description, 'n/a')
xml_obj.write_xml(xml_file)

#repack FISH package
output_dirname = os.path.dirname(parser_args.fname)
output_fname = parser_args.fname.split('.tar.gz')[0].split('.tgz')[0] + '.fish.tar.gz'
wfd = tarfile.open(output_fname, 'w:gz')
for obj in os.listdir(package_dir):
    wfd.add(os.path.join(package_dir, obj), obj)

print ("Wrote updated FISH package to %s") % output_fname
print ("File contents:")
wfd.list()
wfd.close()

