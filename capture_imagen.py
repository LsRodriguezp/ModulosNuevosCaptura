"""
Módulo de Captura de Imagen - Proyecto Galletas
Captura un frame desde una cámara Allied Vision usando el SDK vmbpy.
 
Uso:
    python capture_imagen.py <ip_camara> <carpeta_destino> <config.json>
 
Ejemplo:
    python capture_imagen.py 192.168.1.10 ./capturas ./config_camara.json
"""
 
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime
 
# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)
 
# ─── Importación del SDK ───────────────────────────────────────────────────────
try:
    import vmbpy
    from vmbpy import VmbSystem, Camera, Frame, FrameStatus, VmbFeatureError
    import numpy as np
    import cv2
except ImportError as e:
    log.error(
        "Dependencia faltante: %s\n"
        "Instala los requisitos con:\n"
        "  pip install vmbpy numpy opencv-python",
        e,
    )
    sys.exit(1)
 
 
# ─── Constantes ───────────────────────────────────────────────────────────────
ESTABILIZACION_SEG = 5          # Tiempo de warm-up del stream
TIMEOUT_CAPTURA_MS = 5_000      # Tiempo máximo de espera por un frame (ms)
 
 
# ─── Helpers ──────────────────────────────────────────────────────────────────
 
def cargar_config(ruta_json: str) -> dict:
    """Lee y valida el archivo JSON de configuración de la cámara."""
    ruta = Path(ruta_json)
    if not ruta.is_file():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {ruta}")
    with ruta.open("r", encoding="utf-8") as f:
        config = json.load(f)
    log.info("Configuración cargada desde '%s': %s", ruta, config)
    return config
 
 
def aplicar_configuracion(cam: Camera, config: dict) -> None:
    """
    Aplica los parámetros del JSON a la cámara.
 
    Parámetros soportados en el JSON (todos opcionales):
        exposure_mode   (str)   – Ej. "Timed" | "Auto"
        exposure_time   (float) – Tiempo de exposición en µs
        gain            (float) – Ganancia en dB
        gamma           (float) – Corrección gamma
        pixel_format    (str)   – Ej. "Mono8" | "BayerRG8" | "RGB8"
        width           (int)   – Ancho del ROI en píxeles
        height          (int)   – Alto del ROI en píxeles
        offset_x        (int)   – Offset horizontal del ROI
        offset_y        (int)   – Offset vertical del ROI
        balance_white_auto (str)– Ej. "Off" | "Once" | "Continuous"
        trigger_source  (str)   – Ej. "Software" | "Line1"
        trigger_mode    (str)   – Ej. "Off" | "On"
        features        (dict)  – Mapa genérico feature_name → value
                                   para cualquier feature no listada arriba.
    """
    MAP_FEATURES = {
        "exposure_mode":       "ExposureAuto",
        "exposure_time":       "ExposureTimeAbs",
        "gain":                "Gain",
        "gamma":               "Gamma",
        "pixel_format":        "PixelFormat",
        "width":               "Width",
        "height":              "Height",
        "offset_x":            "OffsetX",
        "offset_y":            "OffsetY",
        "balance_white_auto":  "BalanceWhiteAuto",
        "trigger_source":      "TriggerSource",
        "trigger_mode":        "TriggerMode",
    }
 
    def _set(feature_name: str, value):
        try:
            feat = cam.get_feature_by_name(feature_name)
            feat.set(value)
            log.info("  ✓ %-30s = %s", feature_name, value)
        except VmbFeatureError as exc:
            log.warning("  ✗ No se pudo configurar '%s': %s", feature_name, exc)
 
    log.info("Aplicando configuración a la cámara…")
    for clave, feature_name in MAP_FEATURES.items():
        if clave in config:
            _set(feature_name, config[clave])
 
    # Parámetros genéricos / avanzados bajo la clave "features"
    for feature_name, valor in config.get("features", {}).items():
        _set(feature_name, valor)
 
 
def guardar_frame(frame: Frame, carpeta: str) -> Path:
    """Convierte el frame capturado a PNG y lo guarda en la carpeta indicada."""
    carpeta_path = Path(carpeta)
    carpeta_path.mkdir(parents=True, exist_ok=True)
 
    # Convertir a array numpy
    imagen = frame.as_numpy_ndarray()
 
    # Si el frame es Bayer u otro formato no RGB, convertir
    if imagen.ndim == 2:
        # Monocromático → guardar tal cual (o convertir si se desea RGB)
        imagen_bgr = cv2.cvtColor(imagen, cv2.COLOR_GRAY2BGR)
    elif imagen.shape[2] == 3:
        # Ya es RGB (Vimba entrega RGB); OpenCV usa BGR
        imagen_bgr = cv2.cvtColor(imagen, cv2.COLOR_RGB2BGR)
    else:
        imagen_bgr = imagen  # fallback
 
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ruta_salida = carpeta_path / f"captura_{timestamp}.png"
    cv2.imwrite(str(ruta_salida), imagen_bgr)
    log.info("Imagen guardada en: %s", ruta_salida)
    return ruta_salida
 
 
# ─── Función principal ─────────────────────────────────────────────────────────
 
