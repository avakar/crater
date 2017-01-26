import os, errno, sys, six, shutil, stat

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

    def checkout(self, path, log):
        _clean_env()

        log.write('Checking out {}...\n'.format(path))

        if os.path.isdir(os.path.join(path, '.git')):
            r = log.call(['git', 'rev-parse', '--quiet', '--verify', '{}^{{commit}}'.format(self._commit)], stdout=None, cwd=path)
            if r != 0:
                log.check_call(['git', 'fetch', 'origin'], cwd=path)

            #commit = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=path).strip()
            #if commit == self._commit:
            #    return
        else:
            try:
                os.makedirs(os.path.split(path)[0])
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

            log.check_call(['git', 'clone', self._url, path, '--no-checkout'])

        # XXX print('checkout {} to {}'.format(lock.commit, lock.path))
        log.check_call(['git', 'config', 'hooks.suppresscrater', 'true'], cwd=path)
        log.check_call(['git', '-c', 'advice.detachedHead=false', 'checkout', self._commit], cwd=path)

    @classmethod
    def status(cls, path, log):
        try:
            commit = log.check_output(['git', 'rev-parse', '--quiet', '--verify', 'HEAD'], cwd=path).strip()
            origin = log.check_output(['git', 'config', '--get', 'remote.origin.url'], cwd=path).strip()

            log.check_call(['git', 'update-index', '-q', '--refresh'], cwd=path)
            dirty = log.call(['git', 'diff-index', '--quiet', 'HEAD', '--'], cwd=path) != 0
        except log.CalledProcessError as e:
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

    def init(self, path, log):
        assert self._branches

        log.check_call(['git', 'clone', self._url, path, '--no-checkout'])

        try:
            log.check_call(['git', 'fetch', 'origin'] + self._branches, cwd=path)

            if len(self._branches) == 1:
                merge_base = log.check_output(['git', 'rev-parse', '--quiet', '--verify', self._branches[0]], cwd=path).strip()
            else:
                merge_base = log.check_output(['git', 'merge-base'] + ['origin/{}'.format(b) for b in self._branches], cwd=path).strip()

            return GitLock(self._url, merge_base)
        except:
            def readonly_handler(rm_func, path, exc_info):
                if issubclass(exc_info[0], OSError) and exc_info[1].winerror == 5:
                    os.chmod(path, stat.S_IWRITE)
                    return rm_func(path)
                raise exc_info[1]
            shutil.rmtree(path, onerror=readonly_handler)
            raise

    def handler(self):
        return GitCrate

class GitCrate:
    @classmethod
    def load_lock(cls, spec):
        return GitLock(spec['url'], spec['commit'])

    @classmethod
    def load_depspec(cls, spec):
        url = spec.get('repo') or spec['url']
        branches = spec.get('branch', 'master')
        if isinstance(branches, six.string_types):
            branches = [branches]

        return GitDepSpec(url, branches)


def _clean_env():
    # This is a workaround. For whatever reason, git calls are not reentrant.
    for key in list(os.environ):
        if key.startswith('GIT_') and key != 'GIT_SSH':
            os.unsetenv(key)
            del os.environ[key]
