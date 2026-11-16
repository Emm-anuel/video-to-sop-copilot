# Medición de la búsqueda exacta (RNF-02, RNF-03)

`scripts/medir_busqueda.py`, solo Postgres. Videos sintéticos publicados a partir de las
transcripciones de A–E (videos del equipo); se borran al terminar.

| Corrida | Videos | Palabras por video | Min por video | Palabras en el índice | Punta p50 | Punta p95 | Servidor p95 | RNF-02 | RNF-03 |
|---|---:|---|---|---:|---:|---:|---:|---|---|
| 1: copias de A–E (un video por transcripción) | 50 | 227–455 (media 326) | 1.9–5.8 (media 3.8) | 16300 | 12.51 ms | 19.54 ms | 15.19 ms | pasa | pasa |
| 2: A–E concatenadas hasta ~1500 palabras por video | 50 | 1501–1547 (media 1520) | 12.8–15.2 (media 14) | 76020 | 22.04 ms | 32.54 ms | 27.4 ms | pasa | pasa |

## Corrida 1: copias de A–E (un video por transcripción) (2026-11-15T22:14:16)

Commit `1cfccb3` en `feat/s6` (8 archivos con cambios sin commit).

- Índice: 50 videos publicados (50 sembrados), 16300 palabras.
- **Palabras por video:** 227–455 (media 326); minutos por video: 1.9–5.8 (media 3.8).
  (palabras y minutos por video calculados al anexar, con los mismos analisis.json.)
- 32 consultas × 5 repeticiones, tras 3 de calentamiento; `BUSQUEDA_UNIR_S=3`.
- **RNF-02 (< 1000 ms):** pasa · punta a punta p50 12.51 ms, p95 19.54 ms · servidor p50 8.09 ms, p95 15.19 ms.
- **RNF-03 (±1 s):** pasa (10 de 10).

### Por tipo de consulta (ms)

| Tipo | n | Servidor p50 | Servidor p95 | Punta p50 | Punta p95 | Punta máx |
|---|---:|---:|---:|---:|---:|---:|
| comun | 40 | 13.95 | 15.44 | 18.42 | 19.86 | 21.56 |
| rara | 40 | 6.72 | 7.95 | 11.13 | 13.41 | 18.8 |
| frase | 50 | 7.93 | 11.1 | 12.05 | 15.36 | 16.08 |
| frase_larga | 10 | 13.12 | 16.08 | 17.39 | 20.73 | 21.75 |
| sin_resultados | 20 | 4.55 | 8.59 | 9.08 | 13.12 | 13.64 |
| total | 160 | 8.09 | 15.19 | 12.51 | 19.54 | 21.75 |

### Consultas

