# test_wxauto.py
from wxauto import WeChat
import time


def main():
    print("⏳ 正在寻找微信窗口...")
    try:
        # 初始化 WeChat，它会自动寻找屏幕上已经打开的微信客户端
        wx = WeChat()
        print("✅ 成功获取微信窗口！")

        # 获取当前所有的未读消息
        print("📥 当前会话列表：", wx.GetSessionList())

        # 测试发送消息 (注意：这里要写对方的微信昵称或你给他的备注名)
        target = "文件传输助手"
        msg = "你好！这是来自 wxauto 的 UI 自动化测试消息。"

        print(f"📨 正在向 {target} 发送消息...")
        wx.SendMsg(msg, target)
        print("✅ 发送成功！")

    except Exception as e:
        print("\n❌ 无法获取微信窗口，请确保：")
        print("1. 微信客户端已经打开并登录。")
        print("2. 微信窗口没有被最小化到右下角托盘。")
        print(f"具体错误信息: {e}")


if __name__ == "__main__":
    main()