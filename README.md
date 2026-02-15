# 🚀 AI Poxy Tools（Python 实现）

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-v1.2.2-orange.svg)](CHANGELOG.md)

本项目用于在 **不改 Trae 源码** 的情况下，把它发往多个供应商域名（OpenAI / Anthropic / Gemini 等）的请求透明改写到你指定的上游站点，并将响应回传给 Trae。

**实现方式**：本机 TLS 终止 + 重新建立上游 HTTPS（MITM）

## ✨ 核心特性

- 🔐 **自动证书管理**：一键生成本地 Root CA 及域名证书
- 🌐 **智能 Hosts 管理**：自动写入/移除 DNS 劫持记录
- 🔄 **多供应商转发**：支持 OpenAI、Anthropic、Gemini 等多个 AI 服务
- ⚙️ **灵活配置**：支持按域名指定上游、路径改写等高级功能
- 🎨 **现代化 GUI**：PySide6 界面，支持托盘、主题、开机自启
- 📊 **实时日志**：支持过滤、搜索、滚动跟随的日志控制台
- ⚡ **高性能**：异步架构 + 多线程 UI，流畅不卡顿
- 📦 **打包优化**：EXE 体积仅 175 MB（优化后减少 80%）

## 物理定律级别的前提

HTTPS 是端到端的 TLS 校验。你要“在传输过程中改写域名”，就必须让 Trae
信任你本机签发的证书（Root CA）。否则 TLS 校验会失败，Trae 会直接拒绝连接。

等价表述：

- 不安装/信任本地 Root CA → TLS 校验失败 → Trae 连接失败
- 安装/信任本地 Root CA → 可进行 MITM → 才能“透明改写”

**若 Trae 使用证书固定（Certificate Pinning），即便装了 Root CA 也可能失败。**

## 本项目怎么工作

1. 在本机生成一个 Root CA，并为各个供应商域名生成叶子证书
2. Trae 访问这些域名时，DNS/hosts 解析到本机
3. 本机 HTTPS 服务用伪造证书完成 TLS
4. 将请求转发到指定上游（默认 `https://newapi.loserrc.com`）
5. 把响应回传给 Trae

## 运行环境

- Windows 10/11
- Python 3.10+

## 快速开始

### 1) 安装依赖

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### UI 启动（推荐）

```
python gui_app.py
```

> 证书安装与 hosts 修改需要管理员权限，若权限不足会弹窗提示。

### UI 配置（可选）

复制 `.env.example` 为 `.env`，并放入你的图标：

- `.env`：应用名称、版本、开发者、官网等信息
- `icons/app.png`：应用图标（可在 .env 中修改路径）

### 打包成 EXE（PyInstaller）

```
pip install pyinstaller
pyinstaller trae_poxy_ui.spec
```

产物目录：`dist/AI-Poxy-Tools/AI-Poxy-Tools.exe`

> `.env` 建议放在 EXE 同目录，便于修改；图标默认读取 `icons/app.png`。
> 若需要打包 `icons/`，已在 spec 中包含。

### 2) 生成本地 CA 与证书

```
python run.py init
```

生成文件位置：

- `certs/ca.pem`（Root CA 证书）
- `certs/ca.key`（Root CA 私钥）
- `certs/api.openai.com.pem`（叶子证书）
- `certs/api.openai.com.key`（叶子私钥）

### 3) 信任本地 Root CA（必须）

打开 **证书管理器**（`certmgr.msc`），把 `certs/ca.pem` 导入到：

```
受信任的根证书颁发机构
```

> 也可以使用 `certutil -addstore root certs\ca.pem`（需要管理员权限）。

### 4) 修改 hosts 解析

把需要劫持的域名指向本机，例如：

```
127.0.0.1 api.openai.com
127.0.0.1 api.anthropic.com
127.0.0.1 generativelanguage.googleapis.com
```

hosts 文件位置：`C:\Windows\System32\drivers\etc\hosts`

### 5) 启动本机 HTTPS 服务

默认监听 `127.0.0.1:8443`：

