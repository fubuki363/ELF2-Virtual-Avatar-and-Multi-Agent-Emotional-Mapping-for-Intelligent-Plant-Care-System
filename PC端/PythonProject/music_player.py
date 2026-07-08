import os
import time
import requests
import threading
import warnings

# 🤫 屏蔽无关日志
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"
warnings.filterwarnings("ignore", category=UserWarning, module="pygame.pkgdata")

import pygame
from pyncm import GetCurrentSession
from pyncm.apis import cloudsearch, track

# ==========================================
# 🎵 1. 全局配置区
# ==========================================
MUSIC_U_COOKIE = os.getenv("Netease_MUSIC_U_COOKIE")

# 设置 VIP Cookie（修复：去掉永为 False 的冗余条件）
if MUSIC_U_COOKIE:
    GetCurrentSession().cookies.set('MUSIC_U', MUSIC_U_COOKIE, domain='.music.163.com')
    print("🍪 已加载网易云 VIP Cookie ✓")

AI_IS_SINGING = False

# 🎯 双轨声卡配置
AI_VOICE_DEVICE = "CABLE Input (VB-Audio Virtual Cable)"
NORMAL_BGM_DEVICE = "扬声器 (2- Realtek(R) Audio)"

# 音频质量等级（从高到低尝试）
BITRATE_LEVELS = [
    (999000, "无损"),       # 无损
    (320000, "HQ 高品质"),   # 320kbps
    (192000, "标准品质"),    # 192kbps
    (128000, "普通品质"),    # 128kbps
]

# 最少文件大小（字节），小于此值认为是试听片段
MIN_AUDIO_SIZE = 500 * 1024  # 500KB


# ==========================================
# 🗑️ 2. 全局无头清理线程
# ==========================================
def _global_cache_cleaner():
    while True:
        time.sleep(3)
        if pygame.mixer.get_init() and not pygame.mixer.music.get_busy():
            try:
                pygame.mixer.music.unload()
            except AttributeError:
                pass

        for file in os.listdir("."):
            if file.startswith("bgm_") and file.endswith(".mp3"):
                try:
                    os.remove(file)
                except PermissionError:
                    pass


threading.Thread(target=_global_cache_cleaner, daemon=True).start()


# ==========================================
# 🎧 3. 获取音频 URL（多级降级策略）
# ==========================================
def _get_audio_url(song_id: int) -> tuple:
    """
    获取歌曲的音频直链，使用多级音质降级策略。

    返回: (url, bitrate_used, quality_label) 或 (None, 0, "")
    """
    for bitrate, label in BITRATE_LEVELS:
        try:
            print(f"  尝试 {label} ({bitrate//1000}kbps)...")
            audio_info = track.GetTrackAudio([song_id], bitrate=bitrate)
            track_data = audio_info.get('data', [{}])

            if not track_data:
                continue

            url = track_data[0].get('url', '')
            size = track_data[0].get('size', 0)
            audio_type = track_data[0].get('type', '')

            if not url:
                # URL 为空可能是该音质等级不可用
                print(f"  {label} URL 为空，降级尝试...")
                continue

            # 如果有 size 信息且太小，跳过
            if size and size < MIN_AUDIO_SIZE:
                print(f"  {label} 文件过小 ({size}B)，可能是试听片段，降级尝试...")
                continue

            print(f"  ✅ 获取到 {label} 音频 ({size}B, type={audio_type})")
            return url, bitrate, label

        except Exception as e:
            print(f"  {label} 请求失败: {e}")
            continue

    return None, 0, ""


