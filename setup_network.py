#!/usr/bin/env python3
"""
Crea la infraestructura de red en OCI usando la API REST directamente.
No requiere el SDK de OCI — usa requests + firma HTTP con cryptography.
"""

import base64
import datetime
import email.utils
import hashlib
import json
import os
import sys
import textwrap

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# ─── Configuración desde ~/.oci/config ───

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
            if in_profile and "=" in line:
                key, val = line.split("=", 1)
                config[key.strip()] = val.strip()

    # Cargar clave privada
    key_path = config.get("key_file", "").replace("\\\\", "\\")
    if not os.path.exists(key_path):
        print(f"[!] Clave privada no encontrada: {key_path}")
        sys.exit(1)

    with open(key_path, "rb") as f:
        config["_private_key"] = serialization.load_pem_private_key(f.read(), password=None)

    return config


# ─── Firma HTTP para la API de OCI ───

class OCISigner:
    def __init__(self, config):
        self.api_key = f"{config['tenancy']}/{config['user']}/{config['fingerprint']}"
        self.private_key = config["_private_key"]

    def sign(self, method, url, body=None):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query

        now = email.utils.formatdate(usegmt=True)
        headers = {
            "date": now,
            "host": host,
            "(request-target)": f"{method.lower()} {path}",
        }

        signing_headers = ["(request-target)", "date", "host"]
        request_headers = {"date": now}

        if body is not None:
            body_bytes = body.encode("utf-8") if isinstance(body, str) else body
            body_hash = base64.b64encode(hashlib.sha256(body_bytes).digest()).decode()
            content_length = str(len(body_bytes))
            content_type = "application/json"

            headers["content-length"] = content_length
            headers["content-type"] = content_type
            headers["x-content-sha256"] = body_hash

            signing_headers += ["content-type", "content-length", "x-content-sha256"]
            request_headers["content-type"] = content_type
            request_headers["content-length"] = content_length
            request_headers["x-content-sha256"] = body_hash

        signing_string = "\n".join(f"{h}: {headers[h]}" for h in signing_headers)
        signature = base64.b64encode(
            self.private_key.sign(
                signing_string.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        ).decode()

        auth_header = (
            f'Signature version="1",'
            f'keyId="{self.api_key}",'
            f'algorithm="rsa-sha256",'
            f'headers="{" ".join(signing_headers)}",'
            f'signature="{signature}"'
        )
        request_headers["authorization"] = auth_header
        return request_headers


# ─── Cliente REST de OCI ───

class OCIClient:
    def __init__(self, config):
        self.config = config
        self.signer = OCISigner(config)
        self.region = config["region"]
        self.base_url = f"https://iaas.{self.region}.oraclecloud.com/20160918"

    def _request(self, method, url, body=None):
        body_str = json.dumps(body) if body else None
        headers = self.signer.sign(method, url, body_str)
        resp = requests.request(method, url, headers=headers, data=body_str, timeout=30)
        return resp

    def get(self, path, params=None):
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return self._request("GET", url)

    def post(self, path, body):
        url = f"{self.base_url}{path}"
        return self._request("POST", url, body)

    def put(self, path, body):
        url = f"{self.base_url}{path}"
        return self._request("PUT", url, body)


# ─── Main ───

VCN_ID = "ocid1.vcn.oc1.iad.amaaaaaatfil2vyanhlqhnbn7ingriu2vxrkb27cjkm7rx56faqerudnsq5a"
COMPARTMENT_ID = "ocid1.tenancy.oc1..aaaaaaaafagv5od7qmmed2xljniofsbohtzuejd465edqcgm5ccylet6bcxq"


def main():
    config = load_oci_config()
    client = OCIClient(config)

    print("=" * 55)
    print(" Creando infraestructura de red OCI (API REST)")
    print("=" * 55)

    # 1. Internet Gateway
    print("\n[1/4] Creando Internet Gateway...")
    # Verificar si ya existe
    resp = client.get("/internetGateways", {"compartmentId": COMPARTMENT_ID, "vcnId": VCN_ID})
    if resp.status_code == 200:
        existing = [g for g in resp.json() if g.get("lifecycleState") == "AVAILABLE"]
        if existing:
            igw_id = existing[0]["id"]
            print(f"  ℹ️  Ya existe: {igw_id[:60]}...")
        else:
            resp = client.post("/internetGateways", {
                "compartmentId": COMPARTMENT_ID,
                "vcnId": VCN_ID,
                "displayName": "igw-main",
                "isEnabled": True,
            })
            if resp.status_code in (200, 201):
                igw_id = resp.json()["id"]
                print(f"  ✅ Creado: {igw_id[:60]}...")
            else:
                print(f"  ❌ Error {resp.status_code}: {resp.text}")
                sys.exit(1)
    else:
        print(f"  ❌ Error listando IGWs: {resp.status_code} {resp.text}")
        sys.exit(1)

    # 2. Route Table — obtener default y añadir ruta
    print("\n[2/4] Configurando Route Table...")
    resp = client.get(f"/vcns/{VCN_ID}")
    if resp.status_code != 200:
        print(f"  ❌ Error obteniendo VCN: {resp.text}")
        sys.exit(1)

    vcn_data = resp.json()
    rt_id = vcn_data["defaultRouteTableId"]
    sl_id = vcn_data["defaultSecurityListId"]

    resp = client.get(f"/routeTables/{rt_id}")
    rt_data = resp.json()
    existing_rules = rt_data.get("routeRules", [])
    has_default = any(r.get("destination") == "0.0.0.0/0" for r in existing_rules)

    if not has_default:
        new_rules = existing_rules + [{
            "destination": "0.0.0.0/0",
            "destinationType": "CIDR_BLOCK",
            "networkEntityId": igw_id,
        }]
        resp = client.put(f"/routeTables/{rt_id}", {"routeRules": new_rules})
        if resp.status_code == 200:
            print(f"  ✅ Ruta 0.0.0.0/0 → IGW añadida")
        else:
            print(f"  ❌ Error: {resp.text}")
            sys.exit(1)
    else:
        print(f"  ℹ️  Ruta por defecto ya existe")

    # 3. Security List — abrir puertos 22 y 25565
    print("\n[3/4] Configurando Security List (puertos 22, 25565)...")
    resp = client.get(f"/securityLists/{sl_id}")
    sl_data = resp.json()
    ingress = sl_data.get("ingressSecurityRules", [])
    egress = sl_data.get("egressSecurityRules", [])

    existing_ports = set()
    for rule in ingress:
        tcp = rule.get("tcpOptions", {})
        dp = tcp.get("destinationPortRange", {})
        if dp.get("min"):
            existing_ports.add(dp["min"])

    needed = {22: "SSH", 25565: "Minecraft"}
    new_ingress = list(ingress)

    for port, desc in needed.items():
        if port not in existing_ports:
            new_ingress.append({
                "protocol": "6",
                "source": "0.0.0.0/0",
                "sourceType": "CIDR_BLOCK",
                "tcpOptions": {
                    "destinationPortRange": {"min": port, "max": port}
                },
                "description": f"Puerto {port} ({desc})",
            })
            print(f"  ✅ Puerto {port} ({desc}) abierto")
        else:
            print(f"  ℹ️  Puerto {port} ya abierto")

    resp = client.put(f"/securityLists/{sl_id}", {
        "ingressSecurityRules": new_ingress,
        "egressSecurityRules": egress,
    })
    if resp.status_code == 200:
        print(f"  ✅ Security List actualizada")
    else:
        print(f"  ❌ Error: {resp.text}")
        sys.exit(1)

    # 4. Subnet pública
    print("\n[4/4] Creando Subnet pública...")
    resp = client.get("/subnets", {"compartmentId": COMPARTMENT_ID, "vcnId": VCN_ID})
    if resp.status_code == 200:
        existing_subs = [s for s in resp.json() if s.get("lifecycleState") == "AVAILABLE"]
        if existing_subs:
            subnet_id = existing_subs[0]["id"]
            print(f"  ℹ️  Ya existe: {subnet_id}")
        else:
            resp = client.post("/subnets", {
                "compartmentId": COMPARTMENT_ID,
                "vcnId": VCN_ID,
                "displayName": "public-subnet",
                "cidrBlock": "10.0.0.0/24",
                "routeTableId": rt_id,
                "securityListIds": [sl_id],
                "prohibitPublicIpOnVnic": False,
                "dnsLabel": "pubsub",
            })
            if resp.status_code in (200, 201):
                subnet_id = resp.json()["id"]
                print(f"  ✅ Subnet creada: {subnet_id}")
            else:
                print(f"  ❌ Error: {resp.status_code} {resp.text}")
                sys.exit(1)
    else:
        print(f"  ❌ Error listando subnets: {resp.text}")
        sys.exit(1)

    print(f"\n{'=' * 55}")
    print(f" ✅ RED LISTA")
    print(f"{'=' * 55}")
    print(f"  SUBNET_ID = {subnet_id}")
    print(f"{'=' * 55}")

    # Guardar para uso posterior
    with open("subnet_id.txt", "w") as f:
        f.write(subnet_id)
    print(f"\n  Guardado en subnet_id.txt")


if __name__ == "__main__":
    main()
