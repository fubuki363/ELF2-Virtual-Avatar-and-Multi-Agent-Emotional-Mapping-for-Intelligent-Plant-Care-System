import av
import struct
import queue

class VideoStreamHandler:
    """视频流处理类"""
    def __init__(self, frame_queue_size=2):
        self.codec = None
        self.width = 0
        self.height = 0
        self.frame_queue = queue.Queue(maxsize=frame_queue_size)

    def configure(self, width, height):
        """配置视频流参数"""
        self.width = width
        self.height = height
        self.codec = av.CodecContext.create('hevc', 'r')
        print(f"Video configured: {width}x{height}")

    def process_frame(self, frame_data, nalu_count):
        """处理视频帧数据"""
        if not self.codec:
            print("Video not configured yet")
            return

        # 解析NAL单元
        pos = 0
        for _ in range(nalu_count):
            nalu_size = struct.unpack("<L", frame_data[pos:pos+4])[0]
            pos += 4
            nalu_data = frame_data[pos:pos+nalu_size]
            pos += nalu_size

            # 解码帧
            try:
                packet = av.packet.Packet(nalu_data)
                for frame in self.codec.decode(packet):
                    if isinstance(frame, av.VideoFrame):
                        # 转换为OpenCV格式
                        img = frame.to_ndarray(format='bgr24')

                        # 尝试放入队列（队列满时丢弃旧帧）
                        if self.frame_queue.full():
                            try:
                                self.frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        try:
                            self.frame_queue.put_nowait(img)
                        except queue.Full:
                            pass
            except Exception as e:
                print(f"Video decode error: {e}")

    def get_frame(self, timeout=0.1):
        """从队列获取视频帧"""
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None
