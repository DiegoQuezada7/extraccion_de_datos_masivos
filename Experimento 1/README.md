# Experimento 1 · Escalabilidad respecto del volumen de registros

**Responsable:** Benjamín Arancibia.

## Pregunta e hipótesis

¿Cómo cambia el rendimiento de una agregación al aumentar los registros de ChileCompra de 2,5 a 5 y 10 millones?

**Hipótesis.** El tiempo aumentará con el volumen y la memoria se mantendrá relativamente estable al agrupar por organismo público.

## Reproducir el experimento

Requiere Linux, Python **3.10+**, Docker Compose y varios GB libres. Los [resultados originales](resultados/) ya están disponibles; reproducir las mediciones es opcional. Desde la raíz del repositorio:

```bash
docker compose up -d
# Esperar a que ClickHouse esté disponible antes de crear la tabla de referencia.
docker exec -i clickhouse-bigdata sh -c 'exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery' < crear_tabla.sql

# Descargar, normalizar, cargar y medir cada escenario antes de ampliarlo.
for escenario in 2500000:2.5M 5000000:5M 10000000:10M; do
  filas="${escenario%%:*}"
  etapa="${escenario#*:}"
  bash "Experimento 1/scripts/descargar_datos.sh" "$filas" || break
  python3 "Experimento 1/scripts/normalizar_${etapa}.py" || break
  bash "Experimento 1/scripts/cargar_datos.sh" "$filas" || break
  python3 "Experimento 1/scripts/benchmark_${filas}.py" || break
done
```

Los históricos reales de 2025 y 2024 provienen de `https://transparenciachc.blob.core.windows.net/oc-da/{año}-{mes}.zip`. Se normalizan a UTF-8, comas y sin encabezado, recuperando bytes CP1252 e incorporando `CodigoProyectoPlanAnualCompras` vacío cuando falta. Los datos masivos se guardan en `Experimento 1/datos/`, excluida de Git.

La carga valida los conteos y usa `bigdata.esc1_repro_escalabilidad`, sin modificar la tabla original. Conserva tablas auxiliares y requiere espacio adicional. Si falla, revisar `datos/estado_*.json` sin borrarlo ni reinsertar manualmente. Las nuevas mediciones se guardan en carpetas únicas de `resultados/nuevas/`.

## Diseño experimental

- **Variable independiente:** 2.500.000, 5.000.000 y 10.000.000 registros reales, sin replicación artificial.
- **Consulta:** agrupa por organismo, cuenta registros y suma montos; devuelve los diez organismos con más registros.
- **Controles:** misma consulta, 5 calentamientos, 100 repeticiones, `max_threads=12` y `use_query_cache=0`. Entorno original: Linux Mint 22, Docker y ClickHouse 25.8.33.6.
- **Métricas:** tiempo, memoria, filas y bytes leídos de `system.query_log`; promedio, mediana, p95 inclusivo y desviación estándar muestral.

## Resultados

| Métrica | 2,5 M | 5 M | 10 M |
|---|---:|---:|---:|
| Tiempo promedio (ms) | 45,97 | 78,66 | 142,27 |
| Mediana (ms) | 42 | 70 | 132 |
| Percentil 95 (ms) | 65 | 111,05 | 200,25 |
| Desviación estándar (ms) | 11,51 | 18,35 | 28,52 |
| Memoria promedio (MiB) | 19,09 | 19,05 | 19,16 |

[Resumen](resultados/resumen_escalabilidad.csv) · [Mediciones y configuración](resultados/) · [Gráficos](graficos/).

## Conclusión

Al duplicar los registros, el tiempo promedio aumentó un **71,11 %** y un **80,87 %**: comportamiento sublineal en los intervalos evaluados, con memoria próxima a 19 MiB. Cambian también los meses y años incorporados; hardware, cachés y versión pueden afectar la comparación. La adaptación se verificó estáticamente, sin repetir cargas ni benchmarks.
