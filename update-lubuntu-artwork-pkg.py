#!/usr/bin/env python3
import ftplib
import functools
import io
import os
import pyalpm
import re
import subprocess
import sys

lubuntu_artwork_src = sys.argv[1]

with ftplib.FTP('archive.ubuntu.com') as ubuntu_ftp:
    ubuntu_ftp.login()
    ubuntu_ftp.cwd('ubuntu/pool/universe/l/lubuntu-artwork')
    dsc_list = []
    for i in ubuntu_ftp.nlst():
        if i.endswith('.dsc'):
            dsc_list.append(i)

    dsc_list = list(sorted(dsc_list, key=functools.cmp_to_key(pyalpm.vercmp)))
    dsc_name = dsc_list[-1]

    with io.BytesIO() as dsc_io:
        dsc_io = io.BytesIO()
        ubuntu_ftp.retrbinary('RETR {}'.format(dsc_name), dsc_io.write)
        dsc_content = dsc_io.getvalue().decode('utf8')

    debian_version = re.search(r'{}\s+([^\s]+)'.format('Version:'),
        dsc_content).group(1)
    pkgver = debian_version.rsplit('-', 1)[0]
    package_name = 'lubuntu-artwork_{}.'.format(pkgver)
    start_pos = re.search(re.escape('Checksums-Sha256:'), dsc_content).span()[1]
    pat = re.compile(r'([^\s]+)\s+([^\s]+)\s+{}'.format(re.escape(package_name)))
    sha256sum = pat.search(dsc_content, start_pos).group(1)

    pkgbuild_path = os.path.join(lubuntu_artwork_src, 'PKGBUILD')
    with open(pkgbuild_path, 'r') as pkgbuild:
        pkgbuild_content = pkgbuild.read()
        pkgbuild_content = re.sub(r'(?<=pkgver\=)[^\n]+', pkgver,
                pkgbuild_content, flags=re.MULTILINE)
        pkgbuild_content = re.sub(r'(?<=pkgrel\=)[^\n]+', '1',
                pkgbuild_content, flags=re.MULTILINE)
        pkgbuild_content = re.sub(r'(?<=sha256sums\=\(\')[^\']+', sha256sum,
                pkgbuild_content, flags=re.MULTILINE)
    with open(pkgbuild_path, 'w') as pkgbuild:
        pkgbuild.write(pkgbuild_content)
    cwd = os.getcwd()
    os.chdir(lubuntu_artwork_src)
    try:
        subprocess.check_call(['git', 'commit', 'PKGBUILD', '-m',
            '[lubuntu-artwork] Update pkg ({})'.format(pkgver)])
    except subprocess.CalledProcessError:
        pass
    else:
        subprocess.check_call('git push'.split())
