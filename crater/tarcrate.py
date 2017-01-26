import subprocess, os, errno, sys, requests, tarfile, hashlib, shutil

class TarCrate:
    def __init__(self, root, name, hash, url, subdir, exclude):
        CrateBase.__init__(self, root, name)
        self.hash = hash
        self.url = url

        def _remove_trailing_slash(s):
            while s.endswith('/'):
                s = s[:-1]
            return s

        self._subdir = _remove_trailing_slash(subdir)
        self._exclude = [_remove_trailing_slash(exc) for exc in exclude]

    def status(self):
        return '?'

    @classmethod
    def load(cls, root, name, spec):
        return cls(root, name, hash=spec['hash'], url=spec['url'], subdir=spec.get('subdir'), exclude=spec.get('exclude', []))

    def save(self):
        r = {
            'type': 'tar',
            'hash': self.hash,
            'url': self.url,
            }

        if self._subdir:
            r['subdir'] = self._subdir
        if self._exclude:
            r['exclude'] = self._exclude
        self._save_deps(r)
        return r

    def checkout(self):
        r = requests.get(self.url, stream=True)
        if r.status_code != 200:
            raise RuntimeError('dowload failure: {}'.format(self.url))

        hashes = []
        bufsize = 16*1024
        def extract(f, canon_name, path):
            h = hashlib.sha256()

            try:
                os.makedirs(os.path.split(path)[0])
            except:
                pass

            with open(path, 'wb') as fout:
                while True:
                    d = f.read(bufsize)
                    fout.write(d)
                    h.update(d)
                    if len(d) < bufsize:
                        break
            hashes.append((canon_name, h.hexdigest()))

        with tarfile.open(fileobj=r.raw, mode='r|*') as tf:
            for ti in tf:
                name = ti.name.replace('\\', '/')

                parts = name.split('/')
                if not parts[0] or any(part in ('.', '..') for part in parts):
                    continue

                name = '/'.join(part for part in parts if part)
                if self._subdir and not name.startswith(self._subdir + '/'):
                    continue

                if self._subdir:
                    name = name[len(self._subdir)+1:]

                if any(name.startswith(exc + '/') for exc in self._exclude):
                    continue

                f = tf.extractfile(ti)
                if f is not None:
                    extract(f, name, os.path.join(self.path, name))

        hashes.sort()
        manifest = ''.join('{} {}\n'.format(h, n) for n, h in hashes)

        real_hash = hashlib.sha256(manifest).hexdigest()
        if self.hash is None:
            self.hash = real_hash
        elif self.hash != real_hash:
            raise RuntimeError('hash mismatch!')

        with open(os.path.join(self.path, '.crate.manifest'), 'w') as fout:
            fout.write(manifest)

    def update(self):
        pass
