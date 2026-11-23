# ClickHouse — Ingesta por lotes

Experimento de la Etapa 3 de Extracción y Gestión de Datos Masivos. Se compara cómo cambia el tiempo de carga al variar la cantidad de filas por `INSERT` en una tabla `MergeTree`.

Prepara ClickHouse y el CSV siguiendo las [instrucciones de la raíz](../README.md). Ejecuta los comandos siguientes desde la raíz del repositorio.

## Ejecutar el experimento

Corrida completa, con tres repeticiones para cada tamaño de lote:

```bash
python3 "Experimento 3/benchmark_insert_csv.py" chilecompra_feb_mar_2025.csv --filas-esperadas 777199
```

Demostración en vivo, con una corrida para cada uno de los tres tamaños:

```bash
python3 "Experimento 3/benchmark_insert_csv.py" chilecompra_feb_mar_2025.csv --filas-esperadas 777199 --repeticiones 1
```

El script prepara los lotes antes de cronometrar. Para cada corrida crea una tabla vacía, pausa las fusiones de esa tabla y realiza los `INSERT`. Mide el tiempo desde que comienza a abrir y enviar los lotes hasta que termina la última inserción. Luego cuenta las partes activas, verifica las filas cargadas, reanuda las fusiones y elimina la tabla de prueba.

## Resultados de referencia

| Filas por `INSERT` | Número de `INSERT` | Tiempo mediano | Filas/s (mediana) | Partes activas |
|---:|---:|---:|---:|---:|
| 1.000 | 778 | 76,517 s | 10.157,26 | 778 |
| 10.000 | 78 | 17,977 s | 43.232,85 | 78 |
| 100.000 | 8 | 6,532 s | 118.978,10 | 8 |

Las nueve mediciones originales están en [resultados_insert_csv_20261123_162046_bc9fc606.csv](resultados_insert_csv_20261123_162046_bc9fc606.csv). Cada nueva ejecución genera su propio `resultados_insert_csv_*.csv`.
