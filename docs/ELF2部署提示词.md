# ELF 2 部署系统提示词

你需要在飞凌 ELF 2 开发板（RK3588, Ubuntu 22.04, Python 3.10）上部署一套智能温室AI助手系统。

## 硬件环境
- 芯片: Rockchip RK3588 (4×A76@2.4GHz + 4×A55@1.8GHz, 6TOPS NPU)
- 内存: 4GB LPDDR4
- 存储: 32GB eMMC, 剩余空间≥10GB
- 系统: ELF Desktop Ubuntu 22.04 (Linux 5.10.209)
- 网络: 千兆以太网/WiFi, 需可访问互联网 (DeepSeek API + EMQX Cloud)
- 外设: 语音模块接 /dev/ttyS9 (9600bps), 7寸MIPI屏 (可选)

## 软件依赖清单

### 系统包 (apt)
```
python3-pip python3-dev python3-venv
portaudio19-dev espeak-ng alsa-utils
libsndfile1 ffmpeg libavcodec-dev libavformat-dev
mysql-server
```

### Python包 (pip)
```
# 核心
pyserial>=3.5 serial-asyncio>=0.6
paho-mqtt>=2.0 openai>=1.0 pymysql>=1.1
python-dotenv>=1.0 websockets>=12.0

# TTS (二选一)
piper-tts>=1.2  # 推荐, 本地离线

# Agent (LangGraph工作流)
langgraph>=0.2 langchain-chroma>=0.3
chromadb>=0.5 zhipuai>=2.0
python-docx>=1.0 requests>=2.31 beautifulsoup4>=4.12

# 视频+YOLO (可选)
torch ultralytics opencv-python av
```

## 部署步骤

### Step 1: 系统准备
```bash
sudo apt update && sudo apt install -y [上述apt包列表]
python3 -m venv ~/greenhouse-venv && source ~/greenhouse-venv/bin/activate
pip install --upgrade pip
```

### Step 2: 项目代码
将仓库 `elf2-projects/` 完整拷贝至 `~/elf2-projects/`

### Step 3: 依赖安装
```bash
cd ~/elf2-projects/elf2/
pip install -r requirements.txt
```

### Step 4: 环境变量
```bash
cp .env.example .env
# 编辑 .env，必填: DEEPSEEK_API_KEY, MYSQL_PASSWORD, MQTT_PASSWORD
# 可选: ZHIPU_API_KEY (RAG向量检索需要)
```

### Step 5: 数据库
```bash
sudo systemctl start mysql
sudo mysql -e "CREATE DATABASE IF NOT EXISTS ai_agent_memory2 CHARACTER SET utf8mb4;"
python -c "import database; database.init_tables()"
```

### Step 6: 模型文件
```bash
# Piper TTS 模型
mkdir -p ~/.local/share/piper-tts/
wget -P ~/.local/share/piper-tts/ \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json

# YOLOv5 模型
cp best.pt ~/elf2-projects/sensor-listener/sensor_listener/

# 知识库导入 (可选)
mkdir -p ~/elf2-projects/docs/
# 放入植物资料 .txt/.docx
python -m agent.ingest_docs
```

### Step 7: 启动验证
```bash
# 终端1: 温室控制器
cd ~/elf2-projects/sensor-listener/ && python -m sensor_listener --verbose

# 终端2: AI角色分身
cd ~/elf2-projects/elf2/ && python elf2_main.py
```

## 验证标准
- [ ] `python -m sensor_listener --verbose` 启动无 import 错误
- [ ] 终端出现 "监听 0.0.0.0:8259，等待数据..."
- [ ] K230 上线后每秒更新传感器数据
- [ ] 健康指数显示 0-100 的合理值
- [ ] `python elf2_main.py` 启动无错误
- [ ] MQTT 显示 "成功连接到 EMQX Cloud"
- [ ] 串口语音输入能触发 Agent 回复
- [ ] TTS 能正常播放语音

## 无需部署的内容
- ❌ 不需要 GPU/CUDA (YOLO 用 CPU 或 NPU 推理)
- ❌ 不需要 Docker
- ❌ 不需要 nginx/Apache
- ❌ 不需要 Node.js
- ❌ 不需要交叉编译 (全部 Python pip 安装)
