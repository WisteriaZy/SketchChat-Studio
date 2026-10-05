# 绘聊工坊 · 开发与目录说明

## 当前结构

- `desktop.py`：桌面入口；`StartStudio.exe` / `StartStudio.cmd`：日常启动。
- `sketchbook/`：角色库、渲染编排、GUI、聊天监听、主题、快捷键。
- `launcher/`：无终端 Windows 启动器源码和构建脚本。
- `scripts/Verify.ps1`：统一测试、语法检查及可选启动器构建验证。
- `tests/`：自动化回归及离屏可视化验证脚本。
- `docs/USER_GUIDE.md`：详细使用手册。
- `tools/image_region_tool.html`：早期独立标注工具；日常推荐使用桌面编辑器。
- `archive/deprecated/`：不再使用的启动器，仅留作参考。
- `library/`：用户角色库、设置、日志；不加入版本控制。
- `local-backups/`：用户原配置/字体副本和旧日志；不加入版本控制。
- `.implementation-check/`：本地开发脚本和验证截图；不加入版本控制，不作为维护入口。

根目录的 `main.py`、`config.py`、`config_loader.py`、`Start.cmd`、`start_debug.py` 保留旧版兼容。
`text_fit_draw.py`、`image_fit_paste.py` 仍由桌面渲染复用；`BaseImages/`、`font.ttf` 和 `config.yaml` 仍是旧版及迁移数据来源。
这轮没有为整齐而移动这些运行依赖，也没有搬动虚拟环境或用户素材库。

## 验证

```powershell
powershell -NoProfile -File .\scripts\Verify.ps1
powershell -NoProfile -File .\scripts\Verify.ps1 -BuildLauncher
```

第二条会重编译根目录的启动器，请先退出应用。
测试通过不代表每个聊天客户端均兼容；实际发送前先在自己的聊天中关闭自动发送验证。

## 发布前检查

1. 重建 `.venv` 并安装依赖，执行上述验证。
2. 检查 README 和手册链接、启动器和图形界面。
3. 不发布 `library/`、`local-backups/`、日志、开发临时脚本或整个 `.venv`。
4. 检查旧 `BaseImages/`、`font.ttf`、`config.yaml` 是否包含个人修改及未授权素材。
5. 保留 MIT 版权声明，另行确认图片和字体的分发授权。
6. 当前没有独立安装包；EXE 仅是启动器，分发时须说明运行环境。

仓库文件夹暂保留旧名称；直接移动 `.venv` 可能使工具中的绝对路径失效。
如需更名目录，应先备份素材库，在新目录重建虚拟环境，而不是直接假定旧环境可移动。

## 手动构建与启动探针

在安装有 .NET Framework C# 编译器的 Windows 上，从项目根目录执行：

```powershell
powershell -NoProfile -File .\launcher\Build.ps1
.\StartStudio.exe --check
.\StartStudio.exe --verify-launch
```

`--check` 仅离线检测依赖并返回退出码，不安装、不弹初始化向导。
`--verify-launch` 只运行控制台句柄探针，不启动管理器或聊天监听。

初始化向导默认使用 PyPI，并遵循用户 pip 配置。仅在确认安装后联网；
安装期间不支持强制取消，失败可重试，残缺 `.venv` 不会自动删除。
自动测试使用模拟键盘/剪贴板接口，不向真实 QQ/微信发送消息，不能替代真实桌面验收。
