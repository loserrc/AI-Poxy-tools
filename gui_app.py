import json
import subprocess
import sys
from pathlib import Path
import ctypes
import winreg
import shutil
import os
import urllib.error
import urllib.request

from PySide6 import QtCore, QtGui, QtWidgets
import re
from typing import Callable, Any


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def bundle_root() -> Path:
    base = getattr(sys, "_MEIPASS", "")
    return Path(base) if base else app_root()


def resolve_resource(rel_path: str) -> Path:
    rel = Path(rel_path)
    candidate = app_root() / rel
    if candidate.exists():
        return candidate
    bundled = bundle_root() / rel
    return bundled


ROOT = app_root()
CONFIG_PATH = ROOT / "config.json"
PID_PATH = ROOT / ".poxy" / "service.pid"
HOSTS_PATH = Path(r"C:\Windows\System32\drivers\etc\hosts")
ENV_PATH = ROOT / ".env"


def load_env() -> dict:
    env = {}
    env_path = ENV_PATH
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            env[key.strip()] = value.strip().strip('"')
    return env


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run_cmd(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        args, capture_output=True, text=True, cwd=str(ROOT), shell=False
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def ensure_pid_dir() -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)


def read_pid() -> int | None:
    if not PID_PATH.exists():
        return None
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_pid(pid: int) -> None:
    ensure_pid_dir()
    PID_PATH.write_text(str(pid), encoding="utf-8")


def clear_pid() -> None:
    if PID_PATH.exists():
        PID_PATH.unlink()


def _cli_cmd(command: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, f"--{command}"]
    return [sys.executable, "run.py", command]


