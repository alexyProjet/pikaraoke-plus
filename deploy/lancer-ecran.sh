#!/usr/bin/env bash
# TV kiosk launcher: fullscreen browser on the splash screen.
#
# Audio is plug and play: when the Yamaha MG-XU mixer is connected over USB
# it becomes the default ALSA output (music goes through the mixing desk);
# otherwise sound falls back to the TV over HDMI.
set -u

carte=$(aplay -l 2>/dev/null | awk 'tolower($0) ~ /mg/ && /^card/ {gsub(":", "", $2); print $2; exit}')
if [ -n "$carte" ]; then
    printf 'pcm.!default { type plug slave.pcm "hw:%s,0" }\nctl.!default { type hw card %s }\n' \
        "$carte" "$carte" > "$HOME/.asoundrc"
else
    printf 'pcm.!default { type plug slave.pcm "hdmi:CARD=vc4hdmi0,DEV=0" }\n' > "$HOME/.asoundrc"
fi

navigateur=$(command -v chromium-browser || command -v chromium)
exec cage -- "$navigateur" \
    --kiosk \
    --autoplay-policy=no-user-gesture-required \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    http://localhost:5555/splash