| Tipo | Consulta | Tokens | Total | Devueltos | Servidor p50 | Punta p50 |
|---|---|---:|---:|---:|---:|---:|
| comun | el | 1 | 650 | 50 | 15.40 | 19.85 |
| comun | de | 1 | 510 | 50 | 15.13 | 19.54 |
| comun | la | 1 | 510 | 50 | 14.77 | 19.05 |
| comun | the | 1 | 240 | 50 | 14.15 | 18.47 |
| comun | y | 1 | 310 | 50 | 13.73 | 17.84 |
| comun | I | 1 | 240 | 50 | 13.51 | 17.60 |
| comun | a | 1 | 210 | 50 | 13.53 | 17.69 |
| comun | del | 1 | 210 | 50 | 12.94 | 17.02 |
| rara | dura. | 1 | 10 | 10 | 6.40 | 10.69 |
| rara | mica | 1 | 10 | 10 | 6.67 | 10.98 |
| rara | casi | 1 | 10 | 10 | 6.88 | 11.48 |
| rara | primer | 1 | 10 | 10 | 7.87 | 13.26 |
| rara | back. | 1 | 10 | 10 | 6.82 | 11.42 |
| rara | across | 1 | 10 | 10 | 6.84 | 11.26 |
| rara | stays, | 1 | 10 | 10 | 6.77 | 11.16 |
| rara | replaced. | 1 | 10 | 10 | 5.79 | 10.21 |
| frase | Buenos días, | 2 | 40 | 40 | 9.72 | 13.96 |
| frase | menos de 2 | 3 | 30 | 30 | 11.01 | 15.09 |
| frase | bien hasta aquí la | 4 | 10 | 10 | 8.28 | 12.49 |
| frase | mí El | 2 | 10 | 10 | 6.97 | 11.06 |
| frase | extension bar called | 3 | 10 | 10 | 7.12 | 11.28 |
| frase | agua, saco el cartucho | 4 | 20 | 20 | 10.24 | 14.45 |
| frase | nuevo limpio | 2 | 10 | 10 | 6.62 | 10.77 |
| frase | cuarteado. Retomo yo, | 3 | 10 | 10 | 6.76 | 10.92 |
| frase | la puerta de acrílico | 4 | 20 | 20 | 9.72 | 14.03 |
| frase | has been | 2 | 10 | 10 | 5.76 | 10.08 |
| frase_larga | Con la llave de la carcasa aflojo el vaso girando a la | 12 | 10 | 10 | 11.57 | 15.96 |
| frase_larga | ahora retiro la carcasa, con la llave de carcasa aflojo el vaso girando a la izquierda, lo bajo con cuidado porque trae agua, saco el cartucho usado y lo meto a la bolsa de residuos, reviso el anillo de hule, | 40 | 10 | 10 | 14.61 | 19.10 |
| sin_resultados | zzxq | 1 | 0 | 0 | 4.27 | 8.86 |
| sin_resultados | xilófono | 1 | 0 | 0 | 4.42 | 8.84 |
| sin_resultados | válvula cuántica intergaláctica | 3 | 0 | 0 | 4.56 | 9.13 |
| sin_resultados | esta frase nadie la dijo nunca | 6 | 0 | 0 | 8.27 | 12.51 |

### RNF-03: 10 palabras de video_a (copia sin desplazar)

| Palabra | t transcripción | t resultado | Diferencia (s) | Pasa |
|---|---:|---:|---:|---|
| Buenos | 1.36 | 1.36 | 0.0 | sí |
| así | 9.66 | 9.66 | 0.0 | sí |
| cierro | 31.52 | 31.52 | 0.0 | sí |
| entonces | 41.2 | 41.2 | 0.0 | sí |
| salir. | 59.32 | 59.32 | 0.0 | sí |
| saco | 75.4 | 75.4 | 0.0 | sí |
| nuevo, | 92.46 | 92.46 | 0.0 | sí |
| cuarto | 101.22 | 101.22 | 0.0 | sí |
| solo | 116.6 | 116.6 | 0.0 | sí |
| cambio | 132.61 | 132.61 | 0.0 | sí |

### EXPLAIN ANALYZE de la consulta más lenta: «ahora retiro la carcasa, con la llave de carcasa aflojo el vaso girando a la izquierda, lo bajo con cuidado porque trae agua, saco el cartucho usado y lo meto a la bolsa de residuos, reviso el anillo de hule,»

Solo la sentencia principal (coincidencias, unión y orden); la de la frase trae a lo
más 50 ventanas por el único `(video_id, posicion)`.

