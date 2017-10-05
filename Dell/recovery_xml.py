#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# «recovery_xml» - Helper Class for parsing and using a bto.xml
#
# Copyright (C) 2010-2011, Dell Inc.
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

import xml.dom.minidom
import codecs
import os
import sys

if sys.version >= '3':
    text_type = str
    binary_type = bytes
else:
    text_type = unicode
    binary_type = str

def utf8str(old):
    if isinstance(old, text_type):
        return old
    else:
        return text_type(binary_type(old), 'utf-8', errors='ignore')

class BTOxml:
    def __init__(self):
        self.dom = None
        self.new = False
        self.load_bto_xml()

    def set_base(self, name, md5=''):
        """Sets the base image"""
        self.replace_node_contents('base', name)
        if md5:
            self.dom.getElementsByTagName('base')[0].setAttribute('md5', md5)

    def append_fish(self, fish_type, name, md5='', srv=''):
        """Appends a fish package"""
        elements = self.dom.getElementsByTagName('fish')
        new_element = self.dom.createElement(fish_type)
        if md5:
            new_element.setAttribute('md5', md5)
        if srv:
            new_element.setAttribute('srv', srv)
        new_node = self.dom.createTextNode(name)
        new_element.appendChild(new_node)
        elements[0].appendChild(new_element)

    def fetch_node_contents(self, tag):
        """Fetches all children of a tag"""
        elements = self.dom.getElementsByTagName(tag)
        values = text_type('')
        if len(elements) > 1:
            values = []
        if elements:
            for element in elements:
                child = element.firstChild
                if child:
                    if len(elements) > 1:
                        values.append(child.nodeValue.strip())
                    else:
                        values = child.nodeValue.strip()
        return values

    def replace_node_contents(self, tag, new):
        """Replaces a node contents (that we assume exists)"""
        elements = self.dom.getElementsByTagName(tag)
        if not elements:
            print("Missing elements for tag")
            return
        if elements[0].hasChildNodes():
            for node in elements[0].childNodes:
                elements[0].removeChild(node)
        noob = self.dom.createTextNode(utf8str(new))
        elements[0].appendChild(noob)

    def load_bto_xml(self, fname=None):
        """Initialize an XML file into memory"""
        def create_top_level(dom):
            """Initializes a top level document"""
            element = dom.createElement('bto')
            dom.appendChild(element)
            return element

        def create_tag(dom, tag, append_to):
            """Create a subtag as necessary"""
            element = dom.getElementsByTagName(tag)
            if element:
                element = element[0]
            else:
                element = dom.createElement(tag)
                append_to.appendChild(element)
            return element

        if fname:
            self.new = False
            try:
                if os.path.exists(fname):
                    with open(fname, 'rb') as f:
                        fname = f.read()
                self.dom = xml.dom.minidom.parseString(utf8str(fname))
            except xml.parsers.expat.ExpatError:
                print("Damaged XML file, regenerating")

        if not (fname and self.dom):
            self.new = True
            self.dom = xml.dom.minidom.Document()

        #test for top level bto object
        if self.dom.firstChild and self.dom.firstChild.localName != 'bto':
            self.dom.removeChild(self.dom.firstChild)
        if not self.dom.firstChild:
            bto = create_top_level(self.dom)
        else:
            bto = self.dom.getElementsByTagName('bto')[0]

        #create all our second and third level tags that are supported
        for tag in ['date', 'versions', 'base', 'fid', 'fish', 'logs']:
            element = create_tag(self.dom, tag, bto)
            subtags = []
            if tag == 'versions':
                subtags = ['os', 'iso', 'generator', 'bootstrap', 'ubiquity', 'revision', 'platform']
            elif tag == 'fid':
                subtags = ['git_tag', 'deb_archive']
            elif tag == 'logs':
                subtags = ['syslog', 'debug']
            for subtag in subtags:
                create_tag(self.dom, subtag, element)

    def write_xml(self, fname):
        """Writes out a BTO XML file based on the current data"""
        with codecs.open(fname, 'w', 'utf-8') as wfd:
            if self.new:
                self.dom.writexml(wfd, "", "  ", "\n", encoding='utf-8')
            else:
                self.dom.writexml(wfd, encoding='utf-8')
