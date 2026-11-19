"""Sweep object mass/friction (and contact priority) to see where the scripted grasp fails."""
import contextlib
import io

import grasp
import scene_builder

for priority in (0, 2):
    scene_builder.OBJECT_PRIORITY = priority
    for mass in (0.03, 0.2, 0.5, 1.0):
        for mu in (0.1, 0.3, 0.8):
            scene_builder.OBJECT_MASS_KG = mass
            scene_builder.OBJECT_FRICTION = f"{mu} 0.005 0.0001"
            with contextlib.redirect_stdout(io.StringIO()):
                dz = grasp.run("box_small.obj", render=False)
            verdict = "LIFTED" if dz > 0.03 else "failed"
            print(f"priority={priority} mass={mass:.2f} kg mu={mu}: dz={dz*100:5.1f} cm {verdict}")