```
Limit  (cost=62.03..62.03 rows=1 width=143) (actual time=1.803..1.807 rows=10 loops=1)
  Buffers: shared hit=726
  ->  Sort  (cost=62.03..62.03 rows=1 width=143) (actual time=1.802..1.805 rows=10 loops=1)
        Sort Key: v.creado DESC, c.video_id DESC, c.t_inicio, c.pos_ini
        Sort Method: quicksort  Memory: 26kB
        Buffers: shared hit=726
        ->  WindowAgg  (cost=52.84..62.02 rows=1 width=143) (actual time=1.760..1.764 rows=10 loops=1)
              Buffers: shared hit=717
              ->  Nested Loop Left Join  (cost=52.84..62.00 rows=1 width=135) (actual time=1.742..1.757 rows=10 loops=1)
                    Buffers: shared hit=717
                    ->  Nested Loop  (cost=52.70..61.18 rows=1 width=85) (actual time=1.739..1.751 rows=10 loops=1)
                          Buffers: shared hit=717
                          ->  Unique  (cost=52.56..52.62 rows=1 width=44) (actual time=1.733..1.737 rows=10 loops=1)
                                Buffers: shared hit=697
                                ->  Incremental Sort  (cost=52.56..52.61 rows=2 width=44) (actual time=1.733..1.736 rows=10 loops=1)
                                      Sort Key: c.video_id, c.cadena, c.t_inicio, c.pos_ini
                                      Presorted Key: c.video_id, c.cadena
                                      Full-sort Groups: 1  Sort Method: quicksort  Average Memory: 25kB  Peak Memory: 25kB
                                      Buffers: shared hit=697
                                      ->  WindowAgg  (cost=52.47..52.55 rows=2 width=44) (actual time=1.716..1.721 rows=10 loops=1)
                                            Buffers: shared hit=694
                                            ->  Incremental Sort  (cost=52.47..52.52 rows=2 width=36) (actual time=1.714..1.716 rows=10 loops=1)
                                                  Sort Key: c.video_id, c.cadena
                                                  Presorted Key: c.video_id
                                                  Full-sort Groups: 1  Sort Method: quicksort  Average Memory: 25kB  Peak Memory: 25kB
                                                  Buffers: shared hit=694
                                                  ->  Subquery Scan on c  (cost=52.40..52.46 rows=1 width=36) (actual time=1.697..1.708 rows=10 loops=1)
                                                        Buffers: shared hit=694
                                                        ->  WindowAgg  (cost=52.40..52.45 rows=1 width=40) (actual time=1.696..1.706 rows=10 loops=1)
                                                              Buffers: shared hit=694
                                                              ->  Subquery Scan on m  (cost=52.40..52.43 rows=1 width=32) (actual time=1.690..1.697 rows=10 loops=1)
                                                                    Buffers: shared hit=694
                                                                    ->  WindowAgg  (cost=52.40..52.43 rows=1 width=32) (actual time=1.690..1.696 rows=10 loops=1)
                                                                          Buffers: shared hit=694
                                                                          ->  Sort  (cost=52.40..52.41 rows=1 width=28) (actual time=1.682..1.684 rows=10 loops=1)
                                                                                Sort Key: p0.video_id, p0.t_inicio, p0.posicion
                                                                                Sort Method: quicksort  Memory: 25kB
                                                                                Buffers: shared hit=694
                                                                                ->  Nested Loop  (cost=5.46..52.39 rows=1 width=28) (actual time=0.200..1.671 rows=10 loops=1)
                                                                                      Join Filter: ((v_1.id = p3.video_id) AND (p3.posicion = (p0.posicion + 3)))
                                                                                      Rows Removed by Join Filter: 10
                                                                                      Buffers: shared hit=694
                                                                                      ->  Nested Loop  (cost=5.17..51.96 rows=1 width=44) (actual time=0.191..1.605 rows=10 loops=1)
                                                                                            Join Filter: ((v_1.id = p2.video_id) AND (p2.posicion = (p0.posicion + 2)))
                                                                                            Rows Removed by Join Filter: 40
                                                                                            Buffers: shared hit=662
                                                                                            ->  Nested Loop  (cost=4.89..50.99 rows=1 width=40) (actual time=0.177..1.555 rows=10 loops=1)
                                                                                                  Join Filter: ((v_1.id = p1.video_id) AND (p1.posicion = (p0.posicion + 1)))
                                                                                                  Buffers: shared hit=624
                                                                                                  ->  Nested Loop  (cost=4.60..50.60 rows=1 width=36) (actual time=0.159..1.512 rows=10 loops=1)
                                                                                                        Join Filter: (v_1.id = pf.video_id)
                                                                                                        Buffers: shared hit=594
                                                                                                        ->  Nested Loop  (cost=4.31..42.27 rows=1 width=20) (actual time=0.151..1.490 rows=10 loops=1)
                                                                                                              Buffers: shared hit=564
                                                                                                              ->  Seq Scan on videos v_1  (cost=0.00..10.39 rows=1 width=4) (actual time=0.004..0.028 rows=50 loops=1)
                                                                                                                    Filter: publicado
                                                                                                                    Rows Removed by Filter: 39
                                                                                                                    Buffers: shared hit=10
                                                                                                              ->  Bitmap Heap Scan on palabras p0  (cost=4.31..31.87 rows=1 width=16) (actual time=0.026..0.029 rows=0 loops=50)
                                                                                                                    Recheck Cond: (((palabra_normalizada)::text = 'ahora'::text) AND (video_id = v_1.id))
                                                                                                                    Filter: ((SubPlan 1) = '{ahora,retiro,la,carcasa,con,la,llave,de,carcasa,aflojo,el,vaso,girando,a,la,izquierda,lo,bajo,con,cuidado,porque,trae,agua,saco,el,cartucho,usado,y,lo,meto,a,la,bolsa,de,residuo,reviso,el,anillo,de,hul}'::text[])
                                                                                                                    Rows Removed by Filter: 2
                                                                                                                    Heap Blocks: exact=70
                                                                                                                    Buffers: shared hit=554
                                                                                                                    ->  Bitmap Index Scan on ix_palabras_palabra_normalizada_video_id_posicion  (cost=0.00..4.31 rows=2 width=0) (actual time=0.002..0.002 rows=2 loops=50)
                                                                                                                          Index Cond: (((palabra_normalizada)::text = 'ahora'::text) AND (video_id = v_1.id))
                                                                                                                          Buffers: shared hit=100
                                                                                                                    SubPlan 1
                                                                                                                      ->  Aggregate  (cost=10.09..10.10 rows=1 width=32) (actual time=0.011..0.011 rows=1 loops=110)
                                                                                                                            Buffers: shared hit=384
                                                                                                                            ->  Index Scan using uq_palabras_video_id_posicion on palabras p  (cost=0.29..10.09 rows=2 width=9) (actual time=0.002..0.006 rows=40 loops=110)
                                                                                                                                  Index Cond: ((video_id = p0.video_id) AND (posicion >= p0.posicion) AND (posicion <= (p0.posicion + 39)))
                                                                                                                                  Buffers: shared hit=384
                                                                                                        ->  Index Scan using uq_palabras_video_id_posicion on palabras pf  (cost=0.29..8.31 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=10)
                                                                                                              Index Cond: ((video_id = p0.video_id) AND (posicion = (p0.posicion + 39)))
                                                                                                              Buffers: shared hit=30
                                                                                                  ->  Index Only Scan using ix_palabras_palabra_normalizada_video_id_posicion on palabras p1  (cost=0.29..0.38 rows=1 width=8) (actual time=0.004..0.004 rows=1 loops=10)
                                                                                                        Index Cond: ((palabra_normalizada = 'retiro'::text) AND (video_id = pf.video_id))
                                                                                                        Heap Fetches: 10
                                                                                                        Buffers: shared hit=30
                                                                                            ->  Index Only Scan using ix_palabras_palabra_normalizada_video_id_posicion on palabras p2  (cost=0.29..0.68 rows=16 width=8) (actual time=0.004..0.004 rows=5 loops=10)
                                                                                                  Index Cond: ((palabra_normalizada = 'la'::text) AND (video_id = pf.video_id))
                                                                                                  Heap Fetches: 50
                                                                                                  Buffers: shared hit=38
                                                                                      ->  Index Only Scan using ix_palabras_palabra_normalizada_video_id_posicion on palabras p3  (cost=0.29..0.40 rows=2 width=8) (actual time=0.003..0.006 rows=2 loops=10)
                                                                                            Index Cond: ((palabra_normalizada = 'carcasa'::text) AND (video_id = pf.video_id))
                                                                                            Heap Fetches: 20
                                                                                            Buffers: shared hit=32
                          ->  Index Scan using pk_videos on videos v  (cost=0.14..8.16 rows=1 width=49) (actual time=0.001..0.001 rows=1 loops=10)
                                Index Cond: (id = c.video_id)
                                Buffers: shared hit=20
                    ->  Index Scan using pk_sops on sops s  (cost=0.14..0.77 rows=1 width=54) (actual time=0.000..0.000 rows=0 loops=10)
                          Index Cond: (id = v.sop_id)
Planning:
  Buffers: shared hit=294
Planning Time: 4.090 ms
Execution Time: 2.038 ms
```

