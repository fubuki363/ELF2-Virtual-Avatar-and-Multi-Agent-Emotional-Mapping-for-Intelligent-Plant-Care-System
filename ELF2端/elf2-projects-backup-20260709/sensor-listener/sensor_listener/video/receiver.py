import socket
import struct
import queue
import threading
from threading import Lock

BUFFER_SIZE = 1048576  # 1MB缓冲区
SERVER_IP = '0.0.0.0'  # 监听所有接口
SERVER_PORT = 6000

# 定义数据类型常量
DATA_TYPE_CONFIG = 0xFFFFFFFF
DATA_TYPE_VIDEO_FRAME = 0x00000000
DATA_TYPE_MESSAGE = 0x00000001

class DataReceiver:
    """通用数据接收器"""
    def __init__(self, video_handler=None, port=SERVER_PORT):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((SERVER_IP, self.port))
        self.sock.listen(1)
        self.video_handler = video_handler

        # 消息队列和锁
        self.message_queue = queue.Queue(maxsize=1)
        self.conn_lock = Lock()
        self.current_conn = None
        self.running = False
        self.thread = None

    def start(self):
        """启动接收线程"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"DataReceiver started on {SERVER_IP}:{self.port}")

    def stop(self):
        """停止接收器"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.sock.close()

    def _run(self):
        """主运行循环"""
        while self.running:
            try:
                conn, addr = self.sock.accept()
                print(f"Connection from: {addr}")
                try:
                    with self.conn_lock:
                        self.current_conn = conn
                    self._handle_connection(conn)
                except (ConnectionResetError, BrokenPipeError) as e:
                    print(f"Client disconnected: {e}")
                finally:
                    with self.conn_lock:
                        self.current_conn = None
                    conn.close()
            except OSError as e:
                if self.running:
                    print(f"Socket error: {e}")

    def _handle_connection(self, conn):
        """处理客户端连接"""
        # 接收初始配置包
        config_data = self._recv_all(conn, 12)
        if len(config_data) != 12:
            print("Invalid config packet")
            return

        data_type, width, height = struct.unpack("<LLL", config_data)

        if data_type != DATA_TYPE_CONFIG:
            print("Unexpected data type for config packet")
            return

        # 配置视频处理器
        if self.video_handler:
            self.video_handler.configure(width, height)

        # 主数据接收循环
        while self.running:
            # 接收数据类型引导头 (4字节)
            type_header = self._recv_all(conn, 4)
            if len(type_header) < 4:
                break

            data_type = struct.unpack("<L", type_header)[0]

            if data_type == DATA_TYPE_VIDEO_FRAME:
                self._process_video_frame(conn)
            elif data_type == DATA_TYPE_MESSAGE:
                self._process_message(conn)
            else:
                print(f"Unknown data type: 0x{data_type:08X}")
                break

            # 处理完成后检查并发送队列中的消息
            self._send_queued_message()

    def _process_video_frame(self, conn):
        """处理视频帧数据"""
        # 接收帧头 (8字节: 总大小 + NALU数量)
        header = self._recv_all(conn, 8)
        if len(header) < 8:
            return

        total_size, nalu_count = struct.unpack("<LL", header)

        # 接收帧数据
        frame_data = self._recv_all(conn, total_size)
        if len(frame_data) < total_size:
            print(f"Incomplete frame: {len(frame_data)}/{total_size}")
            return

        # 交给视频处理器处理
        if self.video_handler:
            self.video_handler.process_frame(frame_data, nalu_count)

    def _process_message(self, conn):
        """处理文本消息"""
        # 接收消息长度 (4字节)
        len_data = self._recv_all(conn, 4)
        if len(len_data) < 4:
            return

        msg_len = struct.unpack("<L", len_data)[0]

        # 接收消息内容
        msg_data = self._recv_all(conn, msg_len)
        if len(msg_data) < msg_len:
            print(f"Incomplete message: {len(msg_data)}/{msg_len}")
            return

        print("Received Message:", msg_data.decode('utf-8'))

    def _recv_all(self, sock, size):
        """可靠接收指定大小的数据"""
        data = bytearray()
        while len(data) < size and self.running:
            try:
                chunk = sock.recv(min(BUFFER_SIZE, size - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            except socket.timeout:
                continue
            except (ConnectionResetError, BrokenPipeError):
                break
        return data

    def _send_queued_message(self):
        """尝试发送队列中的消息"""
        try:
            message = self.message_queue.get_nowait()
            with self.conn_lock:
                if self.current_conn:
                    try:
                        # 构建消息包：类型 + 长度 + 内容
                        header = struct.pack("<LL", DATA_TYPE_MESSAGE, len(message))
                        self.current_conn.sendall(header + message)
                        print(f"Sent queued message ({len(message)} bytes)")
                        return True
                    except (ConnectionResetError, BrokenPipeError):
                        print("Connection lost while sending message")
                        self.current_conn = None
                        return False
        except queue.Empty:
            return False

    def send_to_device(self, message: bytes) -> int:
        """
        发送消息到设备
        返回:
            1: 成功加入队列
            0: 队列已满
           -1: 无活跃连接
        """
        with self.conn_lock:
            if not self.current_conn:
                return -1

        try:
            self.message_queue.put_nowait(message)
            return 1
        except queue.Full:
            return 0
