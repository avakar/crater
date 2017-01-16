import shutil, tempfile, subprocess, os, sys, unittest, stat, json
from crater import crater

def _rmtree_ro(path):
    def del_rw(action, name, exc):
        os.chmod(name, stat.S_IWRITE)
        os.remove(name)
    shutil.rmtree(path, onerror=del_rw)

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
            subprocess.check_call(['git', 'init', '-q'], cwd=r)
            subprocess.check_call(['git', 'config', 'user.name', 'Tester'], cwd=r)
            subprocess.check_call(['git', 'config', 'user.email', 'test@example.com'], cwd=r)

            open(os.path.join(r, file), 'w').close()
            subprocess.check_call(['git', 'add', file], cwd=r)
            subprocess.check_call(['git', 'commit', '-q', '-m', 'init'], cwd=r)

            self._dirs.append(r)
            return r
        except:
            _rmtree_ro(r)
            raise

class TestCrater(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ctx = Ctx()
        self.ctx.setUp()

    def tearDown(self):
        self.ctx.tearDown()
        return super().tearDown()

    def test_add_git_auto(self):
        repo = self.ctx.make_repo(name='test_repo')

        crater.main('add-git', repo, '-q')

        self.assertTrue(os.path.isfile('_deps/test_repo/content'))
        self.assertTrue(os.path.isfile('.deps.lock'))

        with open('.deps.lock', 'r') as fin:
            d = json.load(fin)
        self.assertEqual(d['_deps/test_repo']['type'], 'git')
        self.assertEqual(d['_deps/test_repo']['url'], repo)

    def test_add_git_target(self):
        repo = self.ctx.make_repo(name='test_repo')

        crater.main('add-git', repo, '_deps/myrepo', '-q')

        self.assertTrue(os.path.isfile('_deps/myrepo/content'))
        self.assertTrue(os.path.isfile('.deps.lock'))

        with open('.deps.lock', 'r') as fin:
            d = json.load(fin)
        self.assertEqual(d['_deps/myrepo']['type'], 'git')
        self.assertEqual(d['_deps/myrepo']['url'], repo)

    def test_checkout_nolock(self):
        self.assertEqual(crater.main('checkout'), 0)
        self.assertFalse(os.path.isfile('.deps.lock'))

    def test_commit_nolock(self):
        self.assertEqual(crater.main('commit'), 0)
        self.assertFalse(os.path.isfile('.deps.lock'))


if __name__ == '__main__':
    unittest.main()