## Corrida 2: A–E concatenadas hasta ~1500 palabras por video (2026-11-15T22:27:57)

Commit `1cfccb3` en `feat/s6` (8 archivos con cambios sin commit).

- Índice: 50 videos publicados (50 sembrados), 76020 palabras.
- **Palabras por video:** 1501–1547 (media 1520); minutos por video: 12.8–15.2 (media 14).
- 32 consultas × 5 repeticiones, tras 3 de calentamiento; `BUSQUEDA_UNIR_S=3`.
- **RNF-02 (< 1000 ms):** pasa · punta a punta p50 22.04 ms, p95 32.54 ms · servidor p50 17.05 ms, p95 27.4 ms.
- **RNF-03 (±1 s):** pasa (10 de 10).

### Por tipo de consulta (ms)

| Tipo | n | Servidor p50 | Servidor p95 | Punta p50 | Punta p95 | Punta máx |
|---|---:|---:|---:|---:|---:|---:|
| comun | 40 | 21.76 | 24.88 | 26.87 | 30.2 | 33.04 |
| rara | 40 | 15.82 | 18.54 | 21.05 | 23.58 | 24.04 |
| frase | 50 | 16.41 | 20.57 | 21.81 | 25.81 | 29.19 |
| frase_larga | 10 | 31.36 | 38.16 | 36.62 | 43.44 | 43.68 |
| sin_resultados | 20 | 4.44 | 10.73 | 9.46 | 15.98 | 16.38 |
| total | 160 | 17.05 | 27.4 | 22.04 | 32.54 | 43.68 |

