"""Input-event ranges for VRslim production, independent of selected output rows."""
from urllib.parse import urlsplit


def event_ranges(total, size):
    if total < 0 or size <= 0:
        raise ValueError('Event count must be nonnegative and chunk size positive')
    return [(start, min(size, total - start)) for start in range(0, total, size)]


def input_range(arguments):
    values = {'skipEvents': 0, 'maxEvents': -1}
    seen = set()
    for argument in arguments:
        key, sep, value = argument.partition('=')
        if key in values and sep:
            if key in seen:
                raise ValueError('Duplicate event-range argument: ' + key)
            seen.add(key)
            values[key] = int(value)
    if values['skipEvents'] < 0 or values['maxEvents'] == 0 or values['maxEvents'] < -1:
        raise ValueError('skipEvents must be nonnegative; maxEvents must be positive or -1')
    return values


def count_input_events(source, timeout=30):
    """Read the MiniAOD Events entry count, with CMS redirector fallbacks."""
    import uproot
    candidates = [source]
    parts = urlsplit(source)
    if parts.scheme == 'root' and parts.path.startswith('//store/'):
        for host in ('cms-xrd-global.cern.ch', 'xrootd-cms.infn.it'):
            alternative = 'root://' + host + parts.path
            if alternative not in candidates:
                candidates.append(alternative)
    failures = []
    for candidate in candidates:
        try:
            options = {'timeout': timeout}
            if candidate.startswith('root://'):
                options['handler'] = uproot.source.xrootd.XRootDSource
            with uproot.open(candidate, **options) as root:
                return int(root['Events'].num_entries)
        except Exception as error:
            failures.append('%s: %s' % (candidate, error))
    raise RuntimeError('Cannot count input events; no partial queue was written:\n' + '\n'.join(failures))
