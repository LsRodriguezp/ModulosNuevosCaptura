#!/usr/bin/env python3
"""
Módulo de captura de imágenes simultáneas con tres cámaras Alvium utilizando VimbaX.
Cámaras soportadas: Alvium 1800 U-511c (color) y 1800 U-511m (monocromática)

Arquitectura:
  - Un hilo por cámara (CameraThread) que captura frames de forma independiente.
  - El hilo principal combina los frames en un layout horizontal y gestiona el teclado.
  - El teclado actúa sobre la cámara "activa" (seleccionable con teclas 1 / 2 / 3).
"""

import cv2
import numpy as np
import logging
import argparse
import sys
import time
import threading
from typing import Optional, List

from camera_controller import CameraController, shutdown_vimba_system
from config import (
    CONTROL_KEYS, HELP_TEXT, DEFAULT_CONFIG,
    get_default_config, ControlMode
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
NUM_CAMERAS = 3

# Carpeta raíz donde se guardan todas las capturas
CAPTURES_ROOT = "D:\Trabajo\AbrilPruebas\Pruebas_1"


def _session_folder() -> str:
    """
    Devuelve la ruta de la carpeta de sesión actual con formato de fecha/hora.
    Ejemplo: capturas/20250409_143022
    La carpeta se crea si no existe.
    """
    import os
    from datetime import datetime
    folder = os.path.join(CAPTURES_ROOT, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(folder, exist_ok=True)
    return folder


def _camera_folder(session: str, camera_index: int) -> str:
    """
    Devuelve (y crea) la subcarpeta de una cámara dentro de la sesión.
    Ejemplo: capturas/20250409_143022/camara_1
    """
    import os
    folder = os.path.join(session, f"camara_{camera_index + 1}")
    os.makedirs(folder, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# Hilo de captura por cámara
# ---------------------------------------------------------------------------
class CameraThread(threading.Thread):
    """
    Hilo que gestiona la inicialización, streaming y captura de UNA cámara.
    Expone el último frame capturado de forma thread-safe mediante un Lock.
    """

    def __init__(self, camera_index: int, config: dict):
        super().__init__(daemon=True, name=f"CameraThread-{camera_index}")
        self.camera_index = camera_index
        self.config = config
        self.logger = logging.getLogger(f"Camera-{camera_index}")

        # Controlador de cámara independiente por hilo
        self.controller = CameraController(self.config)

        # Estado interno
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._running = False
        self._initialized = False
        self._error: Optional[str] = None

    # ------------------------------------------------------------------
    # Propiedades thread-safe
    # ------------------------------------------------------------------
    @property
    def frame(self) -> Optional[np.ndarray]:
        """Devuelve una copia del último frame capturado."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def error(self) -> Optional[str]:
        return self._error

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def initialize(self) -> bool:
        """Inicializa la cámara (llamar antes de start())."""
        self.logger.info(f"Inicializando cámara {self.camera_index}...")

        if not self.controller.initialize(camera_index=self.camera_index):
            self._error = f"Cámara {self.camera_index}: fallo al inicializar sistema"
            return False

        if not self.controller.connect():
            self._error = f"Cámara {self.camera_index}: fallo al conectar"
            return False

        if not self.controller.start_streaming():
            self._error = f"Cámara {self.camera_index}: fallo al iniciar streaming"
            return False

        info = self.controller.get_camera_info()
        self.logger.info(
            f"Cámara {self.camera_index} conectada — "
            f"Modelo: {info.get('model', 'N/A')}  Serie: {info.get('serial', 'N/A')}"
        )
        self._initialized = True
        return True

    def run(self):
        """Loop de captura — se ejecuta en el hilo secundario."""
        self._running = True
        self.logger.info(f"Cámara {self.camera_index}: iniciando loop de captura")

        while self._running:
            try:
                new_frame = self.controller.get_current_frame()
                if new_frame is not None:
                    with self._lock:
                        self._frame = new_frame
            except Exception as exc:
                self.logger.error(f"Cámara {self.camera_index}: error en captura — {exc}")

            time.sleep(0.001)  # ~1 ms; limita el spin sin bloquear

        self.logger.info(f"Cámara {self.camera_index}: loop de captura terminado")

    def stop(self):
        """Detiene el loop de captura y libera recursos."""
        self._running = False
        self.join(timeout=2.0)
        try:
            self.controller.shutdown()
        except Exception as exc:
            self.logger.warning(f"Cámara {self.camera_index}: error en shutdown — {exc}")


# ---------------------------------------------------------------------------
# Aplicación principal multi-cámara
# ---------------------------------------------------------------------------
class MultiCameraApp:
    """
    Orquesta tres CameraThread, combina sus frames en un layout horizontal
    y gestiona los controles de teclado sobre la cámara activa.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or get_default_config()
        self.logger = logging.getLogger(__name__)

        # Crear un hilo por cámara, cada uno con su propia copia de config
        self.camera_threads: List[CameraThread] = [
            CameraThread(i, dict(self.config)) for i in range(NUM_CAMERAS)
        ]

        # Cámara activa sobre la que actúa el teclado (0-indexada)
        self.active_camera_index: int = 0

        # Overlay de información
        self.show_info_overlay: bool = self.config["display"]["show_info_overlay"]
        self.running: bool = True

        # Ventana principal
        self.window_name: str = self.config["display"].get(
            "window_name", "Allied Vision — 3 Cámaras"
        )
        cv2.namedWindow(self.window_name, cv2.WINDOW_AUTOSIZE)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def setup_logging(self, debug: bool = False):
        level = logging.DEBUG if debug else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler("camera_capture.log"),
            ],
        )

    # ------------------------------------------------------------------
    # Inicialización
    # ------------------------------------------------------------------
    def initialize_cameras(self) -> bool:
        """Inicializa las tres cámaras en secuencia y arranca sus hilos."""
        self.logger.info("Inicializando las tres cámaras...")
        all_ok = True

        for ct in self.camera_threads:
            if not ct.initialize():
                self.logger.error(ct.error)
                all_ok = False

        if not all_ok:
            self.logger.error(
                "No se pudieron inicializar todas las cámaras. "
                "Verifica las conexiones y vuelve a intentarlo."
            )
            return False

        # Arrancar los hilos de captura
        for ct in self.camera_threads:
            ct.start()

        self.logger.info("Las tres cámaras están capturando.")
        return True

    # ------------------------------------------------------------------
    # Construcción del frame combinado
    # ------------------------------------------------------------------
    def _placeholder_frame(self, height: int, width: int, index: int) -> np.ndarray:
        """Frame negro con texto cuando una cámara aún no tiene imagen."""
        ph = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.putText(
            ph, f"Cam {index + 1} — Sin señal",
            (20, height // 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 80, 80), 2,
        )
        return ph

    # Ancho máximo total de la ventana en píxeles (las 3 cámaras juntas)
    # Ajusta este valor según tu resolución de pantalla
    MAX_DISPLAY_WIDTH = 1800

    def build_combined_frame(self) -> np.ndarray:
        """
        Obtiene el último frame de cada cámara, los escala para que
        quepan en pantalla y los concatena horizontalmente.
        """
        frames = []

        # Dimensión de referencia: usar el primer frame disponible
        ref_h, ref_w = None, None
        for ct in self.camera_threads:
            f = ct.frame
            if f is not None and ref_h is None:
                ref_h, ref_w = f.shape[:2]
                break

        # Fallback si ninguna cámara tiene frame todavía
        if ref_h is None:
            ref_h, ref_w = 480, 640

        # Calcular escala para que las 3 cámaras quepan en MAX_DISPLAY_WIDTH
        thumb_w = self.MAX_DISPLAY_WIDTH // NUM_CAMERAS
        scale = thumb_w / ref_w
        thumb_h = int(ref_h * scale)

        for i, ct in enumerate(self.camera_threads):
            frame = ct.frame

            if frame is None:
                frame = self._placeholder_frame(thumb_h, thumb_w, i)
            else:
                # Asegurar tamaño uniforme antes de escalar
                if frame.shape[:2] != (ref_h, ref_w):
                    frame = cv2.resize(frame, (ref_w, ref_h))

                # Convertir mono a BGR si es necesario
                if len(frame.shape) == 2:
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

                # Escalar al tamaño de miniatura
                frame = cv2.resize(frame, (thumb_w, thumb_h))

            # Overlay de información
            if self.show_info_overlay:
                frame = self._draw_overlay(frame, ct, i)

            # Resaltar la cámara activa con borde verde
            if i == self.active_camera_index:
                cv2.rectangle(frame, (0, 0), (thumb_w - 1, thumb_h - 1), (0, 255, 0), 4)

            frames.append(frame)

        return np.hstack(frames)

    def _draw_overlay(
        self, frame: np.ndarray, ct: CameraThread, cam_idx: int
    ) -> np.ndarray:
        """Dibuja el overlay de información sobre un frame individual."""
        out = frame.copy()
        settings = ct.controller.get_current_settings()

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        color = (0, 255, 0)
        thickness = 1
        line_h = 20

        active_label = " ◀ ACTIVA" if cam_idx == self.active_camera_index else ""
        lines = [
            f"Cam {cam_idx + 1}{active_label}",
            f"FPS: {settings['stats']['fps']:.1f}",
            f"Frames: {settings['stats']['frame_count']}",
            f"Exp: {settings['exposure']['mode']} "
            + (f"{settings['exposure']['value']:.0f}μs" if settings['exposure']['value'] else "N/A"),
            f"Gain: {settings['gain']['mode']} "
            + (f"{settings['gain']['value']:.1f}dB" if settings['gain']['value'] else "N/A"),
            f"Int: {settings['intensity']['mode']} "
            + f"({settings['intensity']['manual_value']})",
        ]

        y = 18
        for line in lines:
            cv2.putText(out, line, (8, y), font, font_scale, color, thickness)
            y += line_h

        return out

    # ------------------------------------------------------------------
    # Cámara activa (propiedad de conveniencia)
    # ------------------------------------------------------------------
    @property
    def active_camera(self) -> CameraThread:
        return self.camera_threads[self.active_camera_index]

    # ------------------------------------------------------------------
    # Teclado
    # ------------------------------------------------------------------
    def handle_keyboard_input(self, key: int) -> bool:
        if key == -1:
            return True

        key = key & 0xFF

        # Salir
        if key in (CONTROL_KEYS["quit"], CONTROL_KEYS["quit_alt"]):
            self.logger.info("Saliendo de la aplicación...")
            return False

        # Seleccionar cámara activa con 1 / 2 / 3
        elif key == ord("1"):
            self.active_camera_index = 0
            self.logger.info("Cámara activa: 1")
        elif key == ord("2"):
            self.active_camera_index = 1
            self.logger.info("Cámara activa: 2")
        elif key == ord("3"):
            self.active_camera_index = 2
            self.logger.info("Cámara activa: 3")

        # Ayuda
        elif key == CONTROL_KEYS["help"]:
            self._show_help()

        # Toggle overlay
        elif key == CONTROL_KEYS["toggle_info"]:
            self.show_info_overlay = not self.show_info_overlay
            self.logger.info(
                f"Overlay {'activado' if self.show_info_overlay else 'desactivado'}"
            )

        # Guardar frame de la cámara activa
        elif key == CONTROL_KEYS["save_image"]:
            ctrl = self.active_camera.controller
            session = _session_folder()
            folder = _camera_folder(session, self.active_camera_index)
            if ctrl.save_current_frame(output_dir=folder):
                self.logger.info(
                    f"Imagen guardada — Cámara {self.active_camera_index + 1} → {folder}"
                )
            else:
                self.logger.error(f"Error guardando imagen — Cámara {self.active_camera_index + 1}")

        # Guardar frames de TODAS las cámaras
        elif key == ord("a"):
            self._save_all_frames()

        # ---- Controles de la cámara activa ----
        ctrl = self.active_camera.controller

        # Modo exposición
        if key == CONTROL_KEYS["toggle_exposure_mode"]:
            if ctrl.toggle_exposure_mode():
                self.logger.info(f"Cam {self.active_camera_index + 1} — Modo exposición: {ctrl.current_exposure_mode.value}")

        # Modo ganancia
        elif key == CONTROL_KEYS["toggle_gain_mode"]:
            if ctrl.toggle_gain_mode():
                self.logger.info(f"Cam {self.active_camera_index + 1} — Modo ganancia: {ctrl.current_gain_mode.value}")

        # Modo intensidad
        elif key == CONTROL_KEYS["toggle_intensity_mode"]:
            if ctrl.toggle_intensity_mode():
                self.logger.info(f"Cam {self.active_camera_index + 1} — Modo intensidad: {ctrl.current_intensity_mode.value}")

        # Exposición gruesa
        elif key == CONTROL_KEYS["exposure_increase"]:
            if ctrl.adjust_exposure(1, fine=False):
                self.logger.info(f"Cam {self.active_camera_index + 1} — Exposición: {ctrl.current_exposure_value:.0f}μs")
        elif key == CONTROL_KEYS["exposure_decrease"]:
            if ctrl.adjust_exposure(-1, fine=False):
                self.logger.info(f"Cam {self.active_camera_index + 1} — Exposición: {ctrl.current_exposure_value:.0f}μs")

        # Exposición fina
        elif key == CONTROL_KEYS["exposure_increase_fine"]:
            if ctrl.adjust_exposure(1, fine=True):
                self.logger.info(f"Cam {self.active_camera_index + 1} — Exposición (fino): {ctrl.current_exposure_value:.0f}μs")
        elif key == CONTROL_KEYS["exposure_decrease_fine"]:
            if ctrl.adjust_exposure(-1, fine=True):
                self.logger.info(f"Cam {self.active_camera_index + 1} — Exposición (fino): {ctrl.current_exposure_value:.0f}μs")

        # Ganancia
        elif key == CONTROL_KEYS["gain_increase"]:
            if ctrl.adjust_gain(1):
                self.logger.info(f"Cam {self.active_camera_index + 1} — Ganancia: {ctrl.current_gain_value:.1f}dB")
        elif key == CONTROL_KEYS["gain_decrease"]:
            if ctrl.adjust_gain(-1):
                self.logger.info(f"Cam {self.active_camera_index + 1} — Ganancia: {ctrl.current_gain_value:.1f}dB")

        # Intensidad
        elif key == CONTROL_KEYS["intensity_increase"]:
            if ctrl.adjust_intensity(1):
                self.logger.info(f"Cam {self.active_camera_index + 1} — Intensidad: {ctrl.current_intensity_value}")
        elif key == CONTROL_KEYS["intensity_decrease"]:
            if ctrl.adjust_intensity(-1):
                self.logger.info(f"Cam {self.active_camera_index + 1} — Intensidad: {ctrl.current_intensity_value}")

        # Reset
        elif key == CONTROL_KEYS["reset_defaults"]:
            self._reset_active_camera()

        return True

    # ------------------------------------------------------------------
    # Guardar todos los frames
    # ------------------------------------------------------------------
    def _save_all_frames(self):
        """
        Guarda el frame actual de las tres cámaras simultáneamente.
        Estructura:
            capturas/YYYYMMDD_HHMMSS/camara_1/capture_....jpg
            capturas/YYYYMMDD_HHMMSS/camara_2/capture_....jpg
            capturas/YYYYMMDD_HHMMSS/camara_3/capture_....jpg
        """
        session = _session_folder()
        threads = []
        for i, ct in enumerate(self.camera_threads):
            folder = _camera_folder(session, i)
            t = threading.Thread(
                target=ct.controller.save_current_frame,
                kwargs={"output_dir": folder},
                daemon=True,
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=2.0)
        self.logger.info(f"Imágenes guardadas — Todas las cámaras → {session}")

    # ------------------------------------------------------------------
    # Ayuda
    # ------------------------------------------------------------------
    def _show_help(self):
        help_img = np.zeros((680, 860, 3), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX

        extra = (
            "\n--- MULTI-CÁMARA ---\n"
            "1 / 2 / 3  : Seleccionar cámara activa\n"
            "A          : Guardar frame de TODAS las cámaras\n"
            "S          : Guardar frame de la cámara activa\n"
            "(el borde verde indica la cámara activa)\n"
            "Los demás controles actúan sobre la cámara activa."
        )
        full_text = HELP_TEXT + extra

        y = 25
        for line in full_text.strip().split("\n"):
            cv2.putText(help_img, line, (10, y), font, 0.48, (255, 255, 255), 1)
            y += 20

        cv2.imshow("Ayuda — Multi-Cámara", help_img)
        cv2.waitKey(0)
        cv2.destroyWindow("Ayuda — Multi-Cámara")

    # ------------------------------------------------------------------
    # Reset cámara activa
    # ------------------------------------------------------------------
    def _reset_active_camera(self):
        ctrl = self.active_camera.controller
        try:
            defaults = get_default_config()
            ctrl.current_exposure_value = defaults["exposure"]["manual_value"]
            if defaults["exposure"]["mode"] == ControlMode.AUTO.value:
                ctrl.set_exposure_auto(True)
            else:
                ctrl.set_exposure_auto(False)
                ctrl.set_exposure_time(defaults["exposure"]["manual_value"])

            ctrl.current_gain_value = defaults["gain"]["manual_value"]
            if defaults["gain"]["mode"] == ControlMode.AUTO.value:
                ctrl.set_gain_auto(True)
            else:
                ctrl.set_gain_auto(False)
                ctrl.set_gain(defaults["gain"]["manual_value"])

            ctrl.current_intensity_value = defaults["intensity_controller"]["manual_value"]
            if defaults["intensity_controller"]["mode"] == ControlMode.AUTO.value:
                ctrl.set_intensity_auto(True, defaults["intensity_controller"]["manual_value"])
            else:
                ctrl.set_intensity_auto(False)

            self.logger.info(
                f"Cámara {self.active_camera_index + 1} — configuración restablecida"
            )
        except Exception as exc:
            self.logger.error(f"Error restableciendo cámara activa: {exc}")

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------
    def run(self) -> bool:
        if not self.initialize_cameras():
            return False

        self.logger.info(
            "Aplicación iniciada — 3 cámaras activas.\n"
            "  1 / 2 / 3  → seleccionar cámara activa\n"
            "  A          → guardar todas\n"
            "  H          → ayuda completa\n"
            "  Q / ESC    → salir"
        )

        try:
            while self.running:
                combined = self.build_combined_frame()
                cv2.imshow(self.window_name, combined)

                key = cv2.waitKey(1)
                if not self.handle_keyboard_input(key):
                    break

                time.sleep(0.001)

        except KeyboardInterrupt:
            self.logger.info("Interrupción de usuario detectada")
        except Exception as exc:
            self.logger.error(f"Error en loop principal: {exc}")
        finally:
            self._cleanup()

        return True

    def _cleanup(self):
        self.logger.info("Limpiando recursos...")
        cv2.destroyAllWindows()
        for ct in self.camera_threads:
            ct.stop()
        # Cerrar VimbaX una sola vez al final
        shutdown_vimba_system()
        self.logger.info("Limpieza completada")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Captura simultánea para tres cámaras Allied Vision (VimbaX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python main.py                   # Configuración por defecto
  python main.py --debug           # Logging detallado
  python main.py --no-overlay      # Sin overlay de información
  python main.py --config-file cfg.yaml
        """,
    )
    parser.add_argument("--debug", action="store_true", help="Logging detallado")
    parser.add_argument("--no-overlay", action="store_true", help="Sin overlay en pantalla")
    parser.add_argument("--config-file", type=str, help="Configuración YAML personalizada")
    return parser.parse_args()


def load_custom_config(config_file: str) -> Optional[dict]:
    try:
        import yaml
        with open(config_file, "r") as f:
            return yaml.safe_load(f)
    except Exception as exc:
        logging.error(f"Error cargando configuración: {exc}")
        return None


def main():
    args = parse_arguments()

    app = MultiCameraApp()
    app.setup_logging(debug=args.debug)

    if args.config_file:
        custom = load_custom_config(args.config_file)
        if custom:
            app.config.update(custom)

    if args.no_overlay:
        app.config["display"]["show_info_overlay"] = False
        app.show_info_overlay = False

    print("=" * 60)
    print("Software de Captura Allied Vision — MULTI-CÁMARA")
    print("Cámaras: Alvium 1800 U-511 (×3)")
    print("SDK: VimbaX  |  Hilos: 3 + principal")
    print("=" * 60)
    print()
    print("  1 / 2 / 3  → seleccionar cámara activa (borde verde)")
    print("  A          → guardar frame de las 3 cámaras a la vez")
    print("  H          → ver todos los controles")
    print("  Q / ESC    → salir")
    print()

    try:
        success = app.run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nAplicación interrumpida por el usuario")
        sys.exit(0)
    except Exception as exc:
        logging.error(f"Error fatal: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()