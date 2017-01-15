from .crates import CrateBase
import subprocess, os, errno, sys

class GitCrate(CrateBase):
    def __init__(self, root, name, commit, url):
        CrateBase.__init__(self, root, name)
        self.commit = commit
        self.url = url

    def status(self):
        try:
            commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=self.path).strip()
        except subprocess.CalledProcessError as e:
            return 'D'

        if self.commit == commit:
            return ' '
        else:
            return 'M'

    @classmethod
    def load(cls, root, name, spec):
        return cls(root, name, spec['commit'], spec['url'])

    def save(self):
        r = {
            'type': 'git',
            'commit': self.commit,
            'url': self.url,
            }
        self._save_deps(r)
        return r

    def checkout(self):
        self._clean_env()
        if os.path.isdir(os.path.join(self.path, '.git')):
            with open(os.devnull, 'w') as devnull:
                r = subprocess.call(['git', 'rev-parse', '--verify', '--quiet', self.commit], stdout=devnull, cwd=self.path)
            if r != 0:
                subprocess.check_call(['git', 'fetch', 'origin'], cwd=target_dir)

            commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=self.path).strip()
            if commit == self.commit:
                return
        else:
            try:
                os.makedirs(os.path.split(self.path)[0])
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

            subprocess.check_call(['git', 'clone', self.url, self.path, '--no-checkout'])

        print('checkout {} to {}'.format(self.commit, self.path))
        subprocess.check_call(['git', 'config', 'hooks.suppresscrater', 'true'], cwd=self.path)
        subprocess.check_call(['git', '-c', 'advice.detachedHead=false', 'checkout', self.commit], cwd=self.path)

    def commit(self):
        self._clean_env()
        subprocess.check_call(['git', 'update-index', '-q', '--refresh'], cwd=self.path)

        r = subprocess.call(['git', 'diff-index', '--quiet', 'HEAD', '--'], cwd=self.path)
        if r != 0:
            raise RuntimeError('error: there are changes in {}'.format(self.path))

        commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=self.path).strip()
        if self.commit != commit:
            print('updating lock on {} to {}'.format(self.repo, commit))

        self.commit = commit

    def _clean_env(self):
        # This is a workaround. For whatever reason, git calls are not reentrant.
        for key in list(os.environ):
            if key.startswith('GIT_') and key != 'GIT_SSH':
                os.unsetenv(key)
                del os.environ[key]
