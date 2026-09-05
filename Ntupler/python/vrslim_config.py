"""Pure-Python validation shared by CMSSW configuration and local tests."""
import hashlib
import math
from urllib.parse import urlsplit


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


def source_name(source):
    """Return the location-independent MiniAOD basename from a path or URI."""
    name = urlsplit(source).path.rstrip('/').rsplit('/', 1)[-1]
    if not name:
        raise ValueError('Input MiniAOD URI has no filename: ' + source)
    return name


def stable_source_id(source):
    """Return a reproducible uint64 identity for one MiniAOD basename."""
    digest = hashlib.sha256(source_name(source).encode('utf-8')).digest()
    return int.from_bytes(digest[:8], byteorder='big', signed=False)
