"""
Configuraciones y constantes para el sistema de captura de cámaras Allied Vision
"""

import logging
from enum import Enum
from typing import Dict, Any

class CameraModel(Enum):
    """Modelos de cámara soportados"""
    ALVIUM_1800_U_511C = "Alvium 1800 U-511c"  # Color
    ALVIUM_1800_U_511M = "Alvium 1800 U-511m"  # Monocromática
    AUTO_DETECT = "auto"

class ControlMode(Enum):
    """Modos de control para parámetros de cámara"""
    AUTO = "auto"
    MANUAL = "manual"

class PixelFormat(Enum):
    """Formatos de píxel soportados"""
    MONO8 = "Mono8"
    MONO12 = "Mono12"
    BGR8 = "BGR8"
    RGB8 = "RGB8"
    BAYER_RG8 = "BayerRG8"
    BAYER_BG8 = "BayerBG8"
    AUTO_DETECT = "auto"

# Configuraciones por defecto
DEFAULT_CONFIG = {
    "camera": {
        "model": CameraModel.AUTO_DETECT,
        "acquisition_mode": "Continuous",
        "trigger_mode": "Off",
        "pixel_format": PixelFormat.AUTO_DETECT,
    },

    "exposure": {
        "mode": ControlMode.AUTO,
        "manual_value": 10000,  # microsegundos
        "min_value": 76.377,    # microsegundos (valor mínimo real de Alvium 1800 U-511c)
        "max_value": 9999960.996,   # microsegundos (valor máximo real)
    },

    "gain": {
        "mode": ControlMode.AUTO,
        "manual_value": 0.0,    # dB
        "min_value": 0.0,       # dB
        "max_value": 47.9,      # dB (valor máximo real de Alvium 1800 U-511c)
    },

    "intensity_controller": {
        "mode": ControlMode.AUTO,
        "manual_value": 50,     # Target intensity (rango real: 10-90)
        "min_value": 10,        # Valor mínimo real de Alvium 1800 U-511c
        "max_value": 90,        # Valor máximo real de Alvium 1800 U-511c
    },

    "display": {
        "window_name": "Allied Vision Camera",
        "window_width": 1280,
        "window_height": 720,
        "show_info_overlay": True,
        "fps_display": True,
    },

    "acquisition": {
        "buffer_count": 5,
        "timeout_ms": 2000,
        "max_frame_rate": 30.0,
    }
}

# Configuraciones específicas por modelo de cámara
CAMERA_SPECIFIC_CONFIG = {
    CameraModel.ALVIUM_1800_U_511C: {
        "pixel_format": PixelFormat.BGR8,
        "sensor_type": "color",
        "resolution": (2448, 2048),
        "sensor_name": "Sony IMX547",
        "max_fps": 79,
    },

    CameraModel.ALVIUM_1800_U_511M: {
        "pixel_format": PixelFormat.MONO8,
        "sensor_type": "mono",
        "resolution": (2448, 2048),
        "sensor_name": "Sony IMX547",
        "max_fps": 79,
    }
}

# Teclas de control interactivo
CONTROL_KEYS = {
    # Modos de control
    "toggle_exposure_mode": ord('e'),
    "toggle_gain_mode": ord('g'),
    "toggle_intensity_mode": ord('i'),

    # Ajustes manuales - Exposición
    "exposure_increase": ord('+'),
    "exposure_decrease": ord('-'),
    "exposure_increase_fine": ord('='),
    "exposure_decrease_fine": ord('_'),

    # Ajustes manuales - Ganancia
    "gain_increase": ord(']'),
    "gain_decrease": ord('['),

    # Ajustes manuales - Intensidad
    "intensity_increase": ord(')'),
    "intensity_decrease": ord('('),

    # Control general
    "help": ord('h'),
    "reset_defaults": ord('r'),
    "toggle_info": ord('t'),
    "save_image": ord('s'),
    "quit": ord('q'),
    "quit_alt": 27,  # ESC
}

# Mensajes de ayuda
HELP_TEXT = """
=== CONTROLES DE CÁMARA ALLIED VISION ===

MODOS DE CONTROL:
  E - Alternar modo exposición (Auto/Manual)
  G - Alternar modo ganancia (Auto/Manual)
  I - Alternar modo intensidad (Auto/Manual)

AJUSTES MANUALES:
  Exposición:
    + / - : Aumentar/Disminuir exposición (pasos grandes)
    = / _ : Aumentar/Disminuir exposición (pasos finos)

  Ganancia:
    ] / [ : Aumentar/Disminuir ganancia

  Intensidad:
    ) / ( : Aumentar/Disminuir intensidad objetivo

GENERAL:
  H - Mostrar esta ayuda
  T - Alternar información en pantalla
  R - Restablecer valores por defecto
  S - Guardar imagen actual
  Q / ESC - Salir

Presiona cualquier tecla para continuar...
"""

# Configuración de logging
LOGGING_CONFIG = {
    "level": logging.INFO,
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "handlers": [
        {
            "type": "console",
            "level": logging.INFO
        },
        {
            "type": "file",
            "filename": "camera_capture.log",
            "level": logging.DEBUG
        }
    ]
}

# Pasos de ajuste para controles manuales
ADJUSTMENT_STEPS = {
    "exposure": {
        "coarse": 5000,     # microsegundos
        "fine": 1000,       # microsegundos
    },
    "gain": {
        "step": 1.0,        # dB
    },
    "intensity": {
        "step": 5,          # unidades
    }
}

# Configuraciones de validación
VALIDATION_RANGES = {
    "exposure": {
        "min": 76.377,      # microsegundos (valor mínimo real Alvium 1800 U-511c)
        "max": 9999960.996, # microsegundos (valor máximo real ~10 segundos)
    },
    "gain": {
        "min": 0.0,         # dB
        "max": 47.9,        # dB (valor máximo real Alvium 1800 U-511c)
    },
    "intensity": {
        "min": 10,          # nivel mínimo real (Alvium 1800 U-511c)
        "max": 90,          # nivel máximo real (Alvium 1800 U-511c)
    }
}

def get_default_config() -> Dict[str, Any]:
    """Retorna una copia de la configuración por defecto"""
    import copy
    return copy.deepcopy(DEFAULT_CONFIG)

def get_camera_config(model: CameraModel) -> Dict[str, Any]:
    """Retorna la configuración específica para un modelo de cámara"""
    return CAMERA_SPECIFIC_CONFIG.get(model, {})

def validate_config_value(category: str, value: Any) -> bool:
    """Valida si un valor está dentro del rango permitido"""
    if category not in VALIDATION_RANGES:
        return True

    range_config = VALIDATION_RANGES[category]
    return range_config["min"] <= value <= range_config["max"]