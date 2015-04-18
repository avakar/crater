import fnmatch, os, os.path

def _split_path(path):
    res = []
    while path:
        path, tail = os.path.split(path)
        if not tail:
            if path:
                res.append(path)
            break
        res.append(tail)
    res.reverse()
    return res

def _glob(pattern_parts, path):
    if not pattern_parts:
        if os.path.isfile(path):
            yield path
        return

    head = pattern_parts[0]
    tail = pattern_parts[1:]
    if '*' not in head and '?' not in head:
        for r in _glob(tail, os.path.join(path, head)):
            yield r
        return

    for fname in os.listdir(path):
        if fnmatch.fnmatch(fname, head):
            for r in _glob(tail, os.path.join(path, fname)):
                yield r

def glob(pattern, path):
    return _glob(_split_path(pattern), path)
