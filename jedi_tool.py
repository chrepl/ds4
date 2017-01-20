'''
This is old script from before fw was dumped.
So just use it as reference...for better info reverse fw dump.
'''

import usb.core
import usb.util
import array
import struct
import sys
import binascii
import time
from construct import *

dev = None

DEV_ID_JEDI = (0x054c, 0x05c4)
DEV_ID_UJEDI = (0x054c, 0x0856)


def wait_for_device(dev_id):
    global dev
    dev = usb.core.find(idVendor=dev_id[0], idProduct=dev_id[1])
    while dev is None:
        time.sleep(1)
        dev = usb.core.find(idVendor=dev_id[0], idProduct=dev_id[1])

#ctrl_transfer(bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None)


class HID_REQ:
    DEV_TO_HOST = usb.util.build_request_type(
        usb.util.CTRL_IN, usb.util.CTRL_TYPE_CLASS, usb.util.CTRL_RECIPIENT_INTERFACE)
    HOST_TO_DEV = usb.util.build_request_type(
        usb.util.CTRL_OUT, usb.util.CTRL_TYPE_CLASS, usb.util.CTRL_RECIPIENT_INTERFACE)
    GET_REPORT = 0x01
    SET_REPORT = 0x09


def hid_get_report(dev, report_id, size):
    assert isinstance(size, int), 'get_report size must be integer'
    assert report_id <= 0xff, 'only support report_type == 0'
    return dev.ctrl_transfer(HID_REQ.DEV_TO_HOST, HID_REQ.GET_REPORT, report_id, 0, size + 1)[1:].tobytes()


def hid_set_report(dev, report_id, buf):
    assert isinstance(buf, (bytes, array.array)
                      ), 'set_report buf must be buffer'
    assert report_id <= 0xff, 'only support report_type == 0'
    buf = struct.pack('B', report_id) + buf
    return dev.ctrl_transfer(HID_REQ.HOST_TO_DEV, HID_REQ.SET_REPORT, (3 << 8) | report_id, 0, buf)

# firmware copies from 0x4000 into a mirror in sram
# we can then read this copy 16bits at a time


def set_flash_mirror_read_pos(offset):
    assert offset < 0x800, 'flash mirror offset out of bounds'
    return hid_set_report(dev, 0x08, struct.pack('>BH', 0xff, offset))


def flash_mirror_read_word():
    return hid_get_report(dev, 0x11, 2)


def flash_mirror_read(offset):
    set_flash_mirror_read_pos(offset)
    return flash_mirror_read_word()


def dump_flash_mirror(path):
    # TODO can't correctly calc checksum for some reason
    print('dumping flash mirror to %s...' % (path))
    with open(path, 'wb') as f:
        for i in range(0, 0x800, 2):
            word = flash_mirror_read(i)
            #print('%03x : %s' % (i, binascii.hexlify(word)))
            f.write(word)
    print('done')


def set_bt_link_info(host_addr, link_key):
    assert len(host_addr) == 6
    assert len(link_key) == 16
    hid_set_report(dev, 0x13, host_addr + link_key)


def get_bt_mac_addrs():
    buf = hid_get_report(dev, 0x12, 6 + 3 + 6)
    ds4_mac, unk, host_mac = buf[0:6], buf[6:9], buf[9:15]
    assert unk == b'\x08\x25\x00'
    # TODO they are BT addrs; "proper MAC format" is byte-reversed
    return (ds4_mac, host_mac)


def bt_enable(enable):
    return hid_set_report(dev, 0xa1, struct.pack('B', 1 if enable else 0))


def dfu_enable(enable):
    return hid_set_report(dev, 0xa2, struct.pack('B', 1 if enable else 0))


class VersionInfo:
    version_info_t = Struct(
        'compile_date' / String(0x10, encoding='ascii'),
        'compile_time' / String(0x10, encoding='ascii'),
        'hw_ver_major' / Int16ul,
        'hw_ver_minor' / Int16ul,
        'sw_ver_major' / Int32ul,
        'sw_ver_minor' / Int16ul,
        'sw_series' / Int16ul,
        'code_size' / Int32ul,
    )

    def __init__(s, buf):
        s.info = s.version_info_t.parse(buf)

    def __repr__(s):
        l = 'Compiled at: %s %s\n'\
            'hw_ver:%04x.%04x\n'\
            'sw_ver:%08x.%04x sw_series:%04x\n'\
            'code size:%08x' % (
                s.info.compile_date, s.info.compile_time,
                s.info.hw_ver_major, s.info.hw_ver_minor,
                s.info.sw_ver_major, s.info.sw_ver_minor, s.info.sw_series,
                s.info.code_size
            )
        return l


def get_version_info():
    return VersionInfo(hid_get_report(dev, 0xa3, 0x30))


def test_cmd(arg0=0xff, arg1=0xff, arg2=0xff):
    return hid_set_report(dev, 0xa0, struct.pack('BBB', arg0, arg1, arg2))


def test_reset():
    # swallow the timeout exception
    try:
        test_cmd(4, 1, 0)
    except:
        pass


def test_play_sin(enable):
    test_cmd(1, 1 if enable else 0)


def beep():
    for i in range(3):
        test_play_sin(True)
        time.sleep(.1)
        test_play_sin(False)
        time.sleep(.1)


def dfu_send_fw_block(is_last, offset, data):
    ujedi_fw_block_t = Struct(
        'is_last' / Int8ul,
        'offset' / Int32ul,
        'data' / PrefixedArray(Int8ul, Int8ul)
    )
    return hid_set_report(dev, 0xf0, ujedi_fw_block_t.build(Container(is_last=is_last, offset=offset, data=data)))

wait_for_device(DEV_ID_JEDI)
# this is needed to tell usbhid on nix to go fuck itself
#'''
if dev.is_kernel_driver_active(0):
    try:
        dev.detach_kernel_driver(0)
    except usb.core.USBError as e:
        sys.exit('Could not detatch kernel driver: %s' % str(e))
#'''
# dev.set_configuration()
#dev.set_interface_altsetting(0, 0)
#'''
bt_addrs = get_bt_mac_addrs()
print('ds4 bt mac: %s host bt mac: %s' %
      (binascii.hexlify(bt_addrs[0]), binascii.hexlify(bt_addrs[1])))
print(get_version_info())
exit()
#'''

#set_bt_link_info(b'\0' * 6, b'\0' * 16)

'''
dfu_enable(True)
test_reset()
wait_for_device(DEV_ID_UJEDI)
print(dev)
exit()
#'''
'''
print('sending fw...')
for i in range(0, 0x38000, 0x38):
    while True:
        try:
            dfu_send_fw_block(0, i, b'\xff' * 0x38)
            print(dev.read(0x84, 0x40))
            break
        except:
            time.sleep(.1)
# also exits dfu
print('exit dfu...')
time.sleep(1)
dfu_send_fw_block(1, 0, b'\0' * 0x38)
#'''
