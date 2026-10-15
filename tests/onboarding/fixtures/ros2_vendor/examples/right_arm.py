from demo_arm.action import ArmMove
from demo_arm.msg import ArmState
from rclpy.action import ActionClient

NS = "/wy"

class Demo:
    def __init__(self):
        self.action = ActionClient(self, ArmMove, f"{NS}/right_arm_move_action")
        self.create_subscription(ArmState, f"{NS}/right_arm_state", self.state_cb, 10)

    def state_cb(self, msg):
        self.mode = msg.arm_mode
        self.joints = list(msg.joint_angles)
        if msg.arm_fault.fault_code != 0:
            raise RuntimeError("arm fault")

    def wait_joint_near(self, target, tol=0.03, timeout=5.0, settle=0.2):
        return True

    def movej(self, joints, timeout=20.0):
        goal = ArmMove.Goal(
            move_type="MoveJ",
            joint_angles=list(joints),
            cart_pose=[0.0] * 6,
        )
        result = self.wait(goal, timeout=timeout).result
        return result.error_code.value == 0
