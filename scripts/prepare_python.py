import hashlib
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


VERSION = '3.13.17'
SHA256 = '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'
ROOT = Path(__file__).resolve().parents[1]


def main():
    cache = ROOT / '.build-cache'
    cache.mkdir(exist_ok=True)
    archive = cache / f'python-{VERSION}-embed-amd64.zip'
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        url = f'https://www.python.org/ftp/python/{VERSION}/{archive.name}'
        with urlopen(url, timeout=45) as response:
            data = response.read(16 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise SystemExit('The embedded Python download failed SHA-256 verification.')
        archive.write_bytes(data)
    target = cache / f'python-{VERSION}'
    with ZipFile(archive) as source:
        source.extractall(target)
    print(f'Prepared Python {VERSION} (x64) in {target}')


if __name__ == '__main__':
    main()