```
python run.py serve
```

Trae 实际访问的是 `https://api.openai.com:443`。
你有两种选择：

1. **以管理员权限运行，并把监听端口改成 443**
2. **保留 8443，然后用系统端口转发 443 → 8443**

端口转发示例（管理员 PowerShell）：

```
netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=443 connectaddress=127.0.0.1 connectport=8443
```

## 配置文件

`config.json`（首次 `init` 时自动生成）：

```

## 🎨 UI 功能总览

### 📋 系统操作（两行布局）

**第一行 - 配置操作**
- 🔑 **生成证书与配置**：生成本地 Root CA 及各域名证书
- 📜 **安装 Root CA**：将 Root CA 导入系统信任（需管理员）
- 🌐 **写入 hosts**：写入 hosts 以劫持域名（需管理员）
- ⚡ **一键配置并启动**：自动完成所有配置步骤并启动服务

**第二行 - 还原操作**
- 🗑️ **移除 hosts**：从 hosts 文件中移除劫持记录（需管理员）
- 🔓 **卸载 Root CA**：从系统信任中卸载证书（需管理员）
- ♻️ **还原设置**：一键移除 hosts + 卸载证书（需管理员）

### 🎮 服务控制
- ▶️ **启动服务**：后台启动转发服务
- ⏸️ **停止服务**：停止后台服务
- 🔄 **刷新状态**：刷新服务运行状态

### 📊 日志控制台
- 🔍 **日志过滤**：按级别筛选（ALL/ERROR/WARNING/INFO/DEBUG）
- 🔎 **关键词搜索**：实时搜索日志内容
- 📜 **滚动跟随**：自动滚动显示最新日志
- 🎨 **语法高亮**：不同日志级别使用不同颜色

### 🎛️ 菜单栏功能
- 📂 **文件**：导入/导出备份
- ⚙️ **系统**：首选项、一键配置、证书管理、hosts 管理
- ❓ **帮助**：使用说明、关于、版本信息

### 🎨 首选项设置
- 🔧 **基础设置**：监听地址、端口、上游地址、SSL 校验、日志级别
- 🔬 **高级设置**：preserve_host、log_response_body、normalize_models、劫持域名列表
- 🗺️ **映射设置**：上游域名映射（upstream_map）、路径改写（path_rewrite_map）
- 🎨 **主题设置**：浅色/深色主题切换

### 📱 其他功能
- 🔔 **系统托盘**：最小化到托盘、右键菜单（显示/隐藏/退出）
- 🚀 **开机自启**：支持当前用户开机自启动
- 📈 **状态监控**：实时显示 CA 安装状态、hosts 写入状态、服务运行状态
{
  "listen_host": "127.0.0.1",
  "listen_port": 8443,
  "default_upstream": "https://newapi.loserrc.com",
  "upstream_map": {},
  "verify_upstream_ssl": true,
  "upstream_ca_bundle": "",
  "log_level": "INFO",
  "log_file": "logs/trae_poxy.log",
  "preserve_host": false,
  "log_response_body": false,
  "normalize_models": true,
  "certs_dir": "certs",
  "intercept_hosts": [
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com"
  ],
  "path_rewrite_map": {
    "generativelanguage.googleapis.com": [
      ["/v1beta/openai/", "/v1/"]
    ]
  }
}
```

## 常见问题

**Q: Trae 能否不装 Root CA 直接改写？**
A: 不行。HTTPS 必须通过证书校验，否则连接会被拒绝。

**Q: Trae 可能仍然失败？**
A: 如果 Trae 使用证书固定（Pinning），MITM 会被检测并拒绝。

**Q: 请求头是否被改动？**
A: 只会移除 HTTP 规范要求的 hop-by-hop 头；其余头默认原样转发。
如果你需要连 `Host` 都不改，可在 `config.json` 里设置：

```
"preserve_host": true
```

若要查看上游返回的错误详情（例如 403 的具体原因），可开启响应体日志：

```
"log_response_body": true
```

若 Trae 对 `/v1/models` 响应格式较严格，可开启模型列表规范化（默认开启）：

