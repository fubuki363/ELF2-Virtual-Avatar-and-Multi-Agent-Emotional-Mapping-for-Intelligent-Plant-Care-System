#!/usr/bin/env python3
"""
示例：用代码控制 VTube Studio 古钟角色的表情和动作
=====================================================
表情直接控制（不需要热键），动作需要热键。
"""

import asyncio
from vts_controller import VTSController


async def example_1_quick_start():
    """快速上手：激活表情"""
    async with VTSController() as vts:
        # 查看模型完整信息
        await vts.print_full_summary()

        # 激活「微笑」表情（按名称）
        await vts.activate_expression_by_name("微笑")

        # 等 2 秒
        await asyncio.sleep(2)

        # 停用「微笑」
        await vts.deactivate_expression_by_name("微笑")


async def example_2_by_index():
    """按索引控制表情"""
    async with VTSController() as vts:
        expressions = await vts.list_expressions()
        print(f"共有 {len(expressions)} 个表情:\n")
        for i, e in enumerate(expressions):
            print(f"  [{i}] {e.name}")

        # 激活第 0 个表情
        await vts.activate_expression_by_index(0)
        await asyncio.sleep(1.5)

        # 停用第 0 个
        await vts.deactivate_expression_by_index(0)


async def example_3_play_all():
    """依次播放所有表情"""
    async with VTSController() as vts:
        print("▶ 依次播放所有表情...")
        await vts.play_all_expressions(delay=0.5)
        print("✓ 完成")


async def example_4_precise_control():
    """按条件筛选并控制表情"""
    async with VTSController() as vts:
        expressions = await vts.list_expressions()

        # 找出名字包含「笑」的表情并激活
        for expr in expressions:
            if "笑" in expr.name:
                print(f"激活: {expr.name}")
                await vts.activate_expression(expr.file, active=True)
                await asyncio.sleep(1.0)
                await vts.activate_expression(expr.file, active=False)
                await asyncio.sleep(0.3)


async def example_5_live2d_params():
    """直接操控 Live2D 参数（最底层控制）"""
    async with VTSController() as vts:
        # 列出所有参数
        params = await vts.list_parameters()
        print(f"共有 {len(params)} 个参数\n")

        # 查找常用参数
        for p in params:
            if any(kw in p.name.lower() for kw in
                   ["mouth", "eye", "brow", "smile", "anger", "sad"]):
                print(f"  {p}")

        # 直接设置参数
        # await vts.inject_parameters({
        #     "MouthSmile": 0.8,
        #     "EyeOpenLeft": 0.5,
        # })


async def example_6_art_meshes():
    """控制模型部件显示/隐藏"""
    async with VTSController() as vts:
        meshes = await vts.list_art_meshes()
        print(f"共有 {len(meshes)} 个部件:\n")
        for m in meshes:
            print(f"  {m}")

        # 隐藏某个部件
        # await vts.set_art_meshes({"翅膀": False})


async def example_7_hotkeys():
    """触发热键（需要在 VTS 中预先配置）"""
    async with VTSController() as vts:
        hotkeys = await vts.list_hotkeys()
        if not hotkeys:
            print("没有配置热键。表情可直接用 activate_expression_by_name() 控制。")
            return

        print(f"已配置 {len(hotkeys)} 个热键:")
        for i, hk in enumerate(hotkeys):
            print(f"  [{i}] {hk}")

        # 按索引触发
        # await vts.trigger_hotkey_by_index(0)

        # 按名称触发
        # await vts.trigger_hotkey_by_name("我的热键")


# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    # 修改这个数字选择要运行的示例
    EXAMPLE = 1

    examples = {
        1: example_1_quick_start,
        2: example_2_by_index,
        3: example_3_play_all,
        4: example_4_precise_control,
        5: example_5_live2d_params,
        6: example_6_art_meshes,
        7: example_7_hotkeys,
    }

    func = examples.get(EXAMPLE)
    if func:
        print(f"\n运行示例 {EXAMPLE}: {func.__doc__}\n")
        asyncio.run(func())
    else:
        print(f"示例 {EXAMPLE} 不存在，可选: {list(examples.keys())}")
