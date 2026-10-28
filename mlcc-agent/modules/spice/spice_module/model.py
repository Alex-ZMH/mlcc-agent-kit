"""SI compact model; no fitting or cross-scale data transfer."""
from dataclasses import dataclass,asdict
import math,re

@dataclass(frozen=True)
class MLCC:
    model_name:str
    model_version:str
    source:str
    capacitance_F:float
    esr_ohm:float
    esl_H:float
    leakage_resistance_ohm:float|None
    validated_conditions:dict

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,60}',self.model_name):raise ValueError('safe alphanumeric model name required')
        if not isinstance(self.model_version,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}', self.model_version):raise ValueError('safe model_version required')
        if self.source not in ['synthetic','manual']:raise ValueError('only synthetic/manual sources implemented')
        if not isinstance(self.validated_conditions,dict) or not self.validated_conditions:raise ValueError('explicit applicable conditions required')
        for key, value in self.validated_conditions.items():
            if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,60}',key):raise ValueError('safe condition keys required')
            if not isinstance(value,str) or not value.strip() or len(value)>200 or re.search(r'[\x00-\x1f]|\.(?:control|include|end|exec)\b',value,re.I):raise ValueError('safe nonempty applicability text required')
        for key in ['capacitance_F','esr_ohm','esl_H','leakage_resistance_ohm']:
            v=getattr(self,key)
            if key=='leakage_resistance_ohm' and v is None:continue
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError(f'{key}: finite SI number required')
            if v<0 or (key in ['capacitance_F','leakage_resistance_ohm'] and v==0):raise ValueError(f'{key}: invalid sign')
    @classmethod
    def from_dict(cls,d):return cls(**d)
    def as_dict(self):return asdict(self)

def subcircuit(m):
    """Branch p -> ESR -> ESL -> C -> n, optional leakage across p/n."""
    lines=[f'.subckt {m.model_name} p n'];node='p'
    if m.esr_ohm>0:lines.append(f'Rser {node} nr {m.esr_ohm:.17e}');node='nr'
    if m.esl_H>0:lines.append(f'Lser {node} nl {m.esl_H:.17e}');node='nl'
    lines.append(f'Cmain {node} n {m.capacitance_F:.17e}')
    if m.leakage_resistance_ohm is not None:lines.append(f'Rleak p n {m.leakage_resistance_ohm:.17e}')
    return '\n'.join(lines+[f'.ends {m.model_name}'])
