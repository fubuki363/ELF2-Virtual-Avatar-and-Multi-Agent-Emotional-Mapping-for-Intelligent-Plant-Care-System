class BaseCommand:
    """所有指令的抽象基类"""

    def execute(self, args: str) -> str:
        """
        执行指令的核心方法
        :param args: 指令附带的参数字符串 (可能为空)
        :return: 返回给主机的结果字符串
        """
        raise NotImplementedError("子类必须实现 execute() 方法")
