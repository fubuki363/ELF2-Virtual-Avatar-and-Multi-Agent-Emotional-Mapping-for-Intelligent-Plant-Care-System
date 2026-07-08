# stream_sender.py
import time, os, sys, socket, ustruct, uctypes, select
from media.vencoder import *
from media.sensor import *
from media.display import *
from media.media import *
def mc(sock):
    rlist, _, _ = select.select([sock], [], [], 0)
    if rlist:
        command_header = sock.recv(16)
        print("[默认消息回调]:", command_header)
class StreamSender:
    def __init__(
        self, sensor, cam_chn_id, enc_chn_id, width, height,
        host_ip, port=6001,
        typeCONFIG=0xFFFFFFFF, typeVIDEO=0x00000000, typeMESSAGE=0x00000001,
        message_callback=mc,
        reconetEN=False
    ):
        self.sensor = sensor
        self.cam_chn_id = cam_chn_id
        self.enc_chn_id = enc_chn_id
        self.width = width
        self.height = height
        self.host_ip = host_ip
        self.port = port
        self.sock = None
        self.streamData = StreamData()
        self.message_callback = message_callback

        self.isClose = False

        self.reconetEN = reconetEN

        # 设置传感器格式和尺寸
        self.sensor.set_framesize(chn=cam_chn_id, width=width, height=height)
        self.sensor.set_pixformat(chn=cam_chn_id, pix_format=Sensor.YUV420SP)

        # 建立媒体链路
        MediaManager.link(
            self.sensor.bind_info(chn=cam_chn_id)['src'],
            (VIDEO_ENCODE_MOD_ID, VENC_DEV_ID, enc_chn_id)
        )

        # 初始化编码器属性
        self.encoder = Encoder()
        self.encoder.SetOutBufs(chn=enc_chn_id, buf_num=8, width=width, height=height)
        self.chnAttr = ChnAttrStr(
            self.encoder.PAYLOAD_TYPE_H265,
            self.encoder.H265_PROFILE_MAIN,
            width,
            height
        )

        # 消息类型定义
        self.typeCONFIG  = 0xFFFFFFFF & typeCONFIG
        self.typeVIDEO   = 0xFFFFFFFF & typeVIDEO
        self.typeMESSAGE = 0xFFFFFFFF & typeMESSAGE

    def start(self):
        """启动编码器和连接服务器"""
        self.encoder.Create(self.enc_chn_id, self.chnAttr)
        self.encoder.Start(self.enc_chn_id)
        self._connect()

    def _connect(self):
        """连接到服务器"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(False)
        self.sock.settimeout(0)
        self.sock.connect((self.host_ip, self.port))

        # 发送配置包
        config_packet = ustruct.pack("<LLL", self.typeCONFIG, self.width, self.height)
        self.sock.send(config_packet)

    def send_frame(self):
        """发送视频帧"""
        if not self.sock:
            return False

        # 获取编码后的帧数据
        self.encoder.GetStream(self.enc_chn_id, self.streamData)
        if self.streamData.pack_cnt == 0:
            return False

        # 构建数据包
        total_size = sum(4 + self.streamData.data_size[i] for i in range(self.streamData.pack_cnt))
        nalu_count = self.streamData.pack_cnt
        header = ustruct.pack("<LLL", self.typeVIDEO, total_size, nalu_count)

        # 构建数据缓冲区
        data_buffer = bytearray()
        for i in range(nalu_count):
            nalu_size = self.streamData.data_size[i]
            data_buffer += ustruct.pack("<L", nalu_size)
            nalu_data = uctypes.bytearray_at(self.streamData.data[i], nalu_size)
            data_buffer.extend(nalu_data)

        # 发送数据（非阻塞 socket，分批发送）
        try:
            # 先发送帧头
            self._send_all(header)
            # 再发送帧数据
            self._send_all(data_buffer)
        except Exception as e:
            print("发送错误:", e)
            self._reconnect()
            return False
        finally:
            self.encoder.ReleaseStream(self.enc_chn_id, self.streamData)
        return True

    def _send_all(self, data):
        """非阻塞发送全部数据，遇到 EAGAIN 则短暂等待重试"""
        offset = 0
        total = len(data)
        retries = 0
        MAX_RETRIES = 100

        while offset < total:
            try:
                sent = self.sock.send(data[offset:])
            except OSError as e:
                # MicroPython: errno 11 = EAGAIN, 表示发送缓冲区满
                if e.args[0] != 11:
                    raise
                sent = 0

            if sent > 0:
                offset += sent
                retries = 0
            else:
                retries += 1
                if retries > MAX_RETRIES:
                    raise RuntimeError("发送超时")
                # 等待 PC 消费数据腾出缓冲区
                time.sleep_ms(1)

    def _reconnect(self):
        """重新连接服务器"""
        try:
            if not self.reconetEN:
                self.close()
                self.isClose = True
                return
            if self.sock:
                self.sock.close()
                print("在正在尝试重连pc")
                self._connect()
        except Exception as e:
            print("连接失败:", e)

    def send_message(self, message):
        """发送文本消息"""
        if not self.sock:
            return False

        try:
            msg_bytes = message.encode('utf-8')
            header = ustruct.pack("<LL", self.typeMESSAGE, len(msg_bytes))
            self._send_all(header + msg_bytes)
            return True
        except Exception as e:
            print("发送消息错误:", e)
            return False

    def poll_messages(self):
        """检查并处理接收到的消息"""
        if not self.sock or not self.message_callback:
            return
        self.message_callback(self.sock)

    def close(self):
        """关闭连接和资源"""
        if self.sock:
            self.sock.close()
            self.sock = None

        if hasattr(self, 'encoder'):
            self.encoder.Stop(self.enc_chn_id)
            self.encoder.Destroy(self.enc_chn_id)
