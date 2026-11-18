# Lista de comprobación: instalar y recorrer la demo en otro equipo

El ensayo del 17 nov (informe en [`docs/adr/datos/s7/`](../adr/datos/s7/)) se hizo en un clon aparte de
la máquina de desarrollo. Probó el README, el compose y `scripts/levantar.ps1` desde un clon sin
`.env`, volúmenes ni modelos, pero **no puede probar** lo que esta máquina ya tiene: Docker Desktop,
WSL2, el driver de NVIDIA, las imágenes base en caché, un puerto firewall abierto, la red. Esta lista
cubre eso. Quien la repita no debe ser quien escribió el README, y solo debe seguir el README.

Marca cada casilla y anota el tiempo. La meta (≤ 30 min de clonar a la demo) y la ✓ de "App completa"
en `docs/plan/plan.md` solo cuentan si esta lista pasa en un equipo distinto.

## Antes del equipo

- [ ] **Quién y qué equipo:** persona que no escribió el README; Windows 11, RAM, disco libre, ¿GPU
      NVIDIA? (modelo y driver), CPU. Anótalos en el informe.
- [ ] **Disco libre ≥ 25 GB** en la unidad de Docker (imágenes 13.6 GB, Gemma 6.6 GB, pesos de Whisper
      y MiniLM 2.1 GB; el modo con la API en el host suma ~7 GB de venv y modelos).
- [ ] **Memoria.** Docker Desktop con WSL2 le da a WSL el 50 % de la RAM por defecto. En el ensayo,
      16.7 GB de 32 GB. Con 16 GB totales WSL tendría ~8 GB, y Gemma 4 E4B (~4.7 GB) con Whisper y la base podría quedar justo (no probado).
      Si falla, `%UserProfile%\.wslconfig` con `memory=`.
- [ ] **Puertos libres:** `netstat -ano | findstr ":8000 :4200 :5432 :11434"` sin nada en LISTENING.
      Otro Postgres local en el 5432 es lo más común. El 11434 no se puede cambiar sin editar el compose.
- [ ] **Acceso al repo.** El repo es público hoy; si cambia a privado, la persona necesita credenciales
      de GitHub antes del `git clone` (y eso se cuenta en los 30 min).
