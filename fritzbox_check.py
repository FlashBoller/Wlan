#!/usr/bin/env python3
"""FRITZ!Box-Diagnose: liest nur, ändert nichts am Router.

Aufruf:
    python3 fritzbox_check.py                  # Basis-Check ohne Passwort
    python3 fritzbox_check.py --host 192.168.178.1
    FRITZ_PASSWORD=... python3 fritzbox_check.py --user admin   # erweiterter Check

Für den erweiterten Check (Ereignisprotokoll, DSL-Fehler, WLAN) wird
'fritzconnection' benötigt:  pip install fritzconnection
"""
import argparse
import os
import re
import socket
import time
import urllib.request

OK, WARN, ERR = "[ OK ]", "[WARN]", "[FEHL]"
problems = []


def report(level, msg):
    print(f"{level} {msg}")
    if level != OK:
        problems.append(f"{level} {msg}")


def tcp_time(host, port, timeout=2.0):
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.perf_counter() - start) * 1000
    except OSError:
        return None


def http_get(url, timeout=4):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def soap(host, path, service, action, timeout=4):
    body = (
        '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="{service}"/></s:Body></s:Envelope>'
    ).encode()
    req = urllib.request.Request(
        f"http://{host}:49000{path}", data=body,
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPAction": f'"{service}#{action}"'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        xml = r.read().decode("utf-8", "replace")
    return dict(re.findall(r"<(New\w+)>([^<]*)</\1>", xml))


def check_reachability(host):
    print("\n== Erreichbarkeit ==")
    try:
        ip = socket.gethostbyname(host)
        report(OK, f"{host} -> {ip}")
    except OSError:
        report(ERR, f"{host} lässt sich nicht auflösen. Bist du im Netz der FRITZ!Box?")
        return None
    times = [t for t in (tcp_time(ip, 80) for _ in range(10)) if t is not None]
    lost = 10 - len(times)
    if not times:
        report(ERR, "Weboberfläche (Port 80) antwortet nicht")
        return ip
    avg = sum(times) / len(times)
    report(OK if lost == 0 else WARN, f"10 Verbindungen: {lost} verloren, Ø {avg:.1f} ms, max {max(times):.1f} ms")
    if avg > 20:
        report(WARN, "Hohe Latenz zum Router. Das spricht für ein schwaches WLAN-Signal oder einen überlasteten Kanal.")
    return ip


def check_ports(ip):
    print("\n== Offene Ports am Router (aus dem Heimnetz) ==")
    ports = {21: "FTP", 22: "SSH", 23: "Telnet", 53: "DNS", 80: "HTTP", 139: "NetBIOS",
             443: "HTTPS", 445: "SMB/NAS", 5060: "SIP", 8089: "TR-064 Telefonie",
             49000: "TR-064/UPnP", 49443: "TR-064 TLS"}
    for port, name in ports.items():
        if tcp_time(ip, port, 1.0) is not None:
            level = ERR if port == 23 else (WARN if port in (21, 139, 445) else OK)
            report(level, f"Port {port:5} offen ({name})")
    print("     Hinweis: Die Freigaben ins Internet stehen unter Internet > Freigaben in der FRITZ!Box-Oberfläche.")


def check_dns():
    print("\n== DNS / Internet ==")
    for name in ("avm.de", "google.com", "cloudflare.com"):
        start = time.perf_counter()
        try:
            socket.gethostbyname(name)
            report(OK, f"DNS {name}: {(time.perf_counter() - start) * 1000:.0f} ms")
        except OSError:
            report(ERR, f"DNS-Auflösung von {name} schlägt fehl")
    t = tcp_time("1.1.1.1", 443, 3)
    report(OK if t else ERR, f"Internet (1.1.1.1:443): {t:.0f} ms" if t else "Keine Verbindung ins Internet")


def check_upnp(ip):
    print("\n== Router-Info ohne Passwort (TR-064/UPnP) ==")
    try:
        desc = http_get(f"http://{ip}:49000/tr64desc.xml")
        model = re.search(r"<modelName>([^<]*)", desc)
        fw = re.search(r"<Display>([^<]*)", desc)
        report(OK, f"Modell: {model.group(1) if model else '?'}  Firmware: {fw.group(1) if fw else '?'}")
    except Exception:
        report(WARN, "TR-064 ist nicht erreichbar. Einschalten unter Heimnetz > Netzwerk > Netzwerkeinstellungen.")
    svc = "urn:schemas-upnp-org:service:WANIPConnection:1"
    try:
        st = soap(ip, "/igdupnp/control/WANIPConn1", svc, "GetStatusInfo")
        status = st.get("NewConnectionStatus", "?")
        report(OK if status == "Connected" else ERR, f"Internetverbindung: {status}, "
               f"letzter Fehler: {st.get('NewLastConnectionError', '?')}, "
               f"Uptime: {int(st.get('NewUptime', 0)) // 3600} h")
        if st.get("NewUptime") and int(st["NewUptime"]) < 3600:
            report(WARN, "Die Verbindung besteht erst seit weniger als 1 h. Gab es eine Trennung oder einen Neustart?")
        link = soap(ip, "/igdupnp/control/WANCommonIFC1",
                    "urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1",
                    "GetCommonLinkProperties")
        down = int(link.get("NewLayer1DownstreamMaxBitRate", 0)) / 1e6
        up = int(link.get("NewLayer1UpstreamMaxBitRate", 0)) / 1e6
        report(OK, f"Leitung: {link.get('NewWANAccessType', '?')} "
               f"{down:.0f}/{up:.0f} Mbit/s, Status {link.get('NewPhysicalLinkStatus', '?')}")
    except Exception:
        report(WARN, "UPnP-Status ist nicht abrufbar. Einschalten unter Heimnetz > Netzwerk > "
               "'Statusinformationen über UPnP übertragen'.")


def check_authenticated(ip, user, password):
    print("\n== Erweiterter Check (mit Login) ==")
    try:
        from fritzconnection import FritzConnection
    except ImportError:
        report(WARN, "fritzconnection fehlt: pip install fritzconnection")
        return
    try:
        fc = FritzConnection(address=ip, user=user, password=password, timeout=8)
    except Exception as e:
        report(ERR, f"Login fehlgeschlagen: {e}")
        return

    def call(service, action, **kw):
        try:
            return fc.call_action(service, action, **kw)
        except Exception:
            return None

    info = call("DeviceInfo1", "GetInfo")
    if info:
        report(OK, f"{info.get('NewModelName')} FW {info.get('NewSoftwareVersion')}, "
               f"läuft seit {int(info.get('NewUpTime', 0)) // 86400} Tagen")
    upd = call("UserInterface1", "GetInfo")
    if upd and upd.get("NewUpgradeAvailable"):
        report(WARN, f"Firmware-Update verfügbar: {upd.get('NewX_AVM-DE_Version')}")
    elif upd:
        report(OK, "Firmware ist aktuell")

    dsl = call("WANDSLInterfaceConfig1", "GetInfo")
    if dsl and dsl.get("NewStatus"):
        report(OK if dsl["NewStatus"] == "Up" else ERR, f"DSL-Status: {dsl['NewStatus']}")
        for k, label in (("NewDownstreamNoiseMargin", "Störabstand ↓"),
                         ("NewUpstreamNoiseMargin", "Störabstand ↑")):
            v = dsl.get(k)
            if v is not None:
                db = v / 10
                report(OK if db >= 6 else WARN, f"{label}: {db:.1f} dB" + ("" if db >= 6 else " (niedrig)"))
        stats = call("WANDSLInterfaceConfig1", "X_AVM-DE_GetDSLInfo") or {}
        crc = stats.get("NewCRCErrors") or stats.get("NewFECErrors")
        if crc:
            report(WARN if crc > 1000 else OK, f"DSL-Fehlerzähler: {crc}")

    for i in (1, 2, 3):
        w = call(f"WLANConfiguration{i}", "GetInfo")
        if not w:
            continue
        on = w.get("NewEnable")
        report(OK, f"WLAN {i}: {w.get('NewSSID')} {'an' if on else 'aus'}, Kanal {w.get('NewChannel')}, "
               f"{w.get('NewStandard')}, Verschlüsselung {w.get('NewBeaconType')}")
        if on and w.get("NewBeaconType") in ("None", "Basic", "WPA"):
            report(ERR, f"WLAN {i} ist unsicher verschlüsselt ({w.get('NewBeaconType')})")
    wps = call("WLANConfiguration1", "X_AVM-DE_GetWPSInfo")
    if wps and wps.get("NewX_AVM-DE_WPSStatus") not in (None, "off"):
        report(WARN, "WPS ist aktiv")

    log = call("DeviceInfo1", "GetDeviceLog")
    if log and log.get("NewDeviceLog"):
        keys = ("fehl", "error", "abbruch", "getrennt", "neustart", "verloren",
                "zeitüberschreitung", "nicht erfolgreich", "ungültig", "angriff")
        hits = [l for l in log["NewDeviceLog"].splitlines() if any(k in l.lower() for k in keys)]
        print(f"\n   Ereignisprotokoll: {len(hits)} auffällige Einträge (die neuesten 25):")
        for l in hits[:25]:
            print("     " + l)
        if hits:
            problems.append(f"{WARN} {len(hits)} auffällige Einträge im Ereignisprotokoll")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="fritz.box")
    ap.add_argument("--user", default=os.environ.get("FRITZ_USER", ""))
    args = ap.parse_args()

    ip = check_reachability(args.host)
    if ip:
        check_ports(ip)
        check_upnp(ip)
    check_dns()
    pw = os.environ.get("FRITZ_PASSWORD")
    if ip and pw:
        check_authenticated(ip, args.user, pw)
    elif ip:
        print("\n(Für Protokoll, DSL-Werte und WLAN-Sicherheit setze FRITZ_PASSWORD und starte erneut.)")

    print("\n== Zusammenfassung ==")
    print("\n".join(problems) if problems else "Keine Probleme gefunden.")


if __name__ == "__main__":
    main()
