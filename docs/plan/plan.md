# Plan de desarrollo · AI Co-Pilot Video-to-SOP

- **Versión:** 10 oct 2026 (convertido del diagnóstico `index.html` del proyecto)
- **Estado:** vigente; se revisa cada semana
- **Fuentes:** Brief v1.0, reunión "SOPVID Meeting" del 3 oct (partes 1 y 2), NDA Alignity–Tec,
  Reglamento PI MNA 2026, descripciones de los avances 2–5, paper CRISP-ML(Q).
- Este documento no contiene datos del cliente. Lo que no aparece en las fuentes se marca *Por confirmar*.

---

## 1. Resumen ejecutivo

Partiendo de cero, con ~1 persona efectiva más un apoyo parcial y ~9 semanas, lo viable es una
**columna vertebral de voz**: video → transcripción con timestamps → pasos indexados → búsqueda y
chat que llevan al segundo exacto. Es lo que el patrocinador priorizó en la reunión.

- **Objetivo académico:** avances 2–5 bajo CRISP-ML(Q), resumen ejecutivo (semana 9) y presentación final (penúltima semana).
- **Objetivo de negocio:** demo con datos reales y arranque de piloto en noviembre 2026 (fecha *Por confirmar*).
- **Producto A (buscador / generador de SOPs):** obligatorio, en su versión centrada en la voz.
- **Producto B (copiloto en vivo):** diferido; solo se define la interfaz de fuente de video.

**Restricciones:** costo cero · NDA (nada del cliente en el repo; rostros = dato personal, LFPDPPP) ·
portabilidad (contenedores, pesos abiertos, variables de entorno) · Colab T4 de 16 GB (GPU de 24 GB *Por confirmar*).

> **Desarrollo desde cero: dejar constancia.** El NDA (cl. 1) y el brief (§2) obligan a mejorar el código
> heredado, no a reescribirlo. Se ofreció compartirlo (reunión, 42:49) y no se entregó. Hay que pedir al
> patrocinador una confirmación por correo y registrarla en ADR-001.

### Alcance ajustado vs. brief

| Nivel del brief | Viable | Nota |
|---|---|---|
| Mínimo: 1 video → SOP aprobado y medido | Parcial | Columna de voz medida, sí. SOP aprobado solo si sobra tiempo. |
| Esperado: multi-video, preguntas inteligentes, plataforma | Mínimo | Solo aclaración con menús de etiquetas. |
| Extendido: copiloto en vivo y lentes | No | — |

---

## 2. Brief vs. reunión y ADRs

> **Hallazgo crítico:** el NDA (cl. 1) obliga a usar como base V-JEPA 2, Gemma 4, Whisper/Voxtral,
> HITL de tres bucles y grafo de tareas multi-video. Diferir cualquiera requiere **aprobación escrita del patrocinador**.

| Tema | Brief / NDA | Reunión (3 oct) | Reconciliación |
|---|---|---|---|
| Fuente de verdad | Visión confirma, audio propone | "Hoy el camino es la voz" (30:25) | Voz como fuente; pasos sin respaldo visual = "no verificado" |
| Percepción visual | V-JEPA 2 + attentive probes | Qwen sobre fotogramas | Ambos fuera del camino crítico |
| LLM | Gemma 4 26B A4B (~15 GB en 4 bits) | Modelo pequeño que pregunta antes de buscar | Gemma 4 en la variante que quepa; MVP aclara con menús |
| Estructura | Grafo de orden parcial multi-video | — | Un video = lista ordenada; el esquema admite grafo después |
| Interfaz | Conversacional, por voz | Carga + chat tipo ChatGPT con videos al lado | Dos pantallas, chat de texto; voz diferida |
| Entrada | Video + SOP de referencia | Etiquetado y carga de procedimientos | Etiquetado al MVP; PDF si sobra tiempo |
| Roles | 5 roles | Cargador y administrador | Esquema diseñado; roles si sobra tiempo |
| Código heredado | Mejorar, no reescribir | Se compartiría (42:49) | No llegó; desde cero con ADR-001 |

### ADRs

