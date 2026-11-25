# TriDock（三栖）

TriDock（三栖）是一个 Windows 多系统运行环境管理器，用于管理 Android、iOS、OpenHarmony 实例及其 APK、IPA、HAP 应用包。桌面界面使用 Electron，应用库、环境检查和运行时调用由 Python 负责。

0.4.1 将原 IPA Runner 更名为 TriDock（三栖），更新软件、窗口、EXE、安装器及桌面快捷方式图标。原数据目录和安装升级身份保持兼容。GitHub 仓库地址暂沿用原地址。

## 0.4 导入向导

“添加系统”现在提供本地环境检查：自动查找解压目录、列出已有 Android AVD、匹配 hdc、识别内核与系统盘，显示 CPU、内存、虚拟化和目标数据磁盘的检查结果。检查过程不运行导入目录中的脚本，不下载任何镜像。无法从文件确认的系统版本显示“未知”，文件检查通过也不表示应用兼容性已验证。

可以选择完整运行环境 ZIP，先查看识别结果与展开大小，再选择存放目录。软件在所选目录下新建 runner-import-* 子目录，绝不覆盖已有文件；解压后继续检查。压缩包数量、路径、符号链接、重名条目、展开大小和压缩率均有校验。其他压缩格式请先自行解压，单独 ISO/IMG/IPSW 仍不支持直接导入。大文件解压没有固定十分钟超时，请保持软件开启直至完成。

向导检查通过后允许创建实例，更改配置后需重新检查。创建时和新实例启动前后端都会重新校验。Android 仍需要先通过 Android Studio 下载镜像并创建 AVD，向导会自动列出设备；ASoftware 仍需先完成系统部署。旧实例记录可继续使用。

试启动后会分别报告进程状态与设备状态。Android 使用 boot_completed，OpenHarmony 使用实例专属的 HDC 目标判断是否就绪；iOS 暂仅确认进程，在系统窗口确认引导。不会把“进程启动”显示成“系统已经可用”。左下角旧版 iOS 运行环境状态改为“已配置 / 未配置”。

## 多系统管理

新增“系统实例”入口，统一管理 Android、iOS、OpenHarmony 测试环境。首次安装没有系统实例。安装包只包含管理软件及其 Electron/Python 依赖，**不附带系统镜像和运行引擎，也不会自动下载镜像**。

点击“添加系统”，打开相应下载与准备说明。自行下载并准备好运行环境后，在表单中选目录和资源设置。实例应用支持拖入文件，点击“安装并启动”时自动启动系统并等待设备就绪。原来的 touchHLE 应用库和运行时设置保持可用。

Android 和 OpenHarmony 应用可创建 Windows 桌面快捷方式，双击会打开对应系统并发送应用启动请求。现代 iOS 应用仍从 iOS 系统桌面打开。

| 平台 | 首批支持的外部环境 | 应用与限制 |
| --- | --- | --- |
| Android | [Android SDK Emulator](https://developer.android.com/studio/run/managing-avds)；先在 Android Studio 中创建 AVD，添加时选 SDK 根目录并填写 AVD 名称。需 Emulator、Platform-Tools、Build-Tools。 | APK 使用该实例的 adb serial 安装和启动。镜像架构与 API 兼容性由 Android 环境决定。 |
| iOS | 已部署的 [ASoftware iOS 16](https://github.com/alpersamur3/asoft-ios) 目录及其 work 数据。 | 兼容的 ARM64 IPA，通过运行环境的队列安装并回报结果；应用从 iOS 桌面打开。支持多套配置，同时只运行一套，避免固定端口冲突。 |
| OpenHarmony | [Oniro x86_64](https://docs.oniroproject.org/device-development/developer-boards/emulator/) images 目录（run.bat、run.sh、bzImage、system.img），以及 SDK 的 hdc.exe。需 QEMU、Git Bash/MSYS2 与 Windows Hypervisor Platform。 | Stage 模型 HAP，需含可读 module.json 和有效 bundleName；有 mainElement 时可调用 aa 启动。不是商业 HarmonyOS NEXT 应用兼容层。 |

每个 Android 实例使用独立 AVD；OpenHarmony 使用 `--instance N` 隔离用户数据和端口。Android/OpenHarmony 创建时可设置内存和核心数，iOS 资源配置沿用运行环境自己的设置。任意 ISO、IPSW 或面向开发板的固件不能直接导入成可启动环境。

OpenHarmony 的完整目录还需包含 ramdisk.img、updater.img、vendor.img、userdata.img。Oniro 首次启动独立实例时会在原目录的 instances/N 下创建 userdata.img 与 updater.img 的工作副本，系统只读分区共享；这部分空间由运行环境使用。

实例记录和日志保存在数据目录的 `systems` 子目录。应用包记录原文件路径，移动或更新文件后需重新导入。iOS 提交安装时会向其运行环境的安装队列复制一份包，这是安装所需，不会复制系统镜像。实例页显示所在磁盘可用空间。**移除管理记录保留外部镜像、用户数据和源安装包**；关闭系统会结束本软件启动的实例进程树，系统里未保存的内容应先保存。

验证：Python 行为测试覆盖路径、平台校验、进程身份、停止、设备目标、引导重试和 IPA 队列隔离；`npm run test:systems` 使用临时测试环境验证 Electron 创建实例与拖入 HAP，不启动真实虚拟机。本版本的三平台真实引导、安装和性能仍需在准备好的外部环境中验收，不将文件校验通过显示为系统就绪。

## 快速开始

从 [GitHub Releases](https://github.com/kkkaqi/ipa-runner/releases/latest) 获取已发布版本，或使用本地构建的 `TriDock-*-win-x64-Setup.exe`，双击后在安装向导中选择安装位置。安装包包含 Electron 和 Python，不包含系统镜像。安装后从桌面或开始菜单打开 TriDock（三栖），通过“添加系统”导入运行环境。

从源码运行：

1. 安装 **Node.js 22.12 或更新版本**和 **Python 3.10 或更新版本**，确保 `node`、`npm` 和 `python` 能在终端中运行。
2. 下载本仓库源码，双击 `TriDock.cmd`。首次打开需要联网下载 Electron。也可以在项目目录运行 `npm ci`，然后运行 `npm start`。旧 `IPA Runner.cmd` 作为兼容入口保留。
3. 若要使用早期 iOS 应用，下载并解压 [touchHLE Windows 版](https://github.com/touchHLE/touchHLE/releases)，在 TriDock 的 **运行时** 页选择 `touchHLE.exe` 并保存。
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

此目录名为兼容旧版本保留，改名升级不会迁移或删除其中的数据。

## 图标源文件

`electron/renderer/icon.svg` 是可编辑源文件。运行 `npm run build:icon` 使用 Electron 渲染 PNG 与 Windows 多尺寸 ICO；成品用于标题栏、窗口、任务栏、EXE 和 NSIS 安装器。

## 开发与测试

```powershell
npm ci
python -m unittest discover -s tests -v
npm run test:desktop
```

在 Windows x64 上运行 `npm run build:win` 可以生成安装包，成品位于 `dist`。首次构建需联网获取打包工具与 Python 嵌入包。

Windows 应用启动器的交互设计参考了 [ApkStart](https://github.com/RoutineMiku/apkstart)。
