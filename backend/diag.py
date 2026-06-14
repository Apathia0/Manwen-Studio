# encoding: utf-8
import sys; sys.path.insert(0, '.')
from database import SessionLocal
from models import Plan, PlanFeature, User, UserSubscription

db = SessionLocal()
user = db.query(User).first()
if user:
    print(f'用户: id={user.id} email={user.email} name={user.name}')
else:
    print('无用户'); db.close(); exit(0)

sub = db.query(UserSubscription).filter(UserSubscription.user_id == user.id).first()
if sub:
    plan = db.get(Plan, sub.plan_id)
    pc = plan.code if plan else '?'
    pn = plan.name if plan else '?'
    print(f'订阅: plan_id={sub.plan_id} status={sub.status} plan_code={pc} plan_name={pn}')
    plan_id = sub.plan_id
else:
    plan = db.query(Plan).filter(Plan.code == 'free').first()
    plan_id = plan.id if plan else 0
    print(f'无订阅，使用 Free 套餐 id={plan_id}')

features = db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id).all()
print(f'\n套餐 id={plan_id} 的 PlanFeature:')
for f in features:
    print(f'  {f.feature_key}: {f.value_json}')

db.close()
