# func-democlonefiles

Azure Function (Python v2) que copia selectivamente blobs entre Storage Accounts, preservando la estructura de carpetas por fecha.

## Descripción

Esta función se activa mediante un **Blob Trigger** cuando un archivo nuevo llega al container `from` del Storage Account origen. Evalúa el nombre del archivo contra una lista de prefixes permitidos y, si coincide, lo copia al container `togcp` en un Storage Account destino manteniendo la estructura `año/mes/día`.

## Arquitectura

```
┌─────────────────────────┐         ┌──────────────────────────┐
│  Storage Account Origen │         │  Storage Account Destino │
│                         │         │                          │
│  container: from        │         │  container: togcp        │
│  └── {year}/{month}/{day}│ ──────▶│  └── {year}/{month}/{day}│
│      └── archivo.csv    │  Copy   │      └── archivo.csv     │
└─────────────────────────┘         └──────────────────────────┘
              │
              │ Blob Trigger
              ▼
┌─────────────────────────┐
│    Azure Function App   │
│  (Consumption Plan)     │
│                         │
│  - Filtra por prefix    │
│  - Preserva estructura  │
│  - Cross-storage copy   │
└─────────────────────────┘
```

## Comportamiento

1. Un proceso externo deposita archivos en `from/{year}/{month}/{day}/{filename}`
2. El Blob Trigger detecta el nuevo archivo
3. La función evalúa si el nombre del archivo comienza con un prefix permitido
4. Si coincide, copia el archivo al Storage Account destino preservando la ruta
5. Si no coincide, lo ignora y registra un log de skip

### Prefixes permitidos

| Prefix   | Ejemplo                          |
|----------|----------------------------------|
| `assoc`  | `assoc_clients_2024.csv`         |
| `scan`   | `scan_vulnerabilities.csv`       |
| `report` | `report_monthly_sales.xlsx`      |

Archivos que no comiencen con estos prefixes son ignorados.

### Ejemplo de flujo

```
Origen:  from/2026/07/23/assoc_data.csv     → Destino: togcp/2026/07/23/assoc_data.csv  ✅
Origen:  from/2026/07/23/scan_ports.log     → Destino: togcp/2026/07/23/scan_ports.log  ✅
Origen:  from/2026/07/23/report_q3.pdf      → Destino: togcp/2026/07/23/report_q3.pdf   ✅
Origen:  from/2026/07/23/invoice_001.csv    → Ignorado (prefix no válido)               ❌
```

## Estructura del proyecto

```
.
├── .gitignore             # Excluye secrets y artefactos del repositorio
├── function_app.py        # Código de la función (Python v2 model)
├── host.json              # Configuración del runtime
├── requirements.txt       # Dependencias Python
├── local.settings.json    # Variables de entorno locales (no commitear con secrets)
└── README.md
```

## Requisitos previos

- Python 3.14+
- Azure CLI (`az`) autenticado
- [Azure Functions Core Tools](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local) (para desarrollo local)
- Subscription de Azure con permisos para crear recursos
- Dos Storage Accounts (origen y destino)

### Permisos requeridos

El usuario que ejecuta el despliegue necesita los siguientes roles en el Resource Group:

| Rol | Propósito |
|-----|-----------|
| `Contributor` | Crear Function App, App Service Plan y Storage Accounts |
| `Storage Account Contributor` | Obtener connection strings y crear containers |
| `Storage Blob Data Contributor` | (Opcional) Subir blobs de prueba con `--auth-mode login` |

> Si la organización tiene Azure Policies (ej: enforce HTTPS), asegurarse de incluir `--https-only true` en la creación de la Function App.

## Configuración

### Variables de entorno (App Settings)

| Variable              | Descripción                                              | Default  |
|-----------------------|----------------------------------------------------------|----------|
| `AzureWebJobsStorage` | Connection string del Storage Account **origen**        | —        |
| `DestinationStorage`  | Connection string del Storage Account **destino**        | —        |
| `SOURCE_CONTAINER`    | Nombre del container origen                              | `from`   |
| `DEST_CONTAINER`      | Nombre del container destino                             | `togcp`  |
| `FUNCTIONS_WORKER_RUNTIME` | Runtime del worker                                  | `python` |
| `FUNCTIONS_EXTENSION_VERSION` | Versión del runtime de Functions                 | `~4`     |

