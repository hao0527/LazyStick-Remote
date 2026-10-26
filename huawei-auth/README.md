# 华为台灯授权

独立入口：<https://lazystick.icu/huawei-auth/>。主页不提供入口。
页面沿用远程站点的颜色、卡片和明暗主题样式；资源、逻辑和主题存储独立，不读取巴法云配置。

## 使用

1. 在 Windows 10 / 11（x64）电脑打开页面，下载并解压助手。
2. 运行 `LazyStick-Huawei-Auth.exe`，使用助手自动打开的网页。
3. 如果浏览器询问本地网络访问权限，允许此页面连接本机助手。
4. 登录绑定台灯的华为账号，按提示选择验证方式并填写验证码。
5. 选择欧普智能台灯 2S，下载 `lamp-esp32-session.json`。
6. 在 LazyStick 的设置页导入并启用。需要本次集成华为台灯的新版固件。

关闭助手窗口或点击“断开并退出助手”即可退出。刷新网页会清除连接口令，
可复制助手窗口中的 Page 地址重新打开。公网页面打不开时，使用窗口中的 Local fallback
地址，或者运行 `LazyStick-Huawei-Auth.exe --local` 打开内置的同一套界面。
内置页只用于授权；程序和源码下载请使用公网入口。

下载包同时提供 `使用本地页面.cmd`，双击即可打开内置页面。助手没有安装过程，也不要求 Python。
首次运行可能出现 Windows 未识别应用提示：本版本未作 Windows 代码签名。

## 数据与运行方式

GitHub Pages 只托管静态资源。网页将登录请求发给 `127.0.0.1` 的随机端口，
助手使用经过验证的 Python 协议直连华为；不使用公共代理，也不把账号、密码、验证码或授权上传到站点。
只支持已验证的中国大陆服务和产品 `2BNN`；不会连接 MQTT 或改变台灯状态。

助手校验 loopback 来源、Host、Origin 和每次启动随机生成的 256 位连接口令。
口令通过 URL fragment 传给页面，不发送到静态服务器，页面立即从地址栏移除。
页面只把主题偏好保存在独立的 localStorage 键中；账号密码、验证码和连接口令不持久保存。

登录会话仅保留在助手内存中，闲置 15 分钟后清除；助手闲置 60 分钟后自动退出。
`%LOCALAPPDATA%/LazyStickHuaweiAuth/identities.json` 只保存以账号摘要索引的稳定客户端标识，
用于减少每次登录生成新身份；不保存账号原文、密码、验证码或授权 token。
用户主动下载的 JSON 包含明文授权，请只导入自己的 LazyStick，不要公开分享。

导出前重新读取设备归属、按需刷新令牌，并检查 8 KB 上限。输出为固件支持的 schema 1，
包含目标设备、双令牌、续期凭据和稳定客户端身份，不包含账号密码。

## 从源码运行和构建

需要 Python 3.12；构建 Windows x64 程序时请使用 Windows x64 Python。
在本仓库根目录执行：

```powershell
py -3.12 -m venv .auth-build/venv
.auth-build/venv/Scripts/python.exe -m pip install -r huawei-auth/helper/build-requirements.txt
.auth-build/venv/Scripts/python.exe huawei-auth/helper/main.py --local
```

构建下载包（包含同版源码、依赖许可证和 SHA-256 清单）：

```powershell
.auth-build/venv/Scripts/python.exe scripts/build-huawei-auth.py
```

离线检查，不发送真实登录或短信请求：

```powershell
.auth-build/venv/Scripts/python.exe -m unittest discover -s huawei-auth/tests -v
# 浏览器检查另需 playwright，以及本机 Microsoft Edge
.auth-build/venv/Scripts/python.exe huawei-auth/tests/browser_check.py
```

发布仍使用仓库现有的 `scripts/upload.ps1`。
助手代码及其配套界面按 GPL-3.0-only 分发；协议来源和完整许可证见
`helper/vendor/UPSTREAM.md`、`helper/vendor/huawei_smarthome/LICENSE`。
