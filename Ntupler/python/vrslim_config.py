"""Pure-Python validation shared by CMSSW configuration and local tests."""
import math


def radius_label(radius):
    token = ('%.12g' % radius).lower()
    return 'r' + token.replace('.', 'p').replace('-', 'm').replace('+', '')


def parse_radii(spec):
    values = [float(x.strip()) for x in spec.split(',')]
    if not values or any(x <= 0 or math.isnan(x) or math.isinf(x) for x in values):
        raise ValueError('jetRadii must contain positive finite physical radii')
    labels = [radius_label(x) for x in values]
    if len(set(labels)) != len(labels):
        raise ValueError('Duplicate radii or colliding twelve-digit radius labels')
    return values


def validate_thresholds(gen, reco, final):
    values = [gen, reco, final]
    if any(math.isnan(x) or math.isinf(x) for x in values) or not 0 <= gen <= reco <= final:
        raise ValueError('Require finite 0 <= genJetPtMin <= jetPreselectionPtMin <= jetPtMin')
