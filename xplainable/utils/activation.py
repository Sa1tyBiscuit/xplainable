
import numpy as np

def huntley_activation(v, weight, power_degree, sigmoid_exponent):
    val = (v ** weight) / (10 ** (weight*2))
    
    value = ((val*100 - 50)**power_degree + 50**power_degree) / \
        (2 * (50**power_degree))
    
    return value if sigmoid_exponent < 1 else 1 / (
        1 + np.exp(-((value-0.5)*(10**sigmoid_exponent))))