# ADR-009 · Mantener `has_errors` como tarea de ML académica

- **Estado:** Aprobado por el equipo · pendiente de visto bueno del asesor
- **Fecha:** 2026-10-10
- **Autores:** Emmanuel Merida
- **Decisores:** equipo + asesor (Dr. Gerardo Jesús Camacho González)

---

## Contexto

Los avances 2–5 de TC5035 piden una tarea supervisada: ingeniería de características, baseline,
seis modelos individuales y ensambles. El avance 1 exploró **CaptainCook4D** con la variable objetivo
`has_errors` (si un paso se ejecutó con error). Esa tarea no alimenta directamente el MVP, que
necesita **segmentar la narración del experto en pasos con su segundo exacto**. Por eso, el 10 oct se
evaluó cambiar la tarea a un **clasificador de inicio de paso** (dada una frase de la narración,
¿empieza en ella un paso?). Ese clasificador necesita, a la vez, (1) la narración transcrita con
tiempos y (2) los inicios de paso marcados.

## Opciones consideradas y evidencia

| Opción | Resultado de la verificación (10 oct) |
|---|---|
| **CrossTask** (2,750 videos con pasos anotados) | Las anotaciones se descargan, pero los subtítulos responden 403 y los videos ya no están en YouTube. Sin narración. **Descartada.** |
| **HT-Step + ASR de HowTo100M** (`Jazzcharles/HowTo100M_llama3_refined_caption`) | 16,636 videos y 408,953 frases cruzan con HT-Step, pero la transcripción está **submuestreada** (~60 palabras/min frente a 120–160 de habla normal; una frase cada ~15 s). Contra una etiqueta construida con inicios aleatorios, ~74 % de los positivos se explican por azar. **Descartada.** |
| **HT-Step + subtítulos `.vtt` completos** (`TornadoLabs/howto100m`) | Transcripción completa (137 palabras/min, tiempo por palabra), pero solo 130 videos. Con segmentos de habla, los marcados con inicios reales casi no difieren de los marcados al azar (inician con transición 7 % vs 5 %; misma pausa previa). **Causa:** HT-Step marca el inicio de la **acción visual**, no el momento en que el narrador lo **anuncia**. **Descartada.** |
| **`has_errors` sobre CaptainCook4D** | Datos listos, continuidad con el avance 1 y avance 2 ya construido (`sopvid.features`). **Elegida.** |

## Decisión

Los avances 2–5 siguen con **`has_errors` sobre CaptainCook4D**. El clasificador de inicio de paso
no es tarea académica. Las etiquetas públicas de pasos no siguen a la narración, así que una
etiqueta útil para el producto tiene que hacerse **sobre la narración** (anotación propia o
corrección del experto). La segmentación del producto se decide en [ADR-010](ADR-010-segmentacion-pasos-llm.md).

## Consecuencias

- **Positivas:** continuidad con el avance 1, sin riesgo para la entrega del 11 oct. La exploración
  deja código reutilizable para el producto: parser de `.vtt` con tiempo por palabra
  (`scripts/preparar_htstep_vtt.py`) y segmentación de habla por pausas (rama
  `avance2-inicio-paso`).
- **Negativas / riesgos:** el modelo académico no se integra directamente al MVP. A futuro sirve como
  base de las "advertencias" del copiloto en vivo (Producto B, fuera del trimestre).
- **Seguimiento:** confirmar con el asesor (correo del 13 oct). Si después se dispone de etiquetas
  sobre narración (videos propios o supervisión débil con un LLM), reevaluar con un ADR nuevo.

## Referencias

- [HT-Step](https://github.com/facebookresearch/htstep) (CC-BY-NC 4.0) ·
  [CrossTask](https://github.com/DmZhukov/CrossTask) ·
  [HowTo100M_llama3_refined_caption](https://huggingface.co/datasets/Jazzcharles/HowTo100M_llama3_refined_caption) ·
  [TornadoLabs/howto100m](https://huggingface.co/datasets/TornadoLabs/howto100m)
- Rama `avance2-inicio-paso`: código de la exploración. `docs/plan/estado.md`: resumen del 10 oct.
