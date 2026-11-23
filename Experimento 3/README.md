# ClickHouse — Ingesta por lotes

**Responsable:** Diego Quezada.

## Pregunta e hipótesis

¿Cómo cambia el rendimiento de carga y la cantidad de partes activas al variar las filas por `INSERT`?

**Hipótesis.** Para el mismo volumen de datos, los lotes más grandes requerirán menos operaciones de inserción, reducirán el tiempo total y dejarán menos partes activas.

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

## Diseño experimental

- **Variable independiente:** 1.000, 10.000 o 100.000 filas por `INSERT`, con tres corridas por tamaño.
- **Métricas:** tiempo total de carga, filas por segundo, número de inserciones y partes activas.
- **Controles:** las mismas 777.199 filas de ChileCompra de febrero y marzo de 2025, el mismo motor y esquema, el mismo entorno Docker y una tabla destino vacía en cada corrida. Las inserciones son síncronas.

El script prepara los lotes antes de cronometrar. Para cada corrida crea una tabla vacía, pausa las fusiones de esa tabla y realiza los `INSERT`. Mide el tiempo desde que comienza a abrir y enviar los lotes hasta que termina la última inserción. Luego cuenta las partes activas, verifica las filas cargadas, reanuda las fusiones y elimina la tabla de prueba.

## Resultados de referencia

| Filas por `INSERT` | Número de `INSERT` | Tiempo mediano | Filas/s (mediana) | Partes activas |
|---:|---:|---:|---:|---:|
| 1.000 | 778 | 76,517 s | 10.157,26 | 778 |
| 10.000 | 78 | 17,977 s | 43.232,85 | 78 |
| 100.000 | 8 | 6,532 s | 118.978,10 | 8 |

Las nueve mediciones originales están en [resultados_insert_csv_20261123_162046_bc9fc606.csv](resultados_insert_csv_20261123_162046_bc9fc606.csv). Cada ejecución completa genera su propio `resultados_insert_csv_*.csv`. El [gráfico de ingesta](grafico_ingesta_clickhouse.png) resume el rendimiento por tamaño de lote.

## Conclusión

Al pasar de lotes de 1.000 a 100.000 filas, el tiempo mediano bajó de **76,517 a 6,532 segundos** (91,5 %) y el rendimiento se multiplicó por **11,71**. Se observaron **778, 78 y 8 partes activas**, una por cada `INSERT` en estas corridas. Los lotes grandes redujeron el número de operaciones y dejaron menos partes para las fusiones de `MergeTree`. El cronómetro incluye abrir el cliente y leer los lotes, además de escribirlos en ClickHouse.
