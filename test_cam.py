import vmbpy

with vmbpy.VmbSystem.get_instance() as vmb:
    cameras = vmb.get_all_cameras()
    print(f"Cámaras detectadas: {len(cameras)}")
    for i, cam in enumerate(cameras):
        print(f"  Cámara {i}: ID={cam.get_id()} | Modelo={cam.get_model()} | Serie={cam.get_serial()}")