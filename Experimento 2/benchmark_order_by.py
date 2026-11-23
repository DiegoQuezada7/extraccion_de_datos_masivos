#!/usr/bin/env python3
"""Experimento 2 (Thomas Aránguiz): compara tres claves ORDER BY en ClickHouse."""

import argparse
import csv
import subprocess
import sys
import uuid
from pathlib import Path
from statistics import median


CONFIGS = (
    ("sin_orden", "tuple()"),
    ("organismo", "organismo"),
    ("organismo_fecha", "(organismo, fecha)"),
)
WEEK = "fecha >= '2025-03-01' AND fecha < '2025-03-08'"
FILTERS = (
    ("organismo", "organismo = {org:String}"),
    ("organismo_y_fecha", "organismo = {org:String} AND " + WEEK),
)
# Compare normal reads with primary-index pruning. The implicit count shortcut
# returned an inconsistent total for the composite key in the 25.8 environment.
SETTINGS = (
    " SETTINGS use_query_cache = 0, use_query_condition_cache = 0,"
    " optimize_use_implicit_projections = 0"
)


def query(sql, *, container, stdin=None, options=()):
    result = subprocess.run(
        ["docker", "exec", "-i", container, "clickhouse-client",
         *options, "--query", sql],
        stdin=subprocess.DEVNULL if stdin is None else stdin,
        stdout=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode("utf-8").strip()


def measure(args):
    prefix = "ord_" + uuid.uuid4().hex[:10]
    source = f"bigdata.{prefix}_fuente"
    out = Path(prefix)
    out.mkdir()
    created = []

    def ch(sql, **kwargs):
        return query(sql, container=args.contenedor, **kwargs)

    def create(table, definition):
        ch(f"CREATE TABLE {table} {definition}")
        created.append(table)

    try:
        print("Cargando CSV en una tabla auxiliar…", flush=True)
        create(source, "AS bigdata.chilecompra_2025")
        with args.csv.open("rb") as data:
            ch(f"INSERT INTO {source} FORMAT CSV", stdin=data,
               options=("--input_format_csv_detect_header=0", "--async_insert=0"))
        rows, bad = map(int, ch(
            f"SELECT count(), countIf(toDateOrNull(FechaEnvio) IS NULL) FROM {source}"
        ).split())
        if rows != 777_199 or bad:
            raise RuntimeError(f"Se esperaban 777199 filas con fecha válida: filas={rows}, inválidas={bad}")

        org = ch(
            "SELECT CodigoOrganismoPublico FROM " + source
            + " WHERE CodigoOrganismoPublico != ''"
            + " GROUP BY CodigoOrganismoPublico"
            + " HAVING countIf(FechaEnvio >= '2025-03-01' AND FechaEnvio < '2025-03-08') > 0"
            + " ORDER BY count() DESC, CodigoOrganismoPublico LIMIT 1"
        )
        if not org:
            raise RuntimeError("No se encontró un organismo con envíos en la semana estudiada.")
        org_param = f"--param_org={org}"
        print(f"Organismo elegido: {org}. Rango: 1 al 7 de marzo de 2025.", flush=True)
        tables = {}
        for config, key in CONFIGS:
            table = f"bigdata.{prefix}_{config}"
            print(f"Preparando ORDER BY {key}…", flush=True)
            create(
                table,
                "(organismo String, fecha Date) ENGINE = MergeTree "
                f"ORDER BY {key} SETTINGS index_granularity = 8192, index_granularity_bytes = 0",
            )
            ch(f"INSERT INTO {table} SELECT CodigoOrganismoPublico, toDate(FechaEnvio) FROM {source}")
            ch(f"OPTIMIZE TABLE {table} FINAL")
            _, table_name = table.split(".")
            parts = ch(f"SELECT count() FROM system.parts WHERE database = 'bigdata' "
                       f"AND table = '{table_name}' AND active")
            if parts != "1" or int(ch(f"SELECT count() FROM {table}")) != rows:
                raise RuntimeError(f"No se pudo igualar el número de filas y partes en {table}.")
            tables[config] = table

        jobs = {}
        samples = []
        for workload, predicate in FILTERS:
            queries = {cfg: f"SELECT count() FROM {table} WHERE {predicate}{SETTINGS}"
                       for cfg, table in tables.items()}
            matches = {}
            for cfg, sql in queries.items():
                plan = ch("EXPLAIN indexes = 1 " + sql, options=(org_param,))
                (out / f"plan_{workload}_{cfg}.txt").write_text(plan + "\n", encoding="utf-8")
                matches[cfg] = int(ch(sql, options=(org_param,)))
            if len(set(matches.values())) != 1 or not next(iter(matches.values())):
                raise RuntimeError(f"Cantidad de filas devueltas inconsistente para {workload}: {matches}.")
            configs = list(queries)
            for rep in range(1, args.repeticiones + 1):
                offset = (rep - 1) % len(configs)
                for cfg in configs[offset:] + configs[:offset]:
                    qid = f"{prefix}_{workload}_{cfg}_{rep}"
                    result = int(ch(queries[cfg], options=(org_param, f"--query_id={qid}")))
                    if result != matches[cfg]:
                        raise RuntimeError(f"Resultado inesperado para {qid}.")
                    jobs[qid] = (workload, cfg, rep, result)

        ch("SYSTEM FLUSH LOGS")
        stats = ch(
            "SELECT query_id, query_duration_ms, read_rows, read_bytes, "
            "ProfileEvents['SelectedMarks'] AS marcas FROM system.query_log "
            f"WHERE type = 'QueryFinish' AND startsWith(query_id, '{prefix}_') FORMAT TabSeparated"
        )
        for line in stats.splitlines():
            qid, *values = line.split("\t")
            if qid in jobs:
                samples.append((*jobs[qid], *map(int, values)))
        if len(samples) != len(jobs):
            raise RuntimeError(f"El log devolvió {len(samples)} de {len(jobs)} mediciones.")

        with (out / "mediciones.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("consulta", "orden", "repeticion", "filas_resultado",
                             "tiempo_ms", "filas_leidas", "bytes_leidos", "marcas_seleccionadas"))
            writer.writerows(sorted(samples))
        with (out / "resumen.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("consulta", "orden", "codigo_organismo", "filas_resultado",
                             "mediana_ms", "mediana_filas_leidas", "mediana_bytes_leidos",
                             "mediana_marcas_seleccionadas"))
            for workload, _ in FILTERS:
                for cfg, _ in CONFIGS:
                    group = [s for s in samples if s[:2] == (workload, cfg)]
                    values = [median(s[i] for s in group) for i in range(4, 8)]
                    writer.writerow((workload, cfg, org, group[0][3], *values))
        print(f"Resultados y planes EXPLAIN: {out.resolve()}")
    finally:
        for table in reversed(created):
            try:
                ch(f"DROP TABLE IF EXISTS {table}")
            except subprocess.CalledProcessError:
                print(f"No se pudo limpiar {table}.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="CSV de febrero y marzo de 2025 sin cabecera")
    parser.add_argument("--contenedor", default="clickhouse-bigdata")
    parser.add_argument("--repeticiones", type=int, default=5)
    args = parser.parse_args()
    if args.repeticiones < 1:
        parser.error("--repeticiones debe ser al menos 1.")
    if not args.csv.is_file():
        parser.error(f"No existe {args.csv}.")
    try:
        measure(args)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
