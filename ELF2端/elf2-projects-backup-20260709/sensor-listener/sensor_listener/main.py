"""CLI entry point and asyncio startup for the smart greenhouse controller."""
import argparse
import asyncio
import os
import queue
import sys
import threading

from sensor_listener.display import CsvWriter, DisplayManager
from sensor_listener.protocol import SensorProtocol


async def main() -> None:
    parser = argparse.ArgumentParser(description="智能温室控制器")
    parser.add_argument("--port", type=int, default=8259, help="UDP 监听端口 (默认: 8259)")
    parser.add_argument("--bind", type=str, default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    parser.add_argument("--log-dir", type=str, default="./sensor_logs", help="CSV 存储目录")
    parser.add_argument("--retention-days", type=int, default=60, help="CSV 保留天数 (默认: 60)")
    parser.add_argument("--no-color", action="store_true", help="关闭 ANSI 颜色")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示来源 IP 和字节数")
    parser.add_argument("--no-analysis", action="store_true", help="禁用分析引擎")
    parser.add_argument("--no-control", action="store_true", help="禁用自动控制")
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM")
    parser.add_argument("--llm-api-key", type=str, default=os.environ.get("DEEPSEEK_API_KEY", ""),
                        help="DeepSeek API key (or set DEEPSEEK_API_KEY env var)")
    parser.add_argument("--k230-port", type=int, default=8260, help="K230 控制端口")
    parser.add_argument("--no-mqtt", action="store_true", help="禁用 MQTT 云端连接")
    parser.add_argument("--no-video", action="store_true", help="禁用视频接收和 YOLO")
    parser.add_argument("--video-port", type=int, default=6000, help="TCP 视频端口 (默认: 6000)")
    parser.add_argument("--yolo-interval", type=float, default=10.0, help="YOLO 推理间隔秒 (默认: 10.0)")
    parser.add_argument("--yolo-model", type=str, default="best.pt", help="YOLO 模型路径 (默认: best.pt)")
    parser.add_argument("--yolo-conf", type=float, default=0.5, help="YOLO 置信度阈值 (默认: 0.5)")
    args = parser.parse_args()

    use_color = not args.no_color

    # Conditionally create engines
    analysis_engine = None
    control_engine = None
    llm_advisor = None

    if not args.no_analysis:
        from sensor_listener.analysis import AnalysisEngine
        analysis_engine = AnalysisEngine()

    if not args.no_control:
        from sensor_listener.control import ControlEngine
        control_engine = ControlEngine()
        if not args.no_llm:
            from sensor_listener.llm_advisor import LLMAdvisor
            llm_advisor = LLMAdvisor(api_key=args.llm_api_key)
            control_engine.set_llm_advisor(llm_advisor)

    display = DisplayManager(verbose=args.verbose, use_color=use_color)
    csv_writer = CsvWriter(log_dir=args.log_dir, retention_days=args.retention_days)
    csv_writer.cleanup_old_files()
    display.show_waiting(args.bind, args.port)

    loop = asyncio.get_running_loop()
    transport = None
    protocol = None
    start_time = None

    async def shutdown() -> None:
        nonlocal transport, protocol
        if transport:
            transport.close()
        csv_writer.close()

        if mqtt_client:
            from sensor_listener.mqtt.subscriber import stop_mqtt
            stop_mqtt(mqtt_client)

        elapsed = loop.time() - start_time if start_time else 0.0
        display.show_shutdown(
            runtime_seconds=elapsed,
            total_packets=protocol.total_packets if protocol else 0,
            drop_count=protocol.drop_count if protocol else 0,
            error_count=protocol.error_count if protocol else 0,
            csv_bytes=csv_writer.total_bytes_written,
        )

    try:
        protocol = SensorProtocol(
            display=display, csv_writer=csv_writer,
            analysis_engine=analysis_engine,
            control_engine=control_engine,
            k230_port=args.k230_port,
        )
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            local_addr=(args.bind, args.port),
        )
        start_time = loop.time()

        video_thread = None
        if not args.no_video:
            from sensor_listener.video.receiver import DataReceiver
            from sensor_listener.video.h265 import VideoStreamHandler
            from sensor_listener.video.yolo_detector import YoloDetector

            video_handler = VideoStreamHandler()
            yolo_detector = YoloDetector(
                model_path=args.yolo_model,
                conf=args.yolo_conf,
                interval=args.yolo_interval,
            )
            video_receiver = DataReceiver(video_handler, port=args.video_port)

            def _video_loop() -> None:
                """Run video receive and YOLO detection in background thread."""
                import time as _time
                # Start the receiver in this thread
                video_receiver.start()
                # YOLO inference loop
                while True:
                    _time.sleep(1.0)
                    try:
                        frame = video_handler.get_frame(timeout=1.0)
                        if frame is None:
                            continue
                        if not yolo_detector.should_infer():
                            continue
                        detections = yolo_detector.detect(frame)
                        if not detections:
                            continue
                        new_growth = yolo_detector.is_new_growth(detections)
                        if new_growth:
                            path = yolo_detector.save_screenshot(frame, detections)
                            print(f"[YOLO] 新生长: {new_growth['class']} ({new_growth['confidence']:.2f}) -> {path}")
                    except Exception as _e:
                        print(f"[YOLO] loop error: {_e}")

            video_thread = threading.Thread(target=_video_loop, daemon=True)
            video_thread.start()

        mqtt_client = None
        cmd_queue = queue.Queue()

        if not args.no_mqtt:
            from sensor_listener.mqtt.subscriber import start_mqtt
            mqtt_client = start_mqtt(cmd_queue=cmd_queue)

        from sensor_listener.mqtt.subscriber import router

        while True:
            # Process MQTT commands
            while not cmd_queue.empty():
                payload = cmd_queue.get()
                response = router.process(payload)
                if response.startswith("[FILE]"):
                    from sensor_listener.mqtt.subscriber import send_file_over_mqtt
                    file_path = response.split("[FILE]", 1)[1].strip()
                    send_file_over_mqtt(mqtt_client, file_path)
                elif response and mqtt_client:
                    mqtt_client.publish("rpi5/cloud/data", response)

            await asyncio.sleep(1)  # Check queue every second

    except asyncio.CancelledError:
        pass
    except OSError as e:
        print(f"无法绑定 {args.bind}:{args.port}: {e}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        await shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
