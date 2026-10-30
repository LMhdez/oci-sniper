#!/usr/bin/env python3
import os
import sys
import time
import oci
import requests

# ─── Configuración desde GitHub Secrets ───
def env_required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"[!] Variable faltante: {name}")
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
IMAGE_ID = "ocid1.image.oc1.iad.aaaaaaaa6o52ajhkewa2syfadrxel5b7tfwi5qdm45gl4ykwbqut25tvdxrq"
SSH_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCrKlvwOnFzODuU0VwdC72QzyYKFG2iQutigpwyWDAl6NH8qo+VYod04OF10uMxR5MSX+u0bJIOwggxklPA+YfLFdOTSrIBuvxPrhOAw+hbFwhtfLKri+8vuFby3coiPv3f4fGM80vYvqi0LhbGutPrAv2J6QpBat9d1wG6ys5LuEGt8/A8QHI1c4yTLqMkkZo/dKR7V7bjUTMe0etGGecLywHW74fcqEGBi6Bi1nqQT/iq4w8sHImGINdBcMES2WibTjOsHZDezCgdpBub+ns4tQHC6bWb+6NoJOnxamOoWF5sNiqoUoygydiid5g+E8Qu+WuomAw0rFk6o0IKCexz ssh-key-2026-10-29"

ADS = ["CqwQ:US-ASHBURN-AD-1", "CqwQ:US-ASHBURN-AD-2", "CqwQ:US-ASHBURN-AD-3"]
PROFILES = [
    {"ocpus": 4.0, "memory_in_gbs": 24.0, "label": "4 OCPUs / 24 GB"},
    {"ocpus": 2.0, "memory_in_gbs": 12.0, "label": "2 OCPUs / 12 GB"}
]

def main():
    compute = oci.core.ComputeClient(OCI_CONFIG)
    start_time = time.time()
    
    # 8.5 minutos de bucle constante (dejamos 90s de margen para que el runner de GitHub no colapse)
    max_duration = 480 
    total_attempts = 0

    print(f"[*] Iniciando cacería ininterrumpida en la nube (Duración: 8.5 min)...")

    while time.time() - start_time < max_duration:
        for profile in PROFILES:
            for ad in ADS:
                total_attempts += 1
                ad_short = ad.split(":")[-1]
                sys.stdout.write(f"\r[{total_attempts}] Probando {ad_short} con {profile['label']}... ")
                sys.stdout.flush()

                launch_details = oci.core.models.LaunchInstanceDetails(
                    display_name="mc-server-production",
                    compartment_id=COMPARTMENT_ID,
                    availability_domain=ad,
                    shape="VM.Standard.A1.Flex",
                    shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                        ocpus=profile["ocpus"], memory_in_gbs=profile["memory_in_gbs"]
                    ),
                    source_details=oci.core.models.InstanceSourceViaImageDetails(
                        image_id=IMAGE_ID, boot_volume_size_in_gbs=200, boot_volume_vpus_per_gb=10
                    ),
                    create_vnic_details=oci.core.models.CreateVnicDetails(
                        subnet_id=SUBNET_ID, assign_public_ip=True, assign_private_dns_record=True
                    ),
                    metadata={"ssh_authorized_keys": SSH_KEY}
                )

                try:
                    instance = compute.launch_instance(launch_details).data
                    print(f"\n✅ ¡ÉXITO! Instancia {instance.id} creada en {ad_short}")
                    sys.exit(0)
                except oci.exceptions.ServiceError as e:
                    if "capacity" in e.message.lower() or "OutOfHostCapacity" in str(e.code):
                        pass
                    elif e.status == 429:
                        print(f"\n⚠ Rate limited (429) — pausando 90s")
                        time.sleep(90)
                    elif e.status == 400 and "LimitExceeded" in str(e.code):
                        print("\n❌ Límite superado (¿ya tienes máquina?). Saliendo.")
                        sys.exit(2)
                except Exception:
                    pass
                
                # Pausa breve igual que en local
                time.sleep(15)

    print("\n[·] Tiempo de ronda agotado. Saliendo limpiamente para el siguiente cron.")
    sys.exit(0)

if __name__ == "__main__":
    main()
