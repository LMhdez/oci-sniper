#!/usr/bin/env python3
"""
sniper.py — Versión ligera para GitHub Actions
================================================
Diseñado para ejecutarse en un runner de GitHub Actions con las credenciales
inyectadas como variables de entorno desde los Secrets del repositorio.

Cada ejecución del workflow intenta una ronda completa (3 ADs × 2 perfiles).
Si no hay capacidad, sale con código 1 para que el cron del workflow reintente.
"""

import json
import os
import sys
import time

try:
    import oci
except ImportError:
    print("[!] SDK no encontrado. ¿Falta 'pip install oci' en el workflow?")
    sys.exit(2)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ─── Configuración desde variables de entorno (GitHub Secrets) ───

def env_required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"[!] Variable de entorno requerida no definida: {name}")
        sys.exit(2)
    return val

OCI_CONFIG = {
    "user": env_required("OCI_USER_OCID"),
    "key_content": env_required("OCI_KEY_FILE"),
    "fingerprint": env_required("OCI_FINGERPRINT"),
    "tenancy": env_required("OCI_TENANCY_OCID"),
    "region": env_required("OCI_REGION"),
}

COMPARTMENT_ID = os.environ.get("OCI_COMPARTMENT_ID", OCI_CONFIG["tenancy"])
SUBNET_ID = env_required("OCI_SUBNET_ID")
IMAGE_ID = os.environ.get(
    "OCI_IMAGE_ID",
    "ocid1.image.oc1.iad.aaaaaaaa6o52ajhkewa2syfadrxel5b7tfwi5qdm45gl4ykwbqut25tvdxrq",
)

SSH_KEY = os.environ.get(
    "OCI_SSH_KEY",
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCrKlvwOnFzODuU0VwdC72QzyYKFG2i"
    "QutigpwyWDAl6NH8qo+VYod04OF10uMxR5MSX+u0bJIOwggxklPA+YfLFdOTSrIBuvxP"
    "rhOAw+hbFwhtfLKri+8vuFby3coiPv3f4fGM80vYvqi0LhbGutPrAv2J6QpBat9d1wG6"
    "ys5LuEGt8/A8QHI1c4yTLqMkkZo/dKR7V7bjUTMe0etGGecLywHW74fcqEGBi6Bi1nqQ"
    "T/iq4w8sHImGINdBcMES2WibTjOsHZDezCgdpBub+ns4tQHC6bWb+6NoJOnxamOoWF5s"
    "NiqoUoygydiid5g+E8Qu+WuomAw0rFk6o0IKCexz ssh-key-2026-10-29",
)

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

ADS = [
    "CqwQ:US-ASHBURN-AD-1",
    "CqwQ:US-ASHBURN-AD-2",
    "CqwQ:US-ASHBURN-AD-3",
]

PROFILES = [
    {"ocpus": 4.0, "memory_in_gbs": 24.0, "label": "4 OCPUs / 24 GB"},
    {"ocpus": 2.0, "memory_in_gbs": 12.0, "label": "2 OCPUs / 12 GB"},
]

INSTANCE_NAME = "mc-server-production"
BOOT_VOL_GB = 200
PAUSE_BETWEEN_ADS = 10  # segundos entre cada intento de AD


# ─── Notificación ───

def notify_discord(msg: str):
    if DISCORD_WEBHOOK and HAS_REQUESTS:
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
        except Exception:
            pass


# ─── Lógica principal ───

def main():
    compute = oci.core.ComputeClient(OCI_CONFIG)

    total_attempts = 0

    for profile in PROFILES:
        print(f"\n{'─' * 50}")
        print(f"Perfil: {profile['label']}")
        print(f"{'─' * 50}")

        for ad in ADS:
            ad_short = ad.split(":")[-1]
            total_attempts += 1
            print(f"  [{total_attempts}] Probando {ad_short}...", end=" ", flush=True)

            launch_details = oci.core.models.LaunchInstanceDetails(
                display_name=INSTANCE_NAME,
                compartment_id=COMPARTMENT_ID,
                availability_domain=ad,
                shape="VM.Standard.A1.Flex",
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=profile["ocpus"],
                    memory_in_gbs=profile["memory_in_gbs"],
                ),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    image_id=IMAGE_ID,
                    boot_volume_size_in_gbs=BOOT_VOL_GB,
                    boot_volume_vpus_per_gb=10,
                ),
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    subnet_id=SUBNET_ID,
                    assign_public_ip=True,
                    assign_private_dns_record=True,
                ),
                metadata={"ssh_authorized_keys": SSH_KEY},
            )

            try:
                instance = compute.launch_instance(launch_details).data
                print(f"✅ ¡ÉXITO!")
                print(f"\n{'=' * 50}")
                print(f"  🎉 Instancia creada")
                print(f"  ID:    {instance.id}")
                print(f"  AD:    {ad_short}")
                print(f"  Shape: {profile['label']}")
                print(f"  State: {instance.lifecycle_state}")
                print(f"{'=' * 50}")

                notify_discord(
                    f"🚀 **Servidor OCI creado**\n"
                    f"• AD: `{ad_short}`\n"
                    f"• Config: `{profile['label']}`\n"
                    f"• ID: `{instance.id}`"
                )

                # Guardar resultado como output de GitHub Actions
                github_output = os.environ.get("GITHUB_OUTPUT")
                if github_output:
                    with open(github_output, "a") as f:
                        f.write(f"instance_id={instance.id}\n")
                        f.write(f"status=success\n")

                sys.exit(0)

            except oci.exceptions.ServiceError as e:
                if "capacity" in e.message.lower() or "OutOfHostCapacity" in str(e.code):
                    print(f"Sin capacidad")
                elif e.status == 429:
                    print(f"⚠ Rate limited (429) — pausando 90s")
                    time.sleep(90)
                elif e.status == 400 and "LimitExceeded" in str(e.code):
                    print(f"❌ LimitExceeded: {e.message}")
                    print("   → Ya tienes una instancia ARM o superaste el límite gratuito.")
                    notify_discord(f"❌ *LimitExceeded*: {e.message}")
                    sys.exit(2)  # No reintentar
                else:
                    print(f"⚠ Error {e.status}: {e.message}")

            except Exception as e:
                print(f"⚠ Error de red: {e}")

            time.sleep(PAUSE_BETWEEN_ADS)

    print(f"\n[·] Sin capacidad en ningún AD/perfil. El workflow reintentará en el próximo cron.")
    sys.exit(1)


if __name__ == "__main__":
    main()
