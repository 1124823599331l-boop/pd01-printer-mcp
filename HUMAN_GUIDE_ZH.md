# PD01 打印机 MCP：人类使用教程

这份教程只告诉你应该做什么。

## 第一次使用

### 1. 安装

```powershell
git clone 你的仓库地址
cd pd01-printer-mcp
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 配对打印机

1. 给 PD01 装好热敏纸并开机。
2. 关闭手机上的打印机 App。
3. 打开“Windows 设置 → 蓝牙和设备 → 添加设备”。
4. 选择 `PD01`，等待显示“已配对”。

显示“已配对，未连接”通常是正常的。程序会在检查或打印时临时连接。

### 3. 启动 MCP

```powershell
.\.venv\Scripts\Activate.ps1
python printer_server.py
```

看到下面这行表示启动成功：

```text
Uvicorn running on http://127.0.0.1:4176
```

保持这个 PowerShell 窗口打开。

### 4. 配置 AI

在支持 Streamable HTTP MCP 的客户端中填写：

```text
http://127.0.0.1:4176/mcp
```

先对 AI 说：

```text
检查打印机状态，不要打印。
```

## 每次使用

1. 打开打印机并让灯亮着。
2. 关闭手机打印 App。
3. 启动 `printer_server.py`。
4. 让 AI 检查打印机。
5. 让 AI 准备文字并展示完整内容。
6. 内容正确后明确说“确认打印”。

## 远程 AI

远程 AI 需要额外的安全网络入口，例如 VPN、SSH 隧道或带身份验证的 HTTPS 反向代理。

不要把没有身份验证的打印 MCP 直接公开到互联网。不要把服务器地址、Token 或 SSH 私钥提交到仓库。

## 常见问题

### Windows 显示“已配对，未连接”

正常。保持打印机开机，让 AI 检查即可。

### AI 找不到打印机

- 按一下电源键唤醒打印机。
- 关闭手机打印 App。
- 检查 Windows 蓝牙和配对状态。
- 把打印机放到电脑旁边。

### `WinError 10048`

通常表示 MCP 已经运行，不要重复启动。

### 浏览器显示 400、404 或 406

MCP 不是普通网页。请用 MCP 客户端连接，不要用浏览器状态判断服务是否正常。

## 关闭

在 MCP 的 PowerShell 窗口按 `Ctrl+C`。
