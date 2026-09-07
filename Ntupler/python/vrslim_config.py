"""Pure-Python validation shared by CMSSW configuration and local tests."""
import hashlib
import math
import struct


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
    # Keep this module importable by the Python 2.7 cmsRun in CMSSW_10_6.
    # Query/fragment removal is sufficient here because only the final path
    # component is used; avoid urllib.parse, which exists only in Python 3.
    path = source.split('#', 1)[0].split('?', 1)[0]
    if path.startswith('file:'):
        path = path[5:]
    name = path.rstrip('/').rsplit('/', 1)[-1]
    if not name:
        raise ValueError('Input MiniAOD URI has no filename: ' + source)
    return name


def stable_source_id(source):
    """Return a reproducible uint64 identity for one MiniAOD basename."""
    digest = hashlib.sha256(source_name(source).encode('utf-8')).digest()
    # struct.unpack is available in both Python 2.7 and Python 3 and gives the
    # same big-endian uint64 definition as int.from_bytes(..., 'big').
    return struct.unpack('>Q', digest[:8])[0]
