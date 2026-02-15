# 开发文档

## 项目结构

- `run.py`：CLI 入口（init/serve）
- `trae_poxy/`：核心转发逻辑
- `gui_app.py`：PySide6 控制面板
- `config.json`：运行配置（首次 init 生成）
- `.env`：UI 信息与图标配置（可选）

## 本地运行

```
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python gui_app.py
```

## 证书与 hosts

- `run.py init` 生成 CA 与叶子证书
- hosts 写入需要管理员权限
- CA 安装需要管理员权限

## UI 说明

- “首选项…”：基础/高级/映射/主题
- “一键配置并启动”：自动生成证书、安装 CA、写 hosts、启动服务
- 托盘：右键菜单显示/隐藏/退出
- 高级设置增加 `log_request_body`（请求摘要）与 `log_response_body`（响应日志/转储）

## 打包

```
pip install pyinstaller
pyinstaller trae_poxy_ui.spec
```

## 注意事项

- `log_request_body=true` 会记录用户问题摘要，可能包含敏感信息
- `log_response_body=true` 会记录响应预览并写入 `logs/stream_dump.log`
- UI 日志预览默认显示最后 1000 行
- `/v1/models` 仅对 OpenAI 域名进行规范化
