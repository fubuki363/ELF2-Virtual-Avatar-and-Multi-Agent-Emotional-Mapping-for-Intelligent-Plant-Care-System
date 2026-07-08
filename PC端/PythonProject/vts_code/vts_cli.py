#!/usr/bin/env python3
"""
VTube Studio 命令行控制工具
==============================
独立控制古钟角色模型的每个预设表情和动作。

用法:
    python vts_cli.py                  # 交互模式
    python vts_cli.py --list           # 查看完整信息后退出
    python vts_cli.py --expr 微笑      # 激活指定表情
    python vts_cli.py --expr-off 微笑  # 停用指定表情
    python vts_cli.py --expr-all       # 依次播放所有表情
    python vts_cli.py --reset          # 停用所有表情（回默认）
"""

import asyncio
import argparse
import sys
import logging
from vts_controller import VTSController, VTSAPIError

try:
    import colorama
    colorama.init()
    RED = colorama.Fore.RED
    GREEN = colorama.Fore.GREEN
    CYAN = colorama.Fore.CYAN
    YELLOW = colorama.Fore.YELLOW
    MAGENTA = colorama.Fore.MAGENTA
    RESET = colorama.Style.RESET_ALL
except ImportError:
    RED = GREEN = CYAN = YELLOW = MAGENTA = RESET = ""


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")


# ─── 单次命令 ──────────────────────────────────────────────

async def cmd_list(controller: VTSController):
    await controller.print_full_summary()

async def cmd_activate_expression(controller: VTSController, name_or_index: str):
    """激活表情"""
    if name_or_index.isdigit():
        idx = int(name_or_index)
        try:
            await controller.activate_expression_by_index(idx, active=True)
            print(f"{GREEN}✓ 表情 [{idx}] 已激活{RESET}")
        except ValueError as e:
            print(f"{RED}✗ {e}{RESET}")
            sys.exit(1)
    else:
        try:
            await controller.activate_expression_by_name(name_or_index, active=True)
            print(f"{GREEN}✓ 表情「{name_or_index}」已激活{RESET}")
        except ValueError as e:
            print(f"{RED}✗ {e}{RESET}")
            sys.exit(1)

async def cmd_deactivate_expression(controller: VTSController, name_or_index: str):
    """停用表情"""
    if name_or_index.isdigit():
        idx = int(name_or_index)
        try:
            await controller.activate_expression_by_index(idx, active=False)
            print(f"{GREEN}✓ 表情 [{idx}] 已停用{RESET}")
        except ValueError as e:
            print(f"{RED}✗ {e}{RESET}")
            sys.exit(1)
    else:
        try:
            await controller.activate_expression_by_name(name_or_index, active=False)
            print(f"{GREEN}✓ 表情「{name_or_index}」已停用{RESET}")
        except ValueError as e:
            print(f"{RED}✗ {e}{RESET}")
            sys.exit(1)

async def cmd_play_all_expressions(controller: VTSController):
    await controller.play_all_expressions(delay=0.5)

async def cmd_reset(controller: VTSController):
    await controller.deactivate_all_expressions()
    print(f"{GREEN}✓ 已停用所有表情（回到默认）{RESET}")

async def cmd_trigger_hotkey(controller: VTSController, name_or_index: str):
    """触发热键"""
    if name_or_index.isdigit():
        try:
            await controller.trigger_hotkey_by_index(int(name_or_index))
            print(f"{GREEN}✓ 热键 [{name_or_index}] 已触发{RESET}")
        except ValueError as e:
            print(f"{RED}✗ {e}{RESET}")
            sys.exit(1)
    else:
        try:
            await controller.trigger_hotkey_by_name(name_or_index)
            print(f"{GREEN}✓ 热键「{name_or_index}」已触发{RESET}")
        except ValueError as e:
            print(f"{RED}✗ {e}{RESET}")
            sys.exit(1)


# ─── 交互模式 ──────────────────────────────────────────────

