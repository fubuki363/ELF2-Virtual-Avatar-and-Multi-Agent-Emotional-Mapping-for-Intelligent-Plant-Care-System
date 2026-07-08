import os
from sensor_listener.mqtt.base_cmd import BaseCommand


class FileSend(BaseCommand):
    """
    从指定目录寻找并发送文件
    指令示例: /file.get photo.jpg
    """

    def __init__(self):
        # 设置文件存储的根目录
        # 假设 cmd_file.py 位于 Plant_Project/Connect/ 目录下
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_file_dir = os.path.join(self.current_dir, "File")

        # 设置 MQTT 允许的最大文件大小 (2MB)
        self.max_size_bytes = 2 * 1024 * 1024

    def execute(self, args: str) -> str:
        # 1. 参数校验
        if not args or not args.strip():
            return "[ERROR 400] 缺少文件名参数。正确指令格式: /file.get <文件名> (例如: /file.get test.jpg)"

        file_name = args.strip()

        # 2. 提取文件后缀名 (例如 test.jpg -> jpg)
        if "." not in file_name:
            return f"[ERROR 400] 文件名 '{file_name}' 无效，必须包含后缀名。"

        extension = file_name.rsplit(".", 1)[-1].lower()

        # 3. 拼接目标路径 (Plant_Project/Connect/File/后缀名/文件名)
        target_dir = os.path.join(self.base_file_dir, extension)
        target_file_path = os.path.join(target_dir, file_name)

        # 4. 检查文件是否存在
        if not os.path.exists(target_file_path):
            return f"[ERROR 404] 文件未找到: {file_name} (已在 {extension} 文件夹中查找，请确认文件是否存在)"

        # 5. 检查文件大小，防止撑爆 MQTT
        try:
            file_size = os.path.getsize(target_file_path)
            if file_size > self.max_size_bytes:
                size_mb = file_size / (1024 * 1024)
                return f"[ERROR 413] 文件过大拒绝发送！当前大小: {size_mb:.2f} MB (MQTT 限制上限为 2 MB)。"
        except Exception as e:
            return f"[ERROR 500] 无法读取文件状态: {str(e)}"

        # 6. 一切正常，返回特殊前缀交由主程序的 on_message 进行二进制传输
        return f"[FILE]{target_file_path}"