| ADR | Decisión | Aprueba | Cuándo | Estado |
|---|---|---|---|---|
| ADR-001 | Desarrollo desde cero; el POC queda como referencia funcional | Patrocinador (escrito) | Esta semana | Propuesto |
| ADR-002 | Voz como fuente principal; V-JEPA 2 y fotogramas diferidos | Patrocinador (escrito) | Reunión del viernes | Pendiente |
| ADR-003 | Grafo multi-video diferido; un video = lista ordenada de pasos | Patrocinador (escrito) | Reunión del viernes | Pendiente |
| ADR-004 | Alcance ajustado por capacidad del equipo | Asesor + patrocinador | Esta semana | Pendiente |
| ADR-005 | PostgreSQL + pgvector en lugar del disco temporal de Colab | Equipo | S1 | Pendiente |
| ADR-006 | LLM: variante de Gemma 4 que quepa, servida localmente | Equipo | S2 | Pendiente |
| ADR-007 | Frontend en Angular, igual que el POC, desde cero | Equipo + patrocinador | S1 | Pendiente |
| ADR-008 | SOP y revisión humana como opcionales; HITL de tres bucles fuera del MVP | Patrocinador (escrito) | Reunión del viernes | Pendiente |
| ADR-009 | Tarea de ML académica: `has_errors` (CaptainCook4D) | Asesor | Esta semana | Aprobado (equipo), falta asesor |
| ADR-010 | Segmentación en pasos: LLM local que elige segmentos + corrección del experto; heurística de respaldo | Equipo + patrocinador | Reunión del viernes | Propuesto |

> **ADR-009 y ADR-010 (10 oct).** Se probó un *clasificador de inicio de paso* con tres fuentes
> públicas (CrossTask; HT-Step + ASR submuestreada de HowTo100M; HT-Step + `.vtt` completos). Ninguna
> sirve: las etiquetas públicas marcan la acción visual, no el anuncio del narrador. Los avances siguen
> con `has_errors`. En el producto, los pasos los propone un **LLM local que elige segmentos numerados**
> (los tiempos salen del índice), con heurística de respaldo y corrección del experto (HITL). Ver
> [ADR-009](../adr/ADR-009-tarea-ml.md), [ADR-010](../adr/ADR-010-segmentacion-pasos-llm.md) y [estado.md](estado.md).

---

## 3. Estado actual

| Módulo | Estado | Nota |
|---|---|---|
| EDA (avance 1, CaptainCook4D) | Entregado | Funciones migradas sin cambios a `sopvid.features` (`data`, `preprocessing`) y verificadas contra el notebook |
| Ingeniería de características (avance 2) | Listo para revisión | `sopvid.features.engineering` + `Avance2.51.ipynb`; `build_features` es la entrada del avance 3 |
| Interfaz web (2 pantallas) | Referencia POC | Angular, desde cero |
| Ingesta por partes de 25 MB | Referencia POC | Técnica conocida (11:31) |
| Transcripción e idioma | Referencia POC | Mejora: faster-whisper, palabra a palabra, VAD, WER |
| Búsqueda exacta + semántica | Referencia POC | Índice persistente y métricas |
| Salto al segundo exacto | Referencia POC | Lo más valorado en la demo (40:16) |
| Despliegue | Referencia POC | Local con Docker; Colab solo worker |
| Etiquetado de videos | Pendiente | Base del aclarador (P2 0:16–0:35) |
| Chat conversacional | Pendiente | P2 1:36 |
| Aclaración antes de buscar | Pendiente | MVP con menús |
| Métricas y evaluación | Pendiente | Obligatorio |
| Generación de SOP / HITL / roles / PDF | Si sobra tiempo | — |
| Fotogramas, voz, copiloto en vivo | Diferido | — |

**Repositorio (10 oct):** andamiaje F0 en `main` (4 commits, CI en verde): paquete `src/sopvid`
(plataforma, percepcion, lenguaje, features), API con `/health`, Docker Compose (API + Postgres/pgvector),
Alembic, tests, CI y `CONTRIBUTING.md`. `.env` renombrado a `.env.example` y ADR-001 de herencia movido
a `docs/adr/ADR-001-herencia.md`. `docker compose up` verificado localmente (criterio técnico de F0
cumplido; falta enviar ADR-001). Sin commit: `sopvid.features`, el avance 2, `CLAUDE.md` y este plan.
Pendiente: **hacer privado el repositorio** (hoy es público en GitHub), probar en una máquina limpia y
actualizar la sección 1 del README ("segunda iteración") cuando se apruebe ADR-001.
---

