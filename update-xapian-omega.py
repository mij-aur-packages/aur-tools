#!/usr/bin/env python3
from urllib.request import urlopen
import os
import re
import subprocess
import urllib.parse


def main(pkgbuild_dir):
    pkgbuild_path = os.path.join(pkgbuild_dir, 'PKGBUILD')
    debian_package_page ='https://packages.debian.org/sid/xapian-omega'

    with urlopen(debian_package_page) as page:
        res = re.search('http((?:(?!\.dsc).)+)\.dsc', page.read().decode('utf-8'))
        url_dsc = res.group()

    with urlopen(url_dsc) as dsc:
        dsc_content = dsc.read().decode('utf-8')

    debian_version = re.search(r'{}\s+([^\s]+)'.format('Version:'),
        dsc_content).group(1)
    pkgver = debian_version.rsplit('-', 1)[0]
    package_name = 'xapian-omega_{}.orig.tar.xz'.format(pkgver)
    start_pos = re.search(re.escape('Checksums-Sha256:'), dsc_content).span()[1]
    pat = re.compile(r'([^\s]+)\s+([^\s]+)\s+{}'.format(re.escape(package_name)))
    sha256sum = pat.search(dsc_content, start_pos).group(1)

    with open(pkgbuild_path, 'r') as pkgbuild:
        pkgbuild_content = pkgbuild.read()

    old_pkgver = re.search(r'(?:(?<=pkgver\=)\s*)([^\s]+)',
            pkgbuild_content).group(1)
    vercmp_res = subprocess.check_output(['vercmp', old_pkgver, pkgver]).decode('utf-8')
    vercmp_res = int(vercmp_res)
    if vercmp_res == 0:
        return
    elif vercmp_res > 0:
        raise Exception('PKGBUILD version is higher than the upstream package')

    pkgbuild_content = re.sub(r'(?<=pkgver\=)[^\n]+', pkgver,
            pkgbuild_content, flags=re.MULTILINE)
    pkgbuild_content = re.sub(r'(?<=pkgrel\=)[^\n]+', '1',
            pkgbuild_content, flags=re.MULTILINE)
    pkgbuild_content = re.sub(r'(?<=sha256sums\=\(\')[^\']+', sha256sum,
            pkgbuild_content, flags=re.MULTILINE)

    with open(pkgbuild_path, 'w') as pkgbuild:
        pkgbuild.write(pkgbuild_content)

    cwd = os.getcwd()
    os.chdir(pkgbuild_dir)
    try:
        subprocess.check_call(['git', 'commit', 'PKGBUILD', '-m',
            '[xapian-omega] Update pkg ({})'.format(pkgver)])
    except subprocess.CalledProcessError:
        pass
    else:
        subprocess.check_call('git push'.split())
    os.chdir(cwd)


if __name__ == '__main__':
    import sys
    main(sys.argv[1])
