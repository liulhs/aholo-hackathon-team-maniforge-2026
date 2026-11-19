import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")
import lift_scene as scene  # noqa: E402

READY = scene.available_objects() if (scene.ROBOT_DIR / "so101_nocam.xml").exists() else []
needs_models = pytest.mark.skipif(not READY, reason="run sim/fetch_models.sh first")
SETTLE_STEPS = 500
MIN_UPRIGHT = 0.97  # cos of 14 degrees


def settle(model, data, steps=SETTLE_STEPS):
    for _ in range(steps):
        mujoco.mj_step(model, data)


def test_success_needs_height_held_for_the_hold_time():
    tracker = scene.SuccessTracker()
    assert not tracker.update(scene.LIFT_SUCCESS_M, 0.0)
    assert not tracker.update(scene.LIFT_SUCCESS_M, scene.HOLD_SUCCESS_S / 2)
    assert tracker.update(scene.LIFT_SUCCESS_M, scene.HOLD_SUCCESS_S)


def test_dropping_the_object_restarts_the_hold_clock():
    tracker = scene.SuccessTracker()
    tracker.update(0.06, 0.0)
    tracker.update(0.0, 0.5)
    assert not tracker.update(0.06, 1.2)


def test_random_poses_stay_in_spawn_area():
    rng = np.random.default_rng(0)
    for _ in range(100):
        pose = scene.random_object_pose(rng)
        assert scene.SPAWN_X_M[0] <= pose.x <= scene.SPAWN_X_M[1]
        assert scene.SPAWN_Y_M[0] <= pose.y <= scene.SPAWN_Y_M[1]


def test_unknown_object_is_refused():
    with pytest.raises(ValueError, match="Unknown object"):
        scene.write_scene("no_such_thing")


@needs_models
@pytest.mark.parametrize("name", READY)
def test_object_stands_still_where_it_is_placed(name):
    """At every corner of the play area and two yaws: it does not slide, sink, bounce away or tip over."""
    model, data = scene.load(name)
    for x in scene.SPAWN_X_M:
        for y in scene.SPAWN_Y_M:
            for yaw in (0.0, 2.2):
                scene.place_object(model, data, scene.ObjectPose(x, y, yaw))
                settle(model, data)
                state = scene.object_state(model, data)
                assert np.allclose(state[:2], (x, y), atol=0.004), f"{name} slid at ({x}, {y})"
                assert abs(scene.object_lift_m(model, data)) < 0.003, f"{name} is not resting on the table"
                up = np.cross(state[3:6], state[6:9])  # the object's z axis in the world
                assert up[2] > MIN_UPRIGHT, f"{name} tipped over at ({x}, {y}), yaw {yaw}"
                before = data.qpos.copy()
                settle(model, data, 100)
                assert np.allclose(data.qpos, before, atol=1e-4), f"{name} is still moving"


@needs_models
@pytest.mark.parametrize("name", READY)
def test_object_state_reports_position_yaw_and_size(name):
    model, data = scene.load(name)
    yaw = 0.7
    scene.place_object(model, data, scene.ObjectPose(0.2, 0.05, yaw))
    state = scene.object_state(model, data)
    assert state.shape == (scene.OBJECT_STATE_SIZE,)
    assert np.allclose(state[:2], (0.2, 0.05), atol=1e-6)
    assert np.allclose(state[3:6], (np.cos(yaw), np.sin(yaw), 0.0), atol=1e-6)  # the object's x axis
    assert np.allclose(state[6:9], (-np.sin(yaw), np.cos(yaw), 0.0), atol=1e-6)  # its y axis
    longest_side = scene.OBJECTS[name].grip_width_m
    assert np.isclose(max(state[9], state[10]), longest_side, atol=0.003)  # longer horizontal side, as converted
    assert min(state[9], state[10]) < 0.062, "the shorter horizontal side must fit the 6-7 cm jaw"


@needs_models
@pytest.mark.parametrize("name", READY)
def test_every_scene_has_the_same_state_layout(name):
    """Datasets and the web demo rely on one layout: 6 arm joints, then the object's free joint."""
    model, _ = scene.load(name)
    assert (model.nq, model.nv, model.nu) == (13, 12, 6)
    assert scene.object_qpos_adr(model) == 6


@needs_models
def test_play_area_is_on_the_table_and_clear_of_the_arm_base():
    import simple_table

    half_width = simple_table.TABLE_WIDTH_M / 2
    table_far_x = simple_table.TABLE_EDGE_X_M + simple_table.TABLE_LENGTH_M
    assert scene.SPAWN_X_M[1] + 0.05 < table_far_x
    assert -half_width + 0.05 < scene.SPAWN_Y_M[0] and scene.SPAWN_Y_M[1] < half_width - 0.05
    assert scene.SPAWN_X_M[0] > 0.065 + 0.05  # the arm base reaches x = 0.065
