from insteon_mngr.trigger import InsteonTrigger, PLMTrigger


class BaseSequence(object):
    '''The base class inherited by all sequnce objects'''
    def __init__(self):
        self._success_callback = []
        self._failure_callback = []
        self._complete = False
        self._success = False

    @property
    def is_complete(self):
        '''Returns true if the sequence is complete, else false'''
        return self._complete

    @property
    def is_success(self):
        '''Returns true of the sequence completed successfully, else false'''
        return self._success

    def add_success_callback(self, callback):
        '''Add a callback to be called on success of the sequence'''
        if callback is not None:
            self._success_callback.append(callback)

    def add_failure_callback(self, callback):
        '''Add a callback to be called on failure of the sequence'''
        if callback is not None:
            self._failure_callback.append(callback)

    def _on_success(self):
        self._complete = True
        self._success = True
        for callback in self._success_callback:
            callback()

    def _on_failure(self):
        self._complete = True
        self._success = False
        for callback in self._failure_callback:
            callback()

    def start(self):
        '''Start the sequence'''
        return NotImplemented


class StatusRequest(BaseSequence):
    '''Used to request the status of a device.  The neither cmd_1 nor cmd_2 of the
    return message can be predicted so we just hope it is the next direct_ack that
    we receive'''
    # TODO what would happen if this message was never acked?  Would this
    # trigger remain in waiting and fire the next time we received an ack?
    # should add a maximum timer to the BaseSequence that triggers failure
    def __init__(self, group=None):
        super().__init__()
        self._group = group

    def start(self):
        trigger_attributes = {
            'msg_type': 'direct_ack',
            'plm_cmd': 0x50,
            'msg_length': 'standard'
        }
        trigger = InsteonTrigger(device=self._group.device,
                                 attributes=trigger_attributes)
        trigger.trigger_function = lambda: self._process_status_response()
        trigger.name = self._group.device.dev_addr_str + 'status_request'
        trigger.queue()
        self._group.device.send_command('light_status_request')

    def _process_status_response(self):
        msg = self._group.device.last_rcvd_msg
        base_group = self._group.device.get_object_by_group_num(self._group.device.base_group_number)
        base_group.set_cached_state(msg.get_byte_by_name('cmd_2'))
        aldb_delta = msg.get_byte_by_name('cmd_1')
        if self._group.device.attribute('aldb_delta') != aldb_delta:
            print('aldb has changed, rescanning')
            self._group.device.query_aldb(success=self._on_success,
                                          failure=self._on_failure)
        else:
            self._on_success()


class SetALDBDelta(StatusRequest):
    '''Used to get and store the tracking value for the ALDB Delta'''
    def __init__(self, group=None):
        super().__init__()
        self._group = group

    def _process_status_response(self):
        msg = self._group.device.last_rcvd_msg
        self._group.set_cached_state(msg.get_byte_by_name('cmd_2'))
        self._group.device.set_aldb_delta(msg.get_byte_by_name('cmd_1'))
        print('cached aldb_delta')
        self._on_success()


class WriteALDBRecord(BaseSequence):
    '''Sequence to write an aldb record to a device.'''
    def __init__(self, group=None):
        super().__init__()
        self._group = group
        self._controller = False
        self._linked_group = None
        self._d1 = 0x00
        self._d2 = 0x00
        self._d3 = None
        self._address = None
        self._in_use = True

    @property
    def in_use(self):
        return self._in_use

    @in_use.setter
    def in_use(self, use):
        self._in_use = use

    @property
    def controller(self):
        '''If true, this device is the controller, false the responder.
        Defaults to false.'''
        return self._controller

    @controller.setter
    def controller(self, boolean):
        self._controller = boolean

    @property
    def linked_group(self):
        '''Required. The group on the other end of this link.'''
        return self._linked_group

    @linked_group.setter
    def linked_group(self, device):
        self._linked_group = device

    @property
    def data1(self):
        '''The device specific byte to write to the data1 location defaults
        to 0x00.'''
        return self._d1

    @data1.setter
    def data1(self, byte):
        self._d1 = byte

    @property
    def data2(self):
        '''The device specific byte to write to the data2 location defaults
        to 0x00.'''
        return self._d2

    @data2.setter
    def data2(self, byte):
        self._d2 = byte

    @property
    def data3(self):
        '''The device specific byte to write to the data3 location defaults
        to the group of the device.'''
        ret = self._group.group_number
        if self._d3 is not None:
            ret = self._d3
        return ret

    @data3.setter
    def data3(self, byte):
        self._d3 = byte

    @property
    def key(self):
        # pylint: disable=E1305
        ret = None
        if self._address is not None:
            ret = ('{:02x}'.format(self._address[0], 'x').upper() +
                   '{:02x}'.format(self._address[1], 'x').upper())
        return ret

    @key.setter
    def key(self, value):
        msb = int(value[0:2], 16)
        lsb = int(value[2:4], 16)
        self._address = bytearray([msb, lsb])

    @property
    def address(self):
        '''The address to write to, as a bytearray, if not specified will use
        the first empty address.'''
        ret = self._address
        if self._address is None:
            key = self._group.device.aldb.get_first_empty_addr()
            msb = int(key[0:2], 16)
            lsb = int(key[2:4], 16)
            ret = bytearray([msb, lsb])
        return ret

    @address.setter
    def address(self, address):
        self._address = address

    @property
    def msb(self):
        return self.address[0]

    def _compiled_record(self):
        msg_attributes = {
            'msb': self.address[0],
            'lsb': self.address[1]
        }
        if not self.in_use:
            msg_attributes['link_flags'] = 0x02
            msg_attributes['group'] = 0x00
            msg_attributes['data_1'] = 0x00
            msg_attributes['data_2'] = 0x00
            msg_attributes['data_3'] = 0x00
            msg_attributes['dev_addr_hi'] = 0x00
            msg_attributes['dev_addr_mid'] = 0x00
            msg_attributes['dev_addr_low'] = 0x00
        elif self.controller:
            msg_attributes['link_flags'] = 0xE2
            msg_attributes['group'] = self._group.group_number
            msg_attributes['data_1'] = self.data1  # hops I think
            msg_attributes['data_2'] = self.data2  # unkown always 0x00
            # group of controller device base_group_numberfor 0x01, 0x00 issue
            msg_attributes['data_3'] = self.data3
            msg_attributes['dev_addr_hi'] = self._linked_group.device.dev_addr_hi
            msg_attributes['dev_addr_mid'] = self._linked_group.device.dev_addr_mid
            msg_attributes['dev_addr_low'] = self._linked_group.device.dev_addr_low
        else:
            msg_attributes['link_flags'] = 0xA2
            msg_attributes['group'] = self._linked_group.group_number
            msg_attributes['data_1'] = self.data1  # on level
            msg_attributes['data_2'] = self.data2  # ramp rate
            # group of responder, i1 = 00, i2 = 01
            msg_attributes['data_3'] = self.data3
            msg_attributes['dev_addr_hi'] = self._linked_group.device.dev_addr_hi
            msg_attributes['dev_addr_mid'] = self._linked_group.device.dev_addr_mid
            msg_attributes['dev_addr_low'] = self._linked_group.device.dev_addr_low
        return msg_attributes

    def start(self):
        '''Starts the sequence to write the aldb record'''
        if self.linked_group is None and self.in_use:
            print('error no linked_group defined')
        else:
            self._group.device.aldb.aldb_sequence.add_sequence(self)

    def aldb_start(self):
        self._perform_write()

    def _perform_write(self):
        if self.key is None:
            self.key = self._group.device.aldb.get_first_empty_addr()
        record = self._group.device.aldb.get_record(self.key)
        record.link_sequence = self


