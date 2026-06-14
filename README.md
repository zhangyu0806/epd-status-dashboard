# EPD Status Dashboard

UC8179 800x480 三色墨水屏看板。**模块化 Widget 架构**：所有内容（服务器监控、Notion 待办、天气、农历日历、倒数日、每日一句……）都是独立模块，在 `config.yaml` 里自由拼装布局。

架构：

```text
OC24 按 config.yaml 渲染 800x480 三色 PNG
  -> HTTP 暴露 status.png
Windows 本机下载 status.png
  -> 按 EPD-nRF5 协议编码三色图
  -> BLE 传给 nRF52811 + UC8179 屏
```

## 快速理解：模块化怎么用

整张屏幕由一棵**布局树**切分，叶子节点是 widget（模块）。你只需要改 `config.yaml` 的 `layout` 段，就能决定屏幕上有哪些模块、各占多大、放哪里。

```yaml
layout:
  direction: column        # 竖向排列
  padding: 8               # 内边距
  gap: 6                   # 子项间距
  children:
    - px: 96               # 固定高 96 像素的顶栏
      direction: row       # 横向排列
      children:
        - {size: 1, widget: lunar_calendar}   # 农历日历，占 1 份宽
        - {size: 1, widget: weather}          # 天气，占 1 份宽
        - {px: 210, widget: rings_legend}     # 图例，固定 210 像素宽
    - size: 1              # 剩余空间全给主体
      direction: row
      children:
        - {size: 2, ...}   # 左列占 2 份
        - {size: 1, ...}   # 右列占 1 份
```

尺寸规则（简单无歧义）：

- `px: 数字`：固定像素，优先分配。
- `size: 数字`：权重比例（默认 1），瓜分固定像素之后的剩余空间。
- `gap`：兄弟模块间距；`padding`：容器内边距。
- `direction`：`row` 横排 / `column` 竖排。

查看所有可用模块：

```bash
python generate.py --list-widgets
```

## 模块库

| 模块名 | 作用 | 主要 options |
|---|---|---|
| `server_rings` | 服务器同心三环（外CPU/中内存/内磁盘），一台一个圆 | `title`、`columns`、`only`(只显示指定节点名列表) |
| `rings_legend` | 同心环图例说明 | `title`、`labels` |
| `sub2api_panel` | sub2api 服务状态/账号/Key/阻塞 | `title` |
| `notion_todo` | Notion 数据库待办清单 | `title`、`show_due`、`row_height` |
| `weather` | 城市天气（当前温度/状况/最高最低） | `title` |
| `lunar_calendar` | 阳历日期+星期+农历+干支生肖 | `day_size` |
| `clock` | 大字号时钟 | `time_format`、`size`、`show_date`、`color` |
| `countdown` | 倒数日 | `title`、`date`(YYYY-MM-DD)、`label` |
| `quote` | 每日一句（按日期轮换） | `quotes`(字符串或{text,author}列表)、`size` |
| `text` | 自定义文字（支持标题/换行/对齐） | `title`、`content`、`align`、`size`、`color` |
| `panel` | 边框标题卡片，内部包裹一个子模块 | `title`、`border`、`child` |

模块没配置数据时会优雅降级显示"未配置"，不会让整张图崩掉。

## 数据源配置

### 服务器（server_rings / sub2api_panel）

```yaml
thresholds: {cpu: 85, mem: 85, disk: 90}   # 超过阈值的环变红
servers:
  - {name: "OC24", host: "local", disk_path: "/"}
  - {name: "nosla", host: "root@1.2.3.4", disk_path: "/"}
```

`host: local` 采集本机；其余通过 SSH 采集（需提前配置免密登录）。

### Notion 待办（notion_todo）

1. 在 https://www.notion.so/my-integrations 创建一个 Internal Integration，拿到 token。
2. 打开目标数据库页面 → 右上 `⋯` → `Connections` → 把你的 Integration 加进来（**这一步必须做**，否则 API 读不到）。
3. 复制数据库 ID（数据库页面 URL 里 `notion.so/xxxx?v=` 的 `xxxx` 那段）。
4. 配置：

```yaml
notion:
  enabled: true
  token_env: "NOTION_TOKEN"     # 推荐用环境变量，不要把 token 写进配置文件
  database_id: "你的数据库ID"
  title_property: "Name"         # 标题列名
  status_property: "Status"      # 状态列名（checkbox / status / select 均可）
  due_property: "Due"            # 截止日期列名（可选）
  priority_property: "Priority"  # 优先级列名（可选，高优先级标红）
  done_values: ["Done", "完成"]  # 视为"已完成"的状态值
  hide_done: true                # 隐藏已完成项
  limit: 8                       # 最多显示几条
```

token 用环境变量时，运行前 `export NOTION_TOKEN=secret_xxx`；也可直接写 `token: "secret_xxx"`（不推荐，会进文件）。

### 天气（weather）

