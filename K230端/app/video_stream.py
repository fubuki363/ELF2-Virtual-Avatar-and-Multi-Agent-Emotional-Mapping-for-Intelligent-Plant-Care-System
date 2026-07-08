# video_stream.py — Thread-4: CSI 摄像头 H.265 硬编码 + TCP 推流
import time
from media.sensor import Sensor
from media.media import MediaManager
from mculib.g1lib import StreamSender
from config import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS


def video_stream_thread(elf2_ip):
    """Thread-4: 摄像头 1280×720 H.265 → TCP → ELF2:6001, 断线自动重连"""

    print("[Video] Initializing camera...")

    # 初始化传感器
    sensor = Sensor(id=2, width=VIDEO_WIDTH, height=VIDEO_HEIGHT, fps=VIDEO_FPS)
    sensor.reset()

    # 创建视频流发送器
    sender = StreamSender(
        sensor=sensor,
        cam_chn_id=1,        # CAM_CHN_ID_1
        enc_chn_id=0,        # VENC_CHN_ID_0
        width=VIDEO_WIDTH,
        height=VIDEO_HEIGHT,
        host_ip=elf2_ip,
        message_callback=None  # 控制命令走独立 UDP:8260
    )

    # 初始化 MediaManager (所有通道注册后调用)
    MediaManager.init()
    sensor.run()

    # 连接 ELF2 (带重试)
    while True:
        try:
            sender.start()
            print("[Video] Streaming H.265 %dx%d -> %s:6001" % (VIDEO_WIDTH, VIDEO_HEIGHT, elf2_ip))
            break
        except OSError as e:
            print("[Video] ELF2 not ready (%s), retry in 3s..." % e)
            time.sleep(3)

    while True:
        try:
            sender.send_frame()
            sender.poll_messages()

            if sender.isClose:
                print("[Video] ELF2 disconnected, reconnecting...")
                time.sleep(1)
                while True:
                    try:
                        sender.start()
                        print("[Video] Reconnected")
                        break
                    except OSError:
                        print("[Video] ELF2 still not ready, retry in 3s...")
                        time.sleep(3)
        except Exception as e:
            print("[Video] Error:", e)
            time.sleep(1)

        time.sleep_us(11111)