- [ ] **Material fuera del repo:** VIDEO-A.mp4, VIDEO-E.mp4 y `sop_filtro_agua.docx` en una carpeta
      aparte (`..\sopvid-material\`). Sin ellos no hay demo (README, "Material de la demo").

## Instalar lo que el README da por hecho

- [ ] **Virtualización activada** en la BIOS/UEFI (si Docker no arranca con "WSL 2 requires…").
- [ ] **Docker Desktop** con el backend WSL2 y Compose v2: `docker version` y `docker compose version`
      responden. Primera apertura aceptada (licencia), sin pedir reinicio pendiente.
- [ ] **Git** instalado.
- [ ] **Driver NVIDIA** (solo para GPU): `nvidia-smi` lista la tarjeta; el del ensayo es 617.42.
      Comprobación de que Docker pasa la GPU:
      `docker run --rm --gpus all nvidia/cuda:13.4.2-base-ubuntu24.04 nvidia-smi`. Sin GPU, el
      script lo dice (`Ollama en CPU · no se detectó GPU NVIDIA`) y todo funciona, más lento (en CPU
      RNF-01 no se cumple).
- [ ] **Salida a internet para las descargas** (con proxy corporativo o antivirus que inspecciona TLS,
      algunas fallan): Docker Hub (`registry-1.docker.io`), `deb.debian.org`, `pypi.org` y
      `download.pytorch.org` (al construir la imagen), `registry.npmjs.org` (`npm ci` del frontend),
      `registry.ollama.ai` (Gemma) y `huggingface.co` (Whisper y MiniLM, la primera vez que se sube un
      video). Anota cualquier bloqueo.

## Correr el README al pie de la letra

- [ ] `git clone` y `.\scripts\levantar.ps1`. Cronometra y anota cada mensaje inesperado.
- [ ] **Resultado esperado del script:** crea `.env` y muestra las dos claves; "Ollama en GPU" o "en
      CPU" según el equipo; migraciones sin error; avance de la descarga de Gemma; al final
      `db=ok · llm=ok`. Sin esperar ninguna pantalla en blanco larga: si pasa algo raro, anota el último
      mensaje.
- [ ] **El script desde cero nunca se ha corrido completo** (el ensayo corrió los mismos pasos a mano y
      el script solo sobre un clon ya levantado): lo que falle aquí es hallazgo de verdad. Revisa en
      especial la espera y el avance de la descarga de Gemma y la carga previa del modelo.
- [ ] `docker compose exec ollama ollama ps` después de la primera petición: `100% GPU` con GPU.
- [ ] Recorre [`guion.md`](guion.md) completo y compara con lo esperado de cada paso.

## Lo que el ensayo no pudo probar

- [ ] **Descargas en una red distinta** (el ensayo: ~25 MB/s). Con una red lenta, 6.6 GB de Gemma son
      el cuello; el script espera hasta 40 min.
- [ ] **Imágenes base sin caché.** En el ensayo python, node, pgvector y ollama ya estaban en la caché
      de Docker (13.6 GB entre imágenes): su descarga no se midió. Anota cuánto tardan aquí.
- [ ] **Primera carga de Gemma en un disco frío:** 101 s en el ensayo, con la API esperando hasta
      `LLM_TIMEOUT_S` (180 s). En un disco más lento puede no alcanzar: la primera conversión de SOP
      falla con "Ollama no responde" y se repite. El script carga el modelo antes para evitarlo.
- [ ] **Primera subida de video:** descarga Whisper (~1.6 GB) y MiniLM (~0.5 GB) dentro de la
      etapa de transcripción. Comprueba que no cae en timeout y anota cuánto sumó.
- [ ] **GPU de otra marca o sin GPU.** AMD o Intel no tienen camino de GPU aquí. En CPU, Gemma tarda
      mucho más (hasta 483 s para un SOP generado de E, medido el 10 nov).
- [ ] **Dos navegadores o dos personas a la vez:** la API procesa **un video a la vez** (cola de un
      trabajador). No se probó con carga concurrente.

## QR con el celular y firewall

- [ ] Celular y equipo en la misma red; sin VPN ni datos móviles. Redes de invitados, hoteles y
      algunas universitarias **aíslan a los clientes**: ahí no abre nada, y no es un fallo de la app.
- [ ] `APP_URL_PUBLICA=http://<IP>:4200` en `.env`, reiniciar la API y **regenerar el PDF**.
- [ ] **Prueba primero sin regla de firewall propia.** En el ensayo funcionó con la regla "Puerto 4200"
      (perfil Private) ya creada y, además, Docker Desktop Backend trae reglas de entrada para Private y
      Public: no se sabe si la regla propia hacía falta. Si el celular no abre `http://<IP>:4200`,
      README ("QR del PDF con el celular") trae el comando y el que la quita.
- [ ] **Perfil de red Público.** El ensayo fue en una red *Privada*; la regla del README es para
      Privada. En una red Pública tendría que ir con `-Profile Public`, decisión de quien lo instale.
- [ ] **Exposición a la red:** Docker publica el 8000 (API) y el 5432 (Postgres, contraseña de
      desarrollo) en todas las interfaces. Desde el celular, abre `http://<IP>:8000/health` y
      `http://<IP>:5432`: si responden, esos puertos son alcanzables desde la red y la API solo
      depende de las claves. No abras esos puertos en el firewall de una red que no sea de confianza.

## Al terminar

- [ ] Anota en el informe (`docs/adr/datos/s7/`): equipo, tiempos por paso, cada fallo y qué se
      corrigió. Sin videos, transcripciones, SOP del cliente ni capturas con rostros.
- [ ] Si todo pasó sin intervención de quien escribió el README: ahí, y solo ahí, se marca ✓ la
      "App completa" en `docs/plan/plan.md`.
- [ ] Limpia: `.\scripts\levantar.ps1 -Detener` conserva datos y modelos; para borrar todo (volúmenes y
      modelos incluidos) `docker compose --profile llm down -v` **solo** en un equipo de prueba.
      Quita la regla de firewall si la creaste.
