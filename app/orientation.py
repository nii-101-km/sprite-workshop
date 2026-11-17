"""Shared rigid orientation format, matching Three.js quaternion [x,y,z,w]."""
import math


def quaternion(value):
    if not isinstance(value, list) or len(value) != 4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in value):
        raise ValueError('Неверное положение 3D-модели')
    length = math.sqrt(sum(v*v for v in value))
    if not .5 <= length <= 1.5:
        raise ValueError('Неверное положение 3D-модели')
    return [v/length for v in value]


def rotation_matrix(value):
    x,y,z,w = quaternion(value)
    return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),0],
            [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),0],
            [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),0],
            [0,0,0,1]]


def height_offset(value):
    """Vertical offset as a percentage of the unrotated model's longest side."""
    if type(value) not in (int,float) or not math.isfinite(value) or not -50 <= value <= 50:
        raise ValueError('Высота должна быть от −50 до 50%')
    return float(value)


def model_scale(value):
    """Absolute percentages in the original model's local axes."""
    if not isinstance(value,list) or len(value)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or not 1<=v<=1000 for v in value):
        raise ValueError('Масштаб X/Y/Z должен быть от 1 до 1000%')
    return [float(v) for v in value]
