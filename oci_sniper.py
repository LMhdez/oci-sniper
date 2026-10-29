#!/usr/bin/env python3
"""
OCI ARM Instance Sniper — versión blindada (API REST)
=====================================================
No requiere el SDK de OCI. Usa requests + firma HTTP directa.

Uso:
    pip install requests cryptography
    python oci_sniper.py
    python oci_sniper.py --dry-run
"""

import argparse
import base64
import email.utils
import hashlib
import json
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# ─────────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────

COMPARTMENT_ID = "ocid1.tenancy.oc1..aaaaaaaafagv5od7qmmed2xljniofsbohtzuejd465edqcgm5ccylet6bcxq"
IMAGE_ID = "ocid1.image.oc1.iad.aaaaaaaa6o52ajhkewa2syfadrxel5b7tfwi5qdm45gl4ykwbqut25tvdxrq"
SUBNET_ID = "ocid1.subnet.oc1.iad.aaaaaaaakcyexrysryiee77ojkysib7d25rzrdd5zcqqne5dqayizilnh3ia"

SSH_PUBLIC_KEY = (
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCrKlvwOnFzODuU0VwdC72QzyYKFG2i"
    "QutigpwyWDAl6NH8qo+VYod04OF10uMxR5MSX+u0bJIOwggxklPA+YfLFdOTSrIBuvxP"
    "rhOAw+hbFwhtfLKri+8vuFby3coiPv3f4fGM80vYvqi0LhbGutPrAv2J6QpBat9d1wG6"
    "ys5LuEGt8/A8QHI1c4yTLqMkkZo/dKR7V7bjUTMe0etGGecLywHW74fcqEGBi6Bi1nqQ"
    "T/iq4w8sHImGINdBcMES2WibTjOsHZDezCgdpBub+ns4tQHC6bWb+6NoJOnxamOoWF5s"
    "NiqoUoygydiid5g+E8Qu+WuomAw0rFk6o0IKCexz ssh-key-2026-10-29"
)

ADS = [
    "CqwQ:US-ASHBURN-AD-1",
    "CqwQ:US-ASHBURN-AD-2",
    "CqwQ:US-ASHBURN-AD-3",
]

PROFILES = [
    {"ocpus": 4.0, "memory_in_gbs": 24.0, "label": "4 OCPUs / 24 GB RAM"},
    {"ocpus": 2.0, "memory_in_gbs": 12.0, "label": "2 OCPUs / 12 GB RAM"},
]

INSTANCE_NAME = "mc-server-production"
BOOT_VOL_GB = 200

# Temporización
INTERVAL_BETWEEN_ADS = 15       # segundos entre cada AD
INTERVAL_BETWEEN_CYCLES = 45    # segundos tras un ciclo completo de 3 ADs
RATE_LIMIT_BACKOFF = 120        # pausa base si 429
MAX_BACKOFF = 300               # tope de retroceso exponencial
JITTER_RANGE = 10               # ±segundos aleatorios
ROUNDS_BEFORE_FALLBACK = 10     # rondas antes de probar perfil menor

# Notificaciones (dejar vacío si no se usan)
DISCORD_WEBHOOK_URL = ""
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""


# ─────────────────────────────────────────────────────────────
#  OCI CONFIG + FIRMA HTTP
# ─────────────────────────────────────────────────────────────

def load_oci_config(profile="DEFAULT"):
    config_path = os.path.join(os.path.expanduser("~"), ".oci", "config")
    if not os.path.exists(config_path):
        print(f"[!] No se encontró {config_path}")
        sys.exit(1)

    config = {}
    in_profile = False
    with open(config_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"[{profile}]"):
                in_profile = True
                continue
            if line.startswith("[") and in_profile:
                break
            if in_profile and "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                config[key.strip()] = val.strip()

    key_path = config.get("key_file", "").replace("\\\\", "\\")
    if not os.path.exists(key_path):
        print(f"[!] Clave privada no encontrada: {key_path}")
        sys.exit(1)

    with open(key_path, "rb") as f:
        config["_private_key"] = serialization.load_pem_private_key(f.read(), password=None)

    return config


