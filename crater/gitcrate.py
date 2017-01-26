import subprocess, os, errno, sys, six

class GitLock:
    def __init__(self, url, commit, dirty=False):
        self.dirty = dirty

        self._url = url
        self._commit = commit

    def save(self):
        assert not self.dirty
        return {
            'type': 'git',
            'commit': self._commit,
            'url': self._url,
            }

    def checkout(self, path):
        _clean_env()
        if os.path.isdir(os.path.join(path, '.git')):
            with open(os.devnull, 'w') as devnull:
                r = subprocess.call(['git', 'rev-parse', '--verify', '--quiet', '{}^{{commit}}'.format(self._commit)], stdout=devnull, cwd=path)
            if r != 0:
                subprocess.check_call(['git', 'fetch', 'origin'], cwd=path)

            #commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=path).strip()
            #if commit == self._commit:
            #    return
        else:
            try:
                os.makedirs(os.path.split(path)[0])
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

            subprocess.check_call(['git', 'clone', self._url, path, '--no-checkout'])

        # XXX print('checkout {} to {}'.format(lock.commit, lock.path))
        subprocess.check_call(['git', 'config', 'hooks.suppresscrater', 'true'], cwd=path)
        subprocess.check_call(['git', '-c', 'advice.detachedHead=false', 'checkout', self._commit], cwd=path)

    @classmethod
    def status(cls, path):
        try:
            commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=path).strip()
            origin = subprocess.check_output(['git', 'config', '--get', 'remote.origin.url'], cwd=path).strip()

            subprocess.check_call(['git', 'update-index', '-q', '--refresh'], cwd=path)
            dirty = subprocess.call(['git', 'diff-index', '--quiet', 'HEAD', '--'], cwd=path) != 0
        except subprocess.CalledProcessError as e:
            return None

        return cls(origin, commit, dirty)

class GitDepSpec:
    def __init__(self, url, branches):
        self.handler = GitCrate

        self._url = url
        self._branches = branches

    def name_hint(self):
        hint = self._url.replace('\\', '/').rsplit('/', 1)[-1]
        if hint.endswith('.git'):
            hint = hint[:-4]
        return hint

    def init(self, path):
        assert self._branches

        subprocess.check_call(['git', 'clone', self._url, path, '--no-checkout'])

        try:
            subprocess.check_call(['git', 'fetch', 'origin'] + self._branches, cwd=path)

            if len(self._branches) == 1:
                merge_base = _get_git_commit(path, self._branches[0])
            else:
                merge_base = subprocess.check_output(['git', 'merge-base'] + ['origin/{}'.format(b) for b in self._branches], cwd=path).strip()

            return GitLock(self._url, merge_base)
        except:
            def readonly_handler(rm_func, path, exc_info):
                if issubclass(exc_info[0], OSError) and exc_info[1].winerror == 5:
                    os.chmod(path, stat.S_IWRITE)
                    return rm_func(path)
                raise exc_info[1]
            shutil.rmtree(target, onerror=readonly_handler)
            raise

    def handler(self):
        return GitCrate

class GitCrate:
    @classmethod
    def load_lock(cls, spec):
        return GitLock(spec['url'], spec['commit'])

    @classmethod
    def load_depspec(cls, spec):
        url = spec['url']
        branches = spec.get('branch', 'master')
        if isinstance(branches, six.string_types):
            branches = [branches]

        return GitDepSpec(url, branches)


def _get_git_commit(path, ref='HEAD'):
    return subprocess.check_output(['git', 'rev-parse', '--verify', ref], cwd=path).strip()

def _clean_env():
    # This is a workaround. For whatever reason, git calls are not reentrant.
    for key in list(os.environ):
        if key.startswith('GIT_') and key != 'GIT_SSH':
            os.unsetenv(key)
            del os.environ[key]