### Consultas

| Tipo | Consulta | Tokens | Total | Devueltos | Servidor p50 | Punta p50 |
|---|---|---:|---:|---:|---:|---:|
| comun | el | 1 | 2990 | 50 | 24.78 | 30.10 |
| comun | de | 1 | 2390 | 50 | 22.78 | 27.49 |
| comun | la | 1 | 2380 | 50 | 22.01 | 26.74 |
| comun | the | 1 | 1130 | 50 | 19.58 | 24.52 |
| comun | y | 1 | 1390 | 50 | 21.77 | 27.80 |
| comun | I | 1 | 1130 | 50 | 19.79 | 24.95 |
| comun | a | 1 | 960 | 50 | 21.23 | 27.64 |
| comun | del | 1 | 980 | 50 | 18.98 | 24.81 |
| rara | dura. | 1 | 50 | 50 | 17.79 | 22.98 |
| rara | mica | 1 | 50 | 50 | 16.11 | 21.13 |
| rara | casi | 1 | 50 | 50 | 15.12 | 20.24 |
| rara | primer | 1 | 50 | 50 | 15.93 | 21.39 |
| rara | back. | 1 | 50 | 50 | 16.69 | 21.54 |
| rara | across | 1 | 50 | 50 | 15.51 | 20.57 |
| rara | stays, | 1 | 50 | 50 | 15.55 | 20.60 |
| rara | replaced. | 1 | 40 | 40 | 13.55 | 18.42 |
| frase | Buenos días, | 2 | 200 | 50 | 17.45 | 22.79 |
| frase | menos de 2 | 3 | 150 | 50 | 16.52 | 21.95 |
| frase | bien hasta aquí la | 4 | 50 | 50 | 17.80 | 22.65 |
| frase | mí El | 2 | 50 | 50 | 15.35 | 20.31 |
| frase | extension bar called | 3 | 50 | 50 | 15.44 | 20.36 |
| frase | agua, saco el cartucho | 4 | 90 | 50 | 19.46 | 24.55 |
| frase | nuevo limpio | 2 | 40 | 40 | 15.87 | 21.40 |
| frase | cuarteado. Retomo yo, | 3 | 40 | 40 | 16.31 | 21.90 |
| frase | la puerta de acrílico | 4 | 90 | 50 | 18.48 | 23.48 |
| frase | has been | 2 | 40 | 40 | 13.39 | 18.32 |
| frase_larga | Con la llave de la carcasa aflojo el vaso girando a la | 12 | 50 | 50 | 27.39 | 32.51 |
| frase_larga | ahora retiro la carcasa, con la llave de carcasa aflojo el vaso girando a la izquierda, lo bajo con cuidado porque trae agua, saco el cartucho usado y lo meto a la bolsa de residuos, reviso el anillo de hule, | 40 | 50 | 50 | 36.26 | 41.77 |
| sin_resultados | zzxq | 1 | 0 | 0 | 4.32 | 9.19 |
| sin_resultados | xilófono | 1 | 0 | 0 | 4.40 | 9.53 |
| sin_resultados | válvula cuántica intergaláctica | 3 | 0 | 0 | 4.42 | 9.20 |
| sin_resultados | esta frase nadie la dijo nunca | 6 | 0 | 0 | 10.71 | 15.78 |