class AddPLMtoDevice(BaseSequence):
    def __init__(self, device=None):
        super().__init__()
        self._device = device

    def start(self):
        # Put the PLM in Linking Mode
        # queues a message on the PLM
        message = self._device.plm.create_message('all_link_start')
        plm_bytes = {
            'link_code': 0x01,
            'group': 0x00,
        }
        message.insert_bytes_into_raw(plm_bytes)
        message.plm_success_callback = self._add_plm_to_dev_link_step2
        message.msg_failure_callback = self._add_plm_to_dev_link_fail
        self._device.plm.queue_device_msg(message)

    def _add_plm_to_dev_link_step2(self):
        # Put Device in linking mode
        message = self._device.create_message('enter_link_mode')
        dev_bytes = {
            'cmd_2': 0x00
        }
        message.insert_bytes_into_raw(dev_bytes)
        message.insteon_msg.device_success_callback = (
            self._add_plm_to_dev_link_step3
        )
        message.msg_failure_callback = self._add_plm_to_dev_link_fail
        self._device.queue_device_msg(message)

    def _add_plm_to_dev_link_step3(self):
        trigger_attributes = {
            'from_addr_hi': self._device.dev_addr_hi,
            'from_addr_mid': self._device.dev_addr_mid,
            'from_addr_low': self._device.dev_addr_low,
            'link_code': 0x01,
            'plm_cmd': 0x53
        }
        trigger = PLMTrigger(plm=self._device.plm,
                             attributes=trigger_attributes)
        trigger.trigger_function = lambda: self._add_plm_to_dev_link_step4()
        trigger.name = self._device.dev_addr_str + 'add_plm_step_3'
        trigger.queue()
        print('device in linking mode')

    def _add_plm_to_dev_link_step4(self):
        print('plm->device link created')
        self._device.query_aldb(success=self._on_success,
                                failure=self._on_failure)

    def _add_plm_to_dev_link_fail(self):
        print('Error, unable to create plm->device link')
        self._on_failure()


class InitializeDevice(BaseSequence):
    '''This sequence performs a series of steps to gather all of the basic
    information about a device.  It is generic enough to be run on any known
    insteon device.'''
    def __init__(self, device=None):
        super().__init__()
        self._device = device

    def start(self):
        if self._device.attribute('engine_version') is None:
            # Trigger will only fire on an ack, not an i2cs nack
            trigger = InsteonTrigger(device=self._device,
                                     command_name='engine_version')
            trigger.trigger_function = lambda: self._init_step_2()
            trigger.name = self._device.dev_addr_str + 'init_step_1'
            trigger.queue()
            self._device.send_handler.get_engine_version()
        else:
            self._init_step_2()

    def _init_step_2(self):
        if (self._device.dev_cat is None or
                self._device.sub_cat is None or
                self._device.firmware is None):
            trigger_attributes = {
                'cmd_1': 0x01,
                'insteon_msg_type': 'broadcast'
            }
            trigger = InsteonTrigger(device=self._device,
                                     attributes=trigger_attributes)
            trigger.trigger_function = lambda: self._device.send_handler.get_status()
            trigger.name = self._device.dev_addr_str + 'init_step_2'
            trigger.queue()
            self._device.send_handler.get_device_version()
        else:
            # TODO this is really only necessary to check aldb delta
            self._device.send_handler.get_status()
