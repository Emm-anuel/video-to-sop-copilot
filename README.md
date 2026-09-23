# AI Co-Pilot Video-to-SOP

Generación asistida, verificable y trazable de Procedimientos Operativos Estándar (SOP) a partir de video de operación, con validación humana (Human-in-the-Loop) y despliegue en planta.

> **Repositorio privado.** El código y la arquitectura son propiedad de Alignity IQ Edge conforme al NDA firmado. No es público y no se comparte fuera del equipo, el asesor y el patrocinador.

---

## 1. Descripción

Sistema que convierte video de operación en planta en SOPs escritos, verificables y trazables. Percibe acciones y objetos del video, transcribe la narración del experto, consolida varios videos de un mismo procedimiento en una estructura de pasos, y redacta el SOP en lenguaje natural con cada paso ligado a su evidencia en video.

Es una **segunda iteración**: el equipo parte de una base de código heredada del trimestre anterior y se obliga a mejorarla, no a reescribirla desde cero (ver `docs/adr/ADR-001-herencia.md`).

Proyecto Integrador (TC5035) · Maestría en Inteligencia Artificial Aplicada · Tecnológico de Monterrey.

## 2. Equipo

| Integrante | Matrícula | Frente |
|---|---|---|
| Marie Kate Palau | A01705711 | _(por acordar en Semana 1)_ |
| Emmanuel Merida | A01795858 | _(por acordar en Semana 1)_ |
| Sara Castillo | A01224696 | _(por acordar en Semana 1)_ |

Asesor: Dr. Gerardo Jesús Camacho González · Patrocinador: Dr. Jose Jacobo Eluani Vázquez (Alignity IQ Edge) · jeluani@tec.mx

## 3. Arquitectura de referencia

| Capa | Pregunta que responde | Tecnología |
|---|---|---|
| 0 · Fuente de video | ¿De dónde llega la imagen? | Abstracción: archivo, cámara fija, teléfono o lentes tras una misma interfaz |
| 1a · Percepción visual | ¿Qué acción ocurre y cuándo? | V-JEPA 2 (attentive probes sobre backbone congelado) |
| 1b · Percepción de audio | ¿Qué explica el experto? | Transcripción con marcas de tiempo (Whisper / Voxtral) |
| 2 · Estructura | ¿Cuál es el procedimiento y en qué orden? | Grafo de tareas de orden parcial |
| 3 · Lenguaje | ¿Cómo se escribe el SOP? ¿Cómo se conversa? | Gemma 4 (pesos abiertos, servible localmente) |
| 4 · Incertidumbre y HITL | ¿Debo preguntar, y qué? | Umbral de confianza + valor esperado de la respuesta |
| 5 · Plataforma | ¿Quién ve y aprueba qué? | Multiusuario, control de acceso, versionado, auditoría |

Dominio de IA predominante: **Visión Computacional**.

## 4. Estructura del repositorio

```
├── README.md
├── .gitignore
├── .env.example            # solo nombres de variables, sin valores
├── requirements.txt        # o environment.yml
├── docker-compose.yml      # el sistema levanta con un solo comando
├── data/                   # data card y reglas de datos (README.md)
├── notebooks/              # análisis y experimentación
├── docs/
│   ├── entregables/        # entregables de las semanas 1, 2, 8 y 9
│   ├── adr/                # Architecture Decision Records
│   ├── arquitectura/       # diagramas
│   └── literatura/         # papers: BibTeX + resúmenes (mín. 8)
└── src/
    ├── percepcion/         # video, audio, estructura de pasos
    ├── lenguaje/           # redacción del SOP, HITL, conversación
    └── plataforma/         # multiusuario, API, contenedores
```

## 5. Cómo levantar el proyecto

> _Pendiente de completar tras la auditoría de la base heredada (Semana 1)._

```bash
git clone <URL-del-repo>
cd video-to-sop-copilot
cp .env.example .env        # llena tus valores localmente; .env NO se sube
docker compose up           # levanta todos los servicios
```

Objetivo de reproducibilidad: clonar y ejecutar un solo script debe reproducir la demo en ≤ 30 minutos en una máquina limpia.

## 6. Datos y privacidad

- El desarrollo se hace con **datasets públicos** y **datos sintéticos o grabados por el equipo** (ver `data/README.md`).
- **Ningún video, SOP o dato identificable del cliente entra al repositorio**, ni siquiera fragmentos, capturas o transcripciones. Se referencia por identificador; el contenido vive en el almacenamiento aprobado por el patrocinador.
- En video de planta pueden aparecer rostros de trabajadores: es dato personal y se trata conforme a la LFPDPPP, con anonimización cuando el caso lo permita.

## 7. Entregables

| Semana | Entregable | Ubicación |
|---|---|---|
| 1 | Planteamiento del proyecto + ADR-001 | `docs/entregables/`, `docs/adr/` |
| 2 | Avance 0. Propuesta y firma de convenios | `docs/entregables/` |
| 8 | Avance 6. Producto de difusión | `docs/entregables/` |
| 9 | Avance 7. Resumen ejecutivo | `docs/entregables/` |

## 8. Gobernanza

- Rama principal protegida; una rama por tarea; nunca push directo a ramas protegidas.
- Todo cambio entra por Pull Request revisado por un integrante distinto al autor, con CI en verde.
- Commits convencionales: `tipo(alcance): descripción corta`.
- **Sin secretos en el repo**: solo los nombres de las variables de entorno en `.env.example`, sin valores. Nada de contraseñas, tokens ni llaves.
- Nada de binarios pesados, modelos grandes ni video en el repo.

## 9. Propiedad intelectual

Todo el contenido de este repositorio está sujeto al Acuerdo de Confidencialidad y Cesión de Propiedad Intelectual firmado con Alignity IQ Edge / Dr. Jose Jacobo Eluani Vázquez.
