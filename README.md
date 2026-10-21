# zprint

Ubuntu 24.04 / GNOME / Wayland 原生截图标记工具。拖选截图，松开鼠标直接标记。

## 安装和启动

推荐从 [GitHub Releases](https://github.com/zhou411X/zprint/releases) 下载 DEB 安装包，然后执行：

```sh
sudo apt install ./zprint_0.2.0-1_all.deb
/usr/bin/zprint
```

DEB 安装到系统目录，首次启动时为当前用户注册默认快捷键，已有绑定会保留。从旧版 DEB 升级也使用上述命令；升级前先退出 zprint，升级后重新启动。启用浮动标记还需按下文加载 GNOME 46 扩展。如果以前通过 `install.sh` 安装，请先关闭应用并运行 `sh install.sh --uninstall` 移除用户安装，再安装 DEB，以免旧版本遮盖新版本。源码和导出图片不受影响。

以下是源码用户安装方式：

依赖均可由 Ubuntu 仓库提供；不需要 pip、Electron 或 root 后台服务：

```sh
sudo apt install python3-gi python3-gi-cairo python3-cairo python3-pil gir1.2-gtk-3.0
cd ~/workspace/zprint
sh install.sh
~/.local/bin/zprint
```

也可直接运行 `/usr/bin/python3 zprint`。安装会复制应用到 `~/.local/share/zprint`，创建用户桌面入口、图标和 `~/.local/bin/zprint` 命令。修改源码后重新运行安装脚本更新应用。不会设置默认图片查看器。

安装脚本默认注册 GNOME 全局快捷键，保留已有设置，冲突时跳过并提示。仅安装应用、不设置快捷键：`sh install.sh --no-shortcuts`。移除本应用安装和其未修改的快捷键：`sh install.sh --uninstall`。

## 截图流程

### 桌面原选区浮动标记（GNOME 46）

源码安装并启用扩展：

```sh
sh install.sh --enable-shell-extension
```

首次安装或更新扩展后，保存桌面上的工作，**注销并重新登录**。安装脚本会启用当前用户的 GNOME 扩展开关，并把 `zprint@zhou411X` 加入启用列表，保留其他扩展配置。不会自动注销，也不会修改系统 PrintScreen 绑定。

之后按 **zprint 自己的截图快捷键**（默认 Ctrl+Alt+S，可在设置中修改，已有设置保持不变），直接在冻结的桌面画面上拖选，**松开鼠标即出现标记工具栏**，不弹出完整编辑器，也不需要系统截图确认。反向拖选同样支持，单击不生成截图；选区时按 Esc 或右键取消，恢复原来的窗口和标记。**PrintScreen 保持 Ubuntu 系统截图行为，不进入自定义选区。**

图片保持在桌面原选区，工具栏出现在下方，可以直接画箭头、画笔、文字、形状、打码和数字。`●` 打开颜色、粗细和文字大小滑条；`✓` / Enter 复制结果并收起；`×` / Esc 放弃标记并收起（正在绘制时，第一次 Esc 仅取消笔画）。`↓` 导出，`↗` 转完整编辑器，保留可撤销的标记。

工具栏靠近屏幕底边时移到图片上方；全屏截图没有外部空间时显示在图片底部内侧。工具栏和选区边框不进入导出或复制结果。收起后 zprint 留在后台提供剪贴板图片，下一张截图直接清除上一张的图像、标记和历史。

扩展使用 GNOME 46 桌面纹理和选区输入组件实现自定义拖选，通过 Mutter 窗口接口定位。原始图片只作为临时缓存，完成收起或下一次截图时清理；需要保留请复制或导出。普通剪贴板图片和导入文件仍在完整编辑器中打开。其他入口产生的系统区域、窗口和屏幕截图也保留浮动标记支持。扩展不读取剪贴板历史，产品不使用模拟按键或 `org.gnome.Shell.Eval`。目前仅声明兼容 GNOME 46。

停用浮动模式：`gnome-extensions disable zprint@zhou411X`。重新启用：`gnome-extensions enable zprint@zhou411X`。扩展未运行或尚未重新登录加载新版时，应用截图入口回退到系统 portal；用 `gnome-extensions info zprint@zhou411X` 查看状态。扩展不改写系统按键配置，也不接管 PrintScreen。

0.2.0 DEB 已包含扩展；首次安装或更新后先保存工作、注销并重新登录，再由当前用户启用：

```sh
gsettings set org.gnome.shell disable-user-extensions false
gnome-extensions enable zprint@zhou411X
```

### 完整编辑器模式

未启用扩展时：

1. 按 **Ctrl+Alt+S**，或点击 zprint 的「截图」。
2. 在系统截图界面选择区域、窗口或全屏，确认截图。
3. zprint 自动打开图片，开始标记。

也支持原来的 **PrintScreen → 完成截图 → Ctrl+Alt+V**，读取剪贴板图片。应用内使用 Ctrl+V。

Wayland 下普通应用不能可靠地模拟 PrintScreen 或全局监听剪贴板。扩展模式由 GNOME Shell 直接取得桌面纹理；扩展不可用时通过 `org.freedesktop.portal.Screenshot` v2 的 `interactive=true` 请求系统截图。portal 模式首次调用可能出现系统权限确认。

结果先通过 portal 返回的 URI 载入；zprint 获得焦点后异步读取剪贴板，只有与本次截图内容一致才采用。剪贴板不可读或内容已变化时仍使用本次截图文件，避免误读旧图。应用不轮询或记录剪贴板历史。截图取消会恢复原窗口；成功取得新截图或剪贴板图片后，直接在当前窗口替换上一张图片，清除旧标记和撤销历史，无论是否已保存都不再询问。

如果系统截图服务不可用，使用 PrintScreen 截图后再粘贴。GNOME 本身可能把原始截图保存在「图片 / 截图」目录；zprint 不会删除这些系统文件。

参考：[GNOME 截图说明](https://help.gnome.org/gnome-help/screen-shot-record.html)、[XDG Screenshot portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Screenshot.html)、[GNOME 46 截图实现](https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/gnome-46/js/ui/screenshot.js)。

## 标记与文件

- 箭头、画笔、中文多行文本、矩形、圆形、马赛克打码、连续数字。
- 预设颜色、自定义颜色、线宽、文字大小；打码工具使用粗细控制马赛克大小。
- 撤销、重做；选择后拖动移动、Delete 删除；双击文字修改内容。
- Shift 拖动画正圆 / 正方形；缩放、适应窗口、滚动查看大图。
- 导入 PNG、JPEG 等 GdkPixbuf 支持的图片，支持拖放及 EXIF 方向。
- PNG 导出保留透明度；JPEG 导出使用白色背景；复制输出包含所有标记。
- 关闭窗口或手动导入文件替换未导出的标记时提示保存；新截图和剪贴板图片直接替换当前图片。导出是合成图片，不是可恢复图层的工程文件。

## 设置与版本

点击左侧底部的「设置」：

- **快捷键**：点击当前组合键后直接按下新组合键；支持停用和恢复默认。点击「保存快捷键」后立即生效，与其他系统快捷键冲突时会提示，不会覆盖其他应用的设置。关闭对话框会丢弃尚未保存的修改。重新安装会保留已保存的快捷键。
- **快捷键 / 帮助**：查看当前全局快捷键、编辑器操作和使用说明；F1 可直接打开此页。
- **关于 zprint**：查看当前应用版本号，版本来自 `zprint_app/__init__.py`。

这里配置的是截图和读取剪贴板的全局快捷键；编辑器内工具、复制、导出等快捷键可在「设置 → 快捷键 / 帮助」中查看。

马赛克用于视觉遮挡，需要完全去除敏感内容时应使用不可逆实色遮盖等专用处理；本版本不提供实色遮盖工具。复制后请保留 zprint 窗口直至粘贴完成，退出后的剪贴板持久性由桌面剪贴板管理器决定。

| 快捷键 | 功能 |
| --- | --- |
| Ctrl+Alt+S / Ctrl+Alt+V | 全局：截图 / 读取剪贴板（安装后） |
| Ctrl+N / Ctrl+O / Ctrl+V | 截图 / 导入 / 粘贴 |
| Ctrl+C / Ctrl+S | 复制合成图片 / 导出 |
| Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y | 撤销 / 重做 |
| V A P T R O M N | 选择、箭头、画笔、文字、矩形、圆形、打码、数字 |
| Delete / Esc | 删除选中标记 / 取消当前绘制 |
| Ctrl+0 / Ctrl+滚轮 | 适应窗口 / 缩放 |

可在「设置 → 键盘 → 自定义快捷键」修改全局按键，对应命令为 `~/.local/bin/zprint --capture` 和 `~/.local/bin/zprint --clipboard`（系统设置中使用绝对路径）。不会修改系统 PrintScreen 绑定。

DEB 安装对应命令为 `/usr/bin/zprint --capture` 和 `/usr/bin/zprint --clipboard`。也可直接在 zprint 的设置中修改。

## 开发和测试

```sh
sudo apt install xvfb xauth gjs
make build
make test
make test-shell
make deb
```

DEB 产物与 SHA256 校验文件位于 `dist/`。构建使用系统 `dpkg-deb`，无需 root；版本号统一读取 `zprint_app/__init__.py`。可通过 `SOURCE_DATE_EPOCH` 固定构建时间戳（默认为 0），相同输入生成相同安装包。

构建为 Python 字节码编译检查。自动化测试用 Xvfb 验证绘图、历史、导出、剪贴板及界面交互，用隔离的假 portal 验证响应和取消生命周期。真实 Wayland 的系统截图权限弹窗、全局按键和焦点策略需要在桌面会话人工验证，Xvfb 不代表这些端到端场景已通过。

`make test` 还需要 `gjs`，覆盖浮动模式的原图坐标、复制收起和工具栏边缘布局。`make test-shell` 需要本机 GNOME Shell 46，创建独立 D-Bus、临时用户配置和无头 Wayland 显示，运行真实系统截图与扩展定位；不重启当前桌面。测试预览与日志写入 `dist/`，不会打包测试用扩展入口。物理多显示器、分数缩放和真实快捷键仍需桌面验证。

隔离 Wayland 测试覆盖应用自定义截图入口、松开直接标记、主窗口不闪现、反向拖选、取消恢复、连续截图像素及缓存清理、停用时释放输入，以及 PrintScreen 保持系统截图行为；也覆盖 portal 的两种通知顺序。该独立会话内的虚拟输入验证工具切换、绘制、撤销、重做和完成收起。测试观察器不进入应用安装包。