> **Nota sobre `SOURCE_CONTAINER`:** Cambiar esta variable requiere reiniciar la Function App para que el blob trigger apunte al nuevo container (el path se resuelve al inicio del proceso).

### Containers requeridos

| Storage Account | Container | Propósito                    |
|----------------|-----------|------------------------------|
| Origen         | `from`    | Recepción de archivos nuevos |
| Destino        | `togcp`   | Destino de archivos copiados (se crea automáticamente si no existe) |

## Despliegue

### 1. Crear infraestructura

```bash
# Variables
RG="<resource-group>"
LOCATION="<region>"
SOURCE_STORAGE="<source-storage-account>"
DEST_STORAGE="<dest-storage-account>"
FUNC_APP="<function-app-name>"

# Storage Account origen (si no existe)
az storage account create --name $SOURCE_STORAGE --resource-group $RG --location $LOCATION --sku Standard_LRS --kind StorageV2

# Storage Account destino
az storage account create --name $DEST_STORAGE --resource-group $RG --location $LOCATION --sku Standard_LRS --kind StorageV2

# Container origen
az storage container create --name from --account-name $SOURCE_STORAGE --auth-mode login

# Container destino (opcional, la función lo crea automáticamente)
az storage container create --name togcp --account-name $DEST_STORAGE --auth-mode login
```

### 2. Crear Function App

```bash
az functionapp create \
  --name $FUNC_APP \
  --resource-group $RG \
  --storage-account $SOURCE_STORAGE \
  --consumption-plan-location $LOCATION \
  --runtime python \
  --runtime-version 3.14 \
  --functions-version 4 \
  --os-type Linux \
  --https-only true
```

> **Nota sobre Flex Consumption:** Linux Consumption Plan alcanza End of Life el 30 de septiembre de 2028.
> La migración a Flex Consumption requiere usar Event Grid como source para el blob trigger
> (`source="EventGrid"`) y crear un Event Grid subscription. Consultar [documentación de migración](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan).

### 3. Configurar App Settings

```bash
# Obtener connection strings
SOURCE_CONN=$(az storage account show-connection-string --name $SOURCE_STORAGE --resource-group $RG -o tsv)
DEST_CONN=$(az storage account show-connection-string --name $DEST_STORAGE --resource-group $RG -o tsv)

# Configurar
az functionapp config appsettings set \
  --name $FUNC_APP \
  --resource-group $RG \
  --settings \
    "AzureWebJobsStorage=$SOURCE_CONN" \
    "DestinationStorage=$DEST_CONN" \
    "SOURCE_CONTAINER=from" \
    "DEST_CONTAINER=togcp"
```

### 4. Deploy

```bash
# Crear zip (excluir archivos innecesarios)
zip -r deploy.zip . -x "local.settings.json" -x "__pycache__/*" -x ".venv/*" -x ".git/*" -x ".gitignore" -x "README.md"

# Deploy con build remoto (instala dependencias de requirements.txt en Azure)
az functionapp deployment source config-zip \
  --name $FUNC_APP \
  --resource-group $RG \
  --src deploy.zip \
  --build-remote true

# Restart para que el runtime cargue la función
az functionapp restart --name $FUNC_APP --resource-group $RG
```

> **Importante:** El restart después del deploy es obligatorio en Linux Consumption Plan. Sin él, la función puede no registrarse hasta el siguiente ciclo de polling del runtime.

### 5. Verificar

```bash
# Confirmar que la función está registrada
az functionapp function list --name $FUNC_APP --resource-group $RG -o table
```

Si la función no aparece, esperar 30 segundos y reintentar. En caso de persistir, verificar la sección de Troubleshooting.

## Desarrollo local

```bash
# Instalar dependencias
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configurar local.settings.json con connection strings reales

# Ejecutar
func start
```

> Requiere [Azure Functions Core Tools](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local) instalado.

## Consideraciones técnicas

### Blob Trigger y archivos existentes

- La función **solo procesa archivos nuevos** a partir del momento del deploy.
- Archivos preexistentes en el container no disparan el trigger.
- El runtime mantiene receipts en el container `azure-webjobs-hosts` para trackear qué blobs ya fueron procesados.

### Latencia del Blob Trigger