### RNF-03: 10 palabras de video_a (video 0, que empieza por ella sin desplazar; si la palabra se repite más adelante en el video, cuenta el primer resultado)

| Palabra | t transcripción | t resultado | Diferencia (s) | Pasa |
|---|---:|---:|---:|---|
| Buenos | 1.36 | 1.36 | 0.0 | sí |
| así | 9.66 | 9.66 | 0.0 | sí |
| cierro | 31.52 | 31.52 | 0.0 | sí |
| entonces | 41.2 | 41.2 | 0.0 | sí |
| salir. | 59.32 | 59.32 | 0.0 | sí |
| saco | 75.4 | 75.4 | 0.0 | sí |
| nuevo, | 92.46 | 92.46 | 0.0 | sí |
| cuarto | 101.22 | 101.22 | 0.0 | sí |
| solo | 116.6 | 116.6 | 0.0 | sí |
| cambio | 132.61 | 132.61 | 0.0 | sí |

### EXPLAIN ANALYZE de la consulta más lenta: «ahora retiro la carcasa, con la llave de carcasa aflojo el vaso girando a la izquierda, lo bajo con cuidado porque trae agua, saco el cartucho usado y lo meto a la bolsa de residuos, reviso el anillo de hule,»

Solo la sentencia principal (coincidencias, unión y orden); la de la frase trae a lo
más 50 ventanas por el único `(video_id, posicion)`.

