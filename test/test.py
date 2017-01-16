import shutil, tempfile, subprocess, os, sys, unittest, stat
from crater import crater

def _rmtree_ro(path):
    def del_rw(action, name, exc):
        os.chmod(name, stat.S_IWRITE)
        os.remove(name)
    shutil.rmtree(path, onerror=del_rw)

class Ctx:
    def __enter__(self):
        self._prev_dir = os.getcwd()
        self._root_dir = tempfile.mkdtemp()
        self._named_root = tempfile.mkdtemp()
        self._dirs = [self._named_root]
        os.chdir(self._root_dir)
        return self

    def __exit__(self, type, value, tb):
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
            subprocess.check_call(['git', 'init'], cwd=r)
            open(os.path.join(r, file), 'w').close()
            subprocess.check_call(['git', 'add', file], cwd=r)
            subprocess.check_call(['git', 'commit', '-m', 'init'], cwd=r)

            self._dirs.append(r)
            return r
        except:
            _rmtree_ro(r)
            raise

class TestCrater(unittest.TestCase):
    def test_add_git_auto(self):
        with Ctx() as ctx:
            repo = ctx.make_repo(name='test_repo')

            crater.main('add-git', repo)

            self.assertTrue(os.path.isfile('_deps/test_repo/content'))
            self.assertTrue(os.path.isfile('.deps.lock'))

if __name__ == '__main__':
    unittest.main()
