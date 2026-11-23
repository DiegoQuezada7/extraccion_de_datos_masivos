# ClickHouse — Ingesta por lotes

Experimento de la Etapa 3 de Extracción y Gestión de Datos Masivos. Se compara cómo cambia el tiempo de carga al variar la cantidad de filas por `INSERT` en una tabla `MergeTree`.

## Requisitos

- Docker con Docker Compose y acceso a Docker desde la terminal.
- Python 3. El script usa la biblioteca estándar.
- `curl` y `unzip` para preparar el dataset. Se necesitan varios GB libres para el CSV, los lotes temporales y las tablas de prueba.

Ejecuta los comandos desde la raíz del repositorio.

## 1. Iniciar ClickHouse y crear la tabla de referencia

```bash
docker compose up -d
docker exec clickhouse-bigdata clickhouse-client --query "SELECT version()"
docker exec -i clickhouse-bigdata clickhouse-client < crear_tabla.sql
```

Si la consulta de versión falla mientras el contenedor arranca, espera unos segundos y repítela. El SQL crea `bigdata.chilecompra_2025`, que el script usa como plantilla para las tablas de prueba.

## 2. Preparar los datos

Se usaron los CSV de órdenes de compra de **febrero y marzo de 2025** del [portal de Datos Abiertos de ChileCompra](https://datos-abiertos.chilecompra.cl/descargas). Si ya tienes `chilecompra_feb_mar_2025.csv`, puedes pasar al siguiente paso.

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

## 3. Ejecutar el experimento

Corrida completa, con tres repeticiones para cada tamaño de lote:

```bash
python3 benchmark_insert_csv.py chilecompra_feb_mar_2025.csv --filas-esperadas 777199
```

Demostración en vivo, con una corrida para cada uno de los tres tamaños:

```bash
python3 benchmark_insert_csv.py chilecompra_feb_mar_2025.csv --filas-esperadas 777199 --repeticiones 1
```

El script prepara los lotes antes de cronometrar. Para cada corrida crea una tabla vacía, pausa las fusiones de esa tabla y realiza los `INSERT`. Mide el tiempo desde que comienza a abrir y enviar los lotes hasta que termina la última inserción. Luego cuenta las partes activas, verifica las filas cargadas, reanuda las fusiones y elimina la tabla de prueba.

## Resultados de referencia

| Filas por `INSERT` | Número de `INSERT` | Tiempo mediano | Filas/s (mediana) | Partes activas |
|---:|---:|---:|---:|---:|
| 1.000 | 778 | 76,517 s | 10.157,26 | 778 |
| 10.000 | 78 | 17,977 s | 43.232,85 | 78 |
| 100.000 | 8 | 6,532 s | 118.978,10 | 8 |

Las nueve mediciones originales están en [resultados_insert_csv_20261123_162046_bc9fc606.csv](resultados_insert_csv_20261123_162046_bc9fc606.csv). Cada nueva ejecución genera su propio `resultados_insert_csv_*.csv`.