## 4. MVP para la demo

**Indispensable**
- Carga de video por partes con etiquetas
- Transcripción con timestamps por palabra
- Pasos indexados con minuto y segundo
- Búsqueda exacta + semántica que reproduce desde el segundo
- Chat con respuesta citada y "no encontré" sin evidencia
- Persistencia (sin reprocesar al reiniciar)
- Arranque con un comando en máquina limpia

**Importante**
- Pregunta aclaratoria con menús de etiquetas (máquina / área)
- Siguiente paso y advertencias en la respuesta
- Métricas generadas por código

**Si sobra tiempo (en orden):** borrador de SOP trazable → aprobación humana con versión →
roles cargador/administrador y bitácora → carga de PDF → aclarador con LLM.

**Fuera del trimestre:** V-JEPA 2 y fotogramas · grafo multi-video · voz, diadema y lentes ·
Producto B · unidad NVIDIA por organización · multi-inquilino, auditor, cifrado en reposo · attentive probes.

---

## 5. Fases

Obligatorias: ~8.5 semanas-persona contra ~9 disponibles.

| Fase | Objetivo | Funcionalidades | Est. | Criterio de cierre |
|---|---|---|---|---|
| **F0** Arranque | Proyecto nuevo y constancia de partir de cero | Correo al patrocinador; ADR-001–004; estructura, README, `.env.example`, Docker Compose (API + Postgres), issues | 0.5 | `docker compose up` levanta API y base vacías; ADR-001 enviado |
| **F1** Columna de voz | Un video recorre ingesta → índice con persistencia | Carga por partes, etiquetas, faster-whisper, limpieza, segmentación en pasos (heurística → LLM, ADR-010), índice, búsqueda, Pantalla 1 | 2.5 | Regresión con video de referencia; reinicio sin reprocesar |
| **F2** Medición | Números generados por código | Conjunto sellado, `evaluate.py`, WER, F1 de fronteras, Recall@k, MRR, error de timestamp | 1 | Métricas del baseline guardadas con su commit |
| **F3** Búsqueda híbrida y chat | Segundo exacto, siguiente paso y citas | Texto completo + vectores + RRF, umbral de abstención, chat RAG, Pantalla 2 | 1.5 | Recall@5 > baseline; 100 % de respuestas con cita válida · **checkpoint: columna estable** |
| **F4** Modelo académico | Tarea de ML de los avances 2–5 integrada | Características, baseline, 6 modelos, ensambles, integración | 0.5 extra | Mejor que la heurística en el conjunto sellado |
| **F5** Aclaración y pulido | Cerrar el MVP | Etiquetas en el chat, menús aclaratorios, siguiente paso, errores | 0.5 | Preguntas ambiguas piden máquina/área; regresión en verde |
| **F+** Opcional | Acercar al brief sin arriesgar la demo | SOP → aprobación → roles → PDF → aclarador LLM | — | Solo si no rompe la regresión |
| **F6** Portabilidad y demo | Demo reproducible con datos del cliente | Máquina limpia, CI, perfil de hardware, ingesta del cliente, ensayo | 1 | Arranque ≤ 30 min; ensayo completo |
| **F7** Cierre | Académico y transferencia (NDA cl. 8) | Resumen ejecutivo, presentación, release, paquete de transferencia | 1 | Release etiquetado en el repo del patrocinador |

**Regla para el integrante de apoyo:** solo tareas acotadas, independientes y no bloqueantes (grabar
videos, anotar preguntas de evaluación, resumir papers, pruebas manuales, documentación), cada una
como issue con su nombre.

---

## 6. Roadmap