默认使用免费、免 API Key 的 [Open-Meteo](https://open-meteo.com/)：

```yaml
weather:
  enabled: true
  city: "北京"          # 自动地理编码取经纬度
  # 或直接指定：
  # latitude: 39.90
  # longitude: 116.40
```

### 字体

```yaml
dashboard:
  font_path: "/path/to/your.ttf"   # 留空则自动探测系统中文字体
```

## 本地生成与预览

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-oc24.txt
cp config.example.yaml config.yaml
python generate.py --config config.yaml --output ./public/status.png
```

会同时生成 `public/status.png`（三色图）和 `public/status.json`（含 `collected_at` 供上传器判断刷新）。

## 新增自定义模块

每个模块就是一个继承 `Widget` 的类，30 行即可：

```python
# epd_dashboard/widgets/my_widget.py
from ..core import BLACK, Rect, RenderContext, Widget, load_font, register

@register("my_widget")            # 配置里写 widget: my_widget
class MyWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        text = str(self.opt("text", "你好"))
        ctx.draw.text((rect.x + 4, rect.y + 4), text, fill=BLACK, font=load_font(16))
```

然后在 `epd_dashboard/widgets/__init__.py` 里 import 一下触发注册即可。需要远程取数的模块，把采集逻辑放到 `epd_dashboard/collectors/`，并用 `ctx.shared("key", producer)` 缓存，保证一次渲染只采集一次。

## OC24 部署

```bash
sudo mkdir -p /opt/epd-status-dashboard
sudo cp -a . /opt/epd-status-dashboard/
cd /opt/epd-status-dashboard
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-oc24.txt
cp config.example.yaml config.yaml
python generate.py --config config.yaml --output ./public/status.png

sudo cp systemd/epd-status-dashboard.service /etc/systemd/system/
sudo cp systemd/epd-status-dashboard.timer /etc/systemd/system/
sudo cp systemd/epd-status-dashboard-http.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now epd-status-dashboard.timer epd-status-dashboard-http.service

# 放行 8088 端口
sudo iptables -I INPUT 1 -p tcp --dport 8088 -j ACCEPT
sudo netfilter-persistent save
```

> 注意：systemd 模板里调用的渲染命令需指向新入口 `generate.py`。若仍引用旧的 `oc24_generate_status.py`，请改成 `python generate.py`。

验证：

```bash
systemctl list-timers epd-status-dashboard.timer
curl -I http://203.0.113.20:8088/status.png
```

## Windows 端（蓝牙传屏）

### 推荐：安装成开机自启小应用

把 Windows 上传包解压后，用 PowerShell 进入该目录执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\install-windows-autostart.ps1
```

安装器会复制程序到 `%LOCALAPPDATA%\EpdStatusDashboard`、创建 venv 装依赖、注册计划任务 `EpdStatusDashboardUpload` 并开机自启。默认 600 秒安全上传间隔：每轮先确认 `status.json` 已更新，再拉取 `status.png` 经 BLE 传屏，避免连续刷屏。

查看日志：

```powershell
Get-Content -Wait "$env:LOCALAPPDATA\EpdStatusDashboard\logs\epd-upload.log"
```

### 手动验证

```powershell
cd C:\epd-status-dashboard
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-windows.txt

python windows_epd_upload.py --validate-only --save-encoded .\encoded-test  # 只验证编码
python windows_epd_upload.py --scan-only                                     # 只扫描 BLE 设备
python windows_epd_upload.py                                                 # 实机上传（默认安全模式）
python windows_epd_upload.py --daemon --log-file .\epd-upload.log            # 常驻循环
```

成功判据：输出 `upload complete; waiting for EPD refresh` 后屏幕开始刷新，完整刷新需几十秒。三色屏残影明显时优先用慢速安全上传，不要提高 `--interleaved-count`。

## 电量显示

dashboard 默认不强制画电量。EPD-nRF5 原生模式能显示电量是因为固件本机调用 `EPD_ReadVoltage()`；本项目走整图上传路径，不触发固件原生 `DrawBattery()`。Windows 上传器支持读取标准 BLE Battery Level（`0x2A19`），但默认上游固件未暴露该服务，需按 `firmware/EPD-nRF5-battery-service.md` 改固件。没电时手动换电池即可。

## 注意

- OC24 云服务器没有本地蓝牙，必须由 Windows/树莓派/本地小主机作为蓝牙网关。
- 三色 UC8179 使用 EPD-nRF5 驱动 ID `0x07`，发送黑白层 48000 bytes + 红白层 48000 bytes。
- 整图必须是纯白/黑/红三色，框架已自动量化，自定义模块无需关心。

## 目录

```text
epd-status-dashboard/
  generate.py                 # 新入口：读 config -> 渲染 -> status.png + status.json
  config.example.yaml         # 配置模板（含 layout 树与各模块配置）
  epd_dashboard/
    core/                     # 颜色/字体/几何/绘图原语/农历/布局树/widget基类/渲染编排
    collectors/               # servers / sub2api / notion / weather 数据采集
    widgets/                  # 11 个内置模块
  oc24_generate_status.py     # 旧版单体渲染器（保留作 fallback）
  windows_epd_upload.py       # Windows 下载图片并蓝牙传屏
  install-windows-autostart.ps1
  systemd/                    # OC24 systemd service/timer 模板
  firmware/                   # 固件相关说明
```
