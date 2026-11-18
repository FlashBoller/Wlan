#!/usr/bin/env python3
"""
Amazfit GTR 3 / GTS 3 – Bluetooth-LE-Werkzeug

Funktionen (nur Standard-BLE-Dienste, kein Auth-Key nötig):
  scan        Nach Amazfit-Uhren in der Nähe suchen
  info        Verbinden und Geräteinfos + Akkustand auslesen
  services    Alle GATT-Dienste und Characteristics auflisten
  hr          Herzfrequenz live mitlesen (Heart Rate Service 0x180D)

Beispiele:
  python amazfit_ble.py scan
  python amazfit_ble.py info --address AA:BB:CC:DD:EE:FF
  python amazfit_ble.py hr --address AA:BB:CC:DD:EE:FF --dauer 60

Hinweis: Funktionen wie Benachrichtigungen senden, Schritte oder
Schlafdaten abrufen laufen bei Zepp-OS-Uhren über ein verschlüsseltes
Huami-Protokoll und brauchen den Auth-Key aus der Zepp-App.
"""

import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# Standard-UUIDs (Bluetooth SIG)
BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"
DEVICE_INFO = {
    "Hersteller": "00002a29-0000-1000-8000-00805f9b34fb",
    "Modell": "00002a24-0000-1000-8000-00805f9b34fb",
    "Seriennummer": "00002a25-0000-1000-8000-00805f9b34fb",
    "Hardware-Version": "00002a27-0000-1000-8000-00805f9b34fb",
    "Firmware-Version": "00002a26-0000-1000-8000-00805f9b34fb",
    "Software-Version": "00002a28-0000-1000-8000-00805f9b34fb",
}

# Huami/Zepp-Dienste, an denen Amazfit-Uhren erkennbar sind
HUAMI_SERVICE_PREFIXES = ("0000fee0", "0000fee1")
NAME_HINTS = ("amazfit", "gtr", "gts", "zepp")


def looks_like_amazfit(device, adv) -> bool:
    name = (device.name or adv.local_name or "").lower()
    if any(hint in name for hint in NAME_HINTS):
        return True
    return any(u.lower().startswith(HUAMI_SERVICE_PREFIXES) for u in adv.service_uuids)


async def find_watch(timeout: float):
    """Erste gefundene Amazfit-Uhr zurückgeben (oder None)."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for device, adv in found.values():
        if looks_like_amazfit(device, adv):
            return device
    return None


async def resolve_address(args) -> str:
    if args.address:
        return args.address
    print(f"Keine Adresse angegeben – suche {args.timeout:.0f} s nach einer Amazfit-Uhr …")
    device = await find_watch(args.timeout)
    if device is None:
        sys.exit("Keine Amazfit-Uhr gefunden. Bluetooth an? Uhr entsperrt und in der Nähe?")
    print(f"Gefunden: {device.name} ({device.address})")
    return device.address


async def cmd_scan(args):
    print(f"Suche {args.timeout:.0f} s nach BLE-Geräten …\n")
    found = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    rows = sorted(found.values(), key=lambda da: da[1].rssi, reverse=True)
    any_watch = False
    for device, adv in rows:
        is_watch = looks_like_amazfit(device, adv)
        if not is_watch and not args.alle:
            continue
        any_watch |= is_watch
        mark = "⌚" if is_watch else "  "
        name = device.name or adv.local_name or "(ohne Namen)"
        print(f"{mark} {device.address}  RSSI {adv.rssi:>4} dBm  {name}")
    if not any_watch:
        print("Keine Amazfit-Uhr gefunden. Mit --alle werden alle Geräte angezeigt.")


async def read_text(client: BleakClient, uuid: str):
    try:
        data = await client.read_gatt_char(uuid)
        return data.decode("utf-8", errors="replace").strip("\x00 ")
    except (BleakError, KeyError, ValueError):
        return None


async def cmd_info(args):
    address = await resolve_address(args)
    async with BleakClient(address, timeout=args.timeout) as client:
        print(f"Verbunden mit {address}\n")
        for label, uuid in DEVICE_INFO.items():
            value = await read_text(client, uuid)
            if value:
                print(f"{label:<18} {value}")
        try:
            battery = await client.read_gatt_char(BATTERY_LEVEL)
            print(f"{'Akku':<18} {battery[0]} %")
        except (BleakError, KeyError, ValueError):
            print(f"{'Akku':<18} (nicht über Standard-Dienst lesbar)")


async def cmd_services(args):
    address = await resolve_address(args)
    async with BleakClient(address, timeout=args.timeout) as client:
        print(f"Verbunden mit {address}\n")
        for service in client.services:
            print(f"[Dienst] {service.uuid}  {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"    {char.uuid}  ({props})  {char.description}")


def parse_heart_rate(data: bytearray) -> int:
    """Heart Rate Measurement (0x2A37) nach Bluetooth-Spezifikation dekodieren."""
    flags = data[0]
    if flags & 0x01:  # 16-Bit-Wert
        return int.from_bytes(data[1:3], "little")
    return data[1]


async def cmd_hr(args):
    address = await resolve_address(args)
    async with BleakClient(address, timeout=args.timeout) as client:
        print(f"Verbunden mit {address}")

        def on_hr(_, data: bytearray):
            bpm = parse_heart_rate(data)
            if bpm:
                print(f"❤  {bpm} bpm")

        try:
            await client.start_notify(HEART_RATE_MEASUREMENT, on_hr)
        except (BleakError, KeyError, ValueError) as exc:
            sys.exit(
                f"Herzfrequenz-Dienst nicht verfügbar ({exc}).\n"
                "Tipp: Auf der Uhr die Herzfrequenz-Freigabe für andere Geräte "
                "aktivieren (je nach Firmware unter Einstellungen bzw. Training)."
            )
        print(f"Lese Herzfrequenz für {args.dauer} s (Strg+C zum Beenden) …")
        try:
            await asyncio.sleep(args.dauer)
        finally:
            await client.stop_notify(HEART_RATE_MEASUREMENT)


def main():
    parser = argparse.ArgumentParser(description="Amazfit GTR 3 / GTS 3 über Bluetooth LE")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--timeout", type=float, default=10.0, help="Scan-/Verbindungs-Timeout in s")
    sub = parser.add_subparsers(dest="befehl", required=True)

    p_scan = sub.add_parser("scan", help="Nach Uhren suchen", parents=[common])
    p_scan.add_argument("--alle", action="store_true", help="Alle BLE-Geräte anzeigen")
    p_scan.set_defaults(func=cmd_scan)

    for name, func, hilfe in (
        ("info", cmd_info, "Geräteinfos und Akku auslesen"),
        ("services", cmd_services, "GATT-Dienste auflisten"),
        ("hr", cmd_hr, "Herzfrequenz live mitlesen"),
    ):
        p = sub.add_parser(name, help=hilfe, parents=[common])
        p.add_argument("--address", help="MAC-Adresse (macOS: UUID) der Uhr; sonst automatische Suche")
        if name == "hr":
            p.add_argument("--dauer", type=int, default=60, help="Messdauer in Sekunden")
        p.set_defaults(func=func)

    args = parser.parse_args()
    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\nBeendet.")
    except BleakError as exc:
        sys.exit(f"Bluetooth-Fehler: {exc}")
    except (FileNotFoundError, OSError) as exc:
        sys.exit(f"Kein Bluetooth verfügbar ({exc}). Ist ein Adapter vorhanden und eingeschaltet?")


if __name__ == "__main__":
    main()