```
"normalize_models": true
```

## 多供应商转发

默认所有被劫持的域名都会转发到 `default_upstream`。
如需为不同供应商指定不同上游，可设置 `upstream_map`：

```
"upstream_map": {
  "api.openai.com": "https://newapi.loserrc.com",
  "api.anthropic.com": "https://newapi.loserrc.com",
  "generativelanguage.googleapis.com": "https://newapi.loserrc.com"
}
```

## 路径改写

某些供应商（例如 Gemini）会通过 OpenAI 兼容路径调用（如 `/v1beta/openai/...`），
而你的上游可能只接受 `/v1/...`。可以用 `path_rewrite_map` 做按域名的前缀替换：

```
"path_rewrite_map": {
  "generativelanguage.googleapis.com": [
    ["/v1beta/openai/", "/v1/"]
  ]
}
```

## 日志

启动 `python run.py serve` 后，控制台会输出请求与转发日志，例如：

```
2026-02-03 09:15:12,345 INFO trae_poxy.proxy: incoming method=POST path=/v1/responses size=1234 upstream=https://newapi.loserrc.com/v1/responses
2026-02-03 09:15:12,901 INFO trae_poxy.proxy: forwarded status=200 bytes=5678 duration_ms=555.8
```

## 📚 项目文档

- 📖 [README.md](README.md) - 项目介绍与使用指南
- 📝 [CHANGELOG.md](CHANGELOG.md) - 版本更新日志
- 🛠️ [DEVELOPMENT.md](DEVELOPMENT.md) - 开发文档与技术细节

## 🏗️ 项目结构

```
AI-Poxy-tools/
├── 📁 trae_poxy/          # 核心代理逻辑
│   ├── certs.py          # TLS 证书生成
│   ├── config.py         # 配置管理
│   ├── proxy.py          # 代理转发逻辑
│   └── server.py         # HTTPS 服务器
├── 📄 gui_app.py          # PySide6 GUI 主程序
├── 📄 run.py              # CLI 命令行工具
├── 📄 trae_poxy_ui.spec   # PyInstaller 打包配置
├── 📄 config.json         # 运行时配置文件
├── 📄 .env                # UI 应用信息配置
├── 📁 certs/              # 证书存储目录
│   ├── ca.pem            # Root CA 证书
│   ├── ca.key            # Root CA 私钥
│   └── *.pem/*.key       # 各域名证书
├── 📁 logs/               # 日志文件目录
├── 📁 icons/              # 应用图标资源
└── 📄 requirements.txt    # Python 依赖包
```

## 🚀 性能指标

### 打包体积优化
| 项目 | 优化前 | 优化后 | 减少幅度 |
|------|--------|--------|----------|
| 总体积 | 894 MB | 175 MB | ⬇️ **80.5%** |
| PySide6 模块 | 全部打包 | 精简至核心 | 排除 51 个未使用模块 |

### UI 响应性能
| 操作 | 优化前 | 优化后 |
|------|--------|--------|
| 启动服务 | 阻塞 2-5 秒 | 立即响应 ⚡ |
| 停止服务 | 阻塞 1-2 秒 | 立即响应 ⚡ |
| 证书安装 | 阻塞 3-6 秒 | 立即响应 ⚡ |
| Hosts 写入 | 阻塞 1-3 秒 | 立即响应 ⚡ |

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 开源协议

本项目采用 MIT 协议开源，详见 [LICENSE](LICENSE) 文件。

## 👨‍💻 作者

**Ying XingYao**

- 🌐 Website: [https://newapi.loserrc.com/](https://newapi.loserrc.com/)
- 📧 Project: https://github.com/loserrc/AI-Poxy-tools

## ⚠️ 免责声明

本工具仅供学习和研究使用，请遵守相关法律法规和服务条款。使用本工具产生的任何后果由使用者自行承担。

## 🙏 致谢

感谢所有使用和支持本项目的朋友们！

---

**如果觉得这个项目对你有帮助，请给个 ⭐ Star 支持一下！**
