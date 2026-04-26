# Módulo de Captura de Imagen - Proyecto Galletas

Sistema de captura de imágenes para cámaras Allied Vision GigE usando el SDK VimbaX (vmbpy), diseñado específicamente para el modelo **Alvium G5-811c**.

---

## Características Principales

- **Compatible con VimbaX SDK (vmbpy 1.2.1+)**: Usa la API oficial moderna de Allied Vision
- **Búsqueda por IP**: Localiza la cámara correcta automáticamente entre todas las conectadas
- **Filtrado de simuladores**: Ignora las cámaras simuladas de VimbaX automáticamente
- **Configuración flexible por JSON**: Todos los parámetros de cámara se controlan desde un archivo externo sin tocar el código
- **Guardado PNG con timestamp**: Las imágenes se nombran automáticamente con fecha y hora exacta
- **Manejo robusto de errores**: La conexión y liberación de recursos están garantizadas incluso ante fallos
- **Integración OpenCV**: Compatible con OpenCV para conversión y guardado de imágenes

---

## Cámaras Soportadas

| Modelo | Interfaz | Sensor | Resolución | FPS Máx |
|--------|----------|--------|------------|---------|
| Alvium G5-811c | GigE | Sony IMX | 2848×2848 | 24 |

> Para cámaras USB3 (Alvium 1800 U-series), se requieren ajustes adicionales en la búsqueda por interfaz.

---

## Requisitos del Sistema

1. **Windows 10/11** (64-bit recomendado)
2. **Python 3.10 o superior**
3. **VimbaX SDK** instalado desde [Allied Vision](https://www.alliedvision.com/en/products/software/vimba-x-sdk/)
4. **Cámara Allied Vision** conectada vía GigE/Ethernet en la misma subred que el PC

---

## Instalación

### 1. Instalar VimbaX SDK

Descarga e instala VimbaX SDK desde el sitio oficial de Allied Vision. Asegúrate de que los drivers de red estén correctamente instalados y verifica con **Vimba X Viewer** que la cámara sea detectada.

### 2. Instalar dependencias de Python

```bash
pip install vmbpy numpy opencv-python
```

### 3. Verificar instalación

```powershell
python -c "import vmbpy; print('VimbaX OK')"
python -c "import cv2; print('OpenCV:', cv2.__version__)"
```

### 4. Listar cámaras detectadas

```powershell
python -c "
import vmbpy
with vmbpy.VmbSystem.get_instance() as vmb:
    cams = vmb.get_all_cameras()
    print(f'Cámaras detectadas: {len(cams)}')
    for cam in cams:
        print(f'  - {cam.get_id()} | {cam.get_name()}')
"
```

---

## Estructura del Proyecto

```
ModulosNuevos/
├── capture_imagen.py            # Script principal de captura
├── config_camara_ejemplo.json   # Archivo de configuración de la cámara
└── README.md                    # Esta documentación
```

---

## Uso

### Desde PowerShell (recomendado)

```powershell
# Navega a la carpeta del script
cd "D:\ModulosNuevos"

# Ejecutar captura
python capture_imagen.py <ip_camara> <carpeta_destino> <ruta_config.json>
```

```powershell
python capture_imagen.py "169.254.163.138" "D:\CarpetaDestino" "D:\ModulosNuevos\config_camara_ejemplo.json"
```

**Con variables para mayor legibilidad:**

```powershell
$ip      = "169.254.163.138"
$salida  = "D:\Trabajo\AbrilPruebas\Modulo_Pacho"
$config  = "D:\Trabajo\Codigos\ModulosNuevos\config_camara_ejemplo.json"

python capture_imagen.py $ip $salida $config
```

### Desde VS Code (launch.json)

Crea o edita el archivo `.vscode/launch.json` en tu proyecto:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Captura Galletas",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/capture_imagen.py",
            "args": [
                "169.254.163.138",
                "D:/Trabajo/AbrilPruebas/Modulo_Pacho",
                "D:/Trabajo/Codigos/ModulosNuevos/config_camara_ejemplo.json"
            ],
            "console": "integratedTerminal"
        }
    ]
}
```

Luego presiona **F5** para ejecutar con depuración.

---

## Parámetros de Entrada

| Parámetro | Tipo | Descripción | Ejemplo |
|-----------|------|-------------|---------|
| `ip_camara` | string | IP de la cámara GigE | `169.254.163.138` |
| `carpeta_destino` | string | Ruta donde se guardarán las imágenes PNG | `D:\Trabajo\AbrilPruebas\Modulo_Pacho` |
| `ruta_config` | string | Ruta al archivo JSON de configuración | `D:\Trabajo\Codigos\ModulosNuevos\config_camara_ejemplo.json` |

---

## Archivo de Configuración JSON

Todos los parámetros de la cámara se controlan desde `config_camara_ejemplo.json`. **No es necesario modificar el código Python.**

### Ejemplo completo

```json
{
  "_comentario": "Configuración para cámara Allied Vision - Proyecto Galletas",

  "exposure_mode":       "Timed",
  "exposure_time":       15000.0,
  "gain":                0.0,
  "gamma":               1.0,
  "pixel_format":        "BayerRG8",

  "width":               2448,
  "height":              2048,
  "offset_x":            0,
  "offset_y":            0,

  "balance_white_auto":  "Off",
  "trigger_source":      "Software",
  "trigger_mode":        "Off",

  "features": {
    "AcquisitionMode": "SingleFrame"
  }
}
```

### Referencia de parámetros

| Clave JSON | Feature de cámara | Tipo | Rango / Opciones | Descripción |
|---|---|---|---|---|
| `exposure_mode` | `ExposureAuto` | string | `"Timed"` / `"Auto"` | Modo de exposición |
| `exposure_time` | `ExposureTimeAbs` | float | `76.4` → `~10,000,000` µs | Tiempo de exposición en microsegundos |
| `gain` | `Gain` | float | `0.0` → `47.9` dB | Ganancia del sensor |
| `gamma` | `Gamma` | float | `0.5` → `2.0` | Corrección gamma |
| `pixel_format` | `PixelFormat` | string | `"BayerRG8"` / `"Mono8"` / `"RGB8"` | Formato de píxel |
| `width` | `Width` | int | hasta `2848` | Ancho del área de captura |
| `height` | `Height` | int | hasta `2848` | Alto del área de captura |
| `offset_x` | `OffsetX` | int | `0` → `width_max - width` | Desplazamiento horizontal del ROI |
| `offset_y` | `OffsetY` | int | `0` → `height_max - height` | Desplazamiento vertical del ROI |
| `balance_white_auto` | `BalanceWhiteAuto` | string | `"Off"` / `"Once"` / `"Continuous"` | Balance de blancos automático |
| `trigger_source` | `TriggerSource` | string | `"Software"` / `"Line1"` | Fuente del trigger |
| `trigger_mode` | `TriggerMode` | string | `"Off"` / `"On"` | Modo de trigger |
| `features` | *(cualquiera)* | dict | — | Features avanzadas por nombre directo |

### Ajuste de Ganancia y Gamma

Para el proyecto de galletas en ambiente controlado con iluminación fija:

| Parámetro | Valor recomendado | Efecto |
|---|---|---|
| `gain` | `0.0` (mínimo) | Minimiza ruido digital |
| `gain` | `2.0` – `5.0` | Aumenta brillo con algo de ruido |
| `gamma` | `1.0` | Respuesta lineal (neutro) |
| `gamma` | `< 1.0` ej. `0.8` | Aclara sombras |
| `gamma` | `> 1.0` ej. `1.2` | Oscurece medios tonos |

> **Regla general:** mantén `gain` lo más bajo posible y ajusta primero `exposure_time` para controlar el brillo.

---

## Flujo de Ejecución

```
1. Leer config JSON
       ↓