| Semana | Fase | Técnico | Académico |
|---|---|---|---|
| S0 · 5–11 oct | F0 | Correo de no entrega, ADR-001, estructura, Docker base | **Avance 2 (11 oct)** |
| S1 · 12–18 oct | F1 | Carga por partes, faster-whisper, persistencia | Avance 3 (18 oct) |
| S2 · 19–25 oct | F1 + F2 | Segmentación, índice, conjunto de evaluación | Avance 4 (25 oct) |
| S3 · 26 oct–1 nov | F1 + F3 | Pantalla 1 con salto al segundo, búsqueda | Avance 5 (1 nov) |
| S4 · 2–8 nov | F3 + F4 | Búsqueda híbrida, chat RAG, modelo integrado · ✓ columna estable | — |
| S5 · 9–15 nov | F5 + F+ | Aclaración, pulido · ✓ MVP completo | — |
| S6 · 16–22 nov | F6 | Máquina limpia, CI, datos del cliente, ensayo | — |
| S7 · 23–29 nov | F7 | Demo con el cliente (*Por confirmar*) | Resumen ejecutivo (*Por confirmar*) |
| S8 · 30 nov–6 dic | F7 | Paquete de transferencia | Presentación final (*Por confirmar*) |
| S9 · 7–13 dic | F7 | Release y entrega (NDA cl. 8) | Cierre |

### Próximos pasos inmediatos

- **Sáb 10 oct (hecho):** estructura F0 en `main`; avance 2 ejecutable, con justificaciones en borrador.
- **Dom 11 oct:** revisar el avance 2 (justificaciones, conclusión y decisión sobre `rec_duration`) y entregarlo; hacer privado el repositorio.
- **Lun 12:** correo al patrocinador sobre la no entrega del código; ADR-001.
- **Mar 13:** correo al asesor con el ajuste de alcance, el reparto real del equipo y la decisión de ADR-009.
- **Mié 14–jue 15:** pipeline ffmpeg → whisper → JSON persistido en Postgres.
- **Vie 16:** reunión con el patrocinador: ADRs, código, layouts, video y etiquetas.
- **Dom 18:** avance 3 (baseline).

---

## 7. Arquitectura

Una API sirve dos pantallas. El pipeline procesa cada video una vez; el chat solo lee el índice,
única fuente de timestamps.

```
Ingesta (partes 25 MB + etiquetas)
  → Transcripción (faster-whisper, VAD, palabra a palabra)
  → [Fotogramas: diferido]
  → Indexación (pasos, segmentos, vectores)
  → Búsqueda / chat (aclarar → buscar → citar)
  → [SOP y revisión humana: si sobra tiempo]
```

| Componente | Responsabilidad |
|---|---|
| Pantalla 1 · Carga y análisis (Angular) | Subir, etiquetar, ver pasos, reproducir desde el segundo |
| Pantalla 2 · Chat (Angular) | Pregunta, aclaración, respuesta con mm:ss y fragmentos al lado |
| API FastAPI | `/videos`, `/pasos`, `/search`, `/chat` (si sobra tiempo: `/sop`, roles, bitácora) |
| Pipeline offline | ffmpeg → faster-whisper (tiempo por palabra) → segmentos de habla por pausas → pasos (LLM elige segmentos; heurística de respaldo) → embeddings + texto completo |
| Orquestador | Aclarador (menús) · Buscador (híbrido + umbral) · Redactor (solo lo recuperado, con citas) |
| PostgreSQL + pgvector | Videos, etiquetas, segmentos, pasos, vectores; tablas de SOP/usuarios previstas |
| Almacenamiento de medios | Volumen aprobado fuera del repo; el repo guarda identificadores |
| Evolución | Producto B (fuente de video → voz en streaming → copiloto); V-JEPA 2 por segmento; grafo multi-video |

**Roles:** Operador/consulta (MVP, sin login) · Cargador experto y Administrador (si sobra tiempo) · Auditor (diferido).

---

## 8. Riesgos principales