class OCISigner:
    def __init__(self, config):
        self.api_key = f"{config['tenancy']}/{config['user']}/{config['fingerprint']}"
        self.private_key = config["_private_key"]

    def sign(self, method, url, body=None):
        parsed = urlparse(url)
        host = parsed.hostname
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query

        now = email.utils.formatdate(usegmt=True)
        headers_map = {
            "date": now,
            "host": host,
            "(request-target)": f"{method.lower()} {path}",
        }
        signing_headers = ["(request-target)", "date", "host"]
        req_headers = {"date": now}

        if body is not None:
            body_bytes = body.encode("utf-8") if isinstance(body, str) else body
            body_hash = base64.b64encode(hashlib.sha256(body_bytes).digest()).decode()
            headers_map["content-length"] = str(len(body_bytes))
            headers_map["content-type"] = "application/json"
            headers_map["x-content-sha256"] = body_hash
            signing_headers += ["content-type", "content-length", "x-content-sha256"]
            req_headers.update({
                "content-type": "application/json",
                "content-length": str(len(body_bytes)),
                "x-content-sha256": body_hash,
            })

        signing_string = "\n".join(f"{h}: {headers_map[h]}" for h in signing_headers)
        signature = base64.b64encode(
            self.private_key.sign(signing_string.encode(), padding.PKCS1v15(), hashes.SHA256())
        ).decode()

        req_headers["authorization"] = (
            f'Signature version="1",'
            f'keyId="{self.api_key}",'
            f'algorithm="rsa-sha256",'
            f'headers="{" ".join(signing_headers)}",'
            f'signature="{signature}"'
        )
        return req_headers


class OCICompute:
    def __init__(self, config):
        self.signer = OCISigner(config)
        self.region = config["region"]
        self.base = f"https://iaas.{self.region}.oraclecloud.com/20160918"

    def launch_instance(self, body):
        url = f"{self.base}/instances"
        body_str = json.dumps(body)
        headers = self.signer.sign("POST", url, body_str)
        return requests.post(url, headers=headers, data=body_str, timeout=60)


# ─────────────────────────────────────────────────────────────
#  NOTIFICACIONES
# ─────────────────────────────────────────────────────────────

def notify(message):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        except Exception:
            pass
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
#  SNIPER
# ─────────────────────────────────────────────────────────────

