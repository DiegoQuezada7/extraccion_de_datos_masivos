# ClickHouse · Extracción y Gestión de Datos Masivos

Repositorio grupal para la Etapa 3.

## Experimentos

- [Experimento 3 · Ingesta por lotes](Experimento%203/README.md)

## Preparación del entorno

## Requisitos

- Docker con Docker Compose y acceso a Docker desde la terminal.
- Python 3. El script usa la biblioteca estándar.
- `curl` y `unzip` para preparar el dataset. Se necesitan varios GB libres para el CSV, los lotes temporales y las tablas de prueba.

Ejecuta los comandos desde la raíz del repositorio.

### 1. Iniciar ClickHouse y crear la tabla de referencia

```bash
docker compose up -d
docker exec clickhouse-bigdata clickhouse-client --query "SELECT version()"
docker exec -i clickhouse-bigdata clickhouse-client < crear_tabla.sql
```

Si la consulta de versión falla mientras el contenedor arranca, espera unos segundos y repítela. El SQL crea `bigdata.chilecompra_2025`, que el script usa como plantilla para las tablas de prueba.

### 2. Preparar los datos

Se usaron los CSV de órdenes de compra de **febrero y marzo de 2025** del [portal de Datos Abiertos de ChileCompra](https://datos-abiertos.chilecompra.cl/descargas). Si ya tienes `chilecompra_feb_mar_2025.csv`, puedes omitir este paso.

```bash
curl --fail --location --output 2025-2.zip https://transparenciachc.blob.core.windows.net/oc-da/2025-2.zip
curl --fail --location --output 2025-3.zip https://transparenciachc.blob.core.windows.net/oc-da/2025-3.zip
(
  unzip -p 2025-2.zip '*2025-2.csv' &&
    unzip -p 2025-3.zip '*2025-3.csv'
) > chilecompra_feb_mar_2025.csv
wc -c chilecompra_feb_mar_2025.csv
```

La copia usada en el experimento tiene **1.273.854.320 bytes** y **777.199 filas**. El script espera un CSV UTF-8, separado por comas, sin cabecera y con las 79 columnas en el orden de `crear_tabla.sql`. Si el tamaño difiere, comprueba el contenido de los ZIP con `unzip -l` antes de comparar resultados.
