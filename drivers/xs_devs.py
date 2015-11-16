#!/usr/bin/python
#
# Copyright (C) Citrix Systems Inc.
#
# This program is free software; you can redistribute it and/or modify 
# it under the terms of the GNU Lesser General Public License as published 
# by the Free Software Foundation; version 2.1 only.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
# Device tagging utility functions
#

import subprocess
import sys
import os
import re
from pyudev import Context, Device

XSDEVPATH = "/var/lib/xs_devs"
UDEVADM = "/usr/sbin/udevadm"
DMSETUP = "/usr/sbin/dmsetup"

class DeviceNotUsable(Exception):
    def __init__(self, name):
        self.name = name
    def __str__(self):
        return "Device '%s' not usable (no :xs_dev: tag)" % self.name

class DeviceTaggingError(Exception):
    def __init__(self, name, system):
        self.name = name
        self.system = system
    def __str__(self):
        return "Failed to tag device '%s' with '%s'" % (self.name, self.system)

def _try_unlink(path):
    try:
        os.unlink(path)
    except:
        pass

def _call(cmd_args):
    p = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True)
    stdout, stderr = p.communicate()
    return stdout, stderr, p.returncode

def _settle():
    cmd = [ UDEVADM, "settle" ]
    _call(cmd)

def _trigger_change(devname):
    cmd = [ UDEVADM, "trigger", "--sysname-match=%s" % devname ]
    _call(cmd)

def _load_dev(devname, ctx=None):
    if ctx is None:
        ctx = Context()
    return ctx, Device.from_name(ctx, "block", devname)

def _tag_device(devname, system):
    sysdir = os.path.join(XSDEVPATH, "devs-%s" % system)
    tagfile = os.path.join(sysdir, devname)

    # Ensure system directory exists
    if not os.path.exists(sysdir):
        os.makedirs(sysdir)

    # "Touch" a tag file
    open(tagfile, 'a').close()

    _trigger_change(devname)

def untag_device(devname, system = None):
    # Attempt to get parent device
    try:
        ctx, dev = _load_dev(devname)
        devparent = dev.find_parent('block')
        if devparent:
            devname = os.path.basename(devparent.device_node)
    except:
        pass
        # XXX: If the caller originally tagged "sdd5", we would have instead
        #  tagged "sdd". If the device then went away and the caller untagged
        #  "sdd5", we would be failing to find the parent here at untag().
        #  That could potentially leave a stale "sdd" tag in XSDEVPATH. This
        #  probably needs to be addressed if callers start using partitions.

    if system is None:
        # Untag from everywhere if "system" was not specified
        for dirname, dirlist, filelist in os.walk(XSDEVPATH):
            if os.path.basename(dirname).startswith("devs-"):
                tagfile = os.path.join(dirname, devname)
                _try_unlink(tagfile)
    else:
        # Untag specifically from a system
        sysdir = os.path.join(XSDEVPATH, "devs-%s" % system)
        tagfile = os.path.join(sysdir, devname)
        _try_unlink(tagfile)

    _trigger_change(devname)

def tag_device(devname, system, check=True):
    # Ensure device exists
    ctx, dev = _load_dev(devname)

    # Use parent disk if partition
    devparent = dev.find_parent('block')
    if devparent:
        devname = os.path.basename(devparent.device_node)

    # Tag device
    _tag_device(devname, system)
    if not check:
        return

    # Reload device
    _settle()
    ctx, dev = _load_dev(devname, ctx)

    # Check if tagging succeeded
    tag = "inuse_%s" % system
    if not tag in dev.tags:
        untag_device(devname, system)
        # NB. must remove tag file or udev will automatically tag this
        #     device in the future (when the other system's tag is gone)
        raise DeviceTaggingError(devname, system)

def refresh_dm(devname):
    # Fetch the device mapper metadata
    cmd = [ DMSETUP, "info", "-c", "-o", "name,blkdevs_used", "--noheadings",
                     "/dev/%s" % devname ]
    stdout = _call(cmd)[0].rstrip()
    name, devs = stdout.split(":")

    # Don't do much for VDIs or SRs
    if name.startswith("XSLocalEXT"):
        print "sr"
        return
    if name.startswith("VG_XenStorage"):
        print "vdi"
        return

    # Assume it is a multipath device and tag devs accordingly
    for dev in devs.split(","):
        tag_device(dev, "mpath", check=False)
    print "mpath"

def usage():
    print "Usage: %s tag <dev_name> <system>" % sys.argv[0]
    print "           - tag 'dev_name' as in use by 'system'"
    print "           - ex: %s tag sdb xs" % sys.argv[0]
    print "       %s untag <dev_name> [system]" % sys.argv[0]
    print "           - untag 'dev_name' as no longer used by 'system'"
    print "           - ex: %s untag sdb xs" % sys.argv[0]
    print "       %s show <dev_name>" % sys.argv[0]
    print "           - show all udev tags for 'dev_name'"
    print "           - ex: %s show sdb" % sys.argv[0]
    print "       %s refresh <dm_dev_name>" % sys.argv[0]
    print "           - update tags for multipath device"
    print "           - ex: %s refresh dm-1"
    sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) == 4:
        if sys.argv[1] == "tag":
            tag_device(sys.argv[2], sys.argv[3])
        elif sys.argv[1] == "untag":
            untag_device(sys.argv[2], sys.argv[3])
        else:
            usage()
    elif len(sys.argv) == 3:
        if sys.argv[1] == "show":
            ctx, dev = _load_dev(sys.argv[2])
            for tag in dev.tags:
                print tag
        elif sys.argv[1] == "untag":
            untag_device(sys.argv[2])
        elif sys.argv[1] == "refresh":
            refresh_dm(sys.argv[2])
        else:
            usage()
    else:
        usage()
    sys.exit(0)