class Sniper:
    def __init__(self, compute: OCICompute, dry_run=False):
        self.compute = compute
        self.dry_run = dry_run
        self.shutdown = False
        self.total_attempts = 0
        self.out_of_capacity = 0
        self.rate_limits = 0
        self.consecutive_429 = 0
        self.network_errors = 0
        self.other_errors = 0
        self.full_cycles = 0
        self.started_at = datetime.now(timezone.utc)

        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, *_):
        print("\n\n⚡ Interrupción recibida. Cerrando limpiamente...")
        self.shutdown = True

    def _jitter(self, base):
        return max(1.0, base + random.uniform(-JITTER_RANGE, JITTER_RANGE))

    def _sleep(self, secs):
        end = time.time() + secs
        while time.time() < end and not self.shutdown:
            time.sleep(min(1.0, end - time.time()))

    def _select_profile(self):
        if self.full_cycles > 0 and self.full_cycles % ROUNDS_BEFORE_FALLBACK == 0:
            return PROFILES[-1]
        return PROFILES[0]

    def _try_launch(self, ad, profile):
        ad_short = ad.split(":")[-1]
        self.total_attempts += 1
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")

        print(
            f"  [{now}] #{self.total_attempts:05d} | {ad_short} | {profile['label']}",
            end="",
            flush=True,
        )

        if self.dry_run:
            print(" → [DRY-RUN]")
            return None

        body = {
            "compartmentId": COMPARTMENT_ID,
            "availabilityDomain": ad,
            "displayName": INSTANCE_NAME,
            "shape": "VM.Standard.A1.Flex",
            "shapeConfig": {
                "ocpus": profile["ocpus"],
                "memoryInGBs": profile["memory_in_gbs"],
            },
            "sourceDetails": {
                "sourceType": "image",
                "imageId": IMAGE_ID,
                "bootVolumeSizeInGBs": BOOT_VOL_GB,
                "bootVolumeVpusPerGB": 10,
            },
            "createVnicDetails": {
                "subnetId": SUBNET_ID,
                "assignPublicIp": True,
                "assignPrivateDnsRecord": True,
            },
            "metadata": {
                "ssh_authorized_keys": SSH_PUBLIC_KEY,
            },
        }

        try:
            resp = self.compute.launch_instance(body)

            if resp.status_code in (200, 201):
                data = resp.json()
                print(f" → ✅ ¡ÉXITO!")
                return data

            error_code = ""
            error_msg = ""
            try:
                err = resp.json()
                error_code = err.get("code", "")
                error_msg = err.get("message", "")
            except Exception:
                error_msg = resp.text[:200]

            if resp.status_code == 500 and "capacity" in error_msg.lower():
                self.out_of_capacity += 1
                self.consecutive_429 = 0
                print(f" → Sin capacidad")
                return None

            if "OutOfHostCapacity" in error_code or "out of capacity" in error_msg.lower():
                self.out_of_capacity += 1
                self.consecutive_429 = 0
                print(f" → Sin capacidad")
                return None

            if resp.status_code == 429:
                self.rate_limits += 1
                self.consecutive_429 += 1
                backoff = min(RATE_LIMIT_BACKOFF * (2 ** (self.consecutive_429 - 1)), MAX_BACKOFF)
                print(f" → ⚠ 429 Rate Limited. Pausa {backoff:.0f}s")
                self._sleep(backoff)
                return None

            if resp.status_code == 400 and "LimitExceeded" in error_code:
                print(f"\n\n  ❌ LimitExceeded: {error_msg}")
                print("     → Ya tienes una instancia ARM o superaste el límite gratuito.")
                notify(f"❌ LimitExceeded: {error_msg}")
                self.shutdown = True
                return None

            self.other_errors += 1
            print(f" → ⚠ Error {resp.status_code}: {error_msg[:100]}")
            self._sleep(15)
            return None

        except (requests.ConnectionError, requests.Timeout, OSError) as e:
            self.network_errors += 1
            print(f" → ⚠ Red: {type(e).__name__}")
            self._sleep(20)
            return None

        except Exception as e:
            self.other_errors += 1
            print(f" → ⚠ {type(e).__name__}: {e}")
            self._sleep(15)
            return None

    def _on_success(self, data, profile):
        instance_id = data.get("id", "?")
        ad = data.get("availabilityDomain", "?")
        state = data.get("lifecycleState", "?")
        elapsed = datetime.now(timezone.utc) - self.started_at

        banner = (
            f"\n{'=' * 60}\n"
            f" 🎉  ¡INSTANCIA CREADA CON ÉXITO!\n"
            f"{'=' * 60}\n"
            f"  ID:        {instance_id}\n"
            f"  AD:        {ad}\n"
            f"  Shape:     VM.Standard.A1.Flex\n"
            f"  OCPUs:     {profile['ocpus']}\n"
            f"  RAM:       {profile['memory_in_gbs']} GB\n"
            f"  Estado:    {state}\n"
            f"  Tiempo:    {elapsed}\n"
            f"{'=' * 60}\n"
            f"  Estadísticas:\n"
            f"    Intentos totales:  {self.total_attempts}\n"
            f"    Sin capacidad:     {self.out_of_capacity}\n"
            f"    Rate limits:       {self.rate_limits}\n"
            f"    Errores de red:    {self.network_errors}\n"
            f"    Otros errores:     {self.other_errors}\n"
            f"    Ciclos completos:  {self.full_cycles}\n"
            f"{'=' * 60}"
        )
        print(banner)

        # Guardar resultado
        result_path = Path("oci_sniper_result.json")
        result_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Resultado guardado en {result_path.absolute()}")

        notify(
            f"🚀 Servidor OCI creado\n"
            f"• AD: {ad}\n• Config: {profile['label']}\n"
            f"• ID: {instance_id}\n• Intentos: {self.total_attempts}"
        )

    def run(self):
        print(
            f"\n{'=' * 60}\n"
            f" ⚡ OCI ARM Sniper — Iniciado\n"
            f"{'=' * 60}\n"
            f"  Región:      us-ashburn-1\n"
            f"  ADs:         {len(ADS)}\n"
            f"  Perfiles:    {' → '.join(p['label'] for p in PROFILES)}\n"
            f"  Intervalo:   {INTERVAL_BETWEEN_ADS}s entre ADs, {INTERVAL_BETWEEN_CYCLES}s entre ciclos\n"
            f"  Dry-run:     {'SÍ' if self.dry_run else 'NO'}\n"
            f"{'=' * 60}\n"
        )

        while not self.shutdown:
            profile = self._select_profile()

            for ad in ADS:
                if self.shutdown:
                    break

                result = self._try_launch(ad, profile)
                if result is not None:
                    self._on_success(result, profile)
                    return

                self._sleep(self._jitter(INTERVAL_BETWEEN_ADS))

            self.full_cycles += 1

            if not self.shutdown:
                pause = self._jitter(INTERVAL_BETWEEN_CYCLES)
                print(
                    f"\n  ── Ciclo #{self.full_cycles} completado "
                    f"({self.out_of_capacity} sin capacidad). "
                    f"Pausa {pause:.0f}s ──\n"
                )
                self._sleep(pause)

        print(f"\n🛑 Sniper detenido. {self.total_attempts} intentos en {self.full_cycles} ciclos.")


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OCI ARM Instance Sniper")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin crear nada")
    parser.add_argument("--profile", default="DEFAULT", help="Perfil de ~/.oci/config")
    parser.add_argument("--discord", default=None, help="Discord webhook URL")
    args = parser.parse_args()

    global DISCORD_WEBHOOK_URL
    if args.discord:
        DISCORD_WEBHOOK_URL = args.discord

    config = load_oci_config(args.profile)
    compute = OCICompute(config)
    sniper = Sniper(compute, dry_run=args.dry_run)
    sniper.run()


if __name__ == "__main__":
    main()