HELP_TEXT = f"""
{CYAN}═══════════════════════════════════════════════════
  VTube Studio 表情 & 动作控制
═══════════════════════════════════════════════════{RESET}

  {YELLOW}【表情控制 — 直接生效，无需热键】{RESET}
    {GREEN}list{RESET} / {GREEN}l{RESET}               查看模型完整信息
    {GREEN}expr <N|名称>{RESET}           激活指定表情
    {GREEN}expr-off <N|名称>{RESET}       停用指定表情
    {GREEN}expr-all{RESET}                依次播放所有表情
    {GREEN}reset{RESET}                   停用所有表情（回到默认）
    {GREEN}setup{RESET}                  一键创建控制参数 + 映射指引

  {YELLOW}【嘴巴 & 眼睛】{RESET}
    {GREEN}mouth <0.0~1.0>{RESET}        嘴巴开合 (0=闭, 1=张)
    {GREEN}eye <0.0~1.0>{RESET}          眼睛睁开 (0=闭, 1=睁)
    {GREEN}blink{RESET}                   眨眼一次
    {GREEN}wink-l / wink-r{RESET}       左/右眼 wink
    {GREEN}smile-eye <0.0~1.0>{RESET}    笑眼程度

  {YELLOW}【身体摇晃】{RESET}
    {GREEN}sway <x> <y> <z>{RESET}       三轴身体摇晃 (-1~1)
    {GREEN}sway-x <值>{RESET}            左右摇晃 (负=左, 正=右)
    {GREEN}sway-y <值>{RESET}            前后倾斜
    {GREEN}sway-z <值>{RESET}            歪头
    {GREEN}sway-anim{RESET}              身体摇晃动画
    {GREEN}body-reset{RESET}             重置身体姿态
    {GREEN}shake [次数]{RESET}            左右晃头 (否定)
    {GREEN}nod [次数]{RESET}              点头 (肯定)

  {YELLOW}【其他】{RESET}
    {GREEN}params [关键字]{RESET}         搜索/列出参数
    {GREEN}set <参数> <值>{RESET}         直接设置参数值
    {GREEN}move <x> <y> <rot> <size>{RESET} 物理移动模型
    {GREEN}refresh{RESET}                 刷新所有数据
    {GREEN}help{RESET} / {GREEN}h{RESET}              显示帮助
    {GREEN}quit{RESET} / {GREEN}q{RESET}              退出
"""

