import paho.mqtt.client as mqtt
import ssl
import json
import importlib
import os
import queue

# ================= 路径与配置区域 =================
# 动态获取当前 subscriber.py 所在的绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BROKER = os.getenv("MQTT_BROKER", "your_broker.ala.cn-hangzhou.emqxsl.cn")
PORT = int(os.getenv("MQTT_PORT", "8883"))
USERNAME = os.getenv("MQTT_USERNAME", "your_mqtt_username")
PASSWORD = os.getenv("MQTT_PASSWORD", "your_mqtt_password_here")
CA_CRT = os.path.join(BASE_DIR, "emqxsl-ca.crt")  # 动态拼接证书路径

TOPIC_SUB = "rpi5/cloud/command"
TOPIC_PUB = "rpi5/cloud/data"
TOPIC_PUB_FILE = "rpi5/cloud/file"

# 🌟 全局变量，用于存放主程序传进来的队列
global_cmd_queue = None


# ================= 路由类 (用于兼容单独运行模式) =================
class CommandRouter:
    def __init__(self, config_file="commands.json"):
        config_path = os.path.join(BASE_DIR, config_file)
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.routes = json.load(f)
            print(f">>> 成功加载 {len(self.routes)} 条指令配置。")
        except Exception as e:
            print(f">>> 警告：无法加载配置文件 {config_path}，如果不单独运行可忽略。错误: {e}")
            self.routes = {}

    def process(self, payload: str) -> str:
        payload = payload.strip()
        if not payload.startswith("/"):
            return f"[ERROR 400] 非法请求。指令必须以 '/' 开头。"

        parts = payload.split(" ", 1)
        cmd_string = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        if cmd_string not in self.routes:
            return f"[ERROR 404] 未知指令 '{cmd_string}'。"

        route_info = self.routes[cmd_string]

        try:
            module = importlib.import_module(route_info["module"])
            command_class = getattr(module, route_info["class"])
            command_instance = command_class()
            result = command_instance.execute(args)
            return str(result)
        except Exception as e:
            return f"[ERROR 500] 指令执行崩溃：{str(e)}"


router = CommandRouter()


# ================= 文件发送逻辑 =================
def send_file_over_mqtt(client, file_path):
    if not os.path.exists(file_path):
        error_msg = f"[ERROR] 准备发送的文件未找到: {file_path}"
        client.publish(TOPIC_PUB, error_msg)
        print(error_msg)
        return

    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    print(f">>> 准备发送文件: {file_name} (大小: {file_size / 1024:.2f} KB)")

    if file_size > 2 * 1024 * 1024:
        print(">>> [警告] 文件较大，如果 EMQX 云端未提升 max_packet_size 限制，可能会断开连接！")

    try:
        meta_data = json.dumps({"filename": file_name, "size": file_size})
        client.publish(TOPIC_PUB, f"[FILE_META] {meta_data}", qos=1)

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        client.publish(TOPIC_PUB_FILE, file_bytes, qos=1)
        print(f"--> [文件已成功发送至云端]: {TOPIC_PUB_FILE}")
        client.publish(TOPIC_PUB, f"[SUCCESS] 文件 {file_name} 传输完成。")

    except Exception as e:
        error_msg = f"[ERROR] 发送文件时发生异常: {str(e)}"
        client.publish(TOPIC_PUB, error_msg)
        print(error_msg)


# ================= MQTT 回调设置 =================
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(">>> 成功连接到 EMQX Cloud!")
        client.subscribe(TOPIC_SUB)
        print(f">>> 正在监听主题: {TOPIC_SUB}")
    else:
        print(f">>> 连接失败，错误码: {reason_code}")


def on_message(client, userdata, msg):
    payload = msg.payload.decode('utf-8')
    print(f"\n<-- [收到主机消息]: {payload}")

    # 🌟 核心：如果主程序挂载了队列，则将消息推入队列，由主程序在主线程中处理
    if global_cmd_queue is not None:
        global_cmd_queue.put(payload)
        return

    # 若未挂载队列（例如直接运行 subscriber.py），则走原来的动态加载逻辑
    response = router.process(payload)

    if response.startswith("[FILE]"):
        file_path = response.split("[FILE]", 1)[1].strip()
        send_file_over_mqtt(client, file_path)
    else:
        client.publish(TOPIC_PUB, response)
        print(f"--> [返回主机结果]: {response}")


# ================= 供主程序调用的启停接口 =================
def start_mqtt(cmd_queue=None):
    global global_cmd_queue
    global_cmd_queue = cmd_queue

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(ca_certs=CA_CRT, tls_version=ssl.PROTOCOL_TLSv1_2)

    client.on_connect = on_connect
    client.on_message = on_message

    print(">>> 正在连接 Broker...")
    client.connect(BROKER, PORT, 60)

    # 使用 loop_start() 开启非阻塞的后台守护线程
    client.loop_start()
    return client


def stop_mqtt(client):
    if client:
        client.loop_stop()
        client.disconnect()
        print(">>> MQTT 客户端已安全断开。")


# 兼容直接单独运行此文件进行测试的情况
if __name__ == "__main__":
    c = start_mqtt()
    try:
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_mqtt(c)
