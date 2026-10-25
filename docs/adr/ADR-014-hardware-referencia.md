# ADR-014 · Usar la PC del equipo como hardware de referencia y correr los modelos en secuencia

- **Estado:** Aprobado por el equipo
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

Con costo cero (ADR-011) no hay GPU en la nube de pago. El plan anterior usaba Colab T4 como worker de
transcripción. La GPU de 24 GB que mencionaba ADR-006 no está confirmada. RNF-01 pide procesar 10 min de
video en menos de 5 min.

PC de Emmanuel (revisada el 17 oct 2026): NVIDIA RTX 2070 SUPER de 8 GB (Turing, compute 7.5, driver
617.42), Intel i7-10700K (8 núcleos, 16 hilos), 32 GB de RAM, SSD de 1 TB con ~199 GB libres,
Windows 11 Pro, WSL2 con Ubuntu y Docker 29.8.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Colab T4 gratuita | 16 GB de VRAM | Sesiones limitadas; subir videos a la nube; no es el escenario del cliente |
| B · PC del equipo | Sin límites; los videos no salen; es el mismo escenario que un servidor del cliente | 8 GB de VRAM, compartidos con el escritorio |
| C · Solo CPU | Funciona en cualquier máquina | No cumple RNF-01 |

## Decisión

**B,** con un perfil CPU para quien desarrolle sin GPU. En 8 GB no caben juntos faster-whisper
`large-v3-turbo` (~2 GB) y Gemma 4 E4B (~4.7 GB) con el escritorio (~1.6 GB): las etapas corren en
secuencia y la transcripción libera la GPU antes de que Ollama cargue el modelo
(`OLLAMA_MAX_LOADED_MODELS=1`). Colab queda solo como respaldo.

## Consecuencias

- **Positivas:** mediciones reproducibles sin costo; el benchmark de ADR-006 ya se hizo en esta GPU.
- **Negativas / riesgos:** cada cambio de modelo cuesta ~10 s con la caché caliente (36–86 s en frío,
  ADR-006); un solo integrante tiene GPU.
- **Seguimiento:** medir RNF-01 en S5; si no se cumple, reducir fotogramas o usar Whisper `small`.
- **Seguimiento (25 oct 2026), faster-whisper fuera del contenedor en el MVP:** el plan (§3) pone
  la transcripción dentro del contenedor de la API, pero la imagen actual solo la corre en CPU: el
  servicio `api` no reserva la GPU y la imagen no trae cuBLAS (CUDA 12) ni cuDNN 9. En el MVP,
  faster-whisper `large-v3-turbo` corre en el host, desde el venv de Windows con el extra `gpu`
  (medido: 58 s de audio en 6.6 s, ~2.4 GB de VRAM que se liberan al terminar;
  `docs/dev/transcripcion.md`). Pendiente decidir cómo dar GPU al contenedor (imagen base CUDA o
  wheels de NVIDIA, +1–2 GB, y reserva de GPU en `api`), o si la transcripción queda en un proceso
  del host. Mientras tanto, en Docker se usa el perfil CPU (`small`, int8).

## Referencias

- ADR-006 (benchmark en la RTX 2070 SUPER); `docs/dev/llm.md`; documento SOP V1.0, RNF-01 y sección 8.1.
