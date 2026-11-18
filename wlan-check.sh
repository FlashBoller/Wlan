#!/usr/bin/env bash
# WLAN-/Router-Diagnose fuer Linux und macOS. Aufruf: bash wlan-check.sh
set -u
OS=$(uname)
hr(){ printf '\n=== %s ===\n' "$1"; }
stats(){ # ping-Ziel, Anzahl -> "verlust% avg jitter"
  ping -c "$2" -i 0.2 "$1" 2>/dev/null | awk -F'[ =/]+' '
    /packet loss/ {for(i=1;i<=NF;i++) if($i ~ /%$/) loss=$i}
    /min\/avg\/max/ {avg=$(NF-3); jit=$(NF-1)}
    END {printf "Verlust %s | Ø %s ms | Jitter %s ms\n", loss, avg, jit}'
}

hr "Router (Gateway)"
if [ "$OS" = Darwin ]; then GW=$(route -n get default 2>/dev/null | awk '/gateway/{print $2}')
else GW=$(ip route | awk '/^default/{print $3; exit}'); fi
echo "Gateway: ${GW:-nicht gefunden}"

hr "WLAN-Signal"
if [ "$OS" = Darwin ]; then
  system_profiler SPAirPortDataType 2>/dev/null | awk '/Current Network Information/{f=1} f&&/PHY Mode|Channel|Signal|Transmit Rate/{print; n++} n>=4{exit}'
elif command -v nmcli >/dev/null; then
  nmcli -f IN-USE,SSID,CHAN,RATE,SIGNAL,SECURITY dev wifi | awk 'NR==1||/^\*/'
  echo; echo "Andere Netze auf deinem Kanal (Störer):"
  CH=$(nmcli -t -f IN-USE,CHAN dev wifi | awk -F: '$1=="*"{print $2}')
  nmcli -t -f CHAN,SSID,SIGNAL dev wifi | awk -F: -v c="$CH" '$1==c' | head
else iw dev 2>/dev/null; fi

hr "Ping zum Router (lokale Strecke)"
[ -n "${GW:-}" ] && stats "$GW" 30
hr "Ping ins Internet (1.1.1.1)"
stats 1.1.1.1 30

hr "DNS-Antwortzeit"
for d in google.de heise.de amazon.de; do
  t0=$(date +%s%N 2>/dev/null || python3 -c 'import time;print(int(time.time()*1e9))')
  nslookup "$d" >/dev/null 2>&1
  t1=$(date +%s%N 2>/dev/null || python3 -c 'import time;print(int(time.time()*1e9))')
  echo "$d: $(( (t1-t0)/1000000 )) ms"
done

hr "Download (100 MB Testdatei)"
curl -s -o /dev/null -w 'Download: %{speed_download} B/s\n' --max-time 20 "https://speed.cloudflare.com/__down?bytes=100000000" \
  | awk '{printf "Download: %.1f Mbit/s\n", $2*8/1e6}'

hr "Bufferbloat (Ping waehrend Download)"
curl -s -o /dev/null --max-time 15 "https://speed.cloudflare.com/__down?bytes=200000000" &
sleep 2; stats 1.1.1.1 40; wait

cat <<'TXT'

=== So liest du das ===
Signal < 50 % (bzw. RSSI < -67 dBm)  -> WLAN ist die Bremse: naeher ran, Repeater/Mesh, 5 GHz nutzen
Router-Ping > 5 ms oder Verlust > 0 % -> WLAN gestoert: anderen Kanal waehlen (2,4 GHz: 1/6/11)
Router ok, Internet-Ping schlecht    -> Problem liegt beim Anschluss/Provider
DNS > 100 ms                         -> anderen DNS eintragen (z.B. 1.1.1.1 oder 9.9.9.9)
Ping unter Last >> Ping ohne Last    -> Bufferbloat: im Router QoS/SQM aktivieren
Download deutlich unter Tarif        -> per LAN-Kabel gegentesten: WLAN oder Leitung?
TXT