def capturar_imagen(ip_camara: str, carpeta_destino: str, ruta_config: str) -> Path:
    """
    Flujo completo de captura:
      1. Conectar a la cámara por IP.
      2. Esperar estabilización del stream.
      3. Aplicar configuración desde JSON.
      4. Capturar un frame.
      5. Guardar como PNG.
      6. Cerrar la cámara y liberar recursos (siempre, incluso si hay error).
 
    Returns:
        Ruta (Path) de la imagen PNG guardada.
 
    Raises:
        RuntimeError si no se puede conectar o capturar el frame.
    """
    config = cargar_config(ruta_config)
    ruta_imagen: Path | None = None
 
    # vmbpy se gestiona con un context-manager que inicializa/finaliza el SDK
    with VmbSystem.get_instance() as vmb:
        # ── 1. Buscar la cámara por IP ─────────────────────────────────────
        log.info("Buscando cámara con IP: %s", ip_camara)
        camaras = vmb.get_all_cameras()
        # Nombres posibles del feature de IP según firmware/SDK
        IP_FEATURES = [
            "GevCurrentIPAddress",   # SDK clásico VimbaPython
            "DeviceIPAddress",       # vmbpy 1.x Alvium
            "CurrentIPAddress",      # algunas versiones intermedias
            "GevPersistentIPAddress",
        ]
 
        def _leer_ip(cam: Camera) -> str | None:
            """Intenta leer la IP de la cámara probando varios nombres de feature."""
            for feat_name in IP_FEATURES:
                try:
                    val = cam.get_feature_by_name(feat_name).get()
                    if isinstance(val, int):
                        val = ".".join(str((val >> (8 * i)) & 0xFF)
                                       for i in reversed(range(4)))
                    return str(val)
                except VmbFeatureError:
                    continue
            return None
 
        camara_encontrada = None
        for cam in camaras:
            # Filtrar simuladores antes de abrir
            if "Simulator" in cam.get_name():
                log.debug("Ignorando simulador: %s", cam.get_id())
                continue
            with cam:
                ip_cam = _leer_ip(cam)
                if ip_cam:
                    log.info("  Cámara %s → IP: %s", cam.get_id(), ip_cam)
                    if ip_cam == ip_camara:
                        camara_encontrada = cam
                        log.info("✓ Cámara encontrada: %s (ID: %s)", ip_cam, cam.get_id())
                        break
                else:
                    log.warning("  No se pudo leer IP de %s — features disponibles: %s",
                                cam.get_id(),
                                [f.get_name() for f in cam.get_all_features()
                                 if "ip" in f.get_name().lower() or "address" in f.get_name().lower()])
 
        if camara_encontrada is None:
            raise RuntimeError(
                f"No se encontró ninguna cámara con IP '{ip_camara}'. "
                f"Cámaras detectadas: {[c.get_id() for c in camaras]}"
            )
 
        # ── 2-6. Operar sobre la cámara encontrada ─────────────────────────
        with camara_encontrada as cam:
            try:
                # ── 2. Estabilización ──────────────────────────────────────
                log.info(
                    "Iniciando stream — esperando %d s de estabilización…",
                    ESTABILIZACION_SEG,
                )
                time.sleep(ESTABILIZACION_SEG)
 
                # ── 3. Configuración ───────────────────────────────────────
                aplicar_configuracion(cam, config)
 
                # ── 4. Captura ─────────────────────────────────────────────
                log.info("Capturando frame…")
                frame = cam.get_frame(timeout_ms=TIMEOUT_CAPTURA_MS)
 
                if frame.get_status() != FrameStatus.Complete:
                    raise RuntimeError(
                        f"Frame incompleto. Estado: {frame.get_status()}"
                    )
                log.info(
                    "Frame capturado correctamente — %dx%d px",
                    frame.get_width(),
                    frame.get_height(),
                )
 
                # ── 5. Guardado ────────────────────────────────────────────
                ruta_imagen = guardar_frame(frame, carpeta_destino)
 
            except Exception:
                log.exception("Error durante la captura — liberando recursos…")
                raise  # re-lanza para que el caller lo maneje
 
            # ── 6. La limpieza se realiza automáticamente al salir del
            #       context-manager `with camara_encontrada as cam`
            finally:
                log.info("Conexión con la cámara cerrada y recursos liberados.")
 
    return ruta_imagen  # type: ignore[return-value]
 
 
# ─── Entry point CLI ──────────────────────────────────────────────────────────
 
def main():
    if len(sys.argv) != 4:
        print(
            "Uso: python capture_imagen.py <ip_camara> <carpeta_destino> <config.json>"
        )
        sys.exit(1)
 
    ip_camara        = sys.argv[1]
    carpeta_destino  = sys.argv[2]
    ruta_config      = sys.argv[3]
 
    try:
        ruta_guardada = capturar_imagen(ip_camara, carpeta_destino, ruta_config)
        log.info(". . Captura completada exitosamente: %s", ruta_guardada)
        sys.exit(0)
    except Exception as exc:
        log.error(". . . Fallo en la captura: %s", exc)
        sys.exit(1)
 
 
if __name__ == "__main__":
    main()
 
    
    """
    def main():
    if len(sys.argv) == 4:
        # Modo consola: usa los argumentos pasados
        ip_camara       = sys.argv[1]
        carpeta_destino = sys.argv[2]
        ruta_config     = sys.argv[3]
    else:
        # Modo VS Code / desarrollo: valores por defecto
        log.warning("Sin argumentos — usando valores por defecto de desarrollo.")
        ip_camara       = "192.168.1.10"
        carpeta_destino = r"D:\Trabajo\AbrilPruebas\Modulo_Pacho"
        ruta_config     = r"D:\Trabajo\AbrilPruebas\Modulo_Pacho\config_camara_ejemplo.json"
    ...
    """