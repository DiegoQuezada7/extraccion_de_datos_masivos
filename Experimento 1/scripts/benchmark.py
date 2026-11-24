import csv
import json
import argparse
import uuid
from datetime import datetime
from statistics import mean, median, quantiles, stdev

from cargar_datos import RAIZ, TABLA, consultar as cliente, identificador as validar_tabla
REPETICIONES = 100
CALENTAMIENTO = 5
HILOS = 12

SQL = f"""
SELECT
    OrganismoPublico,
    count() AS registros,
    round(sum(toFloat64OrZero(MontoTotalOC_PesosChilenos)), 0)
        AS monto_total
FROM {TABLA}
GROUP BY OrganismoPublico
ORDER BY registros DESC
LIMIT 10
"""

def consultar(sql):
    return cliente(sql)


def ejecutar(sql, query_id):
    cliente(sql, opciones=(f"--query_id={query_id}", f"--max_threads={HILOS}",
                          "--log_queries=1", "--use_query_cache=0"))


def main(esperadas):
    global TABLA, SQL
    parser = argparse.ArgumentParser(description="Benchmark original de escalabilidad (100 mediciones).")
    parser.add_argument("--tabla", default=TABLA)
    args = parser.parse_args()
    anterior = TABLA
    TABLA = validar_tabla(args.tabla)
    SQL = SQL.replace(f"FROM {anterior}", f"FROM {TABLA}")
    base, nombre = TABLA.split(".")
    # Comprobación de seguridad
    filas = int(consultar(f"SELECT count() FROM {TABLA}"))

    if filas != esperadas:
        raise SystemExit(
            f"ERROR: La tabla tiene {filas} filas, no {esperadas}."
        )

    fusiones = int(consultar(f"""
    SELECT count()
    FROM system.merges
    WHERE database = '{base}'
      AND table = '{nombre}'
    """))

    if fusiones:
        raise SystemExit(
            "ERROR: Hay fusiones activas. Espera antes de medir."
        )

    identificador = uuid.uuid4().hex
    prefijo = f"esc{esperadas}_{identificador}_"
    inicio = datetime.now().isoformat(timespec="seconds")

    print("BENCHMARK DE ESCALABILIDAD")
    print(f"Registros: {filas:,}")
    print(f"Calentamiento: {CALENTAMIENTO}")
    print(f"Repeticiones: {REPETICIONES}")
    print(f"Hilos: {HILOS}")
    print(f"ID: {identificador}")

    # Calentamiento
    for i in range(1, CALENTAMIENTO + 1):
        ejecutar(SQL, f"{prefijo}warmup_{i}")
        print(f"Calentamiento {i}/{CALENTAMIENTO}", flush=True)

    # Mediciones
    for i in range(1, REPETICIONES + 1):
        ejecutar(SQL, f"{prefijo}medicion_{i:03d}")
        print(f"Medición {i}/{REPETICIONES}", flush=True)

    # Asegurar que los registros estén disponibles
    consultar("SYSTEM FLUSH LOGS")

    # Recuperar las métricas desde ClickHouse
    consulta_log = f"""
    SELECT
        query_id,
        query_duration_ms,
        memory_usage,
        read_rows,
        read_bytes
    FROM system.query_log
    WHERE type = 'QueryFinish'
      AND startsWith(query_id, '{prefijo}medicion_')
    ORDER BY query_id
    FORMAT TSV
    """

    salida = consultar(consulta_log)
    registros = []

    for linea in salida.splitlines():
        campos = linea.split("\t")

        if len(campos) != 5:
            raise RuntimeError(f"Registro inesperado: {linea}")

        query_id, tiempo, memoria, filas_leidas, bytes_leidos = campos

        numero = int(query_id.rsplit("_", 1)[1])

        registros.append({
            "repeticion": numero,
            "tiempo_ms": int(tiempo),
            "memoria_bytes": int(memoria),
            "filas_leidas": int(filas_leidas),
            "bytes_leidos": int(bytes_leidos),
        })

    registros.sort(key=lambda r: r["repeticion"])

    if len(registros) != REPETICIONES:
        raise RuntimeError(
            f"Se encontraron {len(registros)} mediciones; "
            f"se esperaban {REPETICIONES}. "
            "No se generará un CSV incompleto."
        )

    if [r["repeticion"] for r in registros] != list(
        range(1, REPETICIONES + 1)
    ):
        raise RuntimeError("Faltan repeticiones o existen duplicados.")

    if any(r["filas_leidas"] != esperadas for r in registros):
        raise RuntimeError("Las mediciones no leyeron el volumen esperado.")
    if int(consultar(f"SELECT count() FROM {TABLA}")) != esperadas:
        raise RuntimeError("El volumen de la tabla cambió durante la medición.")

    tiempos = [r["tiempo_ms"] for r in registros]
    mediana = median(tiempos)
    p95 = quantiles(tiempos, n=100, method="inclusive")[94]
    for registro in registros:
        registro.update(mediana_tiempo_ms=mediana, p95_tiempo_ms=p95)

    carpeta = RAIZ / "resultados" / "nuevas" / f"resultados_{esperadas}_{identificador}"
    carpeta.mkdir(parents=True, exist_ok=False)

    with open(
        carpeta / "mediciones.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as archivo:
        escritor = csv.DictWriter(
            archivo,
            fieldnames=[
                "repeticion",
                "tiempo_ms",
                "memoria_bytes",
                "filas_leidas",
                "bytes_leidos",
                "mediana_tiempo_ms",
                "p95_tiempo_ms"
            ]
        )
        escritor.writeheader()
        escritor.writerows(registros)

    configuracion = {
        "inicio": inicio,
        "identificador": identificador,
        "tabla": TABLA,
        "registros": filas,
        "repeticiones": REPETICIONES,
        "calentamiento": CALENTAMIENTO,
        "max_threads": HILOS,
        "use_query_cache": 0,
        "version_clickhouse": consultar("SELECT version()"),
        "consulta_sql": SQL.strip()
    }

    with open(
        carpeta / "configuracion.json",
        "w",
        encoding="utf-8"
    ) as archivo:
        json.dump(configuracion, archivo, indent=2, ensure_ascii=False)

    resumen = {
        "registros": filas, "repeticiones": REPETICIONES,
        "promedio_ms": mean(tiempos), "mediana_ms": mediana, "p95_ms": p95,
        "minimo_ms": min(tiempos), "maximo_ms": max(tiempos),
        "desviacion_estandar_ms": stdev(tiempos),
        "memoria_promedio_MiB": mean(r["memoria_bytes"] for r in registros) / 2**20,
    }
    with (carpeta / "resumen.csv").open("x", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(resumen))
        escritor.writeheader()
        escritor.writerow(resumen)

    print("\nBENCHMARK FINALIZADO")
    print(f"Mediciones recuperadas: {len(registros)}")
    print(f"Resultados guardados en: {carpeta.resolve()}")