```
Limit  (cost=347.29..347.30 rows=5 width=143) (actual time=7.793..7.802 rows=50 loops=1)
  Buffers: shared hit=3173
  ->  Sort  (cost=347.29..347.30 rows=5 width=143) (actual time=7.792..7.798 rows=50 loops=1)
        Sort Key: v.creado DESC, u.video_id DESC, u.t_inicio, u.pos_ini
        Sort Method: quicksort  Memory: 31kB
        Buffers: shared hit=3173
        ->  WindowAgg  (cost=329.36..347.23 rows=5 width=143) (actual time=7.745..7.757 rows=50 loops=1)
              Buffers: shared hit=3164
              ->  Nested Loop Left Join  (cost=329.36..347.17 rows=5 width=135) (actual time=7.307..7.730 rows=50 loops=1)
                    Buffers: shared hit=3164
                    ->  Nested Loop  (cost=329.23..343.27 rows=5 width=85) (actual time=7.301..7.708 rows=50 loops=1)
                          Join Filter: (v.id = u.video_id)
                          Rows Removed by Join Filter: 4400
                          Buffers: shared hit=3164
                          ->  Seq Scan on videos v  (cost=0.00..10.39 rows=39 width=49) (actual time=0.004..0.024 rows=89 loops=1)
                                Buffers: shared hit=10
                          ->  Materialize  (cost=329.23..329.97 rows=5 width=36) (actual time=0.082..0.084 rows=50 loops=89)
                                Buffers: shared hit=3154
                                ->  Subquery Scan on u  (cost=329.23..329.94 rows=5 width=36) (actual time=7.293..7.317 rows=50 loops=1)
                                      Buffers: shared hit=3154
                                      ->  Unique  (cost=329.23..329.89 rows=5 width=44) (actual time=7.292..7.311 rows=50 loops=1)
                                            Buffers: shared hit=3154
                                            ->  Incremental Sort  (cost=329.23..329.87 rows=5 width=44) (actual time=7.292..7.305 rows=50 loops=1)
                                                  Sort Key: c.video_id, c.cadena, c.t_inicio, c.pos_ini
                                                  Presorted Key: c.video_id, c.cadena
                                                  Full-sort Groups: 2  Sort Method: quicksort  Average Memory: 27kB  Peak Memory: 27kB
                                                  Buffers: shared hit=3154
                                                  ->  WindowAgg  (cost=329.11..329.64 rows=5 width=44) (actual time=7.246..7.285 rows=50 loops=1)
                                                        Buffers: shared hit=3151
                                                        ->  Incremental Sort  (cost=329.11..329.55 rows=5 width=36) (actual time=7.242..7.265 rows=50 loops=1)
                                                              Sort Key: c.video_id, c.cadena
                                                              Presorted Key: c.video_id
                                                              Full-sort Groups: 2  Sort Method: quicksort  Average Memory: 27kB  Peak Memory: 27kB
                                                              Buffers: shared hit=3151
                                                              ->  Subquery Scan on c  (cost=329.04..329.33 rows=5 width=36) (actual time=7.204..7.252 rows=50 loops=1)
                                                                    Buffers: shared hit=3151
                                                                    ->  WindowAgg  (cost=329.04..329.28 rows=5 width=40) (actual time=7.204..7.248 rows=50 loops=1)
                                                                          Buffers: shared hit=3151
                                                                          ->  Subquery Scan on m  (cost=329.04..329.18 rows=5 width=32) (actual time=7.195..7.219 rows=50 loops=1)
                                                                                Buffers: shared hit=3151
                                                                                ->  WindowAgg  (cost=329.04..329.18 rows=5 width=32) (actual time=7.195..7.215 rows=50 loops=1)
                                                                                      Buffers: shared hit=3151
                                                                                      ->  Sort  (cost=329.04..329.05 rows=5 width=28) (actual time=7.180..7.183 rows=50 loops=1)
                                                                                            Sort Key: p0.video_id, p0.t_inicio, p0.posicion
                                                                                            Sort Method: quicksort  Memory: 27kB
                                                                                            Buffers: shared hit=3151
                                                                                            ->  Nested Loop  (cost=6.08..328.98 rows=5 width=28) (actual time=0.148..7.162 rows=50 loops=1)
                                                                                                  Join Filter: (v_1.id = pf.video_id)
                                                                                                  Buffers: shared hit=3151
                                                                                                  ->  Nested Loop  (cost=5.78..315.33 rows=1 width=32) (actual time=0.143..7.070 rows=50 loops=1)
                                                                                                        Join Filter: ((v_1.id = p3.video_id) AND (p3.posicion = (p0.posicion + 3)))
                                                                                                        Rows Removed by Join Filter: 200
                                                                                                        Buffers: shared hit=3001
                                                                                                        ->  Nested Loop  (cost=5.37..313.30 rows=1 width=28) (actual time=0.134..6.780 rows=50 loops=1)
                                                                                                              Join Filter: ((v_1.id = p1.video_id) AND (p1.posicion = (p0.posicion + 1)))
                                                                                                              Rows Removed by Join Filter: 40
                                                                                                              Buffers: shared hit=2729
                                                                                                              ->  Nested Loop  (cost=4.95..311.57 rows=1 width=24) (actual time=0.125..6.623 rows=50 loops=1)
                                                                                                                    Join Filter: (v_1.id = p2.video_id)
                                                                                                                    Buffers: shared hit=2489
                                                                                                                    ->  Nested Loop  (cost=4.53..303.11 rows=1 width=20) (actual time=0.109..6.413 rows=50 loops=1)
                                                                                                                          Buffers: shared hit=2289
                                                                                                                          ->  Seq Scan on videos v_1  (cost=0.00..10.39 rows=1 width=4) (actual time=0.002..0.039 rows=50 loops=1)
                                                                                                                                Filter: publicado
                                                                                                                                Rows Removed by Filter: 39
                                                                                                                                Buffers: shared hit=10
                                                                                                                          ->  Bitmap Heap Scan on palabras p0  (cost=4.53..292.71 rows=1 width=16) (actual time=0.084..0.126 rows=1 loops=50)
                                                                                                                                Recheck Cond: (((palabra_normalizada)::text = 'ahora'::text) AND (video_id = v_1.id))
                                                                                                                                Filter: ((SubPlan 1) = '{ahora,retiro,la,carcasa,con,la,llave,de,carcasa,aflojo,el,vaso,girando,a,la,izquierda,lo,bajo,con,cuidado,porque,trae,agua,saco,el,cartucho,usado,y,lo,meto,a,la,bolsa,de,residuo,reviso,el,anillo,de,hul}'::text[])
                                                                                                                                Rows Removed by Filter: 9
                                                                                                                                Heap Blocks: exact=328
                                                                                                                                Buffers: shared hit=2279
                                                                                                                                ->  Bitmap Index Scan on ix_palabras_palabra_normalizada_video_id_posicion  (cost=0.00..4.53 rows=11 width=0) (actual time=0.004..0.004 rows=10 loops=50)
                                                                                                                                      Index Cond: (((palabra_normalizada)::text = 'ahora'::text) AND (video_id = v_1.id))
                                                                                                                                      Buffers: shared hit=150
                                                                                                                                SubPlan 1
                                                                                                                                  ->  Aggregate  (cost=22.54..22.55 rows=1 width=32) (actual time=0.010..0.010 rows=1 loops=520)
                                                                                                                                        Buffers: shared hit=1801
                                                                                                                                        ->  Index Scan using uq_palabras_video_id_posicion on palabras p  (cost=0.29..22.51 rows=9 width=9) (actual time=0.002..0.006 rows=39 loops=520)
                                                                                                                                              Index Cond: ((video_id = p0.video_id) AND (posicion >= p0.posicion) AND (posicion <= (p0.posicion + 39)))
                                                                                                                                              Buffers: shared hit=1801
                                                                                                                    ->  Index Only Scan using ix_palabras_palabra_normalizada_video_id_posicion on palabras p2  (cost=0.42..8.44 rows=1 width=8) (actual time=0.004..0.004 rows=1 loops=50)
                                                                                                                          Index Cond: ((palabra_normalizada = 'la'::text) AND (video_id = p0.video_id) AND (posicion = (p0.posicion + 2)))
                                                                                                                          Heap Fetches: 50
                                                                                                                          Buffers: shared hit=200
                                                                                                              ->  Index Only Scan using ix_palabras_palabra_normalizada_video_id_posicion on palabras p1  (cost=0.42..1.70 rows=2 width=8) (actual time=0.002..0.003 rows=2 loops=50)
                                                                                                                    Index Cond: ((palabra_normalizada = 'retiro'::text) AND (video_id = p2.video_id))
                                                                                                                    Heap Fetches: 90
                                                                                                                    Buffers: shared hit=240
                                                                                                        ->  Index Only Scan using ix_palabras_palabra_normalizada_video_id_posicion on palabras p3  (cost=0.42..1.86 rows=10 width=8) (actual time=0.003..0.005 rows=5 loops=50)
                                                                                                              Index Cond: ((palabra_normalizada = 'carcasa'::text) AND (video_id = p2.video_id))
                                                                                                              Heap Fetches: 250
                                                                                                              Buffers: shared hit=272
                                                                                                  ->  Index Scan using uq_palabras_video_id_posicion on palabras pf  (cost=0.29..13.60 rows=4 width=16) (actual time=0.001..0.001 rows=1 loops=50)
                                                                                                        Index Cond: ((video_id = p0.video_id) AND (posicion = (p0.posicion + 39)))
                                                                                                        Buffers: shared hit=150
                    ->  Index Scan using pk_sops on sops s  (cost=0.14..0.77 rows=1 width=54) (actual time=0.000..0.000 rows=0 loops=50)
                          Index Cond: (id = v.sop_id)
Planning:
  Buffers: shared hit=292
Planning Time: 3.663 ms
Execution Time: 7.997 ms
```
