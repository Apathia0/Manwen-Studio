# encoding: utf-8
import sys; sys.path.insert(0, '.')
from database import SessionLocal
from models import Plan, PlanFeature

db = SessionLocal()
plans = db.query(Plan).all()
for plan in plans:
    features = db.query(PlanFeature).filter(PlanFeature.plan_id == plan.id).all()
    print(f'Plan: id={plan.id} code={plan.code} name={plan.name}')
    for f in features:
        v = f.value_json
        if any(k in f.feature_key for k in ['video', 'manga.image.generate', 'manga.image.monthly']):
            print(f'  ** {f.feature_key}: {v}')
    print()
db.close()
