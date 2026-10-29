"""Dimensionless quartic LGD benchmark; no calibrated BaTiO3 parameters."""
import numpy as np

ALPHA, BETA, MOBILITY = -1.0, 1.0, 1.0

def landau(p):
    return -p*p/2 + p**4/4

def wall(x, g=0.5, width_factor=1.0):
    return np.tanh(np.asarray(x)/(np.sqrt(2*g)*width_factor))

def exact_ode(t, p0):
    if p0 == 0:
        return np.zeros_like(np.asarray(t, dtype=float))
    return np.sign(p0)/np.sqrt(1+(1/p0**2-1)*np.exp(-2*np.asarray(t)))
