#!/data/data/com.termux/files/usr/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# KlipperLearn: read-only check of an old Android phone before using it as the Klipper host.
# Run inside Termux:  sh phone_host_check.sh > phone-check.txt
# It installs nothing, changes nothing and sends nothing anywhere; share the output yourself.

say() { printf '%-28s %s\n' "$1" "$2"; }
prop() { getprop "$1" 2>/dev/null; }

echo "== KlipperLearn phone host check ($(date '+%Y-%m-%d %H:%M'))"
say "Model" "$(prop ro.product.manufacturer) $(prop ro.product.model) ($(prop ro.product.device))"
say "Android / SDK" "$(prop ro.build.version.release) / $(prop ro.build.version.sdk)"
say "CPU ABI" "$(prop ro.product.cpu.abi) [$(uname -m)]"
say "Kernel" "$(uname -r)"
say "CPU cores" "$(grep -c ^processor /proc/cpuinfo 2>/dev/null)"
say "RAM total" "$(awk '/MemTotal/ {printf "%.1f GB", $2/1048576}' /proc/meminfo 2>/dev/null)"
say "Free storage (Termux)" "$(df -h "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')"

# Termux source matters: the Play Store build is outdated and cannot run the installer.
say "Termux version" "${TERMUX_VERSION:-unknown}"
if [ -n "$TERMUX_APK_RELEASE" ]; then say "Termux build" "$TERMUX_APK_RELEASE"; fi
say "Termux:API present" "$(command -v termux-usb >/dev/null 2>&1 && echo yes || echo 'no (pkg install termux-api + Termux:API app)')"

# USB host (OTG) support is declared by the vendor as a system feature.
if command -v pm >/dev/null 2>&1; then
  say "USB host feature" "$(pm list features 2>/dev/null | grep -q android.hardware.usb.host && echo yes || echo 'not declared')"
fi
if command -v termux-usb >/dev/null 2>&1; then
  echo "-- USB devices seen now (connect the printer by OTG first):"
  termux-usb -l 2>/dev/null || echo "   (termux-usb could not list devices)"
fi

say "Root (su)" "$(command -v su >/dev/null 2>&1 && echo present || echo 'absent (fine: the route is non-root)')"
say "Python" "$(command -v python >/dev/null 2>&1 && python --version 2>&1 || echo 'not installed yet')"
say "Clang (for chelper)" "$(command -v clang >/dev/null 2>&1 && echo yes || echo 'not installed yet')"

if command -v termux-battery-status >/dev/null 2>&1; then
  echo "-- Battery:"; termux-battery-status 2>/dev/null
fi
say "Wake lock tool" "$(command -v termux-wake-lock >/dev/null 2>&1 && echo yes || echo no)"

# Clock health: klipper_termux patches Klipper for legacy Android clock issues; record it.
say "Monotonic clock" "$(cat /proc/uptime 2>/dev/null | cut -d' ' -f1) s uptime"
say "Listening :8080 / :7125" "$(netstat -ltn 2>/dev/null | grep -E ':(8080|7125) ' | wc -l) sockets"

echo "== Next: if Android >= 7, arm/arm64, USB host yes and >= 2 GB free, follow docs/ANDROID_HOST.md."
