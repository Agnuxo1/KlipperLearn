"""Generate synthetic differential cases using the byte-verified Python reference.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import copy
import importlib.util
import json
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('oracle',ROOT/'reference/optimizer.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
base=mod.loads((ROOT/'reference/synthetic-session.json').read_bytes())
cases=[]
for index in range(30):
    s=copy.deepcopy(base)
    if index==1:
        s['printer']['model']='Café 3D 😀'
        s['base_process']['unicode_note']='Original text preserved — 零'
    elif index==2:
        s['candidates'][1]['process']['outer_wall_speed']=35.0
        s['base_process']['non_tuned_float']=1e-8
    elif index>=3:
        for n,t in enumerate(s['trials']):
            t['print_seconds']=600.0+(index*137+n*71)%700
            t['total_seconds']=t['print_seconds']+120
            t['surface_score']=3.5+(index*37+n*7)%14/10
            t['geometry_score']=3.5+(index*11+n*3)%14/10
        s['policy']['maximum_time_cv']=0.5
    if index>=25:
        s['base_process']['💡']='Unicode-key preservation'
        s['base_process']['\uffff']='Code-point sorted identity'
        s['limits']['filament.pressure_advance']={'min':0,'max':0.2,'max_step':0.01}
        s['candidates'][1]['filament']['pressure_advance']=[1e-5,2e-5,0.00009999,0.0001,1e-6][index-25]
    for t in s['trials']:
        c=next(c for c in s['candidates'] if c['id']==t['candidate_id'])
        t['configuration_sha256']=mod.configuration_sha256(s,c)
    proposal={'schema':'klipperlearn.slicer-proposal/v1','session_sha256':mod.digest(s),
        'anchor_candidate_id':'baseline','parameter':'process.outer_wall_speed','value':42,
        'evidence_trial_ids':[s['trials'][0]['id']],'rationale':'Synthetic one-step test, never measured evidence.'}
    cases.append({'text':json.dumps(s,ensure_ascii=False),'hashes':{c['id']:mod.configuration_sha256(s,c) for c in s['candidates']},
        'review':mod.review_session(s),'profiles':mod.build_profiles(s),'proposal':proposal,'proposal_result':mod.validate_proposal(s,proposal)})
(ROOT/'tests/oracle.json').write_text(json.dumps(cases,ensure_ascii=False),encoding='utf-8')
print(f'{len(cases)} Python oracle cases generated.')
