from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node
DeclareLaunchArgument('namespace', default_value='wy_robot1')
Node(package='arm_control', executable='arm_system_node', namespace='wy_robot1')
