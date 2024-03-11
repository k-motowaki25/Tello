import socket
import struct
from struct import Struct
import crcmod
import datetime
import threading


class Tello:
    CMD_LIST = {'takeoff': 84, 'land': 85, 'stick': 80, 'get_ssid': 17}
    PAC_TYPE_LIST = {'takeoff': 0x68, 'land': 0x68, 'stick': 0x60, 'get_ssid': 0x48}
    VIDEO_PORT = 6038
    ADDRESS = ('192.168.10.1', 8889)

    def __init__(self):
        self.CRC8_FUNC = crcmod.mkCrcFun(0x131, rev=True, initCrc=0x77, xorOut=0x00)
        self.CRC16_FUNC = crcmod.mkCrcFun(0x11021, rev=True, initCrc=0x3692, xorOut=0x0000)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rec_thread = threading.Thread(target=self.receive_data)
        self.rec_thread.start()

        self.sequence = 1
        self.init_state()

        self.connect()
    
    def init_state(self):
        self.speed = 0
        self.ssid = 'unknown'
        self.uptime = 0
        self.height = 0
        self.x = self.y = self.z = 0
        self.vx = self.vy = self.vz = 0
        self.flytime = 0
        self.battery = 0
        self.wifi = 0
        self.get_command = 0
        self.rec_command_id = 0

    def connect(self):
        conn_req_cmd = 'conn_req:'.encode() + self.VIDEO_PORT.to_bytes(2, 'little')
        self.sock.sendto(conn_req_cmd, self.ADDRESS)
        self.send_to('get_ssid')

    def send_to(self, cmd, move=[1024]*4):
        data = []
        if cmd == 'land':
            data = [0x00]
        elif cmd == 'stick':
            self.sequence = 0
            data = self.move_to(move)

        packet = self.build_packet(self.PAC_TYPE_LIST[cmd], self.CMD_LIST[cmd], self.sequence, data)
        self.sock.sendto(self.packet_to_binary(packet), self.ADDRESS)
        # print(cmd, packet)
        self.sequence += 1

    def packet_to_binary(self, packet):
        packet_struct = Struct(f'!{len(packet)}B')
        return packet_struct.pack(*packet)

    def build_packet(self, pac_type, cmd_id, seq_id, data=[]):
        size = 11 + len(data)
        packet = [0] * size
        packet[0] = 0xcc
        packet[1:3] = list((size << 3).to_bytes(2, 'little'))
        packet[3] = self.CRC8_FUNC(bytes(packet[0:3]))
        packet[4] = pac_type
        packet[5:7] = list(cmd_id.to_bytes(2, 'little'))
        packet[7:9] = list(seq_id.to_bytes(2, 'little'))
        packet[9:-2] = data
        crc16 = self.CRC16_FUNC(bytes(packet[0:-2]))
        packet[-2:] = list(crc16.to_bytes(2, 'little'))
        return packet

    def move_to(self, move):
        data = [0] * 11
        stick_data = (self.speed << 44) + (move[0] << 33) + (move[1] << 22) + (move[2] << 11) + move[3]
        data[:6] = list(stick_data.to_bytes(6, 'little'))
        data[6:] = self.get_current_time()
        return data

    def get_current_time(self):
        now = datetime.datetime.now()
        h, m, s = now.hour, now.minute, now.second
        ms = round(now.microsecond / 1000)
        return [h, m, s, *list(ms.to_bytes(2, 'little'))]

    def speed_switch(self):
        self.speed = int(not self.speed)
    
    def receive_data(self):
        while True:
            try:
                data, _ = self.sock.recvfrom(1518)
                rec = struct.unpack('!' + 'B'*len(data), data)
                self.rec_command_id = int(f'{rec[6]}{rec[5]}')
                match self.rec_command_id:
                    case 17:
                        self.ssid = data[11:-2].decode('utf-8')
                    case 26:
                        self.wifi = int(f'{rec[10]}{rec[9]}')
                    case 86:
                        self.parse_data(rec)
            except Exception as e:
                print(f'Error receiving data: {e}')
    
    def parse_data(self, rec):
        self.uptime = rec[7] + 255*rec[8]
        self.height = rec[9] - rec[10]
        self.vy = rec[11] - rec[12]
        self.vx = rec[13] - rec[14]
        self.vz = -(rec[15] - rec[16])
        self.x += round(self.vx / 100, 1)
        self.y += round(self.vy / 100, 1)
        self.z += round(self.vz / 100, 1)
        self.flytime = rec[17] * rec[18]
        self.battery = rec[21]
        self.get_command = f'{rec[26]} {rec[27]}'
    
    def get_drone_data(self):
        return {
            'ssid': self.ssid,
            'height': self.height,
            'vx': self.vx,
            'vy': self.vy,
            'vz': self.vz,
            'x': self.x,
            'y': self.y,
            'z': self.z,
            'flytime': self.flytime,
            'battery': self.battery,
            'wifi': self.wifi,
            'humei': self.get_command,
            'rec_command_id': self.rec_command_id
        }
    
    def cie_reset(self):
        self.x = self.y = self.z = 0

    def stop(self):
        self.sock.close()