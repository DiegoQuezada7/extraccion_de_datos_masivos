# Experimento 2 · Efecto del ORDER BY en ClickHouse

**Responsable:** Thomas Aránguiz.

## Pregunta e hipótesis

¿Cuánto cambia la lectura al ordenar una tabla `MergeTree` por organismo o por organismo y fecha? Se comparan `ORDER BY tuple()`, `ORDER BY organismo` y `ORDER BY (organismo, fecha)`.

**Hipótesis.** Al filtrar por organismo, ordenar por ese campo reducirá los bloques seleccionados y los bytes leídos frente a `tuple()`. Al agregar un rango de fechas, se espera que la clave compuesta reduzca la lectura frente a ordenar solo por organismo.

## Reproducir el experimento

Sigue la [preparación del entorno y del CSV](../README.md#preparación-del-entorno). Desde la raíz del repositorio, ejecuta:

```bash
python3 "Experimento 2/benchmark_order_by.py" chilecompra_feb_mar_2025.csv
```

Para probar una vez cada combinación durante la demo, agrega `--repeticiones 1`. La carga inicial y el armado de las tablas ocurren antes de medir las consultas.

## Diseño experimental

- **Variable independiente:** clave de ordenamiento: `tuple()`, `organismo` o `(organismo, fecha)`.
- **Métricas:** tiempo de consulta, filas y bytes leídos, marcas seleccionadas y uso del índice primario según `EXPLAIN indexes = 1`.
- **Controles:** mismas filas y columnas, mismo motor `MergeTree`, una parte activa, misma granularidad y mismo filtro al comparar las tres tablas.

Se cargan las 777.199 filas de ChileCompra de febrero y marzo de 2025. Las tablas de prueba contienen los mismos valores de `CodigoOrganismoPublico` (`organismo`) y `FechaEnvio` (`fecha`, tipo `Date`), una parte activa por tabla y la misma granularidad de 8.192 filas.

Se cuentan las filas del organismo **111870** y luego las del mismo organismo con fecha del **1 al 7 de marzo de 2025**. El script ejecuta un calentamiento y cinco repeticiones por combinación. Desactiva las cachés de consulta y de condición, y la proyección implícita de conteo, para comparar lecturas con el índice primario. Valida que los conteos coincidan antes de registrar las métricas.

## Resultados

El tiempo y los bytes corresponden a medianas de cinco repeticiones. Los bloques indican cuántos gránulos se seleccionaron de un total de 95.

| Filtro | Orden de la tabla | Tiempo (ms) | Bytes leídos | Bloques seleccionados |
|---|---|---:|---:|---:|
| Organismo | `tuple()` | 6 | 10.156.757 | 95/95 |
| Organismo | `organismo` | 4 | 577.621 | 5/95 |
| Organismo | `(organismo, fecha)` | 3 | 577.621 | 5/95 |
| Organismo y semana | `tuple()` | 6 | 3.434.634 | 95/95 |
| Organismo y semana | `organismo` | 4 | 659.541 | 5/95 |
| Organismo y semana | `(organismo, fecha)` | 4 | 277.000 | 5/95 |

Las tres tablas devolvieron **32.318 filas** con el primer filtro y **4.422** con el segundo.

## Conclusión

Ordenar por organismo permitió que el índice primario disperso de `MergeTree` descartara 90 de los 95 gránulos. En la consulta semanal, el plan de la clave compuesta incluyó organismo y fecha. Ambos ordenamientos seleccionaron cinco gránulos, y la clave compuesta redujo los bytes leídos un **58 %** frente a ordenar solo por organismo. Los dos registraron una mediana de **4 ms**. En esta prueba, el efecto adicional de la fecha se observó en bytes leídos.

[Resumen](resultados/resumen.csv) · [30 mediciones](resultados/mediciones.csv) · [Planes EXPLAIN](resultados/). Cada ejecución nueva genera esos archivos en una carpeta `ord_*`.
