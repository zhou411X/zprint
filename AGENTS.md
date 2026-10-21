# zprint 开发约定

- 用户已明确授权本项目在宿主机本地开发、构建和测试，不使用 Docker。
- 本项目是 Ubuntu 24.04 GNOME / Wayland 原生桌面应用，使用系统 Python、GTK 3、Cairo 和 Pillow。
- 构建检查：`make build`；测试：`make test`（Xvfb 隔离显示，不触碰用户桌面）。
- 不使用 xdotool / pynput 模拟全局按键；截图通过 XDG Screenshot portal，快捷键通过桌面系统设置。
- 本机探测命令 `rg` / `ls` / `find` 保留 `|| true`，搜索限定相关子目录。
- 不提交、不推送，除非用户另行要求。
