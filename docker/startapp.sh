#!/usr/bin/env bash

# 1) Determine the home‐folder name
USERNAME="${USER_NAME:-user}"
export HOME="/home/${USERNAME}"

# 2) Keep only your generated files in that HOME:  
#    push *all* config & cache dirs into /tmp
export XDG_CONFIG_HOME=/tmp/xdg-config
export XDG_CACHE_HOME=/tmp/xdg-cache
export XDG_STATE_HOME=/tmp/xdg-state
export XDG_DATA_HOME=/tmp/xdg-data
export XDG_RUNTIME_DIR=/tmp/xdg-runtime

# Ensure they exist
mkdir -p \
  "$XDG_CONFIG_HOME" \
  "$XDG_CACHE_HOME" \
  "$XDG_STATE_HOME" \
  "$XDG_DATA_HOME" \
  "$XDG_RUNTIME_DIR"

# 1) Sidebar toggle
if [ "${SIDEBAR_HIDDEN:-true}" = "true" ]; then
  gsettings set org.gnome.nautilus.window-state start-with-sidebar false
else
  gsettings set org.gnome.nautilus.window-state start-with-sidebar true
fi

# 2) Randomly pick list or icon view
if [ "${ICONVIEW:-true}" = "true" ]; then
  gsettings set org.gnome.nautilus.preferences default-folder-viewer icon-view
else
  gsettings set org.gnome.nautilus.preferences default-folder-viewer list-view
fi

# ─── seed bookmarks into XDG_CONFIG_HOME only ────────────────
mkdir -p "$XDG_CONFIG_HOME/gtk-3.0"
: > "$XDG_CONFIG_HOME/gtk-3.0/bookmarks"
IFS=',' read -ra BMLIST <<< "${BOOKMARKS:-Documents}"
for d in "${BMLIST[@]}"; do
  echo "file://$HOME/$d    $d" >> "$XDG_CONFIG_HOME/gtk-3.0/bookmarks"
done

# ────────────────────────────────────────────────────────────────
# Gather all GTK themes (dirs with an index.theme inside)
mapfile -t GTK_THEMES < <(
  for d in /usr/share/themes/*/; do
    [ -f "${d}index.theme" ] && basename "$d"
  done
)

# Gather all icon themes (same logic under /usr/share/icons)
mapfile -t ICON_THEMES < <(
  for d in /usr/share/icons/*/; do
    [ -f "${d}index.theme" ] && basename "$d"
  done
)
# ────────────────────────────────────────────────────────────────
  
if [ "${#GTK_THEMES[@]}" -gt 0 ]; then
  CHOSEN_GTK="${GTK_THEMES[RANDOM % ${#GTK_THEMES[@]}]}"
  echo "🔧 Setting GTK theme to: $CHOSEN_GTK" >&2
fi

if [ "${#ICON_THEMES[@]}" -gt 0 ]; then
  CHOSEN_ICON="${ICON_THEMES[RANDOM % ${#ICON_THEMES[@]}]}"
  echo "🔧 Setting Icon theme to: $CHOSEN_ICON" >&2
fi
# ────────────────────────────────────────────────────────────────

export GTK_THEME="$CHOSEN_GTK"

cat > "$HOME/.config/gtk-3.0/settings.ini" <<EOF
[Settings]
gtk-icon-theme-name=$CHOSEN_ICON
EOF


# 3) Launch Nautilus pointed at /workspace
nautilus -q || true
while true; do
  echo "[`date`] Starting Nautilus on $HOME" >&2
  exec dbus-launch --exit-with-session nautilus --no-desktop "$HOME"
  echo "[`date`] Nautilus exited; restarting in 1s…" >&2
  sleep 1
done
