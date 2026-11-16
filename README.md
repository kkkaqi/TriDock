# IPA Runner

IPA Runner 是一个 Windows 桌面启动器，用于管理 `.ipa` 安装包和启动兼容的 iOS 应用。桌面界面使用 Electron，IPA 解析、应用库和运行时调用由 Python 负责。`.ipa` 是 iOS 应用的安装包格式。

## 快速开始

从 [GitHub Releases](https://github.com/kkkaqi/ipa-runner/releases/latest) 下载 `IPA-Runner-*-win-x64-Setup.exe`，双击后在安装向导的目录页面选择安装位置。安装包已包含 Electron 和 Python。安装后从桌面或开始菜单打开 IPA Runner，再按下方第 3、4 步配置运行时和导入 IPA。

从源码运行：

1. 安装 **Node.js 22.12 或更新版本**和 **Python 3.10 或更新版本**，确保 `node`、`npm` 和 `python` 能在终端中运行。
2. 下载本仓库源码，双击 `IPA Runner.cmd`。首次打开需要联网下载 Electron。也可以在项目目录运行 `npm ci`，然后运行 `npm start`。
3. 下载并解压 [touchHLE Windows 版](https://github.com/touchHLE/touchHLE/releases)，在 IPA Runner 的 **运行时** 页选择 `touchHLE.exe` 并保存。
4. 在 **应用库** 点击 **导入 IPA**，或将 `.ipa` 拖到窗口。选中应用后点击 **启动应用**。可以用 [touchHLE 授权归档](https://touchhle.org/app-archive/)中的《Touch & Go LITE》1.2 试玩。

运行时和试玩 IPA 需单独获取。应用库会读取应用名称、图标（可提取时）、Bundle ID、版本、架构和最低 iOS 版本。重新导入同一个 Bundle ID 会更新应用条目。

## 显示和快捷方式

在 touchHLE 应用详情的 **启动显示** 里选择 **窗口**、**放大窗口（2×）** 或 **全屏**，下次启动时应用。点击 **创建桌面快捷方式** 后，可以直接从桌面打开应用。快捷方式会读取当前保存的显示方式。

- **放大窗口（2×）** 会提高运行时内部渲染分辨率，个别旧应用可能出现显示问题，此时可改用窗口或全屏。
- **全屏** 按游戏原有比例放大画面，按 `Alt+F4` 关闭。普通窗口的尺寸由 touchHLE 在启动时设定，拖动 Windows 标题栏时可能短暂停帧。 [touchHLE 显示选项](https://raw.githubusercontent.com/touchHLE/touchHLE/v0.3.0/OPTIONS_HELP.txt) · [SDL 窗口拖动说明](https://wiki.libsdl.org/SDL3/AppFreezeDuringDrag)

## 兼容性

| IPA 类型 | 运行时 | 当前状态 |
| --- | --- | --- |
| 早期 32 位 ARM 应用 | touchHLE | 已在 Windows 上用 v0.3.0 验证《Touch & Go LITE》1.2。其他版本和应用可查 [touchHLE 兼容性数据库](https://appdb.touchhle.org/)。 |
| 与 iOS 16 兼容的 ARM64 应用 | ASoftware iOS 16 | 已测试 IPA 提交和安装状态读取。虚拟机启动与 ARM64 应用安装尚未完成端到端验证。 |

### 试用 ARM64 IPA

1. 按照 [ASoftware iOS 16 文档](https://github.com/alpersamur3/asoft-ios)完成运行时部署。
2. 在 **运行时** 页选择包含 `Start-iOS.cmd` 的安装目录。自定义数据目录时，填入运行时使用的目录。
3. 导入自有且支持 iOS 16 的 ARM64 IPA，点击 **提交安装** 和 **打开 iOS 窗口**。安装状态由运行时回报，安装成功后可从虚拟机的 iOS 主屏幕打开应用。

该运行时暂未提供 App Store 和 Apple ID 服务。 [ASoftware iOS 16 的功能说明](https://github.com/alpersamur3/asoft-ios#features)

## 本地数据

应用库、导入的 IPA 副本、显示设置和日志保存在 `%USERPROFILE%\Saved Games\IPA Runner`。在 **运行时** 页点击 **打开数据目录** 即可查看。桌面快捷方式指向当前源码位置，移动项目后需要重新创建。

## 开发与测试

```powershell
npm ci
python -m unittest discover -s tests -v
npm run test:desktop
```

在 Windows x64 上运行 `npm run build:win` 可以生成安装包，成品位于 `dist`。首次构建需联网获取打包工具与 Python 嵌入包。

Windows 应用启动器的交互设计参考了 [ApkStart](https://github.com/RoutineMiku/apkstart)。
