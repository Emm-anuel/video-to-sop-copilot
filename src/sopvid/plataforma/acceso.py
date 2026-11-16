"""Claves de acceso por vista (§11, RNF-10, ADR-027), sin FastAPI.

Dos vistas: "carga" (SOP, subidas y videos) y "busqueda" (`/buscar`). Cada una se abre con su
clave en el encabezado `X-Clave-Acceso` o con la cookie de sesión que deja `POST /acceso`. La
cookie no lleva la clave: lleva un HMAC de la vista con la clave como llave, así que cambiar la
clave cierra las sesiones abiertas. Una vista con la clave vacía queda abierta (desarrollo).

Los QR del PDF llevan un token por video (`k`), un HMAC del id con `SECRETO_ENLACES`: abre ese
video y su miniatura, nada más. Todas las comparaciones van con `hmac.compare_digest` sobre bytes
UTF-8 (con `str` no ASCII, `compare_digest` lanza TypeError).
"""

import base64
import hashlib
import hmac
from typing import Literal, get_args

from sopvid.plataforma.config import Settings

Vista = Literal["carga", "busqueda"]
VISTAS: tuple[Vista, ...] = get_args(Vista)

ENCABEZADO = "X-Clave-Acceso"
NOMBRE_COOKIE: dict[Vista, str] = {"carga": "sopvid_carga", "busqueda": "sopvid_busqueda"}
NOMBRE_VISTA: dict[Vista, str] = {"carga": "carga", "busqueda": "búsqueda"}

# Un secreto más corto se puede adivinar; /health lo avisa (no impide arrancar).
SECRETO_MIN = 32


def clave(settings: Settings, vista: Vista) -> str:
    """La clave de `vista` sin espacios a los lados; "" si la vista está abierta."""
    secreto = settings.clave_carga if vista == "carga" else settings.clave_busqueda
    return secreto.get_secret_value().strip()


def abierta(settings: Settings, vista: Vista) -> bool:
    """True si `vista` no tiene clave (desarrollo): cualquiera entra."""
    return not clave(settings, vista)


def _iguales(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def clave_correcta(settings: Settings, vista: Vista, valor: str | None) -> bool:
    """True si `valor` es la clave de `vista` (con la vista cerrada; abierta, siempre False)."""
    esperada = clave(settings, vista)
    return bool(esperada) and valor is not None and _iguales(valor.strip(), esperada)


def valor_cookie(settings: Settings, vista: Vista) -> str:
    """Lo que guarda la cookie de `vista`: HMAC-SHA256 de la vista con la clave como llave."""
    llave = clave(settings, vista).encode()
    return hmac.new(llave, f"sopvid-sesion:{vista}".encode(), hashlib.sha256).hexdigest()


def cookie_correcta(settings: Settings, vista: Vista, valor: str | None) -> bool:
    """True si `valor` es la cookie vigente de `vista` (cerrada)."""
    if abierta(settings, vista) or not valor:
        return False
    return _iguales(valor, valor_cookie(settings, vista))


def token_enlace(settings: Settings, video_id: int) -> str | None:
    """El token `k` de los QR de `video_id`, o None sin `SECRETO_ENLACES` (enlaces abiertos).

    16 bytes del HMAC-SHA256 en base64url sin relleno (22 caracteres): el QR no crece de más.
    """
    secreto = settings.secreto_enlaces.get_secret_value().strip()
    if not secreto:
        return None
    firma = hmac.new(secreto.encode(), f"video:{video_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(firma[:16]).rstrip(b"=").decode()


def enlaces_abiertos(settings: Settings) -> bool:
    """True sin `SECRETO_ENLACES`: el video y la miniatura de `/v/<id>` no piden token."""
    return token_enlace(settings, 0) is None


def enlace_correcto(settings: Settings, video_id: int, k: str | None) -> bool:
    """True si `k` es el token de `video_id` (con `SECRETO_ENLACES`; sin él, siempre False)."""
    esperado = token_enlace(settings, video_id)
    return esperado is not None and k is not None and _iguales(k, esperado)


def avisos(settings: Settings) -> list[str]:
    """Lo que /health avisa de la configuración de acceso (vacía en producción bien puesta)."""
    salida = [
        f"CLAVE_{vista.upper()} vacía: la vista de {NOMBRE_VISTA[vista]} está abierta "
        "(solo para desarrollo)"
        for vista in VISTAS
        if abierta(settings, vista)
    ]
    secreto = settings.secreto_enlaces.get_secret_value().strip()
    if not secreto:
        salida.append("SECRETO_ENLACES vacío: los enlaces y QR de los PDF abren el video sin token")
    elif len(secreto) < SECRETO_MIN:
        salida.append(f"SECRETO_ENLACES tiene menos de {SECRETO_MIN} caracteres")
    return salida


def encabezados(settings: Settings, vista: Vista) -> dict[str, str]:
    """`{"X-Clave-Acceso": clave}` para un script que llama a la API; vacío si está abierta."""
    valor = clave(settings, vista)
    return {ENCABEZADO: valor} if valor else {}
