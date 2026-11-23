#!/usr/bin/env python3
"""Compara tamaños de lote en ClickHouse con bloques CSV preparados previamente."""

import argparse
import csv
import io
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

BATCH_SIZES = (1000, 10000, 100000)
FIELDS = (
    "repeticion", "lote", "filas_insertadas", "numero_inserts",
    "tiempo_total_s", "filas_por_s", "partes_activas", "filas_en_partes",
)


def prepare_batches(source, folder, batch_size, column_count):
    batches = []
    stream = None
    total = 0
    try:
        with source.open(encoding="utf-8", newline="") as input_file:
            rows = csv.reader(input_file, strict=True)
            for number, row in enumerate(rows, start=1):
                if len(row) != column_count:
                    raise ValueError(
                        f"Registro {number}: {len(row)} columnas; se esperaban {column_count}."
                    )
                if total % batch_size == 0:
                    if stream is not None:
                        stream.close()
                    path = folder / f"lote_{len(batches) + 1:04}.csv"
                    stream = path.open("w", encoding="utf-8", newline="")
                    writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
                    batches.append(path)
                writer.writerow(row)
                total += 1
    finally:
        if stream is not None:
            stream.close()
    if not total:
        raise ValueError("El CSV está vacío.")
    return batches, total


def client(container, query, input_file=None):
    result = subprocess.run(
        [
            "docker", "exec", "-i", container, "clickhouse-client",
            "--async_insert=0", "--input_format_csv_detect_header=0", "--query", query,
        ],
        stdin=input_file if input_file is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode("utf-8").strip()


def measure(container, schema, target, batches, total):
    client(container, f"CREATE TABLE {target} AS {schema}")
    try:
        client(container, f"SYSTEM STOP MERGES {target}")

        start = time.perf_counter()
        for path in batches:
            with path.open("rb") as source:
                client(container, f"INSERT INTO {target} FORMAT CSV", source)
        elapsed = time.perf_counter() - start

        database, table = target.split(".")
        parts, rows = map(int, client(
            container,
            f"SELECT count(), sum(rows) FROM system.parts "
            f"WHERE database = '{database}' AND table = '{table}' AND active",
        ).split())
        if rows != total:
            raise ValueError(f"{target}: se esperaban {total} filas y se almacenaron {rows}.")
        return elapsed, parts, rows
    finally:
        try:
            client(container, f"SYSTEM START MERGES {target}")
        finally:
            client(container, f"DROP TABLE {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="CSV UTF-8, separado por comas y sin cabecera")
    parser.add_argument("--contenedor", default="clickhouse-bigdata")
    parser.add_argument("--esquema", default="bigdata.chilecompra_2025")
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument(
        "--demo", action="store_true",
        help="ejecuta una corrida con lotes de 100.000 filas y usa todo el CSV",
    )
    parser.add_argument("--filas-esperadas", type=int)
    args = parser.parse_args()
    if args.repeticiones < 1:
        parser.error("--repeticiones debe ser al menos 1.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*\.[A-Za-z_][A-Za-z_0-9]*", args.esquema):
        parser.error("--esquema debe tener la forma base.tabla.")
    if not args.csv.is_file():
        parser.error(f"No encuentro el archivo {args.csv}.")

    sizes = (BATCH_SIZES[-1],) if args.demo else BATCH_SIZES
    repetitions = 1 if args.demo else args.repeticiones
    database = args.esquema.split(".")[0]
    column_count = len(client(args.contenedor, f"DESCRIBE TABLE {args.esquema}").splitlines())
    run = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    prefix = "resultados_demo_insert_csv" if args.demo else "resultados_insert_csv"
    output = Path(f"{prefix}_{run}.csv")
    csv.field_size_limit(10_000_000)
    with output.open("x", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(FIELDS)
        for size in sizes:
            print(f"Preparando lotes de {size:,} filas…", flush=True)
            with tempfile.TemporaryDirectory(prefix="clickhouse_lotes_") as folder:
                batches, total = prepare_batches(args.csv, Path(folder), size, column_count)
                if args.filas_esperadas is not None and total != args.filas_esperadas:
                    raise ValueError(f"El CSV tiene {total} filas; se esperaban {args.filas_esperadas}.")
                for rep in range(1, repetitions + 1):
                    print(f"Probando lote {size:,} · repetición {rep} · {len(batches)} INSERT",
                          flush=True)
                    target = f"{database}.bench_csv_{run}_{size}_{rep}"
                    elapsed, parts, rows = measure(args.contenedor, args.esquema, target, batches, total)
                    line = (rep, size, total, len(batches), f"{elapsed:.3f}",
                            f"{total / elapsed:.2f}", parts, rows)
                    writer.writerow(line)
                    output_file.flush()
                    print(f"{elapsed:.3f} s · {total / elapsed:.2f} filas/s · {parts} partes",
                          flush=True)
    print(f"Resultados guardados en {output.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, csv.Error, subprocess.CalledProcessError) as error:
        sys.exit(f"Error: {error}")