| Riesgo | Impacto | Prob. | Mitigación |
|---|---|---|---|
| Bus factor = 1 | Alto | Alta | README y ADRs al día; todo en el repo; demo con un comando |
| Carga desigual y evaluación | Alto | Alta | Issues con nombre, PRs; informar al asesor por escrito |
| Capacidad vs. brief para 3 personas | Alto | Alta | ADR-004, MVP en niveles, backlog en transferencia |
| Arquitectura del NDA no cumplida | Alto | Media | Aprobación escrita de ADR-002, 003 y 008 |
| Desde cero contradice NDA y brief | Alto | Media | Correo del patrocinador + ADR-001 fechado |
| Subestimar el arranque desde cero | Alto | Media | F1 con 2.5 semanas; checkpoint 8 nov |
| Plazos académicos semanales | Alto | Media | Notebooks que importan módulos del repo |
| Alucinación en respuestas | Alto | Media | Timestamps del índice, citas obligatorias, abstención |
| Fuga de datos del cliente | Alto | Baja | Nada del cliente en repo ni en la nube; revisión de PRs |
| Repositorio público en GitHub (NDA) | Alto | Ocurrido | Cambiar a privado de inmediato; hoy solo contiene código y documentos propios |
| Modelo académico apoyado en artefactos del dataset (`rec_duration`) | Medio | Alta | Reportar con y sin características de grabación; validación agrupada por grabación |
| Angular consume la ruta crítica | Medio | Alta | API probada sola; Angular desde S3, mínimo |
| Datos del cliente tardíos | Medio | Alta | Columna con videos propios; cliente solo en F6 |
| Ruido de planta en el audio | Medio | Alta | VAD, modelo mayor en GPU, WER por nivel de ruido |
| Dependencia de Colab | Medio | Alta | Local con Docker; Colab solo transcribe |
| GPU insuficiente | Medio | Media | LLM cuantizado 3–8B; perfil de hardware |
| El código del POC llega tarde | Medio | Media | Integrar solo si ahorra trabajo comprobable, vía ADR |

---

## 9. Preguntas pendientes

### Patrocinador
1. ¿Aprueba por escrito diferir V-JEPA 2, el grafo multi-video y la revisión humana? *(Alta)*
2. ¿Confirma que el código del POC no se entregará y autoriza partir de cero? *(Alta)*
3. ¿Fecha exacta de la demo y si incluye piloto? *(Alta)*
4. ¿Qué videos y SOPs se liberan, cuándo y dónde se almacenan? *(Alta)*
5. ¿Repositorio y organización GitHub definitivos? *(Alta)*
6. ¿Lista real de etiquetas (máquinas, áreas, procesos)? *(Media)*
7. ¿Puede compartir componentes o layouts de Angular del POC? *(Media)*
8. ¿Hay GPU de 24 GB disponible? *(Media)*
9. ¿Se exige anonimizar rostros en la demo? *(Media)*

### Asesor
1. ¿Se acepta el alcance ajustado (ADR-004) como base de evaluación? *(Alta)*
2. ¿Se evalúa como segunda iteración o como desarrollo nuevo? *(Alta)*
3. ¿Cómo se evalúa la contribución individual con un equipo desigual? *(Alta)*
4. ¿Acepta cambiar al clasificador de inicio de paso desde el avance 3 si para entonces hay datos? *(Alta)*
5. ¿Fechas exactas del resumen ejecutivo y la presentación? *(Media)*
6. ¿Se exige el paper IEEE/ACM de 4–6 páginas del brief? *(Media)*
7. ¿Política sobre uso de asistentes de IA para programar? *(Media)*
8. ¿Bastan datos propios y públicos si no se liberan los del cliente? *(Media)*

---

## 10. Orden de implementación

1. Repositorio, ADRs y conjunto de evaluación anotado
2. Ingesta persistente y transcripción con timestamps
3. Segmentación en pasos (heurística → LLM que elige segmentos; el experto corrige)
4. Índice híbrido y búsqueda al segundo exacto (Pantalla 1)
5. Métricas y regresión → **checkpoint de columna estable**
6. Chat RAG con citas, siguiente paso y abstención (Pantalla 2)
7. Etiquetado + pregunta aclaratoria con menús
8. Docker en máquina limpia, datos del cliente en entorno aprobado, ensayo de demo
9. Resumen ejecutivo, presentación y paquete de transferencia
10. *Si sobra tiempo:* SOP → aprobación → roles y bitácora → PDF → aclarador con LLM
