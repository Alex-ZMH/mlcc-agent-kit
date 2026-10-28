"""Independent circuit algebra and analytic RC ramp response; never solver data."""
import numpy as np
def impedance(m,f):
    w=2*np.pi*np.asarray(f);z=m.esr_ohm+1j*w*m.esl_H+1/(1j*w*m.capacitance_F)
    return z if m.leakage_resistance_ohm is None else 1/(1/z+1/m.leakage_resistance_ohm)
def parallel(models,f):return 1/sum(1/impedance(m,f) for m in models)
def rc_voltage(c,C,t):
    tau=c['source_resistance_ohm']*C;rise=c['rise_s'];td=c['delay_s'];tf=td+rise+c['hold_s'];fall=c['fall_s']
    def F(s):
        s=np.maximum(s,0);return s+tau*np.expm1(-s/tau)
    return c['supply_V']-c['source_resistance_ohm']*c['baseline_A']-c['source_resistance_ohm']*c['step_A']*((F(t-td)-F(t-td-rise))/rise-(F(t-tf)-F(t-tf-fall))/fall)
