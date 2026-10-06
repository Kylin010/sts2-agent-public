"""Conservative visible incoming damage bound for Mangle's temporary loss.

The HUD floors each hit. Invert only reviewed Strength/Weak/Vulnerable factors;
unclassified direct damage hooks defer. Never peek at a native damage formula.
"""
from fractions import Fraction
from pathlib import Path
import json
from policy import enemy_powers as EP

CATALOG=json.loads((Path(__file__).resolve().parent.parent/'kb/public_damage_modifier_sources_v55.json').read_text())

def _power(owner,id):return next((p.get('amount',0)for p in owner if p.get('id')==id),0)

def mangle_incoming_bound(combo,enemy,ctx,targets):
    cards=[c for c in combo if str(c.get('id','')).split('.')[-1]=='MANGLE' and targets.get(id(c))is enemy]
    if not cards or EP.debuff_blocked(enemy):return None
    if _power(enemy.get('powers')or[], 'ARTIFACT_POWER')>0:return None
    losses=[(c.get('stats')or{}).get('strengthloss')for c in cards]
    if any(type(v)is not int or v<=0 for v in losses):return None
    ep=enemy.get('powers')or[];hp=ctx.get('player_powers')or[]
    if any((c.get('stats')or{}).get('enemystrength',0)for c in combo):return None
    if _power(ep,'ENRAGE_POWER')>0 and any(c.get('type')=='Skill'for c in combo):return None
    ignored_enemy={'STRENGTH_POWER','WEAK_POWER','VULNERABLE_POWER','INTANGIBLE_POWER'}
    ignored_hero={'STRENGTH_POWER','WEAK_POWER','VULNERABLE_POWER'}
    for owner,ignored in [(ep,ignored_enemy),(hp,ignored_hero)]:
        for power in owner:
            power_id=power.get('id')
            if power_id in ignored:continue
            rule=CATALOG.get(power_id)
            if not rule or not rule['no_direct_damage_hook']:return None
    for rid in ctx.get('relics')or[]:
        rule=CATALOG.get(rid)
        if not rule or not rule['no_direct_damage_hook']:return None
    multiplier=Fraction(3,4)if _power(ep,'WEAK_POWER')>0 else Fraction(1)
    if _power(hp,'VULNERABLE_POWER')>0:multiplier*=Fraction(3,2)
    shift=sum(losses)*multiplier;before=after=0;bounds=[]
    for intent in enemy.get('intents')or[]:
        if intent.get('type')!='Attack':continue
        d=intent.get('damage');hits=intent.get('hits',1)
        if type(d)is not int or d<0 or type(hits)is not int or hits<1:return None
        # Raw displayed-modified damage lies in [d,d+1). Subtract the
        # additive-strength shift before flooring, retain the worst outcome.
        limit=Fraction(d+1)-shift
        upper=max(0,-(-limit.numerator//limit.denominator)-1)
        lower=max(0,(Fraction(d)-shift).numerator//(Fraction(d)-shift).denominator)
        before+=d*hits;after+=upper*hits;bounds.append(dict(shown=d,hits=hits,after_lower=lower,after_upper=upper))
    return dict(status='source_bounded_visible_strength_effect',shown_before=before,after_upper=after,
                prevented_lower=before-after,hits=bounds,temporary_owner_turn_only=True)
