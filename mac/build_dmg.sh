#!/usr/bin/env bash
# 把 PyInstaller 构建出的 .app 打成可拖拽安装的 DMG。
#
#   mac/build_dmg.sh                     # 用 output/mac/build/BetterMatuUI.app
#
# 产物：output/mac/BetterMatuUI Beta 1.0.dmg
#
# 安装界面：左边是应用图标，右边是 Applications 文件夹的软链，
# 用户直接把图标拖到右边即完成安装。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="BetterMatuUI"
VOL_NAME="BetterMatuUI Beta 1.0"
DMG_OUT="$ROOT/output/mac/$VOL_NAME.dmg"

APP="$ROOT/output/mac/build/$APP_NAME.app"
STAGE="$ROOT/output/mac/dmg_stage"
TMP_DMG="$ROOT/output/mac/tmp_rw.dmg"

[ -d "$APP" ] || { echo "找不到 $APP，先跑 PyInstaller 构建。" >&2; exit 1; }

echo "== 1/5 临时签名（ad-hoc）=="
# 不签名的话包里带的动态库在部分机器上会被直接拒绝加载。
# ad-hoc 不是开发者签名，不能免掉 Gatekeeper 的"未验证开发者"提示，
# 但能让包本身自洽。
codesign --force --deep --sign - "$APP" 2>&1 | tail -2 || echo "  （签名失败，继续）"
codesign --verify --deep --strict "$APP" 2>&1 | tail -1 && echo "  ✓ 签名自检通过" || true

echo "== 2/5 准备安装界面内容 =="
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

echo "== 3/5 生成可写镜像 =="
rm -f "$TMP_DMG"
hdiutil create -srcfolder "$STAGE" -volname "$VOL_NAME" -fs HFS+ \
    -format UDRW -ov "$TMP_DMG" >/dev/null

echo "== 4/5 挂载并排版 =="
MOUNT_DIR="$(hdiutil attach "$TMP_DMG" -noautoopen | grep -o '/Volumes/.*' | head -1)"
echo "  挂载于 $MOUNT_DIR"
# 排版靠 Finder 脚本；沙箱或没有图形会话时可能失败，失败也不影响 DMG 可用
osascript <<AS 2>/dev/null && echo "  ✓ 窗口布局已设置" || echo "  （跳过窗口布局，DMG 仍可用）"
tell application "Finder"
    tell disk "$VOL_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 160, 820, 540}
        set opts to the icon view options of container window
        set arrangement of opts to not arranged
        set icon size of opts to 120
        set position of item "$APP_NAME.app" of container window to {155, 190}
        set position of item "Applications" of container window to {465, 190}
        update without registering applications
        close
    end tell
end tell
AS
sync

echo "== 5/5 压缩成只读 DMG =="
hdiutil detach "$MOUNT_DIR" >/dev/null 2>&1 || hdiutil detach "$MOUNT_DIR" -force >/dev/null
rm -f "$DMG_OUT"
hdiutil convert "$TMP_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG_OUT" >/dev/null
rm -f "$TMP_DMG"
rm -rf "$STAGE"

echo
echo "完成：$DMG_OUT  ($(du -h "$DMG_OUT" | cut -f1))"
