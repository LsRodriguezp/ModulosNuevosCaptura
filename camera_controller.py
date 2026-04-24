"""
Controlador principal para cámaras Allied Vision usando VimbaX SDK
"""
 
import cv2
import numpy as np
import logging
import time
import os
from typing import Optional, Tuple, Any, Callable
from threading import Lock, Event
from datetime import datetime
 
import vmbpy
from vmbpy import VmbSystem, Camera, Frame, FeatureTypes
 
from config import (
    CameraModel, ControlMode, PixelFormat, DEFAULT_CONFIG,
    CAMERA_SPECIFIC_CONFIG, VALIDATION_RANGES, ADJUSTMENT_STEPS,
    get_default_config, validate_config_value
)
 
# ---------------------------------------------------------------------------
# Instancia compartida de VimbaX — un solo contexto para todos los hilos
# ---------------------------------------------------------------------------
_vmb_instance: Optional[VmbSystem] = None
_vmb_lock = Lock()
 
def get_vimba_system() -> VmbSystem:
    """
    Devuelve la instancia global de VmbSystem ya inicializada.
    Se llama DESPUÉS de haber entrado al contexto con __enter__().
    """
    global _vmb_instance
    with _vmb_lock:
        if _vmb_instance is None:
            _vmb_instance = VmbSystem.get_instance()
            _vmb_instance.__enter__()
        return _vmb_instance
 
def shutdown_vimba_system():
    """Cierra la instancia global de VmbSystem."""
    global _vmb_instance
    with _vmb_lock:
        if _vmb_instance is not None:
            try:
                _vmb_instance.__exit__(None, None, None)
            except Exception:
                pass
            _vmb_instance = None
 
 
# IDs de las cámaras reales (se excluyen simuladores automáticamente)
_REAL_CAMERA_IDS: Optional[list] = None
_REAL_CAMERA_LOCK = Lock()
 
def get_real_camera_ids() -> list:
    """
    Devuelve la lista de IDs de cámaras reales (excluye simuladores).
    Se cachea tras la primera llamada.
    """
    global _REAL_CAMERA_IDS
    with _REAL_CAMERA_LOCK:
        if _REAL_CAMERA_IDS is None:
            vmb = get_vimba_system()
            all_cams = vmb.get_all_cameras()
            _REAL_CAMERA_IDS = [
                c.get_id() for c in all_cams
                if "Cam" not in c.get_id() or not c.get_id().startswith("DEV_Cam")
            ]
        return _REAL_CAMERA_IDS
 
 
