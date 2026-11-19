import gymnasium as gym

# SO-101 picks up the Lux3D takeout box, scaled to fit its ~65 mm jaw opening.
gym.register(
    id="LeIsaac-SO101-LiftTakeoutBox-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": f"{__name__}.lift_takeout_box_env_cfg:LiftTakeoutBoxEnvCfg"},
)

# Same task with the box at the Lux3D-predicted size (~12 cm); expected to exceed the jaw opening.
gym.register(
    id="LeIsaac-SO101-LiftTakeoutBox-Real-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": f"{__name__}.lift_takeout_box_env_cfg:LiftTakeoutBoxRealEnvCfg"},
)