async def interactive_mode(controller: VTSController):
    """交互式命令循环"""
    print(HELP_TEXT)
    await controller.print_full_summary()

    while True:
        try:
            raw = input(f"\n{CYAN}VTS>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出")
            break

        if not raw:
            continue

        parts = raw.split(maxsplit=2)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        arg2 = parts[2] if len(parts) > 2 else ""

        try:
            if cmd in ("quit", "q", "exit"):
                print("再见!")
                break

            elif cmd in ("help", "h"):
                print(HELP_TEXT)

            elif cmd in ("list", "l"):
                await controller.print_full_summary()

            elif cmd == "refresh":
                print("刷新中...")
                await controller.fetch_expressions()
                await controller.fetch_hotkeys()
                await controller.fetch_parameters()
                await controller.fetch_art_meshes()
                await controller.print_full_summary()

            elif cmd == "model":
                info = await controller.get_model_info()
                print(f"模型: {info.get('modelName', '未知')}")
                print(f"ID: {info.get('modelID', '')}")

            # ── 表情控制 ──
            elif cmd == "expr":
                if not arg:
                    expressions = await controller.list_expressions()
                    print(f"\n{MAGENTA}用法: expr <索引 或 名称>{RESET}")
                    print(f"当前表情 ({len(expressions)} 个):")
                    for i, e in enumerate(expressions):
                        s = "🟢" if e.active else "⚪"
                        print(f"  [{i}] {s} {e.name}")
                    continue
                await cmd_activate_expression(controller, arg)

            elif cmd == "expr-off":
                if not arg:
                    print(f"{RED}用法: expr-off <索引 或 名称>{RESET}")
                    continue
                await cmd_deactivate_expression(controller, arg)

            elif cmd == "expr-all":
                await cmd_play_all_expressions(controller)

            elif cmd == "reset":
                await cmd_reset(controller)

            elif cmd == "setup":
                await controller.setup_all_control_params()
                print(f"\n{GREEN}✓ 控制参数已就绪。请按上面的指引在 VTS 中完成映射。{RESET}")

            # ── 热键控制 ──
            elif cmd == "hotkey":
                if not arg:
                    hotkeys = await controller.list_hotkeys()
                    if hotkeys:
                        print(f"已配置的热键 ({len(hotkeys)} 个):")
                        for i, hk in enumerate(hotkeys):
                            print(f"  [{i}] {hk}")
                    else:
                        print(f"{YELLOW}当前没有配置热键。表情可直接控制，无需热键。{RESET}")
                    continue
                await cmd_trigger_hotkey(controller, arg)

            # ── 参数控制 ──
            elif cmd == "params":
                if arg:
                    matches = await controller.search_parameters(arg)
                    print(f"\n匹配 '{arg}' 的参数 ({len(matches)} 个):")
                    for i, p in enumerate(matches):
                        print(f"  [{i}] {p}")
                else:
                    params = await controller.list_parameters(refresh=True)
                    print(f"\nLive2D 参数 ({len(params)} 个):")
                    for i, p in enumerate(params):
                        print(f"  [{i}] {p}")
                    print(f"\n{MAGENTA}用法: params <关键字> 搜索, set <参数名> <值>{RESET}")

            elif cmd == "set":
                if not arg or not arg2:
                    print(f"{RED}用法: set <参数名> <值>{RESET}  例: set ParamMouthOpenY 0.8")
                    continue
                try:
                    val = float(arg2)
                    await controller.inject_parameters({arg: val})
                    print(f"{GREEN}✓ 已设置 {arg} = {val}{RESET}")
                except ValueError:
                    print(f"{RED}值必须是数字 (0.0~1.0){RESET}")

            # ── 嘴巴控制 ──
            elif cmd == "mouth":
                if not arg:
                    print(f"{RED}用法: mouth <0.0~1.0>{RESET}  0=闭合, 1=张开")
                    continue
                try:
                    val = float(arg)
                    await controller.set_mouth_open(val)
                    print(f"{GREEN}✓ 嘴巴: {val:.1f}{RESET}")
                except ValueError:
                    print(f"{RED}值必须是 0.0~1.0 之间的数字{RESET}")

            # ── 眼睛控制 ──
            elif cmd == "eye":
                if not arg:
                    print(f"{RED}用法: eye <0.0~1.0>{RESET}  0=闭合, 1=睁开")
                    continue
                try:
                    val = float(arg)
                    await controller.set_eye_open(val)
                    print(f"{GREEN}✓ 眼睛: {val:.1f}{RESET}")
                except ValueError:
                    print(f"{RED}值必须是数字{RESET}")

            elif cmd == "blink":
                await controller.blink()
                print(f"{GREEN}✓ 眨眼{RESET}")

            elif cmd == "wink-l":
                await controller.wink_left()
                print(f"{GREEN}✓ 左眼 wink{RESET}")

            elif cmd == "wink-r":
                await controller.wink_right()
                print(f"{GREEN}✓ 右眼 wink{RESET}")

            elif cmd == "smile-eye":
                if not arg:
                    print(f"{RED}用法: smile-eye <0.0~1.0>{RESET}")
                    continue
                try:
                    val = float(arg)
                    await controller.set_eye_smile(val)
                    print(f"{GREEN}✓ 笑眼: {val:.1f}{RESET}")
                except ValueError:
                    print(f"{RED}值必须是数字{RESET}")

            # ── 身体摇晃 ──
            elif cmd == "sway":
                if not arg:
                    print(f"{RED}用法: sway <x> <y> <z>{RESET}  例: sway 0.5 0 0")
                    continue
                try:
                    # 用完整 split 获取三个轴的值
                    sway_parts = raw.split(maxsplit=3)
                    x = float(sway_parts[1]) if len(sway_parts) > 1 else 0.0
                    y = float(sway_parts[2]) if len(sway_parts) > 2 else 0.0
                    z = float(sway_parts[3]) if len(sway_parts) > 3 else 0.0
                    await controller.set_body_sway(x, y, z)
                    print(f"{GREEN}✓ 身体: X={x:.1f} Y={y:.1f} Z={z:.1f}{RESET}")
                except ValueError:
                    print(f"{RED}值必须是数字{RESET}")

            elif cmd == "sway-x":
                if not arg:
                    print(f"{RED}用法: sway-x <值>{RESET}  负=左, 正=右")
                    continue
                try:
                    await controller.set_body_sway_x(float(arg))
                    print(f"{GREEN}✓ 左右摇晃: {arg}{RESET}")
                except ValueError:
                    print(f"{RED}值必须是数字{RESET}")

            elif cmd == "sway-y":
                if not arg:
                    print(f"{RED}用法: sway-y <值>{RESET}  负=后, 正=前")
                    continue
                try:
                    await controller.set_body_sway_y(float(arg))
                    print(f"{GREEN}✓ 前后倾斜: {arg}{RESET}")
                except ValueError:
                    print(f"{RED}值必须是数字{RESET}")

            elif cmd == "sway-z":
                if not arg:
                    print(f"{RED}用法: sway-z <值>{RESET}  负=左歪, 正=右歪")
                    continue
                try:
                    await controller.set_body_sway_z(float(arg))
                    print(f"{GREEN}✓ 歪头: {arg}{RESET}")
                except ValueError:
                    print(f"{RED}值必须是数字{RESET}")

            elif cmd == "sway-anim":
                await controller.sway_animation(cycles=3, amplitude=0.8, duration=0.5)
                print(f"{GREEN}✓ 摇晃动画完成{RESET}")

            elif cmd == "body-reset":
                await controller.reset_body()
                print(f"{GREEN}✓ 身体姿态已重置{RESET}")

            # ── 晃头 / 点头 ──
            elif cmd == "shake":
                count = int(arg) if arg.isdigit() else 3
                await controller.head_shake(count=count)
                print(f"{GREEN}✓ 晃头 {count} 次{RESET}")

            elif cmd == "nod":
                count = int(arg) if arg.isdigit() else 4
                await controller.head_nod(count=count)
                print(f"{GREEN}✓ 点头 {count} 次{RESET}")

            # ── 模型移动 ──
            elif cmd == "move":
                if not arg:
                    print(f"{RED}用法: move <x> <y> <rotation> <size>{RESET}")
                    continue
                try:
                    parts_list = raw.split(maxsplit=4)
                    mx = float(parts_list[1]) if len(parts_list) > 1 else 0
                    my = float(parts_list[2]) if len(parts_list) > 2 else 0
                    mr = float(parts_list[3]) if len(parts_list) > 3 else 0
                    ms = float(parts_list[4]) if len(parts_list) > 4 else 0
                    await controller.move_model(
                        position_x=mx, position_y=my,
                        rotation=mr, size=ms,
                    )
                    print(f"{GREEN}✓ 模型已移动{RESET}")
                except ValueError:
                    print(f"{RED}参数必须是数字{RESET}")

            else:
                print(f"{RED}未知命令 '{cmd}'，输入 help 查看帮助{RESET}")

        except VTSAPIError as e:
            print(f"{RED}API 错误: {e}{RESET}")
        except Exception as e:
            print(f"{RED}错误: {e}{RESET}")