2. Inicializar VmbSystem (SDK)
       ↓
3. Buscar cámara por IP (filtra simuladores)
       ↓
4. Abrir conexión con la cámara
       ↓
5. Esperar 5 s de estabilización
       ↓
6. Aplicar parámetros del JSON
       ↓
7. Capturar frame (timeout: 5 s)
       ↓
8. Guardar PNG con timestamp
       ↓
9. Cerrar cámara y liberar SDK  ← siempre se ejecuta, incluso con error
```

---

## Salida

Las imágenes se guardan en la `carpeta_destino` con el siguiente formato de nombre:

```
captura_YYYYMMDD_HHMMSS_ffffff.png
```

**Ejemplo:**
```
captura_20260424_132957_483201.png
```

---

## Configuración de Red para Cámaras GigE

Las cámaras detectadas con IPs `169.254.x.x` tienen **IP de enlace local (APIPA)**, lo que significa que no reciben IP del router. Para producción se recomienda asignar IPs fijas:

1. Abre **Vimba X Viewer**
2. Selecciona la cámara → pestaña de configuración de red
3. Asigna una IP estática en el rango de tu red (ej. `192.168.1.10`)
4. Asegúrate de que tu PC esté en la **misma subred** que la cámara
5. Si hay problemas de conexión, agrega excepciones al firewall para VimbaX

Para ver qué cámaras están visibles en la red:

```powershell
arp -a
# Las cámaras Allied Vision tienen MACs que empiezan por 00-0A-47
```

---

## Solución de Problemas

### "No se encontró ninguna cámara con IP '...'"

- Verifica la IP con Vimba X Viewer o corriendo el diagnóstico:
  ```powershell
  python diagnostico_camaras.py
  ```
- Confirma que el PC y la cámara estén en la misma subred
- Revisa que el cable esté conectado al puerto correcto

### "Feature 'X' not found"

Aparece como `[WARNING]` cuando un parámetro del JSON no está disponible en el firmware de esa cámara. No es un error fatal — el script continúa con los parámetros que sí fueron aplicados.

### "Frame incompleto"

- Aumenta el `TIMEOUT_CAPTURA_MS` en el script (por defecto `5000` ms)
- Verifica la conexión de red (cable, switch)
- Reduce la resolución (`width` / `height`) en el JSON

### "Error inicializando VimbaX"

- Verifica que VimbaX SDK esté instalado correctamente
- Ejecuta PowerShell o VS Code **como administrador**
- Reinstala los drivers de la cámara desde Vimba X Viewer

---

## Dependencias

| Paquete | Versión mínima | Uso |
|---|---|---|
| `vmbpy` | 1.2.1 | SDK Allied Vision VimbaX |
| `numpy` | 1.21+ | Conversión de frames a arrays |
| `opencv-python` | 4.5+ | Conversión de color y guardado PNG |

---

## Recursos Adicionales

- [Documentación VimbaX SDK](https://docs.alliedvision.com/Vimba_X/)
- [Allied Vision Support](https://www.alliedvision.com/en/support/)
- [Especificaciones Alvium G5-811c](https://www.alliedvision.com/en/products/camera-series/alvium/)
- [OpenCV Documentation](https://docs.opencv.org/)
