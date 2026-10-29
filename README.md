# OCI ARM Instance Sniper 🎯

Script blindado para capturar automáticamente una instancia **VM.Standard.A1.Flex** (ARM) en Oracle Cloud Free Tier, rotando Availability Domains y degradando recursos de forma adaptativa.

---

## 📁 Estructura

```
oci-sniper/
├── oci_sniper.py                  ← Script local (PC encendido)
├── sniper.py                      ← Script para GitHub Actions
├── .github/workflows/sniper.yml   ← Workflow automático (cron cada 10 min)
└── README.md
```

---

## 🖥️ Opción 1: Ejecución local (`oci_sniper.py`)

### Requisitos
```bash
pip install oci requests
```

### Configurar credenciales OCI
1. En la consola de Oracle: **Perfil → User Settings → API Keys → Add API Key**
2. Descarga el `.pem` y copia el bloque de configuración
3. Crea `~/.oci/config` (Linux/macOS) o `C:\Users\<TuUsuario>\.oci\config` (Windows)
4. Apunta `key_file=` a la ruta de tu archivo `.pem`

### Configurar el script
Edita `oci_sniper.py` y cambia estos valores en la clase `SniperConfig`:
- `subnet_id` — **OBLIGATORIO**, el OCID de tu subnet
- `compartment_id`, `image_id` — si difieren de los predeterminados
- `ssh_public_key` — tu clave SSH pública
- `discord_webhook_url` — (opcional) para recibir alertas al móvil

### Ejecutar
```bash
# Normal
python oci_sniper.py

# Simulación (no envía peticiones)
python oci_sniper.py --dry-run

# Perfil OCI personalizado
python oci_sniper.py --profile MI_PERFIL

# Con notificación a Discord
python oci_sniper.py --discord-webhook "https://discord.com/api/webhooks/..."

# Con Telegram
python oci_sniper.py --telegram-token "123456:ABC..." --telegram-chat-id "987654321"
```

### Características
| Feature | Detalle |
|---|---|
| Rotación de ADs | AD-1 → AD-2 → AD-3 en ciclo infinito |
| Degradación adaptativa | 4 OCPUs/24GB → 2 OCPUs/12GB tras N rondas |
| Retroceso exponencial | Si recibe 429, espera 120s → 240s → 300s (tope) |
| Jitter aleatorio | ±10s en cada pausa para evitar patrones |
| Shutdown limpio | Ctrl+C guarda estadísticas antes de salir |
| Logs duales | Consola + archivo `oci_sniper.log` |
| Estadísticas | Se guardan en `oci_sniper_stats.json` |
| Notificaciones | Discord y/o Telegram al crear la instancia |
| LimitExceeded | Detecta si ya tienes ARM y para automáticamente |

---

## ☁️ Opción 2: GitHub Actions (`sniper.py`)

Para no tener el PC encendido. GitHub ejecuta el script cada 10 minutos gratis.

### 1. Crear repo privado en GitHub

### 2. Añadir Secrets
En **Settings → Secrets → Actions**, crea:

| Secret | Valor |
|---|---|
| `OCI_USER_OCID` | Tu User OCID |
| `OCI_TENANCY_OCID` | Tu Tenancy OCID |
| `OCI_REGION` | `us-ashburn-1` |
| `OCI_FINGERPRINT` | Fingerprint de la API Key |
| `OCI_KEY_FILE` | Contenido completo del `.pem` |
| `OCI_SUBNET_ID` | OCID de tu subnet |
| `OCI_IMAGE_ID` | *(opcional)* OCID de la imagen |
| `OCI_SSH_KEY` | *(opcional)* Tu clave SSH pública |
| `DISCORD_WEBHOOK_URL` | *(opcional)* Webhook de Discord |

### 3. Subir archivos
Sube `sniper.py` a la raíz y `.github/workflows/sniper.yml` al repo.

### 4. Listo
El cron se ejecuta cada 10 min. Puedes lanzarlo manualmente desde **Actions → OCI ARM Capacity Sniper → Run workflow**.

---

## ⚠️ Notas importantes

- **No es baneable**: Miles de personas usan scripts contra la API de OCI. Con 40-60s entre intentos estás dentro de los límites.
- **El subnet_id es obligatorio**: Si usaste un Stack de Terraform, encuéntralo en **Networking → Virtual Cloud Networks → tu VCN → Subnets**.
- **2.000 minutos/mes gratis** en GitHub Actions. A 10 min de intervalo, son ~4.320 ejecuciones/mes. Cada ejecución dura ~1 min, así que sobra de largo.
- **Desactiva el workflow** manualmente en cuanto se cree la instancia para no gastar minutos.
