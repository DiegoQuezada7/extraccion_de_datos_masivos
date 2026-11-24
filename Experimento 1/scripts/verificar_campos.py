#!/usr/bin/env python3
"""Compara los campos experimentales de un original y su normalizado completo."""
import argparse
import csv
from pathlib import Path
from cargar_datos import columnas, filas_originales


def verificar(original, normalizado):
    indices = [columnas().index(n) for n in
               ("OrganismoPublico", "MontoTotalOC_PesosChilenos")]
    total = 0
    with Path(normalizado).open(encoding="utf-8", newline="") as archivo:
        for total, (a, b) in enumerate(zip(filas_originales(original),
                                         csv.reader(archivo, strict=True), strict=True), 1):
            if len(b) != 79 or any(a[i] != b[i] for i in indices):
                raise ValueError(f"Diferencia en el registro {total}")
    print(f"{total:,} registros verificados sin diferencias en los dos campos.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("normalizado", type=Path)
    args = parser.parse_args()
    verificar(args.original, args.normalizado)
