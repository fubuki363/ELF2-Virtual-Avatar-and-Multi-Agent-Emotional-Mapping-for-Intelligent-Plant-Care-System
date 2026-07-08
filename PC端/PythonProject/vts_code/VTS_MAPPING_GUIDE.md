# VTube Studio 参数映射指引（只需设置一次）

## 背景

程序已自动在你的 VTube Studio 中创建了 12 个**自定义追踪参数**（如 `ctrl_mouth_open`、`ctrl_eye_open_left` 等）。

现在需要将它们**映射到模型对应的 Live2D 参数**上，这样程序注入的值才能驱动模型动起来。

---

## 操作步骤（VTS v1.35.x）

### 第一步：打开 Live2D 参数配置

1. 在 VTube Studio 主界面，点击右上角的 **⚙ 齿轮图标** 打开设置
2. 在左侧找到并点击 **「模型 & 背景」** 或类似选项卡

### 第二步：找到参数输入配置

> ⚠ VTS 1.35 的具体菜单位置可能略有不同，请按以下顺序查找：

**路径 A：**
- 在 VTS 下方 / 侧边栏找到 **"参数配置"** (Parameters) 面板
- 如果看不到，在设置中启用 "显示高级选项"

**路径 B：**
- 设置 → 找到模型相关的参数面板
- 在 Live2D 参数列表中，每个参数旁边有 **"+ 输入"** 或 **"添加输入源"** 按钮

### 第三步：逐个映射参数

按照下表，将**自定义参数**映射到对应的 **Live2D 参数**：

| 自定义参数 (已自动创建) | 映射到 Live2D 参数 | 控制功能 |
|---|---|---|
| `ctrl_mouth_open` | `ParamMouthOpenY` | 嘴巴开合 |
| `ctrl_mouth_form` | `ParamMouthForm` | 嘴巴形状 |
| `ctrl_eye_open_left` | `ParamEyeLOpen` | 左眼开合 |
| `ctrl_eye_open_right` | `ParamEyeROpen` | 右眼开合 |
| `ctrl_eye_smile_left` | `ParamEyeLSmile` | 左眼笑眼 |
| `ctrl_eye_smile_right` | `ParamEyeRSmile` | 右眼笑眼 |
| `ctrl_body_sway_x` | `ParamBodyAngleX` | 身体左右摇晃 |
| `ctrl_body_sway_y` | `ParamBodyAngleY` | 身体前后倾斜 |
| `ctrl_body_sway_z` | `ParamBodyAngleZ` | 身体歪头 |
| `ctrl_breath` | `ParamBreath` | 呼吸幅度 |
| `ctrl_brow_y_left` | `ParamBrowLY` | 左眉高低 |
| `ctrl_brow_y_right` | `ParamBrowRY` | 右眉高低 |

### 第四步：测试

映射完成后，在程序交互界面中测试：

```
VTS> mouth 0.8    # 嘴巴应该张开
VTS> mouth 0      # 嘴巴应该闭合
VTS> blink        # 应该眨眼
VTS> sway-anim    # 身体应该左右摇晃
```

---

## 如果找不到映射入口

VTS 的 UI 在不同版本间有差异。如果上述路径不适用，可以尝试：

1. **在 VTS 中搜索 "input" 或 "参数"**
2. **查看 VTS 官方文档**: https://github.com/DenchiSoft/VTubeStudio
3. **检查是否需要勾选设置中的 "显示高级选项"**
4. 或者直接在 VTS 设置中逐个浏览所有选项卡，找到参数/输入相关的面板

> 💡 提示：这个映射**只需做一次**。下次启动程序时参数会自动生效，无需重复配置。
