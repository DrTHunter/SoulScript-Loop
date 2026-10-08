#!/bin/bash
# Boot: give the volume to the agent, lay down the root-owned HUD folder, then run the command server.
set -e

AGENT_USER="${AGENT_USER:-agent}"
HOME_DIR="/home/$AGENT_USER"

# First boot (a fresh volume, or the image's own home): seed the home directory once.
if [ ! -e "$HOME_DIR/.machine-seeded" ]; then
    cp -an /etc/skel/. "$HOME_DIR/"
    [ -e "$HOME_DIR/README.md" ] || sed "s/@AGENT@/$AGENT_USER/g" /opt/machine/README.md > "$HOME_DIR/README.md"
    touch "$HOME_DIR/.machine-seeded"
fi
# Everything in the home is the agent's. -h: never follow a symlink she planted out of the home.
find "$HOME_DIR" -exec chown -h "$AGENT_USER:$AGENT_USER" {} +

# The HUD lives outside anything she owns, so she can read her measurements and can't forge them.
# ~/hud is only a convenient pointer; deleting it changes nothing the loop writes.
mkdir -p /var/hud /var/log/machine
chown root:root /var/hud /var/log/machine
chmod 755 /var/hud /var/log/machine
ln -sfn /var/hud "$HOME_DIR/hud"
chown -h "$AGENT_USER:$AGENT_USER" "$HOME_DIR/hud"

[ -n "$MACHINE_TOKEN" ] || { echo "MACHINE_TOKEN is not set" >&2; exit 1; }
# Stays root: the server drops to the agent for each command, so the token lives in a process she can't read.
exec python3 /opt/machine/server.py
