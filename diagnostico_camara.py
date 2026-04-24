# diagnostico_camara.py
import vmbpy

with vmbpy.VmbSystem.get_instance() as vmb:
    camaras = vmb.get_all_cameras()
    print(f"\nCámaras detectadas: {len(camaras)}\n")
    for cam in camaras:
        with cam:
            print(f"  ID:     {cam.get_id()}")
            print(f"  Nombre: {cam.get_name()}")
            print(f"  Modelo: {cam.get_model()}")
            print(f"  Serial: {cam.get_serial()}")
            try:
                val = cam.get_feature_by_name("GevCurrentIPAddress").get()
                ip = ".".join(str((val >> (8 * i)) & 0xFF) for i in reversed(range(4)))
                print(f"  IP real: {ip}")
            except:
                pass
            print()
            