def start_service() -> None:
    ensure_pid_dir()
    proc = subprocess.Popen(
        _cli_cmd("serve"),
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    write_pid(proc.pid)


def stop_service() -> None:
    pid = read_pid()
    if not pid:
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    clear_pid()


def update_hosts(hosts: list[str]) -> None:
    content = HOSTS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    cleaned = []
    for line in content:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            cleaned.append(line)
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[1] in hosts:
            continue
        cleaned.append(line)
    cleaned.append("")
    for host in hosts:
        cleaned.append(f"127.0.0.1 {host}")
    HOSTS_PATH.write_text("\n".join(cleaned) + "\n", encoding="utf-8")


def hosts_missing(hosts: list[str]) -> list[str]:
    if not HOSTS_PATH.exists():
        return hosts
    content = HOSTS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    existing = set()
    for line in content:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            existing.add(parts[1])
    return [host for host in hosts if host not in existing]


def remove_hosts(hosts: list[str]) -> None:
    if not HOSTS_PATH.exists():
        return
    content = HOSTS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    cleaned = []
    for line in content:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            cleaned.append(line)
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[1] in hosts:
            continue
        cleaned.append(line)
    HOSTS_PATH.write_text("\n".join(cleaned) + "\n", encoding="utf-8")


def ca_installed() -> bool:
    code, out, _ = run_cmd(["certutil", "-store", "root"])
    if code != 0:
        return False
    return "Trae-Poxy Local CA" in out


def tail_log(path: Path, lines: int = 1000) -> str:
    if not path or not path.exists() or not path.is_file():
        return ""
    data = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(data[-lines:])


def append_ui_log(message: str, level: str = "INFO") -> None:
    log_path = CONFIG_PATH.parent / "logs" / "trae_poxy.log"
    if CONFIG_PATH.exists():
        try:
            cfg = load_config()
            if cfg.get("log_file"):
                log_path = Path(cfg["log_file"])
        except Exception:
            pass
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss,zzz")
    with log_path.open("a", encoding="utf-8", errors="ignore") as handle:
        handle.write(f"{ts} {level} UI: {message}\n")


def compare_versions(current: str, latest: str) -> int:
    def normalize(value: str) -> list[int]:
        cleaned = (value or "").strip()
        if cleaned.lower().startswith("v"):
            cleaned = cleaned[1:]
        parts = cleaned.split(".") if cleaned else ["0"]
        numbers = []
        for part in parts:
            match = re.search(r"\\d+", part)
            if match:
                numbers.append(int(match.group()))
            else:
                numbers.append(0)
        return numbers

    current_parts = normalize(current)
    latest_parts = normalize(latest)
    max_len = max(len(current_parts), len(latest_parts))
    for idx in range(max_len):
        cur = current_parts[idx] if idx < len(current_parts) else 0
        new = latest_parts[idx] if idx < len(latest_parts) else 0
        if cur < new:
            return -1
        if cur > new:
            return 1
    return 0


class WorkerThread(QtCore.QThread):
    finished = QtCore.Signal(bool, object)
    progress = QtCore.Signal(str)

    def __init__(self, func: Callable, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._is_running = True

    def run(self):
        try:
            if self._is_running:
                result = self.func(*self.args, **self.kwargs)
                self.finished.emit(True, result)
        except Exception as e:
            self.finished.emit(False, str(e))

    def stop(self):
        self._is_running = False


LEVEL_EMOJI = {
    "ERROR": "❌",
    "WARNING": "⚠️",
    "WARN": "⚠️",
    "INFO": "ℹ️",
    "DEBUG": "🐞",
    "TRACE": "🧭",
    "WARMUP": "🔥",
}


def render_log_html(text: str, level_filter: str, search: str) -> str:
    lines = text.splitlines()
    parts = []
    pattern = re.compile(r"^(\S+\s+\S+)\s+(\w+)\s+(.*)$")
    search_lower = search.strip().lower()
    warmup_groups = []
    current_group = None

    for line in lines:
        level = ""
        message = line
        ts = ""
        match = pattern.match(line)
        if match:
            ts, level, message = match.groups()
        if "[Warmup-API]" in line:
            level = "WARMUP"
        if level_filter != "ALL" and level and level != level_filter:
            continue
        if search_lower and search_lower not in line.lower():
            continue
        emoji = LEVEL_EMOJI.get(level, "•")
        color = "#94a3b8"
        if level in ("ERROR",):
            color = "#ef4444"
        elif level in ("WARNING", "WARN"):
            color = "#f59e0b"
        elif level == "INFO":
            color = "#3b82f6"
        elif level == "DEBUG":
            color = "#8b5cf6"
        elif level == "TRACE":
            color = "#10b981"
        elif level == "WARMUP":
            color = "#f97316"
        safe_line = (
            line.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        entry = (
            f"<div style='margin:2px 0;'>"
            f"<span style='color:{color}; font-weight:600;'>{emoji} {level or 'LOG'}</span> "
            f"<span style='color:#64748b;'>{ts}</span> "
            f"<span>{safe_line}</span>"
            f"</div>"
        )

        if "[Warmup-API]" in line and "START:" in line:
            if current_group:
                warmup_groups.append(current_group)
            current_group = {
                "title": safe_line,
                "items": [entry],
            }
            continue

        if current_group:
            current_group["items"].append(entry)
        else:
            parts.append(entry)

    if current_group:
        warmup_groups.append(current_group)

    for group in warmup_groups:
        items_html = "".join(group["items"])
        parts.append(
            f"<details open><summary style='color:#f97316; font-weight:700;'>🔥 {group['title']}</summary>"
            f"{items_html}</details>"
        )
    if not parts:
        return "<div style='color:#94a3b8;'>No logs</div>"
    return "\n".join(parts)


class TraePoxyWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.env = load_env()
        app_name = self.env.get("APP_NAME", "AI Poxy Tools 控制面板")
        self.setWindowTitle(app_name)
        self.resize(1100, 760)
        icon_path = self.env.get("APP_ICON", "icons/app.ico")
        icon_file = resolve_resource(icon_path)
        if icon_file.exists():
            icon = QtGui.QIcon(str(icon_file))
        else:
            icon = self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        self.setWindowIcon(icon)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 12, 16, 12)

        # Top spacing only
        menu_divider = QtWidgets.QFrame()
        menu_divider.setFrameShape(QtWidgets.QFrame.HLine)
        menu_divider.setFrameShadow(QtWidgets.QFrame.Plain)
        menu_divider.setStyleSheet(
            "border-top: 1px solid #e5e7eb; margin-left:-16px; margin-right:-16px;"
        )
        layout.addWidget(menu_divider)

        self.config = load_config()
        if not self.config:
            self.config = {}

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self._build_system_group(), 2)
        top_row.addWidget(self._build_service_group(), 1)
        layout.addLayout(top_row)

        layout.addWidget(self._build_log_group(), 1)

        self._build_status_bar()
        self._build_menu()
        self._refresh_log()
        self._refresh_pid()
        self._refresh_status()
        self._apply_theme(self._load_ui_theme())
        self._init_tray()
        self._init_log_timer()

    def _build_basic_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("基础设置")
        form = QtWidgets.QFormLayout(group)
        form.setVerticalSpacing(10)

        self.listen_host = QtWidgets.QLineEdit(self.config.get("listen_host", "127.0.0.1"))
        self.listen_host.setToolTip("本地监听地址（默认 127.0.0.1）")
        self.listen_port = QtWidgets.QSpinBox()
        self.listen_port.setRange(1, 65535)
        self.listen_port.setValue(int(self.config.get("listen_port", 8443)))
        self.listen_port.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.listen_port.setToolTip("本地监听端口（默认 8443）")
        self.default_upstream = QtWidgets.QLineEdit(
            self.config.get("default_upstream", "https://newapi.loserrc.com")
        )
        self.default_upstream.setToolTip("默认上游地址（未匹配域名时使用）")
        self.verify_ssl = QtWidgets.QCheckBox()
        self.verify_ssl.setChecked(bool(self.config.get("verify_upstream_ssl", True)))
        self.verify_ssl.setToolTip("是否校验上游 HTTPS 证书")
        self.log_level = QtWidgets.QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level.setCurrentText(self.config.get("log_level", "INFO"))
        self.log_level.setToolTip("日志等级")
        self.log_file = QtWidgets.QLineEdit(self.config.get("log_file", "logs/trae_poxy.log"))
        self.log_file.setToolTip("日志文件路径（留空仅控制台输出）")

        form.addRow(self._label_with_info("listen_host", "本地监听地址（默认 127.0.0.1）"), self.listen_host)
        form.addRow(self._label_with_info("listen_port", "本地监听端口（默认 8443）"), self.listen_port)
        form.addRow(self._label_with_info("default_upstream", "默认上游地址（未匹配域名时使用）"), self.default_upstream)
        form.addRow(self._label_with_info("verify_upstream_ssl", "是否校验上游 HTTPS 证书"), self.verify_ssl)
        form.addRow(self._label_with_info("log_level", "日志等级"), self.log_level)
        form.addRow(self._label_with_info("log_file", "日志文件路径（留空仅控制台输出）"), self.log_file)
        return group

    def _build_advanced_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("高级设置")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(10)
        self.preserve_host = QtWidgets.QCheckBox("preserve_host")
        self.preserve_host.setChecked(bool(self.config.get("preserve_host", False)))
        self.preserve_host.setToolTip("是否保留原始 Host 头（不推荐）")
        self.log_request_body = QtWidgets.QCheckBox("log_request_body")
        self.log_request_body.setChecked(bool(self.config.get("log_request_body", False)))
        self.log_request_body.setToolTip("记录请求体摘要（可能包含用户输入）")
        self.log_response_body = QtWidgets.QCheckBox("log_response_body")
        self.log_response_body.setChecked(bool(self.config.get("log_response_body", False)))
        self.log_response_body.setToolTip("记录上游响应体（影响流式性能）")
        self.normalize_models = QtWidgets.QCheckBox("normalize_models")
        self.normalize_models.setChecked(bool(self.config.get("normalize_models", True)))
        self.normalize_models.setToolTip("仅对 OpenAI 的 /v1/models 进行规范化")
        layout.addWidget(self._wrap_with_info(self.preserve_host, "是否保留原始 Host 头（不推荐）"))
        layout.addWidget(self._wrap_with_info(self.log_request_body, "记录请求体摘要（可能包含用户输入）"))
        layout.addWidget(self._wrap_with_info(self.log_response_body, "记录上游响应体（影响流式性能）"))
        layout.addWidget(self._wrap_with_info(self.normalize_models, "仅对 OpenAI 的 /v1/models 进行规范化"))

        layout.addWidget(QtWidgets.QLabel("intercept_hosts（一行一个）"))
        self.intercept_hosts = QtWidgets.QPlainTextEdit(
            "\n".join(self.config.get("intercept_hosts", []))
        )
        self.intercept_hosts.setFixedHeight(120)
        self.intercept_hosts.setToolTip("需要劫持的域名列表（需配合 hosts）")
        layout.addWidget(self.intercept_hosts)
        return group

    def _build_mapping_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("映射设置（JSON）")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(10)
        self.upstream_map = QtWidgets.QPlainTextEdit(
            json.dumps(self.config.get("upstream_map", {}), ensure_ascii=True, indent=2)
        )
        self.upstream_map.setToolTip("按域名指定上游地址的映射表")
        self.path_rewrite_map = QtWidgets.QPlainTextEdit(
            json.dumps(self.config.get("path_rewrite_map", {}), ensure_ascii=True, indent=2)
        )
        self.path_rewrite_map.setToolTip("按域名配置路径前缀改写")
        layout.addWidget(self._label_with_info("upstream_map", "按域名指定上游地址的映射表"))
        layout.addWidget(self.upstream_map)
        layout.addWidget(self._label_with_info("path_rewrite_map", "按域名配置路径前缀改写"))
        layout.addWidget(self.path_rewrite_map)

        button_row = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("保存配置")
        save_btn.clicked.connect(self._save_config)
        save_btn.setToolTip("保存当前配置到 config.json")
        button_row.addWidget(save_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _build_system_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("系统操作")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(8)
        top_row = QtWidgets.QHBoxLayout()

        init_btn = QtWidgets.QPushButton("生成证书与配置")
        init_btn.clicked.connect(self._run_init)
        init_btn.setToolTip("生成本地 Root CA 及各域名证书")
        install_btn = QtWidgets.QPushButton("安装 Root CA")
        install_btn.clicked.connect(self._install_ca)
        install_btn.setToolTip("将 Root CA 导入系统信任（需管理员）")
        hosts_btn = QtWidgets.QPushButton("写入 hosts")
        hosts_btn.clicked.connect(self._write_hosts)
        hosts_btn.setToolTip("写入 hosts 以劫持域名（需管理员）")
        one_click_btn = QtWidgets.QPushButton("一键配置并启动")
        one_click_btn.clicked.connect(self._one_click_setup)
        one_click_btn.setToolTip("自动生成证书、安装 CA、写入 hosts 并启动服务")

        top_row.addWidget(init_btn)
        top_row.addWidget(install_btn)
        top_row.addWidget(hosts_btn)
        top_row.addWidget(one_click_btn)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        bottom_row = QtWidgets.QHBoxLayout()
        remove_hosts_btn = QtWidgets.QPushButton("移除 hosts")
        remove_hosts_btn.clicked.connect(self._remove_hosts)
        remove_hosts_btn.setToolTip("从 hosts 文件中移除劫持记录（需管理员）")
        uninstall_ca_btn = QtWidgets.QPushButton("卸载 Root CA")
        uninstall_ca_btn.clicked.connect(self._uninstall_ca)
        uninstall_ca_btn.setToolTip("从系统信任中卸载 Root CA 证书（需管理员）")
        rollback_btn = QtWidgets.QPushButton("还原设置")
        rollback_btn.clicked.connect(self._rollback_setup)
        rollback_btn.setToolTip("一键移除 hosts 记录并卸载 Root CA（需管理员）")

        bottom_row.addWidget(remove_hosts_btn)
        bottom_row.addWidget(uninstall_ca_btn)
        bottom_row.addWidget(rollback_btn)
        bottom_row.addStretch(1)
        layout.addLayout(bottom_row)

        portproxy_row = QtWidgets.QHBoxLayout()
        setup_portproxy_btn = QtWidgets.QPushButton("设置端口转发 (443→8443)")
        setup_portproxy_btn.clicked.connect(self._setup_portproxy)
        setup_portproxy_btn.setToolTip("创建 443→8443 端口转发规则（需管理员）")
        remove_portproxy_btn = QtWidgets.QPushButton("取消端口转发")
        remove_portproxy_btn.clicked.connect(self._remove_portproxy)
        remove_portproxy_btn.setToolTip("移除 443→8443 端口转发规则（需管理员）")
        show_portproxy_btn = QtWidgets.QPushButton("查看转发规则")
        show_portproxy_btn.clicked.connect(self._show_portproxy)
        show_portproxy_btn.setToolTip("查看当前端口转发规则（需管理员）")

        portproxy_row.addWidget(setup_portproxy_btn)
        portproxy_row.addWidget(remove_portproxy_btn)
        portproxy_row.addWidget(show_portproxy_btn)
        portproxy_row.addStretch(1)
        layout.addLayout(portproxy_row)

        return group

    def _build_service_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("服务控制")
        layout = QtWidgets.QHBoxLayout(group)
        layout.setSpacing(10)
        start_btn = QtWidgets.QPushButton("启动服务")
        stop_btn = QtWidgets.QPushButton("停止服务")
        refresh_btn = QtWidgets.QPushButton("刷新状态")
        start_btn.clicked.connect(self._start_service)
        stop_btn.clicked.connect(self._stop_service)
        refresh_btn.clicked.connect(self._refresh_pid)
        start_btn.setToolTip("后台启动转发服务")
        stop_btn.setToolTip("停止后台服务")
        refresh_btn.setToolTip("刷新服务状态")
        layout.addWidget(start_btn)
        layout.addWidget(stop_btn)
        layout.addWidget(refresh_btn)
        layout.addStretch(1)
        return group

    def _build_log_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("日志预览（最后 1000 行）")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(10)
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(360)
        self.log_view.setFont(QtGui.QFont("Consolas", 10))
        self.log_view.setStyleSheet("border-radius: 12px;")
        self.auto_log = QtWidgets.QCheckBox("自动刷新")
        self.auto_log.setChecked(True)
        self.auto_log.setToolTip("每隔一段时间自动刷新日志")
        self.log_interval = QtWidgets.QSpinBox()
        self.log_interval.setRange(1, 60)
        self.log_interval.setValue(2)
        self.log_interval.setSuffix(" s")
        self.log_interval.setToolTip("日志刷新间隔")
        self.level_filter = QtWidgets.QComboBox()
        self.level_filter.addItems(["ALL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE", "WARMUP"])
        self.level_filter.setToolTip("按日志等级过滤")
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("搜索关键字…")
        self.search_input.setToolTip("搜索日志内容")
        self.follow_tail = QtWidgets.QCheckBox("滚动跟随")
        self.follow_tail.setChecked(True)
        self.follow_tail.setToolTip("保持滚动到最新日志")
        self.quick_warmup = QtWidgets.QPushButton("仅看 Warmup")
        self.quick_warmup.setToolTip("快捷过滤 [Warmup-API] 日志")
        self.quick_warmup.clicked.connect(self._set_warmup_filter)
        refresh_btn = QtWidgets.QPushButton("刷新日志")
        refresh_btn.clicked.connect(self._refresh_log)
        refresh_btn.setToolTip("刷新日志内容")
        layout.addWidget(self.log_view)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.auto_log)
        row.addWidget(self.log_interval)
        row.addWidget(self.level_filter)
        row.addWidget(self.search_input)
        row.addWidget(self.follow_tail)
        row.addWidget(self.quick_warmup)
        row.addStretch(1)
        row.addWidget(refresh_btn)
        layout.addLayout(row)
        return group

    def _save_config(self) -> None:
        try:
            self.config["listen_host"] = self.listen_host.text().strip()
            self.config["listen_port"] = self.listen_port.value()
            self.config["default_upstream"] = self.default_upstream.text().strip()
            self.config["verify_upstream_ssl"] = self.verify_ssl.isChecked()
            self.config["log_level"] = self.log_level.currentText()
            self.config["log_file"] = self.log_file.text().strip()
            self.config["preserve_host"] = self.preserve_host.isChecked()
            self.config["log_request_body"] = self.log_request_body.isChecked()
            self.config["log_response_body"] = self.log_response_body.isChecked()
            self.config["normalize_models"] = self.normalize_models.isChecked()
            self.config["intercept_hosts"] = [
                h.strip() for h in self.intercept_hosts.toPlainText().splitlines() if h.strip()
            ]
            self.config["upstream_map"] = json.loads(
                self.upstream_map.toPlainText().strip() or "{}"
            )
            self.config["path_rewrite_map"] = json.loads(
                self.path_rewrite_map.toPlainText().strip() or "{}"
            )
            save_config(self.config)
            QtWidgets.QMessageBox.information(self, "成功", "已保存 config.json")
        except json.JSONDecodeError as exc:
            QtWidgets.QMessageBox.warning(self, "JSON 错误", str(exc))

    def _run_init(self) -> None:
        def task():
            code, out, err = run_cmd(_cli_cmd("init"))
            return (code, out, err)

        self._run_async_task(task, "正在生成证书...", self._on_init_done)

    def _on_init_done(self, success: bool, result: Any) -> None:
        if success:
            code, out, err = result
            if code == 0:
                QtWidgets.QMessageBox.information(self, "完成", out or "已生成")
                self._refresh_status()
            else:
                QtWidgets.QMessageBox.warning(self, "失败", err or "执行失败")
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _install_ca(self) -> None:
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限")
            return

        def task():
            code, out, err = run_cmd(
                ["certutil", "-addstore", "root", str(ROOT / "certs" / "ca.pem")]
            )
            return (code, out, err)

        self._run_async_task(task, "正在安装 CA 证书...", self._on_install_ca_done)

    def _on_install_ca_done(self, success: bool, result: Any) -> None:
        if success:
            code, out, err = result
            if code == 0:
                QtWidgets.QMessageBox.information(self, "完成", out or "已安装")
                self._refresh_status()
            else:
                QtWidgets.QMessageBox.warning(self, "失败", err or "执行失败")
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _write_hosts(self) -> None:
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限")
            return

        hosts = [
            h.strip() for h in self.intercept_hosts.toPlainText().splitlines() if h.strip()
        ]

        def task():
            update_hosts(hosts)
            return "hosts 已更新"

        self._run_async_task(task, "正在写入 hosts...", self._on_write_hosts_done)

    def _on_write_hosts_done(self, success: bool, result: Any) -> None:
        if success:
            QtWidgets.QMessageBox.information(self, "完成", result)
            self._refresh_status()
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _remove_hosts(self) -> None:
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限")
            return

        hosts = [
            h.strip() for h in self.intercept_hosts.toPlainText().splitlines() if h.strip()
        ]

        def task():
            remove_hosts(hosts)
            return "hosts 记录已移除"

        self._run_async_task(task, "正在移除 hosts...", self._on_remove_hosts_done)

    def _on_remove_hosts_done(self, success: bool, result: Any) -> None:
        if success:
            QtWidgets.QMessageBox.information(self, "完成", result)
            self._refresh_status()
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _setup_portproxy(self) -> None:
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限")
            return

        def task():
            return run_cmd(
                [
                    "netsh",
                    "interface",
                    "portproxy",
                    "add",
                    "v4tov4",
                    "listenaddress=127.0.0.1",
                    "listenport=443",
                    "connectaddress=127.0.0.1",
                    "connectport=8443",
                ]
            )

        self._run_async_task(task, "正在设置端口转发...", self._on_setup_portproxy_done)

    def _on_setup_portproxy_done(self, success: bool, result: Any) -> None:
        if success:
            code, out, err = result
            if code == 0:
                QtWidgets.QMessageBox.information(
                    self, "完成", out or "已创建 443→8443 端口转发"
                )
            else:
                QtWidgets.QMessageBox.warning(self, "失败", err or out or "执行失败")
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _remove_portproxy(self) -> None:
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限")
            return

        def task():
            return run_cmd(
                [
                    "netsh",
                    "interface",
                    "portproxy",
                    "delete",
                    "v4tov4",
                    "listenaddress=127.0.0.1",
                    "listenport=443",
                ]
            )

        self._run_async_task(task, "正在取消端口转发...", self._on_remove_portproxy_done)

    def _on_remove_portproxy_done(self, success: bool, result: Any) -> None:
        if success:
            code, out, err = result
            if code == 0:
                QtWidgets.QMessageBox.information(
                    self, "完成", out or "已移除 443→8443 端口转发"
                )
            else:
                QtWidgets.QMessageBox.warning(self, "失败", err or out or "执行失败")
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _show_portproxy(self) -> None:
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限")
            return

        def task():
            return run_cmd(
                [
                    "netsh",
                    "interface",
                    "portproxy",
                    "show",
                    "all",
                ]
            )

        self._run_async_task(task, "正在读取端口转发规则...", self._on_show_portproxy_done)

    def _on_show_portproxy_done(self, success: bool, result: Any) -> None:
        if success:
            code, out, err = result
            if code == 0:
                message = (out or "").strip().replace("\r\n", "\n") or "未找到端口转发规则"
                QtWidgets.QMessageBox.information(self, "端口转发规则", message)
            else:
                QtWidgets.QMessageBox.warning(self, "失败", err or out or "执行失败")
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _uninstall_ca(self) -> None:
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限")
            return

        def task():
            code, out, err = run_cmd(["certutil", "-delstore", "root", "Trae-Poxy Local CA"])
            if code == 0:
                return "Root CA 已卸载"
            else:
                raise Exception(err or "卸载失败")

        self._run_async_task(task, "正在卸载 CA 证书...", self._on_uninstall_ca_done)

    def _on_uninstall_ca_done(self, success: bool, result: Any) -> None:
        if success:
            QtWidgets.QMessageBox.information(self, "完成", result)
            self._refresh_status()
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _start_service(self) -> None:
        def task():
            start_service()
            return "服务已启动"

        self._run_async_task(task, "正在启动服务...", self._on_start_service_done)

    def _on_start_service_done(self, success: bool, result: Any) -> None:
        if success:
            self._refresh_pid()
            self._refresh_status()
            append_ui_log(result, "INFO")
            self._refresh_log()
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _stop_service(self) -> None:
        def task():
            stop_service()
            return "服务已停止"

        self._run_async_task(task, "正在停止服务...", self._on_stop_service_done)

    def _on_stop_service_done(self, success: bool, result: Any) -> None:
        if success:
            self._refresh_pid()
            self._refresh_status()
            append_ui_log(result, "INFO")
            self._refresh_log()
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _run_async_task(self, task: Callable, status_msg: str, callback: Callable) -> None:
        self.statusBar().showMessage(status_msg)
        self.setCursor(QtCore.Qt.WaitCursor)

        worker = WorkerThread(task)
        worker.finished.connect(lambda success, result: self._on_async_task_finished(success, result, callback))

        if hasattr(self, '_workers'):
            self._workers.append(worker)
        else:
            self._workers = [worker]

        worker.start()

    def _on_async_task_finished(self, success: bool, result: Any, callback: Callable) -> None:
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.statusBar().clearMessage()
        callback(success, result)

    def _refresh_pid(self) -> None:
        pid = read_pid()
        if hasattr(self, "status_pid"):
            self.status_pid.setText(f"PID: {pid or '-'}")

    def _refresh_log(self) -> None:
        log_path_value = self.config.get("log_file") if self.config else None
        if not log_path_value:
            cfg = load_config()
            log_path_value = cfg.get("log_file")
        path = Path(log_path_value).expanduser() if log_path_value else Path()
        text = tail_log(path)
        html = render_log_html(
            text,
            self.level_filter.currentText(),
            self.search_input.text(),
        )
        self.log_view.setHtml(html)
        if self.follow_tail.isChecked():
            self.log_view.moveCursor(QtGui.QTextCursor.End)
        self._notify_new_warmup(text)

    def _init_log_timer(self) -> None:
        self.log_timer = QtCore.QTimer(self)
        self.log_timer.timeout.connect(self._refresh_log_if_enabled)
        self.log_timer.start(self.log_interval.value() * 1000)
        self.log_interval.valueChanged.connect(self._update_log_timer)

    def _refresh_log_if_enabled(self) -> None:
        if not self.auto_log.isChecked():
            return
        self._refresh_log()

    def _update_log_timer(self) -> None:
        self.log_timer.setInterval(self.log_interval.value() * 1000)

    def _set_warmup_filter(self) -> None:
        self.search_input.setText("[Warmup-API]")
        self.level_filter.setCurrentText("WARMUP")
        self._refresh_log()

    def _notify_new_warmup(self, text: str) -> None:
        lines = text.splitlines()
        current_count = len(lines)
        last_count = getattr(self, "_last_log_count", 0)
        self._last_log_count = current_count
        if current_count <= last_count:
            return
        new_lines = lines[last_count:]
        warmup_hits = [line for line in new_lines if "[Warmup-API]" in line]
        if warmup_hits:
            self.tray.showMessage(
                "Trae-Poxy",
                f"Warmup 日志新增 {len(warmup_hits)} 条",
                QtWidgets.QSystemTrayIcon.Information,
                1500,
            )

    def _init_tray(self) -> None:
        self.tray = QtWidgets.QSystemTrayIcon(self.windowIcon(), self)
        menu = QtWidgets.QMenu()
        menu_font = QtGui.QFont()
        menu_font.setPointSize(12)
        menu.setFont(menu_font)
        menu.setStyleSheet(
            """
            QMenu { background: #f8fafc; border-radius: 12px; padding: 6px; border: 1px solid #e5e7eb; }
            QMenu::item { padding: 6px 16px; border-radius: 8px; margin: 2px; }
            QMenu::item:selected { background: #e5e7eb; }
            """
        )
        show_action = menu.addAction("显示窗口")
        hide_action = menu.addAction("隐藏窗口")
        exit_action = menu.addAction("退出")
        show_action.triggered.connect(self.showNormal)
        hide_action.triggered.connect(self.hide)
        exit_action.triggered.connect(QtWidgets.QApplication.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.tray_action.isChecked():
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "Trae-Poxy",
                "已最小化到托盘",
                QtWidgets.QSystemTrayIcon.Information,
                1500,
            )
        else:
            super().closeEvent(event)

    def _is_autostart_enabled(self) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as key:
                winreg.QueryValueEx(key, "TraePoxyUI")
                return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def _toggle_autostart(self, checked: bool | None = None) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                enabled = checked if checked is not None else self.autostart_action.isChecked()
                if enabled:
                    if getattr(sys, "frozen", False):
                        cmd = f"\"{sys.executable}\""
                    else:
                        cmd = f"\"{sys.executable}\" \"{ROOT / 'gui_app.py'}\""
                    winreg.SetValueEx(key, "TraePoxyUI", 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, "TraePoxyUI")
                    except FileNotFoundError:
                        pass
            QtWidgets.QMessageBox.information(self, "完成", "已更新开机自启动设置")
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "失败", str(exc))

    def _refresh_status(self) -> None:
        ca_ok = ca_installed()
        cfg = self.config or load_config()
        hosts_list = [h.strip() for h in cfg.get("intercept_hosts", []) if h.strip()]
        missing = hosts_missing(hosts_list)
        pid = read_pid()
        self.status_ca.setText(f"Root CA: {'已安装' if ca_ok else '未安装'}")
        self.status_ca.setStyleSheet("color: #16a34a;" if ca_ok else "color: #dc2626;")
        self.status_hosts.setText(
            f"hosts: {'已写入' if not missing else '缺少 ' + str(len(missing)) + ' 条'}"
        )
        self.status_hosts.setStyleSheet("color: #16a34a;" if not missing else "color: #dc2626;")
        self.status_service.setText(f"服务: {'运行中' if pid else '未启动'}")
        self.status_service.setStyleSheet("color: #16a34a;" if pid else "color: #dc2626;")
        self.status_pid.setText(f"PID: {pid or '-'}")

    def _one_click_setup(self) -> None:
        if not CONFIG_PATH.exists():
            self._run_init()
        if is_admin():
            if not ca_installed():
                self._install_ca()
            missing = hosts_missing(
                [h.strip() for h in self.intercept_hosts.toPlainText().splitlines() if h.strip()]
            )
            if missing:
                self._write_hosts()
        else:
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限以安装证书/写入 hosts")
        self._start_service()
        self._refresh_status()

    def _rollback_setup(self) -> None:
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "权限不足", "需要管理员权限")
            return

        def task():
            hosts = [h.strip() for h in self.intercept_hosts.toPlainText().splitlines() if h.strip()]
            remove_hosts(hosts)
            run_cmd(["certutil", "-delstore", "root", "Trae-Poxy Local CA"])
            return "已还原 hosts 并卸载 Root CA"

        self._run_async_task(task, "正在还原设置...", self._on_rollback_done)

    def _on_rollback_done(self, success: bool, result: Any) -> None:
        if success:
            self._refresh_status()
            QtWidgets.QMessageBox.information(self, "完成", result)
        else:
            QtWidgets.QMessageBox.warning(self, "错误", str(result))

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        menu_font = menubar.font()
        menu_font.setPointSize(12)
        menubar.setFont(menu_font)
        menubar.setStyleSheet(
            """
            QMenuBar { font-size: 12pt; border: none; }
            QMenuBar::item { padding: 6px 12px; margin: 0 2px; border-radius: 10px; }
            QMenuBar::item:selected { background: #e2e8f0; }
            QMenu { font-size: 12pt; border-radius: 12px; padding: 6px; background: #f8fafc; border: 1px solid #e5e7eb; }
            QMenu::item { padding: 6px 16px; border-radius: 8px; margin: 2px; }
            QMenu::item:selected { background: #e5e7eb; }
            """
        )
        file_menu = menubar.addMenu("文件")
        import_action = file_menu.addAction("导入备份…")
        export_action = file_menu.addAction("导出备份…")
        import_action.triggered.connect(self._import_backup)
        export_action.triggered.connect(self._export_backup)

        system_menu = menubar.addMenu("系统")
        system_menu.addAction("首选项…", self._open_preferences)
        system_menu.addAction("一键配置并启动", self._one_click_setup)
        system_menu.addAction("生成证书与配置", self._run_init)
        system_menu.addAction("安装 Root CA", self._install_ca)
        system_menu.addAction("写入 hosts", self._write_hosts)
        system_menu.addSeparator()
        system_menu.addAction("启动服务", self._start_service)
        system_menu.addAction("停止服务", self._stop_service)
        system_menu.addSeparator()
        self.autostart_action = system_menu.addAction("开机自启动")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(self._is_autostart_enabled())
        self.autostart_action.triggered.connect(self._toggle_autostart_menu)
        self.tray_action = system_menu.addAction("关闭到托盘")
        self.tray_action.setCheckable(True)
        self.tray_action.setChecked(True)
        self.tray_action.triggered.connect(self._toggle_tray_menu)
        system_menu.addSeparator()
        system_menu.addAction("还原设置", self._rollback_setup)

        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("欢迎", self._show_welcome)
        help_menu.addAction("关于", self._show_about)
        help_menu.addAction("版本", self._show_version)
        help_menu.addAction("检查更新", self._check_for_updates)

        for menu in (file_menu, system_menu, help_menu):
            self._style_menu(menu)

    def _import_backup(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "导入配置备份", str(ROOT), "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            save_config(data)
            self.config = data
            self._reload_from_config()
            QtWidgets.QMessageBox.information(self, "完成", "已导入配置")
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "失败", str(exc))

    def _export_backup(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出配置备份", str(ROOT / "config_backup.json"), "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            if CONFIG_PATH.exists():
                shutil.copyfile(CONFIG_PATH, path)
                QtWidgets.QMessageBox.information(self, "完成", "已导出配置")
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "失败", str(exc))

    def _reload_from_config(self) -> None:
        config = self.config or load_config()
        self.listen_host.setText(config.get("listen_host", "127.0.0.1"))
        self.listen_port.setValue(int(config.get("listen_port", 8443)))
        self.default_upstream.setText(config.get("default_upstream", "https://newapi.loserrc.com"))
        self.verify_ssl.setChecked(bool(config.get("verify_upstream_ssl", True)))
        self.log_level.setCurrentText(config.get("log_level", "INFO"))
        self.log_file.setText(config.get("log_file", "logs/trae_poxy.log"))
        self.preserve_host.setChecked(bool(config.get("preserve_host", False)))
        self.log_request_body.setChecked(bool(config.get("log_request_body", False)))
        self.log_response_body.setChecked(bool(config.get("log_response_body", False)))
        self.normalize_models.setChecked(bool(config.get("normalize_models", True)))
        self.intercept_hosts.setPlainText("\n".join(config.get("intercept_hosts", [])))
        self.upstream_map.setPlainText(json.dumps(config.get("upstream_map", {}), ensure_ascii=True, indent=2))
        self.path_rewrite_map.setPlainText(json.dumps(config.get("path_rewrite_map", {}), ensure_ascii=True, indent=2))

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        status.setStyleSheet(
            "QStatusBar { border-top: 1px solid #e5e7eb; padding: 0 6px; }"
            "QStatusBar::item { border: none; }"
        )
        self.status_ca = QtWidgets.QLabel("Root CA: 未知")
        self.status_hosts = QtWidgets.QLabel("hosts: 未知")
        self.status_service = QtWidgets.QLabel("服务: 未知")
        self.status_pid = QtWidgets.QLabel("PID: -")
        status.addWidget(self.status_ca)
        status.addWidget(self._status_sep())
        status.addWidget(self.status_hosts)
        status.addWidget(self._status_sep())
        status.addWidget(self.status_service)
        status.addWidget(self._status_sep())
        status.addWidget(self.status_pid)

    def _load_ui_theme(self) -> str:
        settings = QtCore.QSettings("TraePoxy", "UI")
        return settings.value("theme", "System")

    def _toggle_theme(self) -> None:
        if getattr(self, "_theme", "Light") == "Light":
            self._apply_theme("Dark")
        else:
            self._apply_theme("Light")

    def _toggle_autostart_menu(self) -> None:
        self._toggle_autostart(self.autostart_action.isChecked())

    def _toggle_tray_menu(self) -> None:
        pass

    def _show_about(self) -> None:
        dev = self.env.get("APP_DEVELOPER", "Unknown")
        ver = self.env.get("APP_VERSION", "v1.0")
        website = self.env.get("APP_WEBSITE", "")
        project = self.env.get("APP_PROJECT_URL", "")
        QtWidgets.QMessageBox.information(
            self,
            "关于",
            f"{self.windowTitle()}\n"
            f"版本: {ver}\n"
            f"开发者: {dev}\n"
            f"网站: {website}\n"
            f"项目: {project}\n",
        )

    def _show_version(self) -> None:
        ver = self.env.get("APP_VERSION", "v1.0")
        QtWidgets.QMessageBox.information(self, "版本", f"{ver}")

    def _check_for_updates(self) -> None:
        url = (self.env.get("UPDATE_CHECK_URL") or "").strip()
        if not url:
            QtWidgets.QMessageBox.information(self, "检查更新", "未配置更新服务器地址")
            return

        current_version = self.env.get("APP_VERSION", "v1.0.0")

        def task() -> dict[str, Any]:
            request_obj = urllib.request.Request(
                url,
                headers={
                    "User-Agent": f"AI-Poxy-Tools/{current_version}",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request_obj, timeout=10) as response:
                    payload = response.read().decode("utf-8")
            except urllib.error.URLError as exc:
                raise RuntimeError("无法连接到更新服务器") from exc
            except UnicodeDecodeError as exc:
                raise RuntimeError("更新信息格式错误") from exc

            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError("更新信息格式错误") from exc

            latest_version = str(data.get("version", "")).strip()
            if not latest_version:
                raise RuntimeError("更新信息格式错误")

            changelog = str(data.get("changelog", "") or "").strip()
            download_url = str(data.get("download_url", "") or "").strip()
            has_update = compare_versions(current_version, latest_version) < 0

            return {
                "current": current_version,
                "latest": latest_version,
                "download_url": download_url,
                "changelog": changelog,
                "has_update": has_update,
            }

        self._run_async_task(task, "正在检查更新...", self._on_check_updates_done)

    def _on_check_updates_done(self, success: bool, result: Any) -> None:
        if not success:
            message = str(result)
            QtWidgets.QMessageBox.warning(self, "检查更新", message)
            append_ui_log(f"检查更新失败: {message}", "ERROR")
            return

        data = result or {}
        if not data.get("has_update"):
            QtWidgets.QMessageBox.information(self, "检查更新", "当前已是最新版本")
            append_ui_log("检查更新: 当前已是最新版本", "INFO")
            return

        changelog = data.get("changelog") or "（无更新日志）"
        download_url = data.get("download_url") or "（暂无下载链接）"
        current_version = data.get("current", "-")
        latest_version = data.get("latest", "-")
        message = (
            f"当前版本: {current_version}\n"
            f"最新版本: {latest_version}\n\n"
            f"更新日志:\n{changelog}\n\n"
            f"下载链接:\n{download_url}"
        )
        QtWidgets.QMessageBox.information(self, "发现新版本", message)
        append_ui_log(f"发现新版本 {latest_version} (当前 {current_version})", "INFO")

    def _show_welcome(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "欢迎",
            "欢迎使用 AI Poxy Tools！建议按顺序：生成证书 → 安装 Root CA → 写入 hosts → 启动服务。",
        )

    def _open_preferences(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("首选项")
        dialog.resize(760, 640)
        layout = QtWidgets.QVBoxLayout(dialog)

        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)

        cfg = load_config()
        settings = QtCore.QSettings("TraePoxy", "UI")
        current_theme = settings.value("theme", "System")

        # 基础设置
        basic_tab = QtWidgets.QWidget()
        basic_form = QtWidgets.QFormLayout(basic_tab)
        pref_listen_host = QtWidgets.QLineEdit(cfg.get("listen_host", "127.0.0.1"))
        pref_listen_port = QtWidgets.QSpinBox()
        pref_listen_port.setRange(1, 65535)
        pref_listen_port.setValue(int(cfg.get("listen_port", 8443)))
        pref_listen_port.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        pref_default_upstream = QtWidgets.QLineEdit(
            cfg.get("default_upstream", "https://newapi.loserrc.com")
        )
        pref_verify_ssl = QtWidgets.QCheckBox()
        pref_verify_ssl.setChecked(bool(cfg.get("verify_upstream_ssl", True)))
        pref_log_level = QtWidgets.QComboBox()
        pref_log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        pref_log_level.setCurrentText(cfg.get("log_level", "INFO"))
        pref_log_file = QtWidgets.QLineEdit(cfg.get("log_file", "logs/trae_poxy.log"))

        basic_form.addRow(self._label_with_info("listen_host", "本地监听地址"), pref_listen_host)
        basic_form.addRow(self._label_with_info("listen_port", "本地监听端口"), pref_listen_port)
        basic_form.addRow(self._label_with_info("default_upstream", "默认上游地址"), pref_default_upstream)
        basic_form.addRow(self._label_with_info("verify_upstream_ssl", "是否校验上游证书"), pref_verify_ssl)
        basic_form.addRow(self._label_with_info("log_level", "日志等级"), pref_log_level)
        basic_form.addRow(self._label_with_info("log_file", "日志文件路径"), pref_log_file)
        tabs.addTab(basic_tab, "基础设置")

        # 界面设置
        ui_tab = QtWidgets.QWidget()
        ui_form = QtWidgets.QFormLayout(ui_tab)
        pref_theme = QtWidgets.QComboBox()
        pref_theme.addItems(["System", "Light", "Dark"])
        pref_theme.setCurrentText(current_theme)
        ui_form.addRow(self._label_with_info("theme", "界面主题（默认跟随系统）"), pref_theme)
        tabs.addTab(ui_tab, "界面设置")

        # 高级设置
        adv_tab = QtWidgets.QWidget()
        adv_layout = QtWidgets.QVBoxLayout(adv_tab)
        pref_preserve_host = QtWidgets.QCheckBox("preserve_host")
        pref_preserve_host.setChecked(bool(cfg.get("preserve_host", False)))
        pref_log_request_body = QtWidgets.QCheckBox("log_request_body")
        pref_log_request_body.setChecked(bool(cfg.get("log_request_body", False)))
        pref_log_response_body = QtWidgets.QCheckBox("log_response_body")
        pref_log_response_body.setChecked(bool(cfg.get("log_response_body", False)))
        pref_normalize_models = QtWidgets.QCheckBox("normalize_models")
        pref_normalize_models.setChecked(bool(cfg.get("normalize_models", True)))
        adv_layout.addWidget(self._wrap_with_info(pref_preserve_host, "是否保留原始 Host 头"))
        adv_layout.addWidget(self._wrap_with_info(pref_log_request_body, "记录请求体摘要（可能包含用户输入）"))
        adv_layout.addWidget(self._wrap_with_info(pref_log_response_body, "记录上游响应体"))
        adv_layout.addWidget(self._wrap_with_info(pref_normalize_models, "仅对 OpenAI 的 /v1/models 规范化"))
        adv_layout.addWidget(QtWidgets.QLabel("intercept_hosts（一行一个）"))
        pref_intercept_hosts = QtWidgets.QPlainTextEdit("\n".join(cfg.get("intercept_hosts", [])))
        adv_layout.addWidget(pref_intercept_hosts)
        tabs.addTab(adv_tab, "高级设置")

        # 映射设置
        map_tab = QtWidgets.QWidget()
        map_layout = QtWidgets.QVBoxLayout(map_tab)
        pref_upstream_map = QtWidgets.QPlainTextEdit(
            json.dumps(cfg.get("upstream_map", {}), ensure_ascii=True, indent=2)
        )
        pref_path_rewrite = QtWidgets.QPlainTextEdit(
            json.dumps(cfg.get("path_rewrite_map", {}), ensure_ascii=True, indent=2)
        )
        map_layout.addWidget(self._label_with_info("upstream_map", "按域名指定上游地址"))
        map_layout.addWidget(pref_upstream_map)
        map_layout.addWidget(self._label_with_info("path_rewrite_map", "按域名配置路径前缀改写"))
        map_layout.addWidget(pref_path_rewrite)
        tabs.addTab(map_tab, "映射设置")

        # Buttons
        button_row = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("保存")
        cancel_btn = QtWidgets.QPushButton("取消")
        button_row.addStretch(1)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

        def on_save() -> None:
            try:
                cfg["listen_host"] = pref_listen_host.text().strip()
                cfg["listen_port"] = pref_listen_port.value()
                cfg["default_upstream"] = pref_default_upstream.text().strip()
                cfg["verify_upstream_ssl"] = pref_verify_ssl.isChecked()
                cfg["log_level"] = pref_log_level.currentText()
                cfg["log_file"] = pref_log_file.text().strip()
                cfg["preserve_host"] = pref_preserve_host.isChecked()
                cfg["log_request_body"] = pref_log_request_body.isChecked()
                cfg["log_response_body"] = pref_log_response_body.isChecked()
                cfg["normalize_models"] = pref_normalize_models.isChecked()
                cfg["intercept_hosts"] = [
                    h.strip() for h in pref_intercept_hosts.toPlainText().splitlines() if h.strip()
                ]
                cfg["upstream_map"] = json.loads(pref_upstream_map.toPlainText().strip() or "{}")
                cfg["path_rewrite_map"] = json.loads(pref_path_rewrite.toPlainText().strip() or "{}")
                save_config(cfg)
                self.config = cfg
                settings.setValue("theme", pref_theme.currentText())
                self._apply_theme(pref_theme.currentText())
                dialog.accept()
            except json.JSONDecodeError as exc:
                QtWidgets.QMessageBox.warning(dialog, "JSON 错误", str(exc))

        save_btn.clicked.connect(on_save)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def _apply_theme(self, theme: str) -> None:
        app = QtWidgets.QApplication.instance()
        if not app:
            return
        if theme == "System":
            scheme = QtWidgets.QApplication.styleHints().colorScheme()
            theme = "Dark" if scheme == QtCore.Qt.ColorScheme.Dark else "Light"
        self._theme = theme
        base_font = QtGui.QFont()
        base_font.setPointSize(11)
        app.setFont(base_font)
        if theme == "Dark":
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#0f172a"))
            palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#e5e7eb"))
            palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#0b1220"))
            palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#111827"))
            palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#e5e7eb"))
            palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#1f2937"))
            palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#e5e7eb"))
            palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#4f46e5"))
            palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
            app.setStyle("Fusion")
            app.setPalette(palette)
            app.setStyleSheet(
                """
                QGroupBox {
                    border: 1px solid #334155;
                    border-radius: 10px;
                    margin-top: 12px;
                    padding: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 4px 0 4px;
                    color: #cbd5f5;
                    font-weight: 600;
                }
                QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
                    border: 1px solid #475569;
                    border-radius: 10px;
                    padding: 6px;
                    background-color: #0b1220;
                }
                QComboBox { color: #e5e7eb; }
                QComboBox QAbstractItemView { background: #0b1220; color: #e5e7eb; }
                QPushButton {
                    border: 1px solid #475569;
                    border-radius: 12px;
                    padding: 7px 14px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #1f2937, stop:1 #0f172a);
                    color: #e5e7eb;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #3b82f6, stop:1 #22c55e);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #1e3a8a, stop:1 #1d4ed8);
                }
                QToolTip {
                    border: 1px solid #334155;
                    border-radius: 8px;
                    padding: 6px;
                    background: #0b1220;
                    color: #e5e7eb;
                }
                QScrollBar:vertical {
                    background: #0b1220;
                    width: 10px;
                    margin: 2px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #334155;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                """
            )
        else:
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#f8fafc"))
            palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#111827"))
            palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#ffffff"))
            palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#f1f5f9"))
            palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#111827"))
            palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#e2e8f0"))
            palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#111827"))
            palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#2563eb"))
            palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
            app.setStyle("Fusion")
            app.setPalette(palette)
            app.setStyleSheet(
                """
                QGroupBox {
                    border: 1px solid #d1d5db;
                    border-radius: 10px;
                    margin-top: 12px;
                    padding: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 4px 0 4px;
                    color: #334155;
                    font-weight: 600;
                }
                QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
                    border: 1px solid #cbd5e1;
                    border-radius: 10px;
                    padding: 6px;
                    background-color: #ffffff;
                }
                QComboBox { color: #111827; }
                QComboBox QAbstractItemView { background: #ffffff; color: #111827; }
                QPushButton {
                    border: 1px solid #cbd5e1;
                    border-radius: 12px;
                    padding: 7px 14px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #eef2ff, stop:1 #e2e8f0);
                    color: #0f172a;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #a7f3d0, stop:1 #bae6fd);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #bfdbfe, stop:1 #93c5fd);
                }
                QToolTip {
                    border: 1px solid #cbd5e1;
                    border-radius: 8px;
                    padding: 6px;
                    background: #ffffff;
                    color: #111827;
                }
                QScrollBar:vertical {
                    background: #f8fafc;
                    width: 10px;
                    margin: 2px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #cbd5e1;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                """
            )

    def _label_with_info(self, text: str, tip: str) -> QtWidgets.QWidget:
        wrapper = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(text)
        info = QtWidgets.QLabel(" *")
        info.setToolTip(tip)
        info.setStyleSheet("color: #3b82f6; font-weight: 600;")
        layout.addWidget(label)
        layout.addWidget(info)
        layout.addStretch(1)
        return wrapper

    def _status_sep(self) -> QtWidgets.QFrame:
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.VLine)
        sep.setStyleSheet("color: #e5e7eb; margin: 0 8px;")
        sep.setFixedHeight(16)
        return sep

    def _style_menu(self, menu: QtWidgets.QMenu) -> None:
        menu.setWindowFlags(menu.windowFlags() | QtCore.Qt.FramelessWindowHint)
        menu.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        menu.setStyleSheet(
            """
            QMenu {
                background: #f8fafc;
                border-radius: 12px;
                padding: 8px;
                border: 1px solid #e5e7eb;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 8px;
                margin: 2px;
            }
            QMenu::item:selected {
                background: #e5e7eb;
            }
            """
        )

    def _wrap_with_info(self, widget: QtWidgets.QWidget, tip: str) -> QtWidgets.QWidget:
        wrapper = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        info = QtWidgets.QLabel("*")
        info.setToolTip(tip)
        info.setStyleSheet("color: #3b82f6; font-weight: 600;")
        layout.addWidget(widget)
        layout.addWidget(info)
        layout.addStretch(1)
        return wrapper


def main() -> None:
    if "--serve" in sys.argv:
        from run import cmd_serve

        cmd_serve()
        return
    if "--init" in sys.argv:
        from run import cmd_init

        cmd_init()
        return
    if "--print-hosts" in sys.argv:
        from run import cmd_print_hosts

        cmd_print_hosts()
        return

    # Create QApplication early for mutex check message box
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_DontUseNativeMenuBar, True)
    app = QtWidgets.QApplication(sys.argv)

    mutex_name = "TraePoxyUI_SingleInstance"
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, True, mutex_name)
    if kernel32.GetLastError() == 183:
        QtWidgets.QMessageBox.information(
            None,
            "提示",
            "应用已在运行中，请勿重复启动。",
        )
        return
    # Ensure taskbar/icon association is consistent for the packaged app.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TraePoxy.UI")
    except Exception:
        pass
    icon_path = load_env().get("APP_ICON", "icons/app.ico")
    icon_file = resolve_resource(icon_path)
    if icon_file.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon_file)))
    window = TraePoxyWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
