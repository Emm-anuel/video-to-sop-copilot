# ADR-027 · Claves de acceso por vista

- **Estado:** Propuesto
- **Fecha:** 2026-11-16
- **Autores:** Emmanuel Merida
- **Decisores:** equipo
- **Issue:** #30 (documento SOP V1.0 §11, RNF-10, RNF-11)

---

## Contexto

§11 separa dos vistas, cada una con su clave en el encabezado `X-Clave-Acceso`: la de **carga**
(SOP, subidas, videos, reportes, descargas) y la de **búsqueda** (`/buscar`). `/v/{id}?t=` es
pública con el enlace (los QR del PDF, RF-29 y RF-30). Hasta S6 ninguna ruta pedía clave: las
vistas solo se separaban por el menú del frontend.

Tres hechos fuerzan el diseño:

- `<img>`, `<video>` y los enlaces de descarga (`<a download>`) no pueden mandar encabezados, y
  la búsqueda y el reporte viven de miniaturas, del reproductor con `Range` y de descargas.
- `/buscar` usa tres rutas de la vista de carga: la miniatura, el video y "Ver SOP" (comentario
  de #30).
- Un QR impreso no sabe de sesiones: quien lo escanea no tiene clave.

## Decisión

1. **Claves solo en `.env`:** `CLAVE_CARGA`, `CLAVE_BUSQUEDA` y `SECRETO_ENLACES` en `Settings`,
   vacías en `.env.example`. Una clave vacía deja su vista abierta (desarrollo, pruebas) y
   `GET /health` lo avisa en `avisos`. **Las dos claves no pueden ser iguales:** la API no arranca
   (la de búsqueda abriría la carga).
2. **Encabezado o cookie.** Cada router declara su vista con una dependencia de FastAPI
   (`plataforma/api/acceso.py`); ninguna ruta revisa la clave por su cuenta. La API acepta
   `X-Clave-Acceso` o la cookie que deja `POST /acceso {vista, clave}`: HttpOnly,
   SameSite=Strict, de sesión del navegador. La cookie **no lleva la clave**: lleva
   `HMAC-SHA256(clave, "sopvid-sesion:<vista>")`, así que cambiar la clave cierra las sesiones.
   `DELETE /acceso` la borra; `GET /acceso` dice qué vistas están abiertas o con sesión (el
   frontend no ve una cookie HttpOnly). Toda comparación, con `hmac.compare_digest` sobre bytes.
3. **Video, miniatura y "Ver SOP" con cualquiera de las dos**, pero con la de búsqueda **solo lo
   publicado**: un video sin publicar (o un SOP sin videos publicados) da 404, como en
   `POST /buscar`, que no distingue "sin publicar" de "no existe". El PDF del SOP como adjunto
   (sin `?ver=true`) sigue siendo de la vista de carga.
4. **Token firmado en `/v`:** los QR llevan `/v/<id>?t=…&k=<token>`, con
   `token = base64url(HMAC-SHA256(SECRETO_ENLACES, "video:<id>")[:16])` (22 caracteres, para que el
   QR no crezca de más). El token abre **solo** `/videos/<id>/video` y `/thumb` de ese video. La
   página `/v/:id` es mínima (el reproductor en el segundo); si la sesión ya tiene la vista de
   carga, ofrece además "Abrir el reporte" o "Abrir el SOP". Sin `SECRETO_ENLACES`, los enlaces
   van sin token y el video y su miniatura quedan abiertos, como en desarrollo.
5. **Clave equivocada en `POST /acceso`: 1 s de espera** antes del 401 (`asyncio.sleep`, sin
   bloquear el trabajador). Frena probar claves a mano; no es un límite de intentos.

`/health`, `/docs` y `/acceso` no piden clave. En el frontend, un guard por ruta
(`data: { vista }`) y un interceptor llevan a `/acceso?vista=…&volver=…` ante la falta de sesión
o un 401, y vuelven a la pantalla con la clave.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| Solo encabezado, guardado en el navegador | Lo literal de §11 | `<img>`, `<video>` y descargas no lo mandan; la clave quedaría legible para cualquier script de la página |
| La clave en la cookie | Simple | La clave viaja y se guarda en claro en cada petición |
| **Encabezado o cookie con HMAC (elegida)** | Sirve para img, video y descargas; la cookie no revela la clave; cambiarla cierra sesiones | Una ruta más (`/acceso`) |
| URL firmada por petición (cada miniatura con su token) | Sin cookie | Cada respuesta de la API tendría que firmar sus URLs; más código para lo mismo |

## Consecuencias

- **Positivas:** las vistas quedan separadas de verdad (RNF-11); la clave nunca está en el código
  ni en Git; el QR sigue funcionando sin sesión; las pruebas y el desarrollo corren sin claves.
- **Riesgos aceptados:**
  - **Un PDF impreso da acceso permanente a su video** (y su miniatura) a quien lo tenga. Se
    revoca cambiando `SECRETO_ENLACES`, lo que invalida **todos** los QR ya impresos.
  - **Claves cortas en la demo sin límite de intentos:** solo la espera de 1 s. Con una clave de
    pocas letras y acceso a la red, se puede adivinar en horas. Para la demo, en una red local,
    se acepta; el límite de intentos queda pendiente en #30.
  - **El token queda en los logs de acceso** (uvicorn y el proxy registran la URL con `?k=`):
    quien lea los logs puede abrir esos videos. Igual que el PDF, se revoca con
    `SECRETO_ENLACES`.
  - Sin `SECRETO_ENLACES` el video de cualquier id se abre sin clave; `/health` lo avisa.
- **Seguimiento:** límite de intentos por IP (#30); si el patrocinador lo pide, enlaces con
  caducidad (el token firmaría también una fecha).

## Referencias

- Issue #30 y su comentario sobre `/buscar` (#27).
- `src/sopvid/plataforma/acceso.py`, `src/sopvid/plataforma/api/acceso.py`,
  `frontend/src/app/acceso/`, `tests/test_acceso.py`.
- Guía: `docs/dev/api.md`, sección "Claves de acceso".
