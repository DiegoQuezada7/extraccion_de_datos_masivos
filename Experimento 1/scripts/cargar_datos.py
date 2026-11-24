#!/usr/bin/env python3
"""Preparación de datos y carga incremental del experimento de escalabilidad."""
import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
import uuid
import zipfile
from collections import Counter
from contextlib import contextmanager
from itertools import islice
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATOS = Path(os.environ.get("ESC1_DATOS", str(RAIZ / "datos"))).expanduser().resolve()
TABLA = os.environ.get("ESC1_TABLA", "bigdata.esc1_repro_escalabilidad")


def identificador(nombre):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*\.[A-Za-z_][A-Za-z_0-9]*", nombre):
        raise ValueError("La tabla debe tener la forma base.tabla (identificadores simples).")
    return nombre


def consultar(sql, *, tabla=None, entrada=None, opciones=()):
    if tabla is not None:
        identificador(tabla)
    # Reutiliza las credenciales del contenedor sin copiarlas al repositorio
    # ni incluir la contraseña entre los argumentos del proceso del host.
    comando = ['exec clickhouse-client --user "${ESC1_USER:-${CLICKHOUSE_USER:-default}}" '
               '--password "${ESC1_PASSWORD:-${CLICKHOUSE_PASSWORD:-}}" "$@"']
    entorno = []
    for nombre in ("ESC1_USER", "ESC1_PASSWORD"):
        if nombre in os.environ:
            entorno += ["--env", nombre]
    resultado = subprocess.run(
        ["docker", "exec", "-i", *entorno,
         os.environ.get("ESC1_CONTENEDOR", "clickhouse-bigdata"),
         "sh", "-c", *comando, "esc1-client", *opciones, "--query", sql],
        stdin=entrada if entrada is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return resultado.stdout.decode("utf-8").strip()


csv.field_size_limit(10_000_000)


def columnas():
    sql = (RAIZ.parent / "crear_tabla.sql").read_text(encoding="utf-8")
    nombres = re.findall(r"`([^`]+)` String", sql)
    if len(nombres) != 79 or nombres[12] != "CodigoProyectoPlanAnualCompras":
        raise ValueError("El esquema compartido no coincide con las 79 columnas esperadas.")
    return nombres


def decodificar(datos, contador=None):
    resultado = []
    for caracter in datos.decode("utf-8", errors="surrogateescape"):
        codigo = ord(caracter)
        if 0xDC80 <= codigo <= 0xDCFF:
            byte = codigo - 0xDC00
            try:
                caracter = bytes([byte]).decode("cp1252")
                clave = f"cp1252_0x{byte:02X}"
            except UnicodeDecodeError:
                caracter = f"\\x{byte:02X}"
                clave = f"escape_0x{byte:02X}"
            if contador is not None:
                contador[clave] += 1
        resultado.append(caracter)
    return "".join(resultado)


def filas_originales(ruta, contador=None):
    esperadas = columnas()
    with Path(ruta).open("rb") as archivo:
        lector = csv.reader((decodificar(linea, contador) for linea in archivo),
                            delimiter=";", strict=True)
        cabecera = next(lector, None)
        if cabecera is None:
            raise ValueError(f"Archivo vacío: {ruta}")
        cabecera[0] = cabecera[0].lstrip("\ufeff")
        sin_columna = esperadas[:12] + esperadas[13:]
        if cabecera not in (esperadas, sin_columna):
            raise ValueError(f"Encabezado u orden de columnas inesperado: {ruta}")
        for numero, fila in enumerate(lector, 2):
            if len(fila) != len(cabecera):
                raise ValueError(f"{ruta}, registro {numero}: {len(fila)} columnas")
            if len(cabecera) == 78:
                fila.insert(12, "")
            yield fila


def sha256(ruta):
    h = hashlib.sha256()
    with Path(ruta).open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def normalizar(origen, destino):
    destino = Path(destino)
    informe = destino.with_suffix(".json")
    temporal = destino.with_suffix(".csv.part")
    if destino.exists() or informe.exists() or temporal.exists():
        raise FileExistsError(f"No se sobrescribe una salida existente: {destino}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    recuperaciones = Counter()
    total = 0
    with temporal.open("x", encoding="utf-8", newline="") as salida:
        escritor = csv.writer(salida)
        for fila in filas_originales(origen, recuperaciones):
            escritor.writerow(fila)
            total += 1
    if not total:
        raise ValueError(f"Sin registros: {origen}")
    datos = {"origen_sha256": sha256(origen), "sha256": sha256(temporal),
             "filas": total, "columnas": 79, "recuperaciones": dict(recuperaciones)}
    # Publica el CSV únicamente después de validar todas sus filas.
    temporal.rename(destino)
    with informe.open("x", encoding="utf-8") as salida:
        json.dump(datos, salida, indent=2, ensure_ascii=False)
    print(f"{destino.name}: {total:,} registros; recuperaciones: {dict(recuperaciones)}")
    return datos


def meses(etapa):
    if etapa == 2500000:
        return [(2025, mes) for mes in range(1, 8)]
    if etapa == 5000000:
        return [(2025, mes) for mes in range(8, 13)]
    return [(2024, mes) for mes in range(1, 13)]


def normalizar_etapa(etapa):
    parser = argparse.ArgumentParser(description="Normaliza los meses adicionales de la etapa.")
    parser.add_argument("--origen", type=Path, default=DATOS / "originales")
    parser.add_argument("--destino", type=Path, default=DATOS / "normalizados")
    args = parser.parse_args()
    for anio, mes in meses(etapa):
        nombre = f"{anio}-{mes}.csv"
        normalizar(args.origen / nombre, args.destino / nombre)


ETAPAS = (2500000, 5000000, 10000000)


@contextmanager
def bloqueo(ruta):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a") as archivo:
        fcntl.flock(archivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def guardar(ruta, datos):
    temporal = ruta.with_suffix(".tmp")
    with temporal.open("w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, indent=2, ensure_ascii=False)
        archivo.flush()
        os.fsync(archivo.fileno())
    temporal.replace(ruta)


def descargar(etapa, raiz):
    for anio, mes in meses(etapa):
        nombre = f"{anio}-{mes}"
        comprimido = raiz / "zip" / f"{nombre}.zip"
        original = raiz / "originales" / f"{nombre}.csv"
        comprimido.parent.mkdir(parents=True, exist_ok=True)
        original.parent.mkdir(parents=True, exist_ok=True)
        if original.exists():
            print(f"Reutilizando {original}; se validará al normalizar.")
            continue
        if not comprimido.exists():
            temporal = comprimido.with_suffix(".zip.part")
            if temporal.exists():
                raise FileExistsError(f"Descarga incompleta: {temporal}. Revisar antes de reintentar.")
            url = f"https://transparenciachc.blob.core.windows.net/oc-da/{nombre}.zip"
            print(f"Descargando {url}", flush=True)
            with urllib.request.urlopen(url, timeout=120) as respuesta, temporal.open("xb") as salida:
                shutil.copyfileobj(respuesta, salida, length=1024 * 1024)
            with zipfile.ZipFile(temporal) as archivo:
                if archivo.testzip() is not None:
                    raise ValueError(f"ZIP corrupto: {temporal}")
            temporal.rename(comprimido)
        with zipfile.ZipFile(comprimido) as archivo:
            candidatos = [n for n in archivo.namelist()
                          if Path(n).name.lower() == f"{nombre}.csv"]
            if len(candidatos) != 1:
                raise ValueError(f"Se esperaba un único {nombre}.csv dentro de {comprimido}")
            temporal = original.with_suffix(".csv.part")
            # No utiliza extractall: los nombres del ZIP no determinan rutas de escritura.
            with archivo.open(candidatos[0]) as entrada, temporal.open("xb") as salida:
                shutil.copyfileobj(entrada, salida, length=1024 * 1024)
            temporal.rename(original)


def segmentos(etapa, informes):
    """Intervalos disjuntos sobre registros CSV, nunca sobre líneas físicas."""
    if etapa == 2500000:
        primeros = [f"2025-{m}" for m in range(1, 7)]
        if sum(informes[n]["filas"] for n in primeros) != 2479124:
            raise ValueError("Enero–junio de 2025 no suma 2479124 registros; revisar fuentes.")
        return [(n, 0, informes[n]["filas"]) for n in primeros] + [("2025-7", 0, 20876)]
    if etapa == 5000000:
        return [("2025-7", 20876, informes["2025-7"]["filas"] - 20876)] + [
            (f"2025-{m}", 0, informes[f"2025-{m}"]["filas"]) for m in range(8, 12)
        ] + [("2025-12", 0, 286892)]
    if sum(informes[f"2024-{m}"]["filas"] for m in range(1, 11)) != 4461350:
        raise ValueError("Enero–octubre de 2024 no suma 4461350 registros.")
    if informes["2024-11"]["filas"] != 470594:
        raise ValueError("Noviembre de 2024 no tiene 470594 registros.")
    return [(f"2024-{m}", 0, informes[f"2024-{m}"]["filas"]) for m in range(1, 12)] + [
        ("2024-12", 0, 68056)]


def preparar(etapa, raiz, salida):
    nombres = ([f"2025-{m}" for m in range(1, 8)] if etapa == 2500000 else
               [f"2025-{m}" for m in range(7, 13)] if etapa == 5000000 else
               [f"2024-{m}" for m in range(1, 13)])
    informes = {}
    for nombre in nombres:
        ruta = raiz / "normalizados" / f"{nombre}.csv"
        informe = json.loads(ruta.with_suffix(".json").read_text(encoding="utf-8"))
        if informe["columnas"] != 79 or sha256(ruta) != informe["sha256"]:
            raise ValueError(f"CSV modificado o esquema inválido: {ruta}")
        informes[nombre] = informe
    intervalos = segmentos(etapa, informes)
    esperado = etapa - (0 if etapa == 2500000 else 2500000 if etapa == 5000000 else 5000000)
    if sum(n for _, _, n in intervalos) != esperado:
        raise ValueError("Los intervalos no suman el incremento esperado; revisar distribución.")
    total = escribir_intervalos(raiz / "normalizados", intervalos, salida)
    return {"intervalos": intervalos, "fuentes": informes, "incremento": total, "sha256": sha256(salida)}


def escribir_intervalos(carpeta, intervalos, salida):
    """Genera un incremento verificando cada intervalo; utilizable con datos pequeños."""
    total = 0
    with salida.open("x", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        for nombre, inicio, cantidad in intervalos:
            if cantidad < 0:
                raise ValueError(f"Intervalo inválido: {nombre}")
            obtenidas = 0
            with (carpeta / f"{nombre}.csv").open(encoding="utf-8", newline="") as fuente:
                for fila in islice(csv.reader(fuente, strict=True), inicio, inicio + cantidad):
                    if len(fila) != 79:
                        raise ValueError(f"Esquema inválido en {nombre}")
                    escritor.writerow(fila)
                    obtenidas += 1
            if obtenidas != cantidad:
                raise ValueError(f"{nombre}: faltan registros para el intervalo solicitado")
            total += obtenidas
    return total


def filas(tabla):
    return int(consultar(f"SELECT count() FROM {tabla}"))


def uuid_tabla(tabla):
    base, nombre = tabla.split(".")
    return consultar(f"SELECT toString(uuid) FROM system.tables WHERE database='{base}' AND name='{nombre}'")


def validar_esquema(tabla):
    descripcion = consultar(f"DESCRIBE TABLE {tabla} FORMAT TSV")
    actual = [linea.split("\t")[:2] for linea in descripcion.splitlines()]
    if actual != [[nombre, "String"] for nombre in columnas()]:
        raise ValueError(f"Esquema incompatible: {tabla}")
    base, nombre = tabla.split(".")
    motor = consultar(f"SELECT engine, sorting_key, partition_key FROM system.tables "
                      f"WHERE database='{base}' AND name='{nombre}' FORMAT JSONEachRow")
    configuracion = json.loads(motor)
    if (configuracion["engine"] != "MergeTree" or configuracion["sorting_key"] != "tuple()"
            or configuracion["partition_key"] != ""):
        raise ValueError(f"Se esperaba MergeTree sin partición y ORDER BY tuple(): {tabla}")


def cargar(etapa, raiz, tabla):
    identificador(tabla)
    base, nombre = tabla.split(".")
    if not nombre.startswith("esc1_repro_"):
        raise ValueError("La carga solo permite tablas esc1_repro_*. Las tablas originales están protegidas.")
    estado_path = raiz / f"estado_{base}_{nombre}.json"
    with bloqueo(raiz / f"{base}_{nombre}.lock"):
        estado = json.loads(estado_path.read_text()) if estado_path.exists() else None
        actual_uuid = uuid_tabla(tabla)
        if estado is None:
            if actual_uuid:
                raise ValueError("Tabla preexistente sin manifiesto propio: no se adopta ni modifica.")
            motor_db = consultar(f"SELECT engine FROM system.databases WHERE name='{base}'")
            if motor_db != "Atomic":
                raise ValueError("La base debe existir y usar Atomic para publicar con EXCHANGE.")
            validar_esquema("bigdata.chilecompra_2025")
            estado = {"tabla": tabla, "filas": 0, "uuid": "", "historial": []}
            guardar(estado_path, estado)
        pendiente = estado.get("pendiente")
        if pendiente:
            if actual_uuid == pendiente["uuid"] and filas(tabla) == pendiente["filas"]:
                estado.update(filas=pendiente["filas"], uuid=actual_uuid)
                estado["historial"].append(pendiente)
                estado.pop("pendiente")
                guardar(estado_path, estado)
            else:
                raise ValueError(f"Carga pendiente o fallida: revisar {estado_path}. No se reinsertará automáticamente.")
        if actual_uuid != estado["uuid"]:
            raise ValueError("El UUID de la tabla cambió fuera de este procedimiento.")
        if actual_uuid:
            validar_esquema(tabla)
            if filas(tabla) != estado["filas"]:
                raise ValueError("Conteo distinto del manifiesto: se bloquea la carga.")
        if etapa == estado["filas"]:
            print(f"Etapa {etapa:,} ya publicada y validada; no se inserta nada.")
            return
        anterior = {2500000: 0, 5000000: 2500000, 10000000: 5000000}[etapa]
        if estado["filas"] != anterior:
            raise ValueError(f"Esta etapa exige {anterior:,} filas previas; hay {estado['filas']:,}.")
        run = uuid.uuid4().hex
        auxiliar = f"{base}.{nombre}_preparacion_{run}"
        lote = raiz / "temporales" / f"incremento_{run}.csv"
        lote.parent.mkdir(parents=True, exist_ok=True)
        informe = preparar(etapa, raiz, lote)
        consultar(f"CREATE TABLE {auxiliar} AS bigdata.chilecompra_2025")
        validar_esquema(auxiliar)
        estado["pendiente"] = {"filas": etapa, "uuid": uuid_tabla(auxiliar),
                               "auxiliar": auxiliar, "lote": str(lote), **informe}
        guardar(estado_path, estado)
        # El destino permanece intacto aunque una inserción falle parcialmente.
        if anterior:
            consultar(f"INSERT INTO {auxiliar} SELECT * FROM {tabla}", opciones=("--async_insert=0",))
        if filas(auxiliar) != anterior:
            raise ValueError("Conteo incorrecto después de copiar el escenario anterior.")
        with lote.open("rb") as entrada:
            consultar(f"INSERT INTO {auxiliar} FORMAT CSV", entrada=entrada,
                      opciones=("--async_insert=0", "--input_format_csv_detect_header=0",
                                "--input_format_allow_errors_num=0", "--input_format_allow_errors_ratio=0"))
        if filas(auxiliar) != etapa:
            raise ValueError("Conteo incorrecto: no se publica el escenario.")
        if uuid_tabla(tabla) != actual_uuid or (anterior and filas(tabla) != anterior):
            raise ValueError("La tabla publicada cambió durante la preparación.")
        if anterior:
            consultar(f"EXCHANGE TABLES {tabla} AND {auxiliar}")
        else:
            consultar(f"RENAME TABLE {auxiliar} TO {tabla}")
        if uuid_tabla(tabla) != estado["pendiente"]["uuid"] or filas(tabla) != etapa:
            raise ValueError("Publicación incierta: no reintentar inserciones manualmente.")
        estado.update(filas=etapa, uuid=uuid_tabla(tabla))
        estado["historial"].append(estado.pop("pendiente"))
        guardar(estado_path, estado)
        print(f"Publicado {tabla}: {etapa:,} filas. Manifiesto: {estado_path}")
        print("Se conservan el lote y las tablas auxiliares; no se borra ninguna tabla.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=("descargar", "cargar"))
    parser.add_argument("etapa", type=int, choices=ETAPAS)
    parser.add_argument("--datos", type=Path, default=DATOS)
    parser.add_argument("--tabla", default=TABLA)
    args = parser.parse_args()
    raiz = args.datos.expanduser().resolve()
    raiz.mkdir(parents=True, exist_ok=True)
    if args.accion == "descargar":
        with bloqueo(raiz / "descarga.lock"):
            descargar(args.etapa, raiz)
    else:
        cargar(args.etapa, raiz, args.tabla)


if __name__ == "__main__":
    main()
