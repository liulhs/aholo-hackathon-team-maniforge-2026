"""Control: same sweep with a plain cuboid of identical extents (no taper)."""
import contextlib
import io

import grasp
import scene_builder

scene_builder.OBJECT_PRIORITY = 2
for mass in (0.03, 0.2, 0.5, 1.0):
    for mu in (0.1, 0.3, 0.8):
        scene_builder.OBJECT_MASS_KG = mass
        scene_builder.OBJECT_FRICTION = f"{mu} 0.005 0.0001"
        with contextlib.redirect_stdout(io.StringIO()):
            dz = grasp.run("plain_box.obj", render=False)
        print(f"plain box priority=2 mass={mass:.2f} mu={mu}: dz={dz*100:5.1f} cm {'LIFTED' if dz > 0.03 else 'failed'}")
