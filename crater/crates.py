import os, cson, errno, six

class Dep:
    def __init__(self, crate_name, name, specs):
        self.crate_name = crate_name
        self.name = name
        self.specs = specs
        self.crate = None

    def full_name(self):
        return '{}:{}'.format(self.crate_name, self.name)

class CrateBase:
    def __init__(self, root, name, links):
        self.root = root
        self.name = name
        self.links = links

        try:
            with open(os.path.join(root, name, 'DEPS'), 'r') as fin:
                d = cson.load(fin)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            d = {}

        self._deps = {}
        for name, data in six.iteritems(d.get('dependencies', {})):
            self._deps[name] = Dep(self.name, name, data)

    def deps(self):
        return six.itervalues(self._deps)

    def full_path(self):
        return os.path.join(self.root, self.name)

    def status(self):
        return '?'

class SelfCrate(CrateBase):
    def __init__(self, root, links):
        CrateBase.__init__(self, root, '', links)

class GitCrate(CrateBase):
    def __init__(self, root, name, links, commit, url):
        CrateBase.__init__(self, root, name, links)
        self.commit = commit
        self.url = url