class CameraController:
    """Controlador principal para cámaras Allied Vision"""
 
    def __init__(self, config: Optional[dict] = None):
        """
        Inicializa el controlador de cámara
 
        Args:
            config: Configuración personalizada (opcional)
        """
        self.config = config or get_default_config()
        self.logger = logging.getLogger(__name__)
 
        # Estado de la cámara
        self.camera: Optional[Camera] = None
        self.vimba_system: Optional[VmbSystem] = None
        self.is_streaming = False
        self.current_frame: Optional[np.ndarray] = None
 
        # Control de threading
        self.frame_lock = Lock()
        self.stop_event = Event()
 
        # Estadísticas
        self.frame_count = 0
        self.fps = 0.0
        self.last_fps_time = time.time()
        self.last_fps_count = 0
 
        # Configuración actual de controles
        self.current_exposure_mode = ControlMode.AUTO
        self.current_gain_mode = ControlMode.AUTO
        self.current_intensity_mode = ControlMode.AUTO
 
        self.current_exposure_value = self.config["exposure"]["manual_value"]
        self.current_gain_value = self.config["gain"]["manual_value"]
        self.current_intensity_value = self.config["intensity_controller"]["manual_value"]
 
        # Información de la cámara detectada
        self.camera_model: Optional[CameraModel] = None
        self.camera_info = {}
 
    def initialize(self, camera_index: int = 0) -> bool:
        """
        Inicializa el sistema VimbaX y selecciona la cámara real por índice.
 
        Args:
            camera_index: Índice dentro de las cámaras reales detectadas (0, 1, 2…)
                          Los simuladores se excluyen automáticamente.
 
        Returns:
            True si la inicialización fue exitosa
        """
        try:
            self.logger.info(f"Inicializando cámara real [{camera_index}]...")
 
            # Obtener instancia compartida de VimbaX (se crea solo la primera vez)
            self.vimba_system = get_vimba_system()
 
            # Obtener IDs de cámaras reales (excluye simuladores)
            real_ids = get_real_camera_ids()
 
            if not real_ids:
                self.logger.error("No se encontraron cámaras reales Allied Vision")
                return False
 
            if camera_index >= len(real_ids):
                self.logger.error(
                    f"Índice {camera_index} fuera de rango — "
                    f"solo hay {len(real_ids)} cámara(s) real(es)"
                )
                return False
 
            target_id = real_ids[camera_index]
            self.logger.info(f"Seleccionando cámara ID: {target_id}")
 
            # Buscar la cámara por ID
            all_cams = self.vimba_system.get_all_cameras()
            self.camera = next((c for c in all_cams if c.get_id() == target_id), None)
 
            if self.camera is None:
                self.logger.error(f"No se encontró la cámara con ID: {target_id}")
                return False
 
            # Detectar modelo de cámara
            self._detect_camera_model()
 
            self.logger.info(f"Cámara [{camera_index}] lista: {self.camera.get_id()}")
            self.logger.info(f"Modelo: {self.camera_model}")
 
            return True
 
        except Exception as e:
            self.logger.error(f"Error inicializando cámara [{camera_index}]: {e}")
            return False
 
    def _detect_camera_model(self):
        """Detecta el modelo específico de la cámara"""
        try:
            camera_id = self.camera.get_id()
            model_name = self.camera.get_model()
 
            self.logger.info(f"ID cámara: {camera_id}")
            self.logger.info(f"Modelo cámara: {model_name}")
 
            # Detectar si es color o monocromática basado en el ID/modelo
            if ("511c" in camera_id.lower() or "511c" in model_name.lower() or
                "color" in model_name.lower() or "U-511c" in model_name):
                self.camera_model = CameraModel.ALVIUM_1800_U_511C
                self.logger.info("Cámara detectada como COLOR (Alvium 1800 U-511c)")
            elif ("511m" in camera_id.lower() or "511m" in model_name.lower() or
                  "mono" in model_name.lower() or "U-511m" in model_name):
                self.camera_model = CameraModel.ALVIUM_1800_U_511M
                self.logger.info("Cámara detectada como MONO (Alvium 1800 U-511m)")
            else:
                self.camera_model = CameraModel.AUTO_DETECT
                self.logger.warning(f"Modelo de cámara no reconocido, usando AUTO_DETECT")
 
            # Obtener información adicional
            self.camera_info = {
                "id": camera_id,
                "model": model_name,
                "serial": self.camera.get_serial(),
                "interface_id": self.camera.get_interface_id(),
            }
 
        except Exception as e:
            self.logger.warning(f"Error detectando modelo: {e}")
            self.camera_model = CameraModel.AUTO_DETECT
 
    def connect(self) -> bool:
        """
        Conecta a la cámara y configura parámetros iniciales
 
        Returns:
            True si la conexión fue exitosa
        """
        if not self.camera:
            self.logger.error("No hay cámara disponible para conectar")
            return False
 
        try:
            self.logger.info("Conectando a la cámara...")
            self.camera.__enter__()
 
            # Configurar parámetros iniciales
            self._configure_camera()
 
            self.logger.info("Cámara conectada exitosamente")
            return True
 
        except Exception as e:
            self.logger.error(f"Error conectando a la cámara: {e}")
            return False
 
    def _configure_camera(self):
        """Configura los parámetros iniciales de la cámara"""
        try:
            # Configurar modo de adquisición
            acquisition_mode = self.camera.get_feature_by_name("AcquisitionMode")
            acquisition_mode.set("Continuous")
 
            # Configurar formato de píxel según el modelo
            self._setup_pixel_format()
 
            # Configurar controles iniciales
            self._setup_exposure_control()
            self._setup_gain_control()
            self._setup_intensity_control()
 
        except Exception as e:
            self.logger.error(f"Error configurando cámara: {e}")
            raise
 
    def _setup_pixel_format(self):
        """Configura el formato de píxel óptimo para la cámara"""
        try:
            pixel_format_feature = self.camera.get_feature_by_name("PixelFormat")
            available_formats = pixel_format_feature.get_available_entries()
 
            # Obtener nombres de formatos disponibles correctamente
            available_format_names = []
            for fmt in available_formats:
                try:
                    if hasattr(fmt, 'get_name'):
                        name = fmt.get_name()
                    elif hasattr(fmt, 'name'):
                        name = fmt.name
                    else:
                        name = str(fmt)
                    available_format_names.append(name)
                except Exception as e:
                    self.logger.warning(f"No se pudo obtener nombre de formato: {e}")
 
            self.logger.info(f"Formatos disponibles: {available_format_names}")
 
            if self.camera_model == CameraModel.ALVIUM_1800_U_511C:
                preferred_formats = ["BGR8", "RGB8", "BayerRG8", "BayerBG8", "BayerGR8", "BayerGB8"]
 
                for preferred in preferred_formats:
                    if preferred in available_format_names:
                        pixel_format_feature.set(preferred)
                        self.logger.info(f"Formato de píxel configurado: {preferred}")
                        return
 
                for fmt_name in available_format_names:
                    if "Mono" not in fmt_name:
                        pixel_format_feature.set(fmt_name)
                        self.logger.info(f"Formato de píxel configurado (fallback): {fmt_name}")
                        return
 
            elif self.camera_model in CAMERA_SPECIFIC_CONFIG:
                pixel_format_name = CAMERA_SPECIFIC_CONFIG[self.camera_model]["pixel_format"].value
                if pixel_format_name in available_format_names:
                    pixel_format_feature.set(pixel_format_name)
                    self.logger.info(f"Formato de píxel configurado: {pixel_format_name}")
                else:
                    self.logger.warning(f"Formato {pixel_format_name} no disponible, usando default")
 
        except Exception as e:
            self.logger.warning(f"Error configurando formato de píxel: {e}")
 
    def _setup_exposure_control(self):
        """Configura el control de exposición"""
        try:
            if self.current_exposure_mode == ControlMode.AUTO:
                self.set_exposure_auto(True)
            else:
                self.set_exposure_auto(False)
                self.set_exposure_time(self.current_exposure_value)
        except Exception as e:
            self.logger.warning(f"Error configurando exposición: {e}")
 
    def _setup_gain_control(self):
        """Configura el control de ganancia"""
        try:
            if self.current_gain_mode == ControlMode.AUTO:
                self.set_gain_auto(True)
            else:
                self.set_gain_auto(False)
                self.set_gain(self.current_gain_value)
        except Exception as e:
            self.logger.warning(f"Error configurando ganancia: {e}")
 
    def _setup_intensity_control(self):
        """Configura el control de intensidad automática"""
        try:
            if self.current_intensity_mode == ControlMode.AUTO:
                self.set_intensity_auto(True, self.current_intensity_value)
            else:
                self.set_intensity_auto(False)
        except Exception as e:
            self.logger.warning(f"Error configurando control de intensidad: {e}")
 
    def start_streaming(self) -> bool:
        """
        Inicia la captura de video continua
 
        Returns:
            True si se inició exitosamente
        """
        if not self.camera:
            return False
 
        try:
            self.logger.info("Iniciando streaming...")
            self.camera.start_streaming(self._frame_handler)
            self.is_streaming = True
            self.stop_event.clear()
            self.logger.info("Streaming iniciado")
            return True
 
        except Exception as e:
            self.logger.error(f"Error iniciando streaming: {e}")
            return False
 
    def _frame_handler(self, cam: Camera, stream, frame: Frame):
        """Callback para manejar frames recibidos"""
        try:
            with self.frame_lock:
                numpy_frame = frame.as_numpy_ndarray()
                pixel_format = frame.get_pixel_format()
 
                if self.frame_count < 5:
                    self.logger.info(f"Frame {self.frame_count}: Formato píxel: {pixel_format}")
                    self.logger.info(f"Frame {self.frame_count}: Shape: {numpy_frame.shape}, dtype: {numpy_frame.dtype}")
                    self.logger.info(f"Frame {self.frame_count}: Modelo cámara: {self.camera_model}")
 
                self.current_frame = self._process_frame_to_bgr(numpy_frame, pixel_format)
 
                if self.frame_count < 5 and self.current_frame is not None:
                    self.logger.info(f"Frame {self.frame_count}: Shape final: {self.current_frame.shape}, dtype: {self.current_frame.dtype}")
                    if len(self.current_frame.shape) == 3:
                        self.logger.info(f"Frame {self.frame_count}: Imagen a COLOR (3 canales)")
                    else:
                        self.logger.info(f"Frame {self.frame_count}: Imagen MONO (1 canal)")
 
                self.frame_count += 1
                self._update_fps()
 
        except Exception as e:
            self.logger.error(f"Error procesando frame: {e}")
        finally:
            cam.queue_frame(frame)
 
    def _process_frame_to_bgr(self, numpy_frame: np.ndarray, pixel_format) -> np.ndarray:
        """
        Procesa un frame para obtener una imagen BGR de 24 bits para OpenCV
        """
        pixel_format_str = str(pixel_format)
 
        if (self.camera_model == CameraModel.ALVIUM_1800_U_511C or
            (self.camera_model == CameraModel.AUTO_DETECT and len(numpy_frame.shape) == 3)):
 
            if "BGR8" in pixel_format_str and len(numpy_frame.shape) == 3:
                return numpy_frame
            elif ("RGB8" in pixel_format_str or "Rgb8" in pixel_format_str) and len(numpy_frame.shape) == 3:
                return cv2.cvtColor(numpy_frame, cv2.COLOR_RGB2BGR)
            elif len(numpy_frame.shape) == 2:
                if "BayerRG8" in pixel_format_str:
                    return cv2.cvtColor(numpy_frame, cv2.COLOR_BayerRG2BGR)
                elif "BayerBG8" in pixel_format_str:
                    return cv2.cvtColor(numpy_frame, cv2.COLOR_BayerBG2BGR)
                elif "BayerGR8" in pixel_format_str:
                    return cv2.cvtColor(numpy_frame, cv2.COLOR_BayerGR2BGR)
                elif "BayerGB8" in pixel_format_str:
                    return cv2.cvtColor(numpy_frame, cv2.COLOR_BayerGB2BGR)
                elif "Bayer" in pixel_format_str:
                    return cv2.cvtColor(numpy_frame, cv2.COLOR_BayerBG2BGR)
                else:
                    return cv2.cvtColor(numpy_frame, cv2.COLOR_GRAY2BGR)
            elif len(numpy_frame.shape) == 3:
                return numpy_frame
            else:
                return cv2.cvtColor(numpy_frame, cv2.COLOR_GRAY2BGR)
        else:
            if len(numpy_frame.shape) == 2:
                return cv2.cvtColor(numpy_frame, cv2.COLOR_GRAY2BGR)
            else:
                gray = cv2.cvtColor(numpy_frame, cv2.COLOR_BGR2GRAY)
                return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
 
    def _update_fps(self):
        """Actualiza el cálculo de FPS"""
        current_time = time.time()
        if current_time - self.last_fps_time >= 1.0:
            self.fps = (self.frame_count - self.last_fps_count) / (current_time - self.last_fps_time)
            self.last_fps_time = current_time
            self.last_fps_count = self.frame_count
 
    def get_current_frame(self) -> Optional[np.ndarray]:
        """Obtiene el frame actual de forma thread-safe"""
        with self.frame_lock:
            return self.current_frame.copy() if self.current_frame is not None else None
 
    def stop_streaming(self):
        """Detiene la captura de video"""
        if self.is_streaming and self.camera:
            try:
                self.logger.info("Deteniendo streaming...")
                self.camera.stop_streaming()
                self.is_streaming = False
                self.stop_event.set()
                self.logger.info("Streaming detenido")
            except Exception as e:
                self.logger.error(f"Error deteniendo streaming: {e}")
 
    def disconnect(self):
        """Desconecta de la cámara"""
        if self.camera:
            try:
                self.stop_streaming()
                self.camera.__exit__(None, None, None)
                self.logger.info("Cámara desconectada")
            except Exception as e:
                self.logger.error(f"Error desconectando cámara: {e}")
 
    def shutdown(self):
        """Desconecta la cámara. El sistema VimbaX compartido lo cierra MultiCameraApp."""
        try:
            self.disconnect()
            # NO cerramos vimba_system aquí — es una instancia compartida entre hilos.
            # shutdown_vimba_system() se llama una sola vez desde MultiCameraApp._cleanup()
        except Exception as e:
            self.logger.error(f"Error en shutdown de cámara: {e}")
 
    # ------------------------------------------------------------------
    # Métodos de control de exposición
    # ------------------------------------------------------------------
    def set_exposure_auto(self, auto: bool) -> bool:
        """Configura el modo automático de exposición"""
        try:
            exposure_auto = self.camera.get_feature_by_name("ExposureAuto")
            exposure_auto.set("Continuous" if auto else "Off")
            self.current_exposure_mode = ControlMode.AUTO if auto else ControlMode.MANUAL
            return True
        except Exception as e:
            self.logger.error(f"Error configurando exposición automática: {e}")
            return False
 
    def set_exposure_time(self, time_us: float) -> bool:
        """Configura el tiempo de exposición manual"""
        if not validate_config_value("exposure", time_us):
            self.logger.warning(f"Valor de exposición fuera de rango: {time_us}")
            return False
        try:
            exposure_time = self.camera.get_feature_by_name("ExposureTime")
            exposure_time.set(time_us)
            self.current_exposure_value = time_us
            return True
        except Exception as e:
            self.logger.error(f"Error configurando tiempo de exposición: {e}")
            return False
 
    def get_exposure_time(self) -> Optional[float]:
        """Obtiene el tiempo de exposición actual"""
        try:
            exposure_time = self.camera.get_feature_by_name("ExposureTime")
            return exposure_time.get()
        except Exception as e:
            self.logger.error(f"Error obteniendo tiempo de exposición: {e}")
            return None
 
    # ------------------------------------------------------------------
    # Métodos de control de ganancia
    # ------------------------------------------------------------------
    def set_gain_auto(self, auto: bool) -> bool:
        """Configura el modo automático de ganancia"""
        try:
            gain_auto = self.camera.get_feature_by_name("GainAuto")
            gain_auto.set("Continuous" if auto else "Off")
            self.current_gain_mode = ControlMode.AUTO if auto else ControlMode.MANUAL
            return True
        except Exception as e:
            self.logger.error(f"Error configurando ganancia automática: {e}")
            return False
 
    def set_gain(self, gain_db: float) -> bool:
        """Configura la ganancia manual"""
        if not validate_config_value("gain", gain_db):
            self.logger.warning(f"Valor de ganancia fuera de rango: {gain_db}")
            return False
        try:
            gain = self.camera.get_feature_by_name("Gain")
            gain.set(gain_db)
            self.current_gain_value = gain_db
            return True
        except Exception as e:
            self.logger.error(f"Error configurando ganancia: {e}")
            return False
 
    def get_gain(self) -> Optional[float]:
        """Obtiene la ganancia actual"""
        try:
            gain = self.camera.get_feature_by_name("Gain")
            return gain.get()
        except Exception as e:
            self.logger.error(f"Error obteniendo ganancia: {e}")
            return None
 
    # ------------------------------------------------------------------
    # Métodos de control de intensidad
    # ------------------------------------------------------------------
    def set_intensity_auto(self, auto: bool, target: Optional[int] = None) -> bool:
        """Configura el control automático de intensidad"""
        try:
            intensity_auto = self.camera.get_feature_by_name("BalanceWhiteAuto")
            intensity_auto.set("Continuous" if auto else "Off")
 
            if auto and target is not None:
                try:
                    intensity_target = self.camera.get_feature_by_name("IntensityControllerTarget")
                    intensity_target.set(target)
                    self.current_intensity_value = target
                except Exception:
                    pass  # No todos los modelos soportan este feature
 
            self.current_intensity_mode = ControlMode.AUTO if auto else ControlMode.MANUAL
            return True
        except Exception as e:
            self.logger.error(f"Error configurando control de intensidad: {e}")
            return False
 
    # ------------------------------------------------------------------
    # Guardado de imágenes  ← MODIFICADO
    # ------------------------------------------------------------------
    def save_current_frame(
        self,
        filename: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> bool:
        """
        Guarda el frame actual como imagen.
 
        Args:
            filename:   Nombre del archivo (sin ruta). Si es None se genera
                        automáticamente con timestamp en microsegundos.
            output_dir: Carpeta donde guardar la imagen. Se crea si no existe.
                        Si es None se usa el directorio de trabajo actual.
 
        Returns:
            True si la imagen se guardó correctamente.
        """
        frame = self.get_current_frame()
        if frame is None:
            self.logger.warning("save_current_frame: no hay frame disponible")
            return False
 
        try:
            # Generar nombre de archivo con timestamp si no se proporcionó uno
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                filename = f"capture_{timestamp}.jpg"
 
            # Resolver ruta final
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                filepath = os.path.join(output_dir, filename)
            else:
                filepath = filename
 
            cv2.imwrite(filepath, frame)
            self.logger.info(f"Imagen guardada: {filepath}")
            return True
 
        except Exception as e:
            self.logger.error(f"Error guardando imagen: {e}")
            return False
 
    # ------------------------------------------------------------------
    # Métodos de utilidad
    # ------------------------------------------------------------------
    def get_camera_info(self) -> dict:
        """Retorna información de la cámara"""
        return self.camera_info
 
    def get_current_settings(self) -> dict:
        """Retorna la configuración actual de la cámara"""
        return {
            "exposure": {
                "mode": self.current_exposure_mode.value,
                "value": self.get_exposure_time(),
                "manual_value": self.current_exposure_value,
            },
            "gain": {
                "mode": self.current_gain_mode.value,
                "value": self.get_gain(),
                "manual_value": self.current_gain_value,
            },
            "intensity": {
                "mode": self.current_intensity_mode.value,
                "manual_value": self.current_intensity_value,
            },
            "stats": {
                "fps": self.fps,
                "frame_count": self.frame_count,
                "is_streaming": self.is_streaming,
            },
        }
 
    def adjust_exposure(self, delta: float, fine: bool = False) -> bool:
        """Ajusta la exposición en modo manual"""
        if self.current_exposure_mode != ControlMode.MANUAL:
            return False
        step = ADJUSTMENT_STEPS["exposure"]["fine" if fine else "coarse"]
        return self.set_exposure_time(self.current_exposure_value + delta * step)
 
    def adjust_gain(self, delta: float) -> bool:
        """Ajusta la ganancia en modo manual"""
        if self.current_gain_mode != ControlMode.MANUAL:
            return False
        step = ADJUSTMENT_STEPS["gain"]["step"]
        return self.set_gain(self.current_gain_value + delta * step)
 
    def adjust_intensity(self, delta: int) -> bool:
        """Ajusta el objetivo de intensidad"""
        step = ADJUSTMENT_STEPS["intensity"]["step"]
        new_value = self.current_intensity_value + delta * step
        if validate_config_value("intensity", new_value):
            self.current_intensity_value = new_value
            if self.current_intensity_mode == ControlMode.AUTO:
                return self.set_intensity_auto(True, new_value)
            return True
        return False
 
    def toggle_exposure_mode(self) -> bool:
        """Alterna entre modo automático y manual de exposición"""
        new_mode = ControlMode.MANUAL if self.current_exposure_mode == ControlMode.AUTO else ControlMode.AUTO
        return self.set_exposure_auto(new_mode == ControlMode.AUTO)
 
    def toggle_gain_mode(self) -> bool:
        """Alterna entre modo automático y manual de ganancia"""
        new_mode = ControlMode.MANUAL if self.current_gain_mode == ControlMode.AUTO else ControlMode.AUTO
        return self.set_gain_auto(new_mode == ControlMode.AUTO)
 
    def toggle_intensity_mode(self) -> bool:
        """Alterna entre modo automático y manual de intensidad"""
        new_mode = ControlMode.MANUAL if self.current_intensity_mode == ControlMode.AUTO else ControlMode.AUTO
        return self.set_intensity_auto(new_mode == ControlMode.AUTO, self.current_intensity_value)