# ==========================================
# 🎧 4. 下载音频并校验完整性
# ==========================================
def _download_audio(url: str, song_title: str) -> str:
    """
    下载音频文件并校验最小大小。

    返回: 临时文件路径
    抛出: ValueError 如果下载的文件是试听片段
    """
    temp_file = f"bgm_{int(time.time())}.mp3"

    print(f"  ⏳ 下载中...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    content = response.content
    file_size = len(content)

    # 校验：VIP 歌曲试听片段通常很小
    if file_size < MIN_AUDIO_SIZE:
        raise ValueError(
            f"下载文件仅 {file_size // 1024}KB，疑似 VIP 试听片段而非完整歌曲。\n"
            f"提示：请确认 Cookie 来自网易云 VIP 账号。"
        )

    with open(temp_file, "wb") as f:
        f.write(content)

    print(f"  ✅ 下载完成: {file_size // 1024}KB")
    return temp_file


# ==========================================
# 🎧 5. 主播专用双轨点歌逻辑
# ==========================================
def play_netease_music(song_name, mode="bgm"):
    """
    mode 参数控制播放通道：
    - "bgm" : 正常后台播放 → 扬声器
    - "ai_sing" : 喂给变声器让酢酱酱强行唱歌 → 虚拟声卡
    """
    global AI_IS_SINGING

    try:
        if mode == "ai_sing":
            print(f"🎤 [整活模式] 酢酱酱准备深情献唱: {song_name}...")
            AI_IS_SINGING = True
        else:
            print(f"🎵 [正常模式] 正在全网搜索 BGM: {song_name}...")
            AI_IS_SINGING = False

        # 1. 搜索歌曲
        search_result = cloudsearch.GetSearchResult(song_name, stype=1, limit=1)
        songs = search_result.get('result', {}).get('songs', [])

        if not songs:
            return False, "哎呀，酢酱酱没有找到这首歌呢~"

        song_id = songs[0]['id']
        song_title = songs[0]['name']
        artist = songs[0]['ar'][0]['name']

        print(f"  🔍 搜索结果: 《{song_title}》- {artist} (ID={song_id})")

        # 2. 获取音频直链（多级降级 + 传入列表）
        audio_url, bitrate, quality = _get_audio_url(song_id)

        if not audio_url:
            return False, (
                f"哎呀，《{song_title}》的所有音质等级都拿不到流呢～\n"
                f"可能是付费 VIP 歌曲或版权限制，试试其他歌吧！"
            )

        # 3. 下载音频并校验
        try:
            temp_file = _download_audio(audio_url, song_title)
        except ValueError as e:
            print(f"  ❌ 下载校验失败: {e}")
            return False, (
                f"哎呀，《{song_title}》是 VIP 歌曲，只拿到了几秒试听片段～\n"
                f"小提示：需要网易云 VIP 账号的 Cookie 才能播放完整版哦！\n"
                f"在 .env 中设置 Netease_MUSIC_U_COOKIE 即可～"
            )

        # 4. 动态音频路由切换
        if pygame.mixer.get_init():
            pygame.mixer.quit()

        target_device = AI_VOICE_DEVICE if mode == "ai_sing" else NORMAL_BGM_DEVICE

        try:
            pygame.mixer.init(devicename=target_device)
        except Exception as e:
            print(f"⚠️ 切换声卡 [{target_device}] 失败: {e}，回退至默认设备！")
            pygame.mixer.init()

        # 5. 加载并播放
        pygame.mixer.music.load(temp_file)
        pygame.mixer.music.play()

        if mode == "ai_sing":
            return True, f"咳咳，接下来由酢酱酱为大家倾情翻唱《{song_title}》（{quality}），捂好耳朵哦！"
        else:
            return True, f"已经安排上啦，正在为你播放 {artist} 的《{song_title}》（{quality}）~"

    except Exception as e:
        print(f"❌ 点歌出错: {e}")
        import traceback
        traceback.print_exc()
        return False, "系统开小差啦，稍后再试吧！"


def stop_music():
    """强制停止当前播放并清理缓存"""
    global AI_IS_SINGING
    try:
        AI_IS_SINGING = False
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            try:
                pygame.mixer.music.unload()
            except AttributeError:
                pass

        cleaned_count = 0
        for file in os.listdir("."):
            if file.startswith("bgm_") and file.endswith(".mp3"):
                try:
                    os.remove(file)
                    cleaned_count += 1
                except PermissionError:
                    pass

        print(f"🛑 音乐已强制停止，清空了 {cleaned_count} 个缓存文件。")
        return True, "收到！已经帮你把音乐关掉，并且把后台打扫得干干净净啦！"

    except Exception as e:
        print(f"❌ 停止音乐出错: {e}")
        return False, "哎呀，强制关停的时候好像卡住了..."


def check_is_singing():
    """供外部冷场系统调用：判断 AI 是否正在唱歌"""
    global AI_IS_SINGING
    if AI_IS_SINGING and pygame.mixer.get_init() and pygame.mixer.music.get_busy():
        return True
    else:
        AI_IS_SINGING = False
        return False
