import select, struct
class FrameParser:
    """
    外层协议解析器，处理指令头和长度信息
    """
    HEADER_SIZE = 8  # 指令头(4字节) + 长度(4字节)

    def __init__(self):
        self.buffer = bytearray()
        self.expected_length = 0
        self.current_command = 0

    def process(self, data):
        """
        处理接收到的数据，返回解析出的完整消息
        :param data: 新接收的字节数据
        :return: (command, payload) 元组列表
        """
        self.buffer.extend(data)
        messages = []

        while len(self.buffer) >= self.HEADER_SIZE:
            # 如果还没有解析出长度信息，尝试解析头部
            if self.expected_length == 0:
                # 解析指令头和长度
                header = self.buffer[:self.HEADER_SIZE]
                self.current_command, self.expected_length = struct.unpack('<II', header)

                # 移除已处理的头部
                self.buffer = self.buffer[self.HEADER_SIZE:]

            # 检查是否有足够的数据
            if len(self.buffer) >= self.expected_length:
                # 提取有效载荷
                payload = self.buffer[:self.expected_length]
                self.buffer = self.buffer[self.expected_length:]

                # 重置状态
                messages.append((self.current_command, payload))
                self.expected_length = 0
            else:
                # 数据不足，等待更多数据
                break

        return messages


class JustFloatDecoder:
    """
    JustFloat协议解码器
    """
    TAIL = b'\x00\x00\x80\x7f'
    MAX_FRAME_SIZE = 64

    def decode(self, data):
        """
        解码JustFloat协议数据
        :param data: 包含完整帧的字节数据（包括帧尾）
        :return: 浮点数列表
        """
        # 检查帧尾
        if data[-4:] != self.TAIL:
            print("错误：帧尾不匹配")
            return []

        # 移除帧尾
        frame_data = data[:-4]

        # 检查长度有效性
        if len(frame_data) % 4 != 0 or len(frame_data) > self.MAX_FRAME_SIZE:
            print(f"错误：无效帧长度 {len(frame_data)}")
            return []

        try:
            # 解析浮点数组（小端字节序）
            num_floats = len(frame_data) // 4
            fmt = '<' + 'f' * num_floats
            return struct.unpack(fmt, frame_data)
        except Exception as e:
            print(f"解码错误: {e}")
            return []

class JustFloatHandler:
    def __init__(self, callback):
        self.frame_parser = FrameParser()          # 创建帧解析器实例
        self.justfloat_decoder = JustFloatDecoder()  # 创建浮点数解码器实例
        self.callback = callback                    # 注册用户回调函数

    def handle_socket(self, sock):
        """处理socket数据的方法"""
        try:
            rlist, _, _ = select.select([sock], [], [], 0)
        except OSError:
            return
        if not rlist:
            return

        try:
            data = sock.recv(128)
        except OSError:
            return
        if not data:
            return

        # 处理接收到的消息帧
        messages = self.frame_parser.process(data)
        for command, payload in messages:
            print(f"\n收到指令: {command}, 长度: {len(payload)}")

            if command == 1:  # JustFloat 数据
                floats = self.justfloat_decoder.decode(payload)
                if floats:
                    print(f"[JustFloat帧] 通道数: {len(floats)}")
                    # 将浮点数列表传递给回调函数
                    self.callback(floats)
                else:
                    print("解码失败")
            else:
                print(f"未知指令类型: {command}")

