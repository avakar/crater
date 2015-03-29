import fnmatch, os, os.path

def glob(pattern, path):
    for fname in os.listdir(path):
        if fnmatch.fnmatch(fname, pattern):
            yield fname
