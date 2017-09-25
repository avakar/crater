import os, errno, sys, six, shutil, stat
from .log import CalledProcessError

class GitRemote:
    def __init__(self, url):
        self.url = url

    def name_hint(self):
        hint = self.url.replace('\\', '/').rsplit('/', 1)[-1]
        if hint.endswith('.git'):
            hint = hint[:-4]
        return hint

    def __eq__(self, rhs):
        if not isinstance(rhs, GitRemote):
            return False
        return self.url == rhs.url

    def __hash__(self):
        return hash(self.url)

class GitVersion:
    def __init__(self, hash):
        self.hash = hash

    def __eq__(self, rhs):
        if not isinstance(rhs, GitVersion):
            return False
        return self.hash == rhs.hash

    def __hash__(self):
        return hash(self.hash)

class GitHandler:
    def __init__(self):
        # This is a workaround. For whatever reason, git calls are not reentrant.
        for key in list(os.environ):
            if key.startswith('GIT_') and key != 'GIT_SSH':
                del os.environ[key]

    def save_lock(self, remote, ver):
        return {
            'type': 'git',
            'url': remote.url,
            'commit': ver.hash,
            }

    def versions(self, path, dep_spec, log):
        if len(dep_spec._branches) == 1:
            merge_base = log.check_output(['git', 'rev-parse', '--quiet', '--verify', 'origin/{}'.format(next(iter(dep_spec._branches)))], cwd=path).decode().strip()
        else:
            merge_base = log.check_output(['git', 'merge-base'] + ['origin/{}'.format(b) for b in dep_spec._branches], cwd=path).decode().strip()

        commits = log.check_output(['git', 'log', '--pretty=format:%H', merge_base], cwd=path).decode().strip().split()
        return [GitVersion(hash) for hash in commits]

    def get_deps_file(self, path, ver, log):
        root_tree = log.check_output(['git', 'ls-tree', '--name-only', ver.hash], cwd=path).decode().split()
        if 'DEPS' in root_tree:
            return log.check_output(['git', 'show', '{}:DEPS'.format(ver.hash)], cwd=path).decode()
        else:
            return '{}'

    def checkout(self, remote, ver, path, log):
        log.write('Checking out {}...\n'.format(path))

        if os.path.isdir(os.path.join(path, '.git')):
            r = log.call(['git', 'rev-parse', '--quiet', '--verify', '{}^{{commit}}'.format(ver.hash)], stdout=None, cwd=path)
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

            log.check_call(['git', 'clone', remote.url, path, '--no-checkout'])

        # XXX print('checkout {} to {}'.format(lock.commit, lock.path))
        log.check_call(['git', 'config', 'hooks.suppresscrater', 'true'], cwd=path)
        log.check_call(['git', '-c', 'advice.detachedHead=false', 'checkout', ver.hash], cwd=path)

    def fetch(self, path, log):
        log.check_call(['git', 'fetch', 'origin'], cwd=path)

    def current_version(self, path, log):
        try:
            commit = log.check_output(['git', 'rev-parse', '--quiet', '--verify', 'HEAD'], cwd=path).decode().strip()
        except log.CalledProcessError as e:
            return None

        return GitVersion(commit)

    def is_dirty(self, path, log):
        try:
            log.check_call(['git', 'update-index', '-q', '--refresh'], cwd=path)
            return log.call(['git', 'diff-index', '--quiet', 'HEAD', '--'], cwd=path) != 0
        except log.CalledProcessError as e:
            return True

    def load_lock(self, spec):
        return GitRemote(spec['url']), GitVersion(spec['commit'])

    def load_depspec(self, spec):
        url = spec.get('repo') or spec['url']
        branches = spec.get('branch', 'master')
        if isinstance(branches, six.string_types):
            branches = [branches]

        return GitRemote(url), GitDepSpec(branches)

    def empty_dep_spec(self):
        return GitDepSpec(())

    def is_compatible_ver(self, path, log, ver, ds):
        return log.check_output(['git', 'merge-base', ver.hash] + list(ds._branches), cwd=path).decode().strip() == ver.hash

class GitDepSpec:
    def __init__(self, branches):
        self._branches = frozenset(branches)

    def init(self, path, remote, log):
        assert self._branches

        log.check_call(['git', 'clone', remote.url, path, '--no-checkout'])

        try:
            log.check_call(['git', 'fetch', 'origin'] + list(self._branches), cwd=path)

            if len(self._branches) == 1:
                merge_base = log.check_output(['git', 'rev-parse', '--quiet', '--verify', 'origin/{}'.format(next(iter(self._branches)))], cwd=path).decode().strip()
            else:
                merge_base = log.check_output(['git', 'merge-base'] + ['origin/{}'.format(b) for b in self._branches], cwd=path).decode().strip()

            return git_handler, GitVersion(merge_base)
        except:
            def readonly_handler(rm_func, path, exc_info):
                if issubclass(exc_info[0], OSError) and exc_info[1].winerror == 5:
                    os.chmod(path, stat.S_IWRITE)
                    return rm_func(path)
                raise exc_info[1]
            shutil.rmtree(path, onerror=readonly_handler)
            raise

    def join(self, o):
        if not isinstance(o, GitDepSpec):
            return None

        new_branches = set(self._branches)
        new_branches.update(o._branches)
        return GitDepSpec(new_branches)

git_handler = GitHandler()
