import music_player

class LiveBGMSong:
    """处理网易云点歌指令的类 (整活：AI 翻唱模式)"""

    def execute(self, args_str, user_name, speak_callback):
        """
        标准执行接口
        :param args_str: 指令后面的参数（例如 "孤勇者"）
        :param user_name: 发送弹幕的用户
        :param speak_callback: 语音播报的回调函数
        """
        if not args_str:
            speak_callback(f"{user_name}，你没有告诉我要听什么歌呀！")
            return

        speak_callback(f"{user_name}，收到点歌请求！酢酱酱正在准备翻唱《{args_str}》...")

        # 🎯 核心修复：在这里加上 mode="ai_sing"，强行把音频塞给变声器
        success, reply_msg = music_player.play_netease_music(args_str, mode="ai_sing")

        # 播报结果
        speak_callback(f"{user_name}，{reply_msg}")

class LiveBGMChange:
    """处理网易云切歌指令的类 (正常：BGM 模式)"""

    def execute(self, args_str, user_name, speak_callback):
        """
        标准执行接口
        :param args_str: 指令后面的参数（例如 "打上花火"）
        :param user_name: 发送弹幕的用户
        :param speak_callback: 语音播报的回调函数
        """
        if not args_str:
            speak_callback(f"{user_name}，你没有告诉我要换什么歌呀！")
            return

        speak_callback(f"{user_name}，收到切歌请求！正在搜索《{args_str}》...")

        # 核心：调用具体的播放功能，并指定模式为 bgm 发送到系统扬声器/耳机
        success, reply_msg = music_player.play_netease_music(args_str, mode="bgm")

        # 播报结果
        speak_callback(f"{user_name}，{reply_msg}")

class LiveBGMClose:
    """处理强制关闭音乐/翻唱的类"""

    def execute(self, args_str, user_name, speak_callback):
        """
        标准执行接口
        :param args_str: 此指令不需要参数，忽略即可
        :param user_name: 发送弹幕的用户
        :param speak_callback: 语音播报的回调函数
        """
        speak_callback(f"{user_name}，收到紧急指令！酢酱酱正在拔掉音响电源...")

        # 调用 music_player 里的强停函数
        success, reply_msg = music_player.stop_music()

        # 播报结果
        speak_callback(f"{user_name}，{reply_msg}")