En Consumption Plan (Linux), el blob trigger usa polling (LogsAndContainerScan). La latencia puede ser:
- **~5-30 segundos** si la función está "caliente" (warm)
- **Hasta 10 minutos** en cold start

Para menor latencia, considerar [Event Grid trigger](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-storage-blob-trigger?tabs=python-v2%2Cisolated-process%2Cnodejs-v4&pivots=programming-language-python#event-grid-trigger) como alternativa.

### Filtro case-insensitive

El filtro de prefixes evalúa en minúsculas (`filename.lower()`), por lo que `ASSOC_data.csv` y `assoc_data.csv` son tratados igual.

### Overwrite

Si un archivo con el mismo nombre se sube nuevamente al origen, se sobreescribe en el destino (`overwrite=True`).

## Personalización

### Modificar prefixes permitidos

Editar la constante `ALLOWED_PREFIXES` en `function_app.py`:

```python
ALLOWED_PREFIXES = ["assoc", "scan", "report"]
```

### Cambiar container origen

Configurar via App Settings y reiniciar (no requiere cambios en el código):

```bash
az functionapp config appsettings set \
  --name $FUNC_APP \
  --resource-group $RG \
  --settings "SOURCE_CONTAINER=mi-origen"

# Reiniciar para que el trigger apunte al nuevo container
az functionapp restart --name $FUNC_APP --resource-group $RG
```

### Cambiar container destino

Configurar via App Settings (no requiere cambios en el código ni restart):

```bash
az functionapp config appsettings set \
  --name $FUNC_APP \
  --resource-group $RG \
  --settings "DEST_CONTAINER=mi-destino"
```

### Cambiar a Move (mover en vez de copiar)

Agregar después del upload en `function_app.py`:

```python
# Delete source blob after copy
source_connection_string = os.environ.get("AzureWebJobsStorage")
source_blob_service_client = BlobServiceClient.from_connection_string(source_connection_string)
source_container_client = source_blob_service_client.get_container_client("from")
source_blob_client = source_container_client.get_blob_client(blob_name)
source_blob_client.delete_blob()
```

Donde `blob_name` es la variable con el path relativo del archivo (ej: `2026/07/24/assoc_data.csv`).

## Troubleshooting

### La función no se registra después del deploy

1. Ejecutar restart: `az functionapp restart --name $FUNC_APP --resource-group $RG`
2. Esperar 30 segundos y verificar con `az functionapp function list`
3. Si persiste, verificar los logs:
   ```bash
   az monitor app-insights query --app $FUNC_APP --resource-group $RG \
     --analytics-query "traces | where message contains 'function' | order by timestamp desc | take 5"
   ```

### El blob trigger no se dispara

1. Verificar que `AzureWebJobsStorage` apunta al Storage Account correcto
2. Verificar que el archivo se sube con la estructura `from/{year}/{month}/{day}/{filename}`
3. Revisar si el `blobscaninfo` existe:
   ```bash
   az storage blob list --account-name <storage> --container-name azure-webjobs-hosts \
     --prefix "blobscaninfo/" --auth-mode key --query "[].name" -o tsv
   ```
4. Si el trigger quedó "pegado", eliminar el scanInfo y reiniciar:
   ```bash
   az storage blob delete --account-name <storage> --container-name azure-webjobs-hosts \
     --name "blobscaninfo/<function-app-name>/<storage-name>/from/scanInfo" --auth-mode key
   az functionapp restart --name $FUNC_APP --resource-group $RG
   ```

### Error de conexión al Storage Account destino

- Verificar que `DestinationStorage` está configurado correctamente
- Confirmar que el connection string incluye la key válida:
  ```bash
  az functionapp config appsettings list --name $FUNC_APP --resource-group $RG \
    --query "[?name=='DestinationStorage'].value" -o tsv | grep -o "AccountName=[^;]*"
  ```

### Cold start lento (hasta 10 minutos)

Esto es normal en Linux Consumption Plan. Para reducir el cold start:
- Considerar migrar a un plan Premium (Always Ready instances)
- Usar Event Grid trigger en vez de polling

## Stack

- **Runtime**: Azure Functions v4
- **Lenguaje**: Python 3.14 (v2 programming model)
- **Plan**: Consumption (Linux)
- **SDK**: azure-storage-blob 12.19+
- **Extension Bundle**: Microsoft.Azure.Functions.ExtensionBundle 4.x