# ─── 主入口 ────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="VTube Studio 角色表情/动作控制器")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--verbose", "-v", action="store_true")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", "-l", action="store_true", help="查看完整信息")
    group.add_argument("--expr", "-e", type=str, metavar="名称/索引", help="激活指定表情")
    group.add_argument("--expr-off", type=str, metavar="名称/索引", help="停用指定表情")
    group.add_argument("--expr-all", action="store_true", help="依次播放所有表情")
    group.add_argument("--reset", "-r", action="store_true", help="停用所有表情")
    group.add_argument("--hotkey", type=str, metavar="名称/索引", help="触发指定热键")

    args = parser.parse_args()
    setup_logging(args.verbose)

    controller = VTSController(host=args.host, port=args.port)

    try:
        await controller.connect()

        if args.list:
            await cmd_list(controller)
        elif args.expr:
            await cmd_activate_expression(controller, args.expr)
        elif args.expr_off:
            await cmd_deactivate_expression(controller, args.expr_off)
        elif args.expr_all:
            await cmd_play_all_expressions(controller)
        elif args.reset:
            await cmd_reset(controller)
        elif args.hotkey:
            await cmd_trigger_hotkey(controller, args.hotkey)
        else:
            await interactive_mode(controller)

    except VTSAPIError as e:
        print(f"\n{RED}连接失败: {e}{RESET}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n中断")
    except Exception as e:
        print(f"\n{RED}未预期错误: {type(e).__name__}: {e}{RESET}")
        if args.verbose:
            raise
        sys.exit(1)
    finally:
        await controller.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
