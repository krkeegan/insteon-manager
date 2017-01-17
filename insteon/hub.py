import xml.etree.ElementTree as ET
import time
import threading
import queue

import requests

from .helpers import BYTE_TO_HEX, ID_STR_TO_BYTES
from .plm import Modem


def hub_thread(hub):
    prev_end_pos = -1
    last_bytestring = ''

    while threading.main_thread().is_alive():
        # Read First
        bytestring = ''
        current_end_pos = 0

        # Get Buffer Contents
        response = requests.get('http://' + hub.ip + ':' +
                                hub.tcp_port + '/buffstatus.xml',
                                auth=requests.auth.HTTPBasicAuth(
                                    hub.user,
                                    hub.password))

        root = ET.fromstring(response.text)
        for response in root:
            if response.tag == 'BS':
                bytestring = response.text
                break

        # Place buffer in sequential order
        current_end_pos = int(bytestring[-2:], 16)
        bytestring = bytestring[current_end_pos:-2] + \
            bytestring[:current_end_pos]

        if last_bytestring != '' and prev_end_pos >= 0:
            new_length = current_end_pos - prev_end_pos
            new_length = (200 + new_length) if new_length < 0 else new_length
            verify_bytestring = bytestring[190 - new_length: 200 - new_length]
            if new_length > 0 and last_bytestring == verify_bytestring:
                # print(bytestring[-new_length:])
                hex_string = bytestring[-new_length:]
                hex_data = bytearray.fromhex(hex_string)
                hub._read_queue.put(bytearray(hex_data))

        last_bytestring = bytestring[-10:]
        prev_end_pos = current_end_pos

        # Now write
        if not hub._write_queue.empty():
            command = hub._write_queue.get()
            cmd_str = BYTE_TO_HEX(command)
            url = ('http://' + hub.ip + ':' +
                   hub.tcp_port + '/3?' + cmd_str + '=I=3')
            response = requests.get(url,
                                    auth=requests.auth.HTTPBasicAuth(
                                        hub.user,
                                        hub.password)
                                    )
            last_bytestring = '0000000000'
            prev_end_pos = 0

        # Only hammering at hub server three times per second.  Seems to result
        # in the PLM ACK and device message arriving together, but no more than
        # that. Could consider slowing down, but waiting too long could cause
        # the buffer to overflow and would slow down our responses.  Would also
        # need to increase the hub ack_time accordingly too.
        time.sleep(.3)


class Hub(Modem):

    def __init__(self, core, **kwargs):
        super().__init__(core, **kwargs)
        self.ack_time = 750
        self.attribute('type', 'hub')
        if 'device_id' in kwargs:
            id_bytes = ID_STR_TO_BYTES(kwargs['device_id'])
            self._dev_addr_hi = id_bytes[0]
            self._dev_addr_mid = id_bytes[1]
            self._dev_addr_low = id_bytes[2]
        self._read_queue = queue.Queue()
        self._write_queue = queue.Queue()
        threading.Thread(target=hub_thread, args=[self]).start()
        self.setup()

    @property
    def ip(self):
        return self.attribute('ip')

    @ip.setter
    def ip(self, value):
        self.attribute('ip', value)
        return self.attribute('ip')

    @property
    def tcp_port(self):
        return self.attribute('tcp_port')

    @tcp_port.setter
    def tcp_port(self, value):
        self.attribute('tcp_port', value)
        return self.attribute('tcp_port')

    @property
    def user(self):
        return self.attribute('user')

    @user.setter
    def user(self, value):
        self.attribute('user', value)
        return self.attribute('user')

    @property
    def password(self):
        return self.attribute('password')

    @password.setter
    def password(self, value):
        self.attribute('password', value)
        return self.attribute('password')

    def _read(self):
        if not self._read_queue.empty():
            self._read_buffer.extend(self._read_queue.get())

    def _write(self, msg):
        self._write_queue.put(msg)
