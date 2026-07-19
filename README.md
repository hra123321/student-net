# 校园网登录助手

轻量化 Windows 后台驻留工具，实现深澜 (SRun) 校园网自动登录 + 全维度系统/网络监控 + 网速优化。

## 功能

- **自动登录**: 深澜 srun_portal 协议自动认证
- **网络检测**: Ping网关 + DNS + 接口状态三重检测
- **网速优化**: 5项一键优化（全部可逆）
- **保活机制**: 防止闲置掉线
- **监控面板**: 6区域全维度数据实时展示
- **防崩溃**: 线程看门狗 + 异常自动恢复
- **系统托盘**: 后台驻留运行
- **校园网识别**: 只有检测到深澜门户且网络处于受限状态时才自动认证，普通网络不会尝试登录

## 配置

复制 `config.example.json` 为 `config.json`，填写校园网账号密码：

```json
{
  "portal_url": "http://192.168.151.10",
  "login_page": "/srun_portal_pc",
  "username": "你的学号",
  "password": "你的密码",
  "ac_id": "1"
}
```

## 运行

```powershell
pip install -r requirements.txt
python main.py
```

安装版由最高权限计划任务以 `--background` 参数开机启动，不弹出面板；桌面和开始菜单快捷方式使用 `--show`，双击只唤醒已有实例，不会创建第二个进程。

## 依赖

- Python 3.12+
- psutil（系统/网络监控）

## 打包

```powershell
pip install pyinstaller
pyinstaller main.py --onefile --uac-admin --name "校园网登录助手"
```

然后用 Inno Setup 打包为安装包。
