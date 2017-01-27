import subprocess, os, threading, colorama

from subprocess import CalledProcessError

class _Dimmer:
    def __init__(self, stream):
        self._stream = colorama.AnsiToWin32(stream, convert=True, strip=True, autoreset=True)

    def write(self, s):
        self._stream.write(colorama.Style.BRIGHT + colorama.Fore.BLACK + s)

    def flush(self):
        pass

class Log:
    def __init__(self, stderr):
        self._stderr = stderr
        self._dimmed = colorama.AnsiToWin32(_Dimmer(stderr), convert=False, strip=True, autoreset=False)
        self._devnull = open(os.devnull, 'r+b')

    def call(self, *args, **kw):
        if 'stdout' not in kw and 'stderr' not in kw:
            kw['stdout'] = subprocess.PIPE
            kw['stderr'] = subprocess.STDOUT
            src = 'stdout'
        elif 'stdout' not in kw:
            kw['stdout'] = subprocess.PIPE
            src = 'stdout'
        elif 'stderr' not in kw:
            kw['stderr'] = subprocess.PIPE
            src = 'stderr'
        else:
            return subprocess.call(*args, **kw)

        if kw['stdout'] is None:
            kw['stdout'] = self._devnull
        if kw['stderr'] is None:
            kw['stderr'] = self._devnull

        p = subprocess.Popen(*args, **kw)

        while True:
            line = getattr(p, src).readline()
            if not line:
                break

            self._dimmed.write(line)

        p.wait()
        return p.returncode

    def check_call(self, *args, **kw):
        r = self.call(*args, **kw)
        if r != 0:
            raise subprocess.CalledProcessError(r, args[0])

    def check_output(self, *args, **kw):
        if 'stderr' not in kw:
            kw['stderr'] = subprocess.PIPE
        else:
            return subprocess.check_output(*args, **kw)

        p = subprocess.Popen(*args, stdout=subprocess.PIPE, **kw)

        stdout = []
        def reader():
            stdout.append(p.stdout.read())

        thr = threading.Thread(target=reader)
        thr.start()

        while True:
            line = p.stderr.readline()
            if not line:
                break

            self._dimmed.write(line)

        thr.join()

        p.wait()
        if p.returncode != 0:
            raise subprocess.CalledProcessError(p.returncode, args[0])

        return ''.join(stdout)

    def write(self, s):
        self._stderr.write(s)

    def error(self, s):
        self._stderr.write('error: {}\n'.format(s))
