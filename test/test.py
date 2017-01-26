import shutil, tempfile, subprocess, os, sys, unittest, stat, json
from crater.log import Log

def _rmtree_ro(path):
    def del_rw(action, name, exc):
        os.chmod(name, stat.S_IWRITE)
        os.remove(name)
    shutil.rmtree(path, onerror=del_rw)

def _load_json(path):
    with open(path, 'r') as fin:
        return json.load(fin)

class Ctx:
    def setUp(self):
        self._prev_dir = os.getcwd()
        self._root_dir = tempfile.mkdtemp()
        self._named_root = tempfile.mkdtemp()
        self._dirs = [self._named_root]
        os.chdir(self._root_dir)
        return self

    def tearDown(self):
        for dir in reversed(self._dirs):
            _rmtree_ro(dir)
        os.chdir(self._prev_dir)
        _rmtree_ro(self._root_dir)

    def make_dir(self):
        r = tempfile.mkdtemp()
        self._dirs.append(r)
        return r

    def make_repo(self, name=None, file='content'):
        if name is None:
            r = tempfile.mkdtemp()
        else:
            r = os.path.join(self._named_root, name)
            os.mkdir(r)

        try:
            r = Git(r)
            r.init()
            r.add(file)
            r.commit()
            self._dirs.append(r.path)
            return r
        except:
            _rmtree_ro(r)
            raise

class Git:
    def __init__(self, path):
        self.path = path
        self._commit_counter = 0

    def init(self):
        subprocess.check_call(['git', 'init', '-q'], cwd=self.path)
        subprocess.check_call(['git', 'config', 'hooks.suppresscrater', 'true'], cwd=self.path)

    def add(self, name):
        open(os.path.join(self.path, name), 'w').close()
        subprocess.check_call(['git', 'add', name], cwd=self.path)

    def commit(self):
        self._commit_counter += 1
        subprocess.check_call(['git', 'config', 'user.name', 'Tester'], cwd=self.path)
        subprocess.check_call(['git', 'config', 'user.email', 'test@example.com'], cwd=self.path)
        subprocess.check_call(['git', 'commit', '-q', '-m', 'commit {}'.format(self._commit_counter)], cwd=self.path)
        return self.current_commit()

    def current_commit(self):
        return subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=self.path).strip().decode()

class TestLog:
    def __init__(self):
        self._devnull = open(os.devnull, 'r+b')

    def call(self, *args, **kw):
        kw.setdefault('stdout', self._devnull)
        kw.setdefault('stderr', self._devnull)

        if kw['stdout'] is None:
            kw['stdout'] = self._devnull
        if kw['stderr'] is None:
            kw['stderr'] = self._devnull

        return subprocess.call(*args, **kw)

    def check_call(self, *args, **kw):
        kw.setdefault('stdout', self._devnull)
        kw.setdefault('stderr', self._devnull)

        if kw['stdout'] is None:
            kw['stdout'] = self._devnull
        if kw['stderr'] is None:
            kw['stderr'] = self._devnull

        return subprocess.check_call(*args, **kw)

    def check_output(self, *args, **kw):
        kw.setdefault('stderr', self._devnull)
        if kw['stderr'] is None:
            kw['stderr'] = self._devnull

        return subprocess.check_output(*args, **kw)

    def write(self, s):
        pass

class TestCrater(unittest.TestCase):
    def __init__(self, *args, **kw):
        super(TestCrater, self).__init__(*args, **kw)
        self._pypath = os.path.abspath(os.path.join(os.path.split(__file__)[0], '..'))

    def setUp(self):
        super(TestCrater, self).setUp()
        self.ctx = Ctx()
        self.ctx.setUp()

    def tearDown(self):
        self.ctx.tearDown()
        return super(TestCrater, self).tearDown()

    def _crater_call(self, cmd, **kw):
        from crater import crater
        with open(os.devnull, 'wb') as devnull:
            r = crater._main(cmd, TestLog())
        if r:
            raise subprocess.CalledProcessError(r, cmd, '')

    def test_checkout_nolock(self):
        self._crater_call(['checkout'])
        self.assertFalse(os.path.isfile('.deps.lock'))

    def test_commit_nolock(self):
        self._crater_call(['commit'])
        self.assertFalse(os.path.isfile('.deps.lock'))

    def test_add_git_auto(self):
        repo = self.ctx.make_repo(name='test_repo')

        self._crater_call(['add-git', repo.path])

        self.assertTrue(os.path.isfile('_deps/test_repo/content'))
        self.assertTrue(os.path.isfile('.deps.lock'))

        with open('.deps.lock', 'r') as fin:
            d = json.load(fin)
        self.assertEqual(d['_deps/test_repo']['type'], 'git')
        self.assertEqual(d['_deps/test_repo']['url'], repo.path)
        self.assertEqual(d['_deps/test_repo']['commit'], repo.current_commit())

    def test_add_git_target(self):
        repo = self.ctx.make_repo(name='test_repo')

        self._crater_call(['add-git', repo.path, '_deps/myrepo'])

        self.assertTrue(os.path.isfile('_deps/myrepo/content'))
        self.assertTrue(os.path.isfile('.deps.lock'))

        with open('.deps.lock', 'r') as fin:
            d = json.load(fin)
        self.assertEqual(d['_deps/myrepo']['type'], 'git')
        self.assertEqual(d['_deps/myrepo']['url'], repo.path)
        self.assertEqual(d['_deps/myrepo']['commit'], repo.current_commit())

    def test_simple_checkout(self):
        repo = self.ctx.make_repo(name='test_repo')
        self._crater_call(['add-git', repo.path, 'myrepo'])
        _rmtree_ro('myrepo')

        self._crater_call(['checkout'])
        self.assertTrue(os.path.isfile('myrepo/content'))

    def test_simple_commit(self):
        repo = self.ctx.make_repo(name='test_repo')
        self._crater_call(['add-git', repo.path, 'myrepo'])

        j = _load_json('.deps.lock')
        self.assertEqual(j['myrepo']['commit'], repo.current_commit())

        g = Git('myrepo')
        g.add('another_file')
        c = g.commit()
        self._crater_call(['commit'])

        j = _load_json('.deps.lock')
        self.assertEqual(j['myrepo']['commit'], c)

if __name__ == '__main__':
    unittest.main()
