#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
web_root="$project_root/web/ui"
build_root="${TMPDIR:-/tmp}/muni-lab-macos-build"
app_path="$build_root/MUNI lab.app"
contents="$app_path/Contents"

cd "$web_root"
bun run build

rm -rf "$build_root"
mkdir -p "$contents/MacOS" "$contents/Resources/web"

swiftc \
  -swift-version 5 \
  -O \
  -framework AppKit \
  -framework Network \
  "$script_dir/MUNILabApp.swift" \
  -o "$contents/MacOS/MUNILab"

cp "$script_dir/Info.plist" "$contents/Info.plist"
cp "$script_dir/MUNILab.icns" "$contents/Resources/MUNILab.icns"
ditto "$web_root/dist" "$contents/Resources/web"
printf '%s\n' "$project_root" > "$contents/Resources/project-root"

xattr -cr "$app_path"
codesign --force --deep --sign - "$app_path"

mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/MUNI lab.app"
ditto "$app_path" "$HOME/Applications/MUNI lab.app"
touch "$HOME/Applications/MUNI lab.app"
mdimport "$HOME/Applications/MUNI lab.app"

printf '%s\n' "$HOME/Applications/MUNI lab.app